from dataclasses import dataclass
from typing import List


@dataclass
class Put:
    strike: float
    bid: float
    offer: float
    bid_qty: int
    offer_qty: int
    oi: float
    volume: int
    ltt: str


def calculate_bps(short_put: Put, long_put: Put, lot_size: int, spot: float):

    # Short put must be higher strike than long put
    if short_put.strike <= long_put.strike:
        return None

    # Short put must be OTM
    if short_put.strike >= spot:
        return None

    # Need executable prices
    if short_put.bid <= 0:
        return None

    if long_put.offer <= 0:
        return None

    width = short_put.strike - long_put.strike

    # Actual executable credit
    credit = short_put.bid - long_put.offer

    if credit <= 0:
        return None

    max_profit_per_unit = credit
    max_loss_per_unit = width - credit

    if max_loss_per_unit <= 0:
        return None

    max_profit = max_profit_per_unit * lot_size
    max_loss = max_loss_per_unit * lot_size

    # Profit : Max Loss = 1:X
    profit_to_loss = max_loss / max_profit

    # Distance of short strike from spot
    otm_points = spot - short_put.strike

    # Percentage OTM
    otm_percent = (otm_points / spot) * 100

    return {

        # ----------------------------------------------------
        # SHORT PUT
        # ----------------------------------------------------

        "sell_strike": short_put.strike,
        "sell_bid": short_put.bid,
        "sell_offer": short_put.offer,
        "sell_bid_qty": short_put.bid_qty,
        "sell_offer_qty": short_put.offer_qty,
        "sell_oi": short_put.oi,
        "sell_volume": short_put.volume,
        "sell_ltt": short_put.ltt,

        # ----------------------------------------------------
        # LONG PUT
        # ----------------------------------------------------

        "buy_strike": long_put.strike,
        "buy_bid": long_put.bid,
        "buy_offer": long_put.offer,
        "buy_bid_qty": long_put.bid_qty,
        "buy_offer_qty": long_put.offer_qty,
        "buy_oi": long_put.oi,
        "buy_volume": long_put.volume,
        "buy_ltt": long_put.ltt,

        # ----------------------------------------------------
        # SPREAD
        # ----------------------------------------------------

        "width": width,
        "credit": credit,
        "max_profit": max_profit,
        "max_loss": max_loss,

        # ----------------------------------------------------
        # OTM
        # ----------------------------------------------------

        "otm_points": otm_points,
        "otm_percent": otm_percent,

        # ----------------------------------------------------
        # PROFIT : MAX LOSS
        # ----------------------------------------------------

        "profit_to_loss": profit_to_loss,
    }


def scan_bps(
    puts: List[Put],
    lot_size: int,
    spot: float,

    # OTM
    min_otm_percent: float = 3.0,

    # Spread width
    max_spread_width: float = 200,

    # Profit : Max Loss
    min_profit_to_loss: float = 3.0,
    max_profit_to_loss: float = 5.0,

    # Liquidity
    min_oi: float = 0,
    min_volume: int = 0,
):

    results = []

    for short_put in puts:

        # Must have a real bid
        if short_put.bid <= 0:
            continue

        # Liquidity
        if short_put.oi < min_oi:
            continue

        if short_put.volume < min_volume:
            continue

        # Calculate OTM
        otm_points = spot - short_put.strike
        otm_percent = (otm_points / spot) * 100

        # Minimum OTM requirement
        if otm_percent < min_otm_percent:
            continue

        for long_put in puts:

            # Long strike must be below short strike
            if long_put.strike >= short_put.strike:
                continue

            # Spread width
            width = short_put.strike - long_put.strike

            if width > max_spread_width:
                continue

            # Need executable offer
            if long_put.offer <= 0:
                continue

            # Liquidity
            if long_put.oi < min_oi:
                continue

            if long_put.volume < min_volume:
                continue

            result = calculate_bps(
                short_put,
                long_put,
                lot_size,
                spot
            )

            if not result:
                continue

            ratio = result["profit_to_loss"]

            # Desired Profit : Max Loss
            if ratio < min_profit_to_loss:
                continue

            if ratio > max_profit_to_loss:
                continue

            results.append(result)

    # --------------------------------------------------------
    # RANKING
    #
    # 1. Farther OTM first
    # 2. Narrower spread
    # 3. Better Profit : Max Loss
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            -x["otm_percent"],
            x["width"],
            x["profit_to_loss"],
        )
    )

    return results


def print_results(results, spot, expiry, lot_size):

    print()
    print("=" * 170)
    print("BULL PUT SPREAD SCANNER")
    print("=" * 170)

    print(f"Spot   : ₹{spot:,.2f}")
    print(f"Expiry : {expiry}")
    print(f"Lot    : {lot_size}")
    print()

    if not results:
        print("No qualifying BPS found.")
        return

    print(
        f"{'SELL':>7} "
        f"{'S-BID':>8} "
        f"{'S-OFF':>8} "
        f"{'BUY':>7} "
        f"{'B-BID':>8} "
        f"{'B-OFF':>8} "
        f"{'OTM%':>7} "
        f"{'OTM PTS':>8} "
        f"{'WIDTH':>7} "
        f"{'CREDIT':>9} "
        f"{'MAX PROFIT':>12} "
        f"{'MAX LOSS':>12} "
        f"{'PROFIT:LOSS':>13}"
    )

    print("-" * 170)

    for x in results:

        print(
            f"{x['sell_strike']:>7.0f} "
            f"{x['sell_bid']:>8.2f} "
            f"{x['sell_offer']:>8.2f} "
            f"{x['buy_strike']:>7.0f} "
            f"{x['buy_bid']:>8.2f} "
            f"{x['buy_offer']:>8.2f} "
            f"{x['otm_percent']:>6.2f}% "
            f"{x['otm_points']:>8.0f} "
            f"{x['width']:>7.0f} "
            f"{x['credit']:>9.2f} "
            f"₹{x['max_profit']:>10,.0f} "
            f"₹{x['max_loss']:>10,.0f} "
            f"1:{x['profit_to_loss']:<11.2f}"
        )

    print()
    print("EXECUTION:")
    print("  SELL leg → BID")
    print("  BUY leg  → OFFER")
    print("  CREDIT   → SELL BID - BUY OFFER")
    print("  Ranking  → Far OTM → Narrow spread → Better Profit:Max Loss")
