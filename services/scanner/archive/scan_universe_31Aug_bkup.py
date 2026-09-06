import os
import csv
import time
import smtplib
from datetime import datetime
from email.message import EmailMessage

from breeze_connect import BreezeConnect
from dotenv import load_dotenv

from bps_engine import Put, scan_bps


# ============================================================
# CONFIGURATION
# ============================================================

# 0 = ALL available stock-like underlyings
MAX_STOCKS = 0


# ------------------------------------------------------------
# OTM
# ------------------------------------------------------------

MIN_OTM_PERCENT = 3.0
MAX_OTM_PERCENT = 8.0


# ------------------------------------------------------------
# Spread
# ------------------------------------------------------------

MAX_SPREAD_WIDTH = 200


# ------------------------------------------------------------
# Profit : Max Loss
#
# 1:3 to 1:5
# ------------------------------------------------------------

MIN_PROFIT_TO_LOSS = 3.0
MAX_PROFIT_TO_LOSS = 5.0


# ------------------------------------------------------------
# Liquidity
# ------------------------------------------------------------

MIN_OI = 100000
MIN_VOLUME = 100000


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
# OPTIONAL STOCK LOT-SIZE FILE
# ============================================================
#
# File:
#   stock_lot.csv
#
# Format:
#
#   STOCK,LOT
#   TCS,175
#   BSE,200
#   KALJEW,175
#
# Rules:
#
#   File does not exist       -> LOT = 1
#   Stock not listed          -> LOT = 1
#   Stock listed + valid LOT  -> use LOT
#   Stock listed + blank LOT  -> LOT = 1
#   Invalid LOT                -> LOT = 1
# ============================================================

STOCK_LOT_FILE = "stock_lot.csv"


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

                # Need at least two columns
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

                # Skip header
                if row_number == 1:

                    if stock in {
                        "STOCK",
                        "SYMBOL",
                        "STOCK_CODE",
                    }:

                        continue

                if not stock:
                    continue

                if not lot_text:
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

                    lots[
                        stock
                    ] = lot

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

    return puts, spot


# ============================================================
# CSV RESULT WRITER
# ============================================================

def save_results(results):

    filename = "bps_results.csv"

    fields = [
        "RK",
        "STOCK",
        "SPOT",
        "SELL",
        "BUY",
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

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for rank, result in enumerate(
            results,
            1,
        ):

            sell_strike = float(
                result["sell_strike"]
            )

            buy_strike = float(
                result["buy_strike"]
            )

            credit = float(
                result["credit"]
            )

            width = float(
                result["width"]
            )

            lot_size = int(
                result.get(
                    "lot_size",
                    1,
                )
            )

            profit_per_lot = (
                credit * lot_size
            )

            loss_per_lot = (
                (width - credit)
                * lot_size
            )

            breakeven = (
                sell_strike - credit
            )

            writer.writerow({
                "RK": rank,
                "STOCK": result.get(
                    "stock",
                    "",
                ),
                "SPOT": result.get(
                    "spot",
                    "",
                ),
                "SELL": sell_strike,
                "BUY": buy_strike,
                "OTM%": result.get(
                    "otm_percent",
                    "",
                ),
                "OTM PTS": result.get(
                    "otm_points",
                    "",
                ),
                "WIDTH": width,
                "CREDIT": credit,
                "LOT": lot_size,
                "PROFIT/LOT": profit_per_lot,
                "LOSS/LOT": loss_per_lot,
                "BREAKEVEN": breakeven,
                "P:L": result.get(
                    "profit_to_loss",
                    "",
                ),
            })

    print()
    print(
        f"Results saved to: {filename}"
    )

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


print(
    f"Stock-like underlyings: "
    f"{len(underlyings)}"
)

print()


# ============================================================
# SCAN
# ============================================================

all_results = []

successful = 0
failed = 0
zero_candidates = 0

failure_details = []

start = time.time()


for number, stock in enumerate(
    underlyings,
    1,
):

    print(
        f"[{number:03d}/"
        f"{len(underlyings):03d}] "
        f"{stock:<8} ",
        end="",
        flush=True,
    )

    try:

        expiry = (
            choose_expiry(
                nfo,
                stock,
            )
        )

        if not expiry:

            print(
                "NO EXPIRY"
            )

            failed += 1

            failure_details.append(
                (
                    stock,
                    "No expiry",
                )
            )

            continue


        response = (
            breeze
            .get_option_chain_quotes(
                stock_code=stock,
                exchange_code="NFO",
                product_type="options",
                expiry_date=expiry,
                right="put",
            )
        )


        if response.get(
            "Status"
        ) != 200:

            error = response.get(
                "Error",
                "Unknown error",
            )

            print(
                f"FAILED │ "
                f"{error}"
            )

            failed += 1

            failure_details.append(
                (
                    stock,
                    str(error),
                )
            )

            continue


        contracts = (
            response.get(
                "Success"
            )
            or []
        )


        if not contracts:

            print(
                "NO CONTRACTS"
            )

            failed += 1

            failure_details.append(
                (
                    stock,
                    "No contracts",
                )
            )

            continue


        puts, spot = (
            convert_contracts(
                contracts
            )
        )


        if spot is None:

            print(
                "NO SPOT"
            )

            failed += 1

            failure_details.append(
                (
                    stock,
                    "No spot",
                )
            )

            continue


        # ----------------------------------------------------
        # Actual lot size if supplied.
        # Otherwise 1.
        # ----------------------------------------------------

        lot_size = get_lot_size(stock)


        # ----------------------------------------------------
        # BPS SCAN
        # ----------------------------------------------------

        results = scan_bps(

            puts,

            lot_size=lot_size,

            spot=spot,

            min_otm_percent=(
                MIN_OTM_PERCENT
            ),

            max_otm_percent=(
                MAX_OTM_PERCENT
            ),

            max_spread_width=(
                MAX_SPREAD_WIDTH
            ),

            min_profit_to_loss=(
                MIN_PROFIT_TO_LOSS
            ),

            max_profit_to_loss=(
                MAX_PROFIT_TO_LOSS
            ),

            min_oi=MIN_OI,

            min_volume=MIN_VOLUME,
        )


        # ----------------------------------------------------
        # Add stock metadata
        # ----------------------------------------------------

        for result in results:

            result[
                "stock"
            ] = stock

            result[
                "spot"
            ] = spot

            result[
                "expiry"
            ] = expiry

            result[
                "lot_size"
            ] = lot_size

            all_results.append(
                result
            )


        successful += 1


        print(
            f"OK │ "
            f"Spot ₹{spot:,.2f} │ "
            f"Contracts {len(contracts):2d} │ "
            f"BPS {len(results):2d}"
        )


        if not results:

            zero_candidates += 1


        time.sleep(
            API_DELAY
        )


    except Exception as e:

        print(
            f"ERROR │ {e}"
        )

        failed += 1

        failure_details.append(
            (
                stock,
                str(e),
            )
        )


# ============================================================
# GLOBAL RANKING
# ============================================================

all_results.sort(
    key=lambda x: (
        -x[
            "otm_percent"
        ],

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
    print("Ranking: Far OTM → Narrow spread → Better P:L")
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
