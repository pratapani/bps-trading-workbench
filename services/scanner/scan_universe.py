import os
import csv
import time
import smtplib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from datetime import datetime
from email.message import EmailMessage

from breeze_connect import BreezeConnect
from dotenv import load_dotenv

from bps_engine import (
    Put,
    scan_bps,
    calculate_put_iv,
)


# ============================================================
# CONFIGURATION
# ============================================================

# 0 = ALL available stock-like underlyings
MAX_STOCKS = 0


# ------------------------------------------------------------
# OTM
# ------------------------------------------------------------

# Screening rules are read from scan_config.json so they can be
# changed before each EC2 scan without editing this Python file.

SCAN_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scan_config.json",
)


def normalize_expiry(value):
    """Normalize the UI-selected expiry to Breeze's DD-Mon-YYYY format."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d-%b-%Y")
        except ValueError:
            pass
    return ""


def load_scan_config():
    required = {
        "expiry",
        "min_otm_percent",
        "max_otm_percent",
        "max_spread_width",
        "min_profit_to_loss",
        "max_profit_to_loss",
        "min_oi",
        "min_volume",
    }

    try:
        with open(SCAN_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {SCAN_CONFIG_FILE} not found.")
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {SCAN_CONFIG_FILE}: {e}")
        raise SystemExit(1)

    if not isinstance(config, dict):
        print("ERROR: scan_config.json must contain a JSON object.")
        raise SystemExit(1)

    missing = required - set(config)
    if missing:
        print(
            "ERROR: scan_config.json is missing: "
            + ", ".join(sorted(missing))
        )
        raise SystemExit(1)

    expiry = normalize_expiry(config.get("expiry"))
    if not expiry:
        print("ERROR: scan_config.json must contain a valid selected expiry.")
        print("       Expected YYYY-MM-DD or DD-Mon-YYYY.")
        raise SystemExit(1)

    try:
        values = {
            "expiry": expiry,
            "min_otm_percent": float(config["min_otm_percent"]),
            "max_otm_percent": float(config["max_otm_percent"]),
            "max_spread_width": float(config["max_spread_width"]),
            "min_profit_to_loss": float(config["min_profit_to_loss"]),
            "max_profit_to_loss": float(config["max_profit_to_loss"]),
            "min_oi": float(config["min_oi"]),
            "min_volume": float(config["min_volume"]),
        }
    except (TypeError, ValueError):
        print("ERROR: Numeric scan_config.json values are invalid.")
        raise SystemExit(1)

    if values["min_otm_percent"] < 0:
        print("ERROR: min_otm_percent cannot be negative.")
        raise SystemExit(1)
    if values["max_otm_percent"] < values["min_otm_percent"]:
        print("ERROR: max_otm_percent must be >= min_otm_percent.")
        raise SystemExit(1)
    if values["max_spread_width"] <= 0:
        print("ERROR: max_spread_width must be > 0.")
        raise SystemExit(1)
    if values["min_profit_to_loss"] < 0:
        print("ERROR: min_profit_to_loss cannot be negative.")
        raise SystemExit(1)
    if values["max_profit_to_loss"] < values["min_profit_to_loss"]:
        print("ERROR: max_profit_to_loss must be >= min_profit_to_loss.")
        raise SystemExit(1)
    if values["min_oi"] < 0 or values["min_volume"] < 0:
        print("ERROR: min_oi and min_volume cannot be negative.")
        raise SystemExit(1)

    print(f"Loaded scan configuration: {SCAN_CONFIG_FILE}")
    return values


SCAN_CONFIG = load_scan_config()

SELECTED_EXPIRY = SCAN_CONFIG["expiry"]
MIN_OTM_PERCENT = SCAN_CONFIG["min_otm_percent"]
MAX_OTM_PERCENT = SCAN_CONFIG["max_otm_percent"]
MAX_SPREAD_WIDTH = SCAN_CONFIG["max_spread_width"]
MIN_PROFIT_TO_LOSS = SCAN_CONFIG["min_profit_to_loss"]
MAX_PROFIT_TO_LOSS = SCAN_CONFIG["max_profit_to_loss"]
MIN_OI = SCAN_CONFIG["min_oi"]
MIN_VOLUME = SCAN_CONFIG["min_volume"]


# ------------------------------------------------------------
# API delay
# ------------------------------------------------------------

API_DELAY = 0.20


# ------------------------------------------------------------
# Email
# ------------------------------------------------------------
# SMTP credentials are read from .env.
# For Gmail use an App Password, not the normal account password.
EMAIL_TO = "durgaprasadbabu@gmail.com"


# ------------------------------------------------------------
# Instruments to exclude
# ------------------------------------------------------------

EXCLUDED = {
    "NIFTY",
    "CNXBAN",
    "NIFFIN",
    "NIF150",
    "NIFNEX",
    "NIFSEL",
    "MCX",
}
# ============================================================
# STOCK LOT-SIZE FILE
# ============================================================
#
# stock_lot.csv is populated from ICICI Direct Security Master by
# download_security_master.py.
#
# Format:
#
#   STOCK,LOT
#   TCS,175
#   DIXON,50
#   KALJEW,1350
#
# The scanner deliberately reads ONLY this CSV for lot size.
# Security Master is the authoritative source used to populate it.
#
# If a stock is not present or its LOT is invalid, LOT = 1.
# ============================================================

STOCK_LOT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "stock_lot.csv",
)


def load_stock_lots():

    lots = {}

    if not os.path.exists(
        STOCK_LOT_FILE
    ):
        print(
            f"Lot file not found: "
            f"{STOCK_LOT_FILE}"
        )

        print(
            "Using LOT = 1 by default."
        )

        return lots

    print(
        f"Loading lot sizes from "
        f"{STOCK_LOT_FILE}..."
    )

    try:

        with open(
            STOCK_LOT_FILE,
            "r",
            newline="",
            encoding="utf-8",
        ) as f:

            reader = csv.reader(f)

            for row_number, row in enumerate(
                reader,
                1,
            ):

                if len(row) < 2:
                    continue

                stock = (
                    row[0]
                    .strip()
                    .upper()
                )

                lot_text = (
                    row[1]
                    .strip()
                )

                if row_number == 1:
                    if stock in {
                        "STOCK",
                        "SYMBOL",
                        "STOCK_CODE",
                    }:
                        continue

                if not stock or not lot_text:
                    continue

                try:
                    lot = int(
                        float(
                            lot_text
                        )
                    )
                except (
                    ValueError,
                    TypeError,
                ):
                    continue

                if lot > 0:
                    lots[stock] = lot

    except Exception as e:

        print(
            f"WARNING: Could not read "
            f"{STOCK_LOT_FILE}: {e}"
        )

        return {}

    print(
        f"Lot sizes loaded: "
        f"{len(lots)} stocks"
    )

    return lots


STOCK_LOTS = load_stock_lots()


def get_lot_size(stock):

    return STOCK_LOTS.get(
        stock.upper(),
        1,
    )


# ============================================================
# EXPIRY HELPERS
# ============================================================

def expiry_sort_key(expiry):

    try:

        return datetime.strptime(
            expiry,
            "%d-%b-%Y",
        )

    except ValueError:

        return datetime.max


def get_available_expiries(
    nfo,
    stock,
):

    expiries = set()

    prefix = (
        f"OPT-{stock}-"
    )

    for key in nfo:

        if not key.startswith(
            prefix
        ):
            continue

        if not key.endswith(
            "-PE"
        ):
            continue

        parts = key.split("-")

        if len(parts) < 7:
            continue

        expiry = "-".join(
            parts[2:5]
        )

        expiries.add(
            expiry
        )

    return sorted(
        expiries,
        key=expiry_sort_key,
    )


def choose_expiry(
    nfo,
    stock,
):

    expiries = (
        get_available_expiries(
            nfo,
            stock,
        )
    )

    if not expiries:
        return None

    # --------------------------------------------------------
    # The master list contains current/future contracts.
    # Pick the earliest expiry.
    # --------------------------------------------------------

    return expiries[0]


# ============================================================
# CONTRACT CONVERSION
# ============================================================

def convert_contracts(
    contracts,
    expiry,
):

    puts = []
    spot = None

    for x in contracts:

        try:

            strike = float(
                x.get(
                    "strike_price",
                    0,
                )
            )

            bid = float(
                x.get(
                    "best_bid_price",
                    0,
                )
            )

            offer = float(
                x.get(
                    "best_offer_price",
                    0,
                )
            )

            bid_qty = int(
                float(
                    x.get(
                        "best_bid_quantity",
                        0,
                    )
                )
            )

            offer_qty = int(
                float(
                    x.get(
                        "best_offer_quantity",
                        0,
                    )
                )
            )

            oi = float(
                x.get(
                    "open_interest",
                    0,
                )
            )

            volume = int(
                float(
                    x.get(
                        "total_quantity_traded",
                        0,
                    )
                )
            )

            ltt = x.get(
                "ltt",
                "",
            )

            if x.get(
                "spot_price"
            ) not in (
                None,
                "",
            ):

                spot = float(
                    x[
                        "spot_price"
                    ]
                )

            if strike <= 0:
                continue

            puts.append(
                Put(
                    strike=strike,
                    bid=bid,
                    offer=offer,
                    bid_qty=bid_qty,
                    offer_qty=offer_qty,
                    oi=oi,
                    volume=volume,
                    ltt=ltt,
                )
            )

        except (
            ValueError,
            TypeError,
        ):

            continue

    # ------------------------------------------------------------
    # Calculate IV locally because Breeze does not provide usable IV.
    # SELL leg IV -> BID
    # BUY leg IV  -> OFFER
    # ------------------------------------------------------------

    if spot is not None and spot > 0:
        for put in puts:
            put.bid_iv = calculate_put_iv(
                option_price=put.bid,
                spot=spot,
                strike=put.strike,
                expiry=expiry,
            )

            put.offer_iv = calculate_put_iv(
                option_price=put.offer,
                spot=spot,
                strike=put.strike,
                expiry=expiry,
            )

    return puts, spot


# ============================================================
# CSV RESULT WRITER
# ============================================================

def save_results(results):
    """Save ranked BPS results with both market quotes and executable prices."""

    filename = "bps_results.csv"

    fields = [
        "RK",
        "STOCK",
        "EXPIRY",
        "SPOT",
        "SELL",
        "BUY",
        "SELL_IV",
        "BUY_IV",
        "SELL_PE_BID",
        "SELL_PE_OFFER",
        "BUY_PE_BID",
        "BUY_PE_OFFER",
        "OTM%",
        "OTM PTS",
        "WIDTH",
        "CREDIT",
        "LOT",
        "PROFIT/LOT",
        "LOSS/LOT",
        "BREAKEVEN",
        "P:L",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for rank, result in enumerate(results, 1):
            sell_strike = float(result["sell_strike"])
            buy_strike = float(result["buy_strike"])
            credit = float(result["credit"])
            width = float(result["width"])
            lot_size = int(result.get("lot_size", 1))

            profit_per_lot = credit * lot_size
            loss_per_lot = (width - credit) * lot_size
            breakeven = sell_strike - credit

            writer.writerow({
                "RK": rank,
                "STOCK": result.get("stock", ""),
                "EXPIRY": result.get("expiry", ""),
                "SPOT": result.get("spot", ""),
                "SELL": sell_strike,
                "BUY": buy_strike,
                "SELL_IV": result.get("sell_iv", ""),
                "BUY_IV": result.get("buy_iv", ""),

                # Preserve both quotes for auditability.
                "SELL_PE_BID": result.get("sell_bid", ""),
                "SELL_PE_OFFER": result.get("sell_offer", ""),
                "BUY_PE_BID": result.get("buy_bid", ""),
                "BUY_PE_OFFER": result.get("buy_offer", ""),

                "OTM%": result.get("otm_percent", ""),
                "OTM PTS": result.get("otm_points", ""),
                "WIDTH": width,

                # IMPORTANT:
                # CREDIT = SELL PE BID - BUY PE OFFER
                "CREDIT": credit,

                "LOT": lot_size,
                "PROFIT/LOT": profit_per_lot,
                "LOSS/LOT": loss_per_lot,
                "BREAKEVEN": breakeven,
                "P:L": result.get("profit_to_loss", ""),
            })

    print()
    print(f"Results saved to: {filename}")
    print("Execution pricing: SELL PE BID - BUY PE OFFER")
    return filename

def send_results_email(filename, result_count):
    """Email the CSV when SMTP credentials are configured."""

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port_text = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    email_to = os.getenv("EMAIL_TO", EMAIL_TO)

    if not smtp_user or not smtp_password:
        print()
        print("EMAIL: SMTP_USER / SMTP_PASSWORD not configured.")
        print("EMAIL: CSV was saved but was not sent.")
        print("EMAIL: Add SMTP credentials to .env to enable email.")
        return False

    try:
        smtp_port = int(smtp_port_text)

        message = EmailMessage()
        message["Subject"] = (
            f"BPS Scanner Results - {datetime.now():%d-%b-%Y %H:%M}"
        )
        message["From"] = smtp_user
        message["To"] = email_to
        message.set_content(
            "BPS Universe Scanner completed.\n\n"
            f"Qualifying BPS strategies: {result_count}\n"
            f"CSV attachment: {filename}\n"
        )

        with open(filename, "rb") as f:
            data = f.read()

        message.add_attachment(
            data,
            maintype="text",
            subtype="csv",
            filename=os.path.basename(filename),
        )

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)

        print()
        print(f"EMAIL: CSV sent to {email_to}")
        return True

    except Exception as e:
        print()
        print(f"EMAIL FAILED: {e}")
        print("The CSV remains available locally.")
        return False


# ============================================================
# AUTHENTICATION
# ============================================================

load_dotenv()

api_key = os.getenv(
    "BREEZE_API_KEY"
)

api_secret = os.getenv(
    "BREEZE_API_SECRET"
)

session_token = os.getenv(
    "BREEZE_SESSION_TOKEN"
)


if not (
    api_key
    and api_secret
    and session_token
):

    print(
        "ERROR: Breeze credentials "
        "missing from .env"
    )

    raise SystemExit(1)


print("=" * 120)
print("BPS UNIVERSE SCANNER")
print("=" * 120)
print()

print(
    "Authenticating..."
)


breeze = BreezeConnect(
    api_key=api_key
)


try:

    breeze.generate_session(
        api_secret=api_secret,
        session_token=session_token,
    )

except Exception as e:

    print(
        f"Authentication FAILED: {e}"
    )

    raise SystemExit(1)


print(
    "Authentication OK"
)

print()


# ============================================================
# LOAD NFO MASTER
# ============================================================

print(
    "Loading NFO contract universe..."
)

try:

    nfo = (
        breeze
        .stock_script_dict_list[4]
    )

except Exception as e:

    print(
        f"ERROR loading NFO universe: {e}"
    )

    raise SystemExit(1)


print(
    f"NFO contracts: {len(nfo):,}"
)

print()


# ============================================================
# DISCOVER UNDERLYINGS
# ============================================================

underlyings = set()

for key in nfo:

    if not key.startswith(
        "OPT-"
    ):
        continue

    if key.startswith(
        "OPT-ShortName"
    ):
        continue

    if not key.endswith(
        "-PE"
    ):
        continue

    parts = key.split("-")

    if len(parts) < 7:
        continue

    stock = parts[1]

    if stock in EXCLUDED:
        continue

    underlyings.add(
        stock
    )


underlyings = sorted(
    underlyings
)


if MAX_STOCKS > 0:

    underlyings = (
        underlyings[
            :MAX_STOCKS
        ]
    )


print(f"Selected expiry: {SELECTED_EXPIRY}")
print()
print(
    f"Stock-like underlyings: "
    f"{len(underlyings)}"
)

print()


# ============================================================
# SCAN
# ============================================================
#
# Network/API work is performed concurrently. Results are collected in
# the main thread so CSV writing and global ranking remain deterministic.
#

all_results = []
successful = 0
failed = 0
zero_candidates = 0
failure_details = []

start = time.time()

# Pre-build the expiry map once. The old sequential implementation scanned
# the entire NFO master separately for every stock.
available_expiries_by_stock = {}
for key in nfo:
    if not key.startswith("OPT-") or not key.endswith("-PE"):
        continue
    parts = key.split("-")
    if len(parts) < 7:
        continue
    stock = parts[1]
    expiry = "-".join(parts[2:5])
    available_expiries_by_stock.setdefault(stock, set()).add(expiry)


def scan_one_stock(number, stock):
    """Fetch and process one stock. No shared result state is modified here."""
    try:
        expiry = SELECTED_EXPIRY
        available_expiries = available_expiries_by_stock.get(stock, set())

        if expiry not in available_expiries:
            return {
                "number": number,
                "stock": stock,
                "status": "failed",
                "reason": f"Selected expiry {expiry} not available",
            }

        # Respect Breeze's documented 100 calls/minute limit globally.
        wait_for_api_slot()

        response = breeze.get_option_chain_quotes(
            stock_code=stock,
            exchange_code="NFO",
            product_type="options",
            expiry_date=expiry,
            right="put",
            strike_price="",
        )

        if response.get("Status") != 200:
            error = response.get("Error", "Unknown error")
            return {
                "number": number,
                "stock": stock,
                "status": "failed",
                "reason": str(error),
            }

        contracts = response.get("Success") or []
        if not contracts:
            return {
                "number": number,
                "stock": stock,
                "status": "failed",
                "reason": "No contracts",
            }

        puts, spot = convert_contracts(contracts, expiry)

        if spot is None:
            return {
                "number": number,
                "stock": stock,
                "status": "failed",
                "reason": "No spot",
            }

        lot_size = get_lot_size(stock)

        results = scan_bps(
            puts,
            lot_size=lot_size,
            spot=spot,
            min_otm_percent=MIN_OTM_PERCENT,
            max_otm_percent=MAX_OTM_PERCENT,
            max_spread_width=MAX_SPREAD_WIDTH,
            min_profit_to_loss=MIN_PROFIT_TO_LOSS,
            max_profit_to_loss=MAX_PROFIT_TO_LOSS,
            min_oi=MIN_OI,
            min_volume=MIN_VOLUME,
        )

        for result in results:
            result["stock"] = stock
            result["spot"] = spot
            result["expiry"] = expiry
            result["lot_size"] = lot_size

        return {
            "number": number,
            "stock": stock,
            "status": "success",
            "spot": spot,
            "contracts": len(contracts),
            "results": results,
        }

    except Exception as e:
        return {
            "number": number,
            "stock": stock,
            "status": "failed",
            "reason": str(e),
        }


print(f"Concurrent workers  : {MAX_WORKERS}")
print(f"API pacing          : {API_CALLS_PER_MINUTE * API_RATE_SAFETY:.0f} calls/min safety target")
print()

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {
        executor.submit(scan_one_stock, number, stock): (number, stock)
        for number, stock in enumerate(underlyings, 1)
    }

    for future in as_completed(futures):
        result = future.result()
        number = result["number"]
        stock = result["stock"]

        print(
            f"[{number:03d}/{len(underlyings):03d}] "
            f"{stock:<8} ",
            end="",
            flush=True,
        )

        if result["status"] == "success":
            results = result["results"]
            all_results.extend(results)
            successful += 1

            if not results:
                zero_candidates += 1

            print(
                f"OK │ Spot ₹{result['spot']:,.2f} │ "
                f"Contracts {result['contracts']:2d} │ "
                f"BPS {len(results):2d}"
            )
        else:
            failed += 1
            failure_details.append((stock, result["reason"]))

            if result["reason"].startswith("Selected expiry"):
                print(f"NO SELECTED EXPIRY │ {SELECTED_EXPIRY}")
            elif result["reason"] == "No contracts":
                print("NO CONTRACTS")
            elif result["reason"] == "No spot":
                print("NO SPOT")
            else:
                print(f"FAILED │ {result['reason']}")

# ============================================================
# GLOBAL RANKING
# ============================================================

all_results.sort(
    key=lambda x: (
        -x[
            "otm_percent"
        ],

        -x.get(
            "sell_iv",
            0,
        ),

        x[
            "width"
        ],

        x[
            "profit_to_loss"
        ],
    )
)


elapsed = (
    time.time()
    - start
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 120)
print("SCAN COMPLETE")
print("=" * 120)

print(
    f"Stocks scanned    : "
    f"{len(underlyings)}"
)

print(
    f"Successful        : "
    f"{successful}"
)

print(
    f"Failed            : "
    f"{failed}"
)

print(
    f"No BPS candidates : "
    f"{zero_candidates}"
)

print(
    f"Total BPS         : "
    f"{len(all_results)}"
)

print(
    f"Elapsed           : "
    f"{elapsed / 60:.1f} minutes"
)

print()


# ============================================================
# RESULTS
# ============================================================

if not all_results:

    print("NO QUALIFYING BPS FOUND.")

else:

    print("=" * 150)
    print("TOP BULL PUT SPREAD OPPORTUNITIES")
    print("=" * 150)
    print()

    # Only decision-relevant fields are shown.
    # Execution prices are SELL BID and BUY OFFER.
    headers = [
        ("RK", 3, "r"),
        ("STOCK", 8, "l"),
        ("SPOT", 11, "r"),
        ("SELL", 7, "r"),
        ("BUY", 7, "r"),
        ("S-IV", 7, "r"),
        ("B-IV", 7, "r"),
        ("OTM%", 7, "r"),
        ("OTM PTS", 8, "r"),
        ("WIDTH", 7, "r"),
        ("CREDIT", 9, "r"),
        ("LOT", 7, "r"),
        ("PROFIT/LOT", 13, "r"),
        ("LOSS/LOT", 13, "r"),
        ("BREAKEVEN", 11, "r"),
        ("P:L", 7, "r"),
    ]

    def fmt_header():
        parts = []
        for name, width, align in headers:
            parts.append(f"{name:>{width}}" if align == "r" else f"{name:<{width}}")
        return " │ ".join(parts)

    print(fmt_header())
    print("─" * 150)

    for rank, x in enumerate(all_results, 1):
        break_even = float(x["sell_strike"]) - float(x["credit"])

        values = [
            f"{rank:>{3}}",
            f"{x['stock']:<8}",
            f"₹{x['spot']:>9,.2f}",
            f"{x['sell_strike']:>7.0f}",
            f"{x['buy_strike']:>7.0f}",
            f"{x.get('sell_iv', 0):>7.2f}",
            f"{x.get('buy_iv', 0):>7.2f}",
            f"{x['otm_percent']:>6.2f}%",
            f"{x['otm_points']:>8.0f}",
            f"{x['width']:>7.0f}",
            f"₹{x['credit']:>7.2f}",
            f"{x['lot_size']:>7}",
            f"₹{x['max_profit']:>11,.2f}",
            f"₹{x['max_loss']:>11,.2f}",
            f"₹{break_even:>9,.2f}",
            f"1:{x['profit_to_loss']:<5.2f}",
        ]
        print(" │ ".join(values))

    print()
    print("Execution price: SELL put = BID │ BUY put = OFFER")
    print("Credit: SELL BID − BUY OFFER")
    print("Ranking: Far OTM → Higher sell IV → Narrow spread → Better P:L")
# ============================================================
# INTERPRETATION
# ============================================================

print()

print("=" * 120)
print("EXECUTION RULES")
print("=" * 120)

print()

print(
    "SELL PUT  → execute against BID"
)

print(
    "BUY PUT   → execute against OFFER"
)

print(
    "CREDIT    → SELL BID − BUY OFFER"
)

print(
    "OTM       → distance of SELL strike below spot"
)

print(
    f"OTM       → {MIN_OTM_PERCENT:.1f}% "
    f"to {MAX_OTM_PERCENT:.1f}%"
)

print(
    f"WIDTH     → maximum {MAX_SPREAD_WIDTH}"
)

print(
    f"P:L       → 1:{MIN_PROFIT_TO_LOSS:.1f} "
    f"to 1:{MAX_PROFIT_TO_LOSS:.1f}"
)

print(
    "RANKING   → Far OTM → Narrow spread → Better P:L"
)


if STOCK_LOTS:
    print()
    print(
        f"LOT SIZES  → {len(STOCK_LOTS)} stocks loaded from {STOCK_LOT_FILE}; "
        "all other stocks use LOT = 1."
    )
else:
    print()
    print(
        f"LOT SIZES  → {STOCK_LOT_FILE} missing/empty; all stocks use LOT = 1."
    )


# ============================================================
# FAILURES
# ============================================================

if failure_details:

    print()

    print("=" * 120)
    print("FAILED / SKIPPED")
    print("=" * 120)

    for stock, reason in (
        failure_details
    ):

        print(
            f"{stock:<10} │ "
            f"{reason}"
        )


# ============================================================
# SAVE RESULTS
# ============================================================

results_file = save_results(all_results)
send_results_email(results_file, len(all_results))

print()
print("=" * 120)
print("DONE")
print("=" * 120)