import os
import csv
import time
from datetime import datetime

from breeze_connect import BreezeConnect
from dotenv import load_dotenv

from bps_engine import Put, scan_bps


# ============================================================
# BPS UNIVERSE SCANNER
# ============================================================
#
# Live Breeze NFO universe
#
# Execution assumption:
#   SELL PUT -> BID
#   BUY PUT  -> OFFER
#
# Ranking:
#   1. Farther OTM
#   2. Narrower spread
#   3. Better Profit : Max Loss
#
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

# Number of stocks:
# 0 = scan ALL available stock-like underlyings
MAX_STOCKS = 0


# OTM filter
MIN_OTM_PERCENT = 3.0
MAX_OTM_PERCENT = 8.0


# Maximum distance between short and long put strikes
MAX_SPREAD_WIDTH = 200


# Desired Profit : Max Loss
#
# Example:
#   3.0 = minimum 1:3
#   5.0 = maximum 1:5
#
MIN_PROFIT_TO_LOSS = 3.0
MAX_PROFIT_TO_LOSS = 5.0


# Liquidity filters
MIN_OI = 100000
MIN_VOLUME = 100000


# Small delay between API calls
API_DELAY = 0.20


# Expiry selection
#
# The scanner will inspect Breeze's NFO contract dictionary
# and choose the earliest available expiry for each stock.
#
# We are currently targeting this expiry because that is what
# your live tests confirmed.
PREFERRED_EXPIRY = "29-Sep-2026"


# Exclude indices / non-stock instruments
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
# OPTIONAL LOT SIZE FILE
# ============================================================
#
# Breeze's NFO dictionary does NOT expose lot size.
#
# If lot_sizes.csv exists, format:
#
# stock,lot_size
# BSE,200
# TCS,175
# RELIND,250
#
# Until supplied, lot size is treated as 1.
#
# This prevents us from displaying false ₹ P&L figures.
# ============================================================

LOT_SIZE_FILE = "lot_sizes.csv"


def load_lot_sizes():

    lot_sizes = {}

    if not os.path.exists(LOT_SIZE_FILE):
        return lot_sizes

    try:

        with open(
            LOT_SIZE_FILE,
            "r",
            newline="",
            encoding="utf-8",
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                stock = row.get("stock", "").strip()

                try:
                    lot = int(float(row.get("lot_size", 0)))
                except (ValueError, TypeError):
                    continue

                if stock and lot > 0:
                    lot_sizes[stock] = lot

    except Exception as e:

        print(
            f"WARNING: Could not read {LOT_SIZE_FILE}: {e}"
        )

    return lot_sizes


LOT_SIZES = load_lot_sizes()


# ============================================================
# HELPERS
# ============================================================

def fmt_money(value):
    return f"₹{value:,.2f}"


def fmt_int(value):
    return f"{value:,.0f}"


def get_available_expiries(nfo, stock):

    expiries = set()

    prefix = f"OPT-{stock}-"

    for key in nfo:

        if not key.startswith(prefix):
            continue

        parts = key.split("-")

        # OPT STOCK DD Mon YYYY STRIKE PE
        if len(parts) < 7:
            continue

        expiry = "-".join(parts[2:5])

        expiries.add(expiry)

    return sorted(
        expiries,
        key=lambda x: datetime.strptime(x, "%d-%b-%Y")
    )


def choose_expiry(nfo, stock):

    expiries = get_available_expiries(nfo, stock)

    if not expiries:
        return None

    # Prefer our confirmed current expiry if available.
    if PREFERRED_EXPIRY in expiries:
        return PREFERRED_EXPIRY

    # Otherwise use earliest available expiry.
    return expiries[0]


def convert_contracts(contracts):

    puts = []
    spot = None

    for x in contracts:

        try:

            strike = float(
                x.get("strike_price", 0)
            )

            bid = float(
                x.get("best_bid_price", 0)
            )

            offer = float(
                x.get("best_offer_price", 0)
            )

            bid_qty = int(
                float(
                    x.get(
                        "best_bid_quantity",
                        0
                    )
                )
            )

            offer_qty = int(
                float(
                    x.get(
                        "best_offer_quantity",
                        0
                    )
                )
            )

            oi = float(
                x.get(
                    "open_interest",
                    0
                )
            )

            volume = int(
                float(
                    x.get(
                        "total_quantity_traded",
                        0
                    )
                )
            )

            ltt = x.get("ltt", "")

            if x.get("spot_price") not in (
                None,
                "",
            ):

                spot = float(
                    x["spot_price"]
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
# AUTHENTICATION
# ============================================================

load_dotenv()

api_key = os.getenv("BREEZE_API_KEY")
api_secret = os.getenv("BREEZE_API_SECRET")
session_token = os.getenv("BREEZE_SESSION_TOKEN")


if not api_key or not api_secret or not session_token:

    print()
    print("ERROR: Breeze credentials missing.")
    print()
    print(
        "Required in .env:"
    )
    print(
        "BREEZE_API_KEY"
    )
    print(
        "BREEZE_API_SECRET"
    )
    print(
        "BREEZE_SESSION_TOKEN"
    )

    raise SystemExit(1)


breeze = BreezeConnect(
    api_key=api_key
)


print("=" * 120)
print("BPS UNIVERSE SCANNER")
print("=" * 120)
print()

print("Authenticating...")

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


print("Authentication OK")
print()


# ============================================================
# LOAD NFO UNIVERSE
# ============================================================

print("Loading Breeze NFO contract universe...")

try:

    nfo = breeze.stock_script_dict_list[4]

except Exception as e:

    print(
        f"Could not load NFO universe: {e}"
    )

    raise SystemExit(1)


print(
    f"NFO contracts loaded: {len(nfo):,}"
)


# ============================================================
# DISCOVER UNDERLYINGS
# ============================================================

underlyings = set()

for key in nfo:

    if not key.startswith("OPT-"):
        continue

    if key.startswith(
        "OPT-ShortName"
    ):
        continue

    parts = key.split("-")

    if len(parts) < 7:
        continue

    stock = parts[1]

    right = parts[-1]

    if right != "PE":
        continue

    if stock in EXCLUDED:
        continue

    underlyings.add(stock)


underlyings = sorted(underlyings)


if MAX_STOCKS > 0:

    underlyings = underlyings[
        :MAX_STOCKS
    ]


print(
    f"Stock-like underlyings: "
    f"{len(underlyings)}"
)

print()

print(
    "Configuration:"
)

print(
    f"  OTM             : "
    f"{MIN_OTM_PERCENT:.2f}% "
    f"to "
    f"{MAX_OTM_PERCENT:.2f}%"
)

print(
    f"  Max width       : "
    f"{MAX_SPREAD_WIDTH}"
)

print(
    f"  Profit:Loss     : "
    f"1:{MIN_PROFIT_TO_LOSS:.1f} "
    f"to "
    f"1:{MAX_PROFIT_TO_LOSS:.1f}"
)

print(
    f"  Minimum OI      : "
    f"{MIN_OI:,}"
)

print(
    f"  Minimum volume  : "
    f"{MIN_VOLUME:,}"
)

print(
    f"  Lot sizes loaded: "
    f"{len(LOT_SIZES)}"
)

print()


# ============================================================
# SCAN
# ============================================================

all_results = []

successful = 0
failed = 0
no_candidates = 0

failure_details = []

start_time = time.time()


for number, stock in enumerate(
    underlyings,
    1,
):

    print(
        f"[{number:03d}/{len(underlyings):03d}] "
        f"{stock:<8} ",
        end="",
        flush=True,
    )

    try:

        expiry = choose_expiry(
            nfo,
            stock,
        )

        if not expiry:

            print(
                "NO EXPIRY"
            )

            failed += 1

            failure_details.append(
                (
                    stock,
                    "No expiry"
                )
            )

            continue


        response = (
            breeze.get_option_chain_quotes(
                stock_code=stock,
                exchange_code="NFO",
                product_type="options",
                expiry_date=expiry,
                right="put",
            )
        )


        if response.get("Status") != 200:

            error = response.get(
                "Error",
                "Unknown error",
            )

            print(
                f"FAILED "
                f"Status={response.get('Status')} "
                f"{error}"
            )

            failed += 1

            failure_details.append(
                (
                    stock,
                    str(error)
                )
            )

            continue


        contracts = (
            response.get("Success")
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
                    "No contracts"
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
                    "No spot price"
                )
            )

            continue


        # ----------------------------------------------------
        # LOT SIZE
        # ----------------------------------------------------

        lot_size = LOT_SIZES.get(
            stock,
            1,
        )


        # ----------------------------------------------------
        # BPS ENGINE
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


        for result in results:

            result["stock"] = stock
            result["spot"] = spot
            result["expiry"] = expiry
            result["lot_size"] = lot_size

            all_results.append(
                result
            )


        successful += 1


        if results:

            print(
                f"OK "
                f"Spot={spot:,.2f} "
                f"Contracts={len(contracts)} "
                f"BPS={len(results)}"
            )

        else:

            no_candidates += 1

            print(
                f"OK "
                f"Spot={spot:,.2f} "
                f"Contracts={len(contracts)} "
                f"BPS=0"
            )


        time.sleep(
            API_DELAY
        )


    except Exception as e:

        print(
            f"ERROR: {e}"
        )

        failed += 1

        failure_details.append(
            (
                stock,
                str(e)
            )
        )


# ============================================================
# RANK
# ============================================================

#
# Ranking priority:
#
# 1. Far OTM
# 2. Narrow spread
# 3. Better Profit:Loss
#
# ------------------------------------------------------------

all_results.sort(
    key=lambda x: (
        -x.get(
            "otm_percent",
            0,
        ),

        x.get(
            "width",
            999999,
        ),

        x.get(
            "profit_to_loss",
            999999,
        ),
    )
)


elapsed = (
    time.time()
    - start_time
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 120)
print("SCAN COMPLETE")
print("=" * 120)

print(
    f"Stocks scanned     : "
    f"{len(underlyings)}"
)

print(
    f"Successful         : "
    f"{successful}"
)

print(
    f"Failed             : "
    f"{failed}"
)

print(
    f"No BPS candidates  : "
    f"{no_candidates}"
)

print(
    f"Total BPS          : "
    f"{len(all_results)}"
)

print(
    f"Elapsed time       : "
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

    print("=" * 180)
    print("TOP BULL PUT SPREAD OPPORTUNITIES")
    print("=" * 180)

    print()

    header = (
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
        f"{'LOT':>6} │ "
        f"{'MAX PROFIT':>13} │ "
        f"{'MAX LOSS':>13} │ "
        f"{'P:L':>7}"
    )

    print(header)

    print("-" * 180)


    for rank, x in enumerate(
        all_results,
        1,
    ):

        lot = x.get(
            "lot_size",
            1,
        )


        # If actual lot size is unavailable,
        # the engine calculated using 1.
        max_profit = x.get(
            "max_profit",
            0,
        )

        max_loss = x.get(
            "max_loss",
            0,
        )


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
            f"{lot:>6} │ "
            f"₹{max_profit:>11,.2f} │ "
            f"₹{max_loss:>11,.2f} │ "
            f"1:{x['profit_to_loss']:<5.2f}"
        )


# ============================================================
# EXECUTION RULES
# ============================================================

print()

print("=" * 120)
print("EXECUTION / INTERPRETATION")
print("=" * 120)

print()

print(
    "SELL leg  → use REAL BID"
)

print(
    "BUY leg   → use REAL OFFER"
)

print(
    "CREDIT    → SELL BID − BUY OFFER"
)

print(
    "OTM       → based on SELL PUT strike vs spot"
)

print(
    "Ranking   → Far OTM → Narrow spread → Better P:L"
)

print(
    f"Filter    → OTM {MIN_OTM_PERCENT:.1f}%–"
    f"{MAX_OTM_PERCENT:.1f}%"
)

print(
    f"Filter    → Profit:Max Loss "
    f"1:{MIN_PROFIT_TO_LOSS:.1f}–"
    f"1:{MAX_PROFIT_TO_LOSS:.1f}"
)

if not LOT_SIZES:

    print()

    print(
        "WARNING: No lot-size file loaded."
    )

    print(
        "₹ MAX PROFIT / MAX LOSS are currently"
        " PER SHARE."
    )

    print(
        "Add lot_sizes.csv when actual lot sizes"
        " are available."
    )


# ============================================================
# FAILURE SUMMARY
# ============================================================

if failure_details:

    print()

    print("=" * 120)
    print("FAILED / SKIPPED STOCKS")
    print("=" * 120)

    for stock, reason in failure_details:

        print(
            f"{stock:<10} │ {reason}"
        )


# ============================================================
# SAVE CSV
# ============================================================

csv_file = "bps_results.csv"

if all_results:

    fieldnames = [
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
    ]

    try:

        with open(
            csv_file,
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )

            writer.writeheader()

            for rank, x in enumerate(
                all_results,
                1,
            ):

                row = dict(x)

                row["rank"] = rank

                writer.writerow(
                    row
                )


        print()

        print(
            f"Results saved to: "
            f"{csv_file}"
        )


    except Exception as e:

        print()

        print(
            f"Could not save CSV: {e}"
        )


print()
print("=" * 120)
print("DONE")
print("=" * 120)
