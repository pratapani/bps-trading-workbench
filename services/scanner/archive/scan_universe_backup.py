import os
import csv
import time
from datetime import datetime

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
# LOT SIZE FILE
# ============================================================
#
# Optional.
#
# Example:
#
# stock,lot_size
# TCS,175
# BSE,200
#
# Until populated, lot size = 1.
#
# Therefore max profit/max loss will be PER UNIT.
# ============================================================


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

def save_results(
    results,
):

    if not results:
        return

    filename = (
        "bps_results.csv"
    )

    fields = [
        "rank",
        "stock",
        "spot",
        "expiry",

        "sell_strike",
        "sell_bid",
        "sell_offer",

        "buy_strike",
        "buy_bid",
        "buy_offer",

        "otm_percent",
        "otm_points",

        "width",
        "credit",

        "lot_size",

        "max_profit",
        "max_loss",

        "profit_to_loss",

        "sell_oi",
        "sell_volume",

        "buy_oi",
        "buy_volume",
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
            extrasaction="ignore",
        )

        writer.writeheader()

        for rank, result in enumerate(
            results,
            1,
        ):

            row = dict(
                result
            )

            row[
                "rank"
            ] = rank

            writer.writerow(
                row
            )

    print()
    print(
        f"Results saved to: "
        f"{filename}"
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

    print(
        "NO QUALIFYING BPS FOUND."
    )

else:

    print("=" * 200)
    print(
        "TOP BULL PUT SPREAD OPPORTUNITIES"
    )
    print("=" * 200)

    print()

    print(
        f"{'RK':>3} │ "
        f"{'STOCK':<8} │ "
        f"{'SPOT':>10} │ "
        f"{'SELL':>7} │ "
        f"{'S-BID':>8} │ "
        f"{'S-OFF':>8} │ "
        f"{'BUY':>7} │ "
        f"{'B-BID':>8} │ "
        f"{'B-OFF':>8} │ "
        f"{'OTM%':>7} │ "
        f"{'OTM PTS':>8} │ "
        f"{'WIDTH':>7} │ "
        f"{'CREDIT':>9} │ "
        f"{'LOT':>7} │ "
        f"{'MAX PROFIT':>13} │ "
        f"{'MAX LOSS':>13} │ "
        f"{'P:L':>7}"
    )

    print(
        "-" * 200
    )


    for rank, x in enumerate(
        all_results,
        1,
    ):

        print(
            f"{rank:>3} │ "
            f"{x['stock']:<8} │ "
            f"₹{x['spot']:>8,.2f} │ "
            f"{x['sell_strike']:>7.0f} │ "
            f"₹{x['sell_bid']:>6.2f} │ "
            f"₹{x['sell_offer']:>6.2f} │ "
            f"{x['buy_strike']:>7.0f} │ "
            f"₹{x['buy_bid']:>6.2f} │ "
            f"₹{x['buy_offer']:>6.2f} │ "
            f"{x['otm_percent']:>6.2f}% │ "
            f"{x['otm_points']:>8.0f} │ "
            f"{x['width']:>7.0f} │ "
            f"₹{x['credit']:>7.2f} │ "
            f"{x['lot_size']:>7} │ "
            f"₹{x['max_profit']:>11,.2f} │ "
            f"₹{x['max_loss']:>11,.2f} │ "
            f"1:{x['profit_to_loss']:<5.2f}"
        )


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


if not STOCK_LOTS:

    print()

    print(
        "NOTE: Actual lot sizes are not loaded."
    )

    print(
        "MAX PROFIT / MAX LOSS are PER UNIT."
    )

    print(
        "This does NOT affect the Profit:Loss ratio."
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

save_results(
    all_results
)


print()
print("=" * 120)
print("DONE")
print("=" * 120)
