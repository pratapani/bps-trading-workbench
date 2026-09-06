import os
import time
from datetime import datetime

from breeze_connect import BreezeConnect
from dotenv import load_dotenv

from bps_engine import Put, scan_bps


# ============================================================
# CONFIGURATION
# ============================================================

EXPIRY = "29-Sep-2026"

TEST_STOCK_COUNT = 10

MIN_OTM_PERCENT = 3.0
MAX_SPREAD_WIDTH = 200

MIN_PROFIT_TO_LOSS = 3.0
MAX_PROFIT_TO_LOSS = 5.0

MIN_OI = 100000
MIN_VOLUME = 100000


# These are indices / non-stock instruments for now
EXCLUDED = {
    "NIFTY",
    "CNXBAN",
    "NIF150",
    "NIFNEX",
    "NIFSEL",
    "NIFFIN",
    "MCX",
}


# ============================================================
# AUTHENTICATION
# ============================================================

load_dotenv()

breeze = BreezeConnect(
    api_key=os.getenv("BREEZE_API_KEY")
)

print("Authenticating...")

breeze.generate_session(
    api_secret=os.getenv("BREEZE_API_SECRET"),
    session_token=os.getenv("BREEZE_SESSION_TOKEN")
)

print("Authentication OK")
print()


# ============================================================
# GET NFO UNIVERSE
# ============================================================

print("Loading NFO contract universe...")

nfo = breeze.stock_script_dict_list[4]

underlyings = sorted(
    set(
        key.split("-")[1]
        for key in nfo
        if key.startswith("OPT-")
        and not key.startswith("OPT-ShortName")
        and f"-{EXPIRY}-" in key
        and key.endswith("-PE")
    )
)

underlyings = [
    x for x in underlyings
    if x not in EXCLUDED
]

print(f"Available stock-like underlyings: {len(underlyings)}")
print()


# ============================================================
# TEST BATCH
# ============================================================

stocks = underlyings[:TEST_STOCK_COUNT]

print("Testing:")
print(", ".join(stocks))
print()


# ============================================================
# SCAN
# ============================================================

all_results = []

successful = 0
failed = 0

start_time = time.time()

for number, stock in enumerate(stocks, 1):

    print(
        f"[{number:02d}/{len(stocks)}] "
        f"{stock:<10}",
        end=" ",
        flush=True
    )

    try:

        response = breeze.get_option_chain_quotes(
            stock_code=stock,
            exchange_code="NFO",
            product_type="options",
            expiry_date=EXPIRY,
            right="put",
        )

        if response.get("Status") != 200:

            print(
                f"FAILED "
                f"Status={response.get('Status')} "
                f"Error={response.get('Error')}"
            )

            failed += 1
            continue

        contracts = response.get("Success") or []

        if not contracts:

            print("NO CONTRACTS")
            failed += 1
            continue

        puts = []
        spot = None

        for x in contracts:

            try:

                strike = float(x.get("strike_price", 0))
                bid = float(x.get("best_bid_price", 0))
                offer = float(x.get("best_offer_price", 0))

                bid_qty = int(
                    float(x.get("best_bid_quantity", 0))
                )

                offer_qty = int(
                    float(x.get("best_offer_quantity", 0))
                )

                oi = float(
                    x.get("open_interest", 0)
                )

                volume = int(
                    float(x.get("total_quantity_traded", 0))
                )

                ltt = x.get("ltt", "")

                if x.get("spot_price") not in (None, ""):
                    spot = float(x["spot_price"])

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

            except (ValueError, TypeError):
                continue

        if spot is None:

            print("NO SPOT")
            failed += 1
            continue

        # ----------------------------------------------------
        # LOT SIZE
        #
        # For now use 1 because the ratio and per-unit
        # calculations do not depend on lot size.
        #
        # We will add the actual lot size before displaying
        # rupee P&L for the full universe.
        # ----------------------------------------------------

        results = scan_bps(
            puts,
            lot_size=1,
            spot=spot,

            min_otm_percent=MIN_OTM_PERCENT,
            max_spread_width=MAX_SPREAD_WIDTH,

            min_profit_to_loss=MIN_PROFIT_TO_LOSS,
            max_profit_to_loss=MAX_PROFIT_TO_LOSS,

            min_oi=MIN_OI,
            min_volume=MIN_VOLUME,
        )

        for r in results:

            r["stock"] = stock
            r["spot"] = spot

        all_results.extend(results)

        print(
            f"OK "
            f"Spot=₹{spot:,.2f} "
            f"Contracts={len(contracts)} "
            f"BPS={len(results)}"
        )

        successful += 1

        # Small delay to be polite to the API
        time.sleep(0.2)

    except Exception as e:

        print(f"ERROR: {e}")
        failed += 1


# ============================================================
# RANK ALL RESULTS
# ============================================================

all_results.sort(
    key=lambda x: (
        -x["otm_percent"],
        x["width"],
        x["profit_to_loss"],
    )
)


# ============================================================
# SUMMARY
# ============================================================

elapsed = time.time() - start_time

print()
print("=" * 110)
print("UNIVERSE SCAN COMPLETE")
print("=" * 110)

print(f"Stocks attempted : {len(stocks)}")
print(f"Successful       : {successful}")
print(f"Failed           : {failed}")
print(f"BPS candidates   : {len(all_results)}")
print(f"Time             : {elapsed:.2f} seconds")
print()


# ============================================================
# RESULTS
# ============================================================

if not all_results:

    print("No qualifying BPS candidates found.")

else:

    print(
        f"{'RANK':>4} "
        f"{'STOCK':<10} "
        f"{'SPOT':>9} "
        f"{'SELL':>7} "
        f"{'BUY':>7} "
        f"{'OTM%':>7} "
        f"{'OTM PTS':>8} "
        f"{'WIDTH':>7} "
        f"{'CREDIT':>9} "
        f"{'P:L':>8}"
    )

    print("-" * 110)

    for rank, x in enumerate(all_results, 1):

        print(
            f"{rank:>4} "
            f"{x['stock']:<10} "
            f"₹{x['spot']:>7,.2f} "
            f"{x['sell_strike']:>7.0f} "
            f"{x['buy_strike']:>7.0f} "
            f"{x['otm_percent']:>6.2f}% "
            f"{x['otm_points']:>8.0f} "
            f"{x['width']:>7.0f} "
            f"₹{x['credit']:>7.2f} "
            f"1:{x['profit_to_loss']:<5.2f}"
        )
