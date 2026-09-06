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


def calculate_bps(
    short_put: Put,
    long_put: Put,
    lot_size: int,
    spot: float,
):
    """
    Calculate a bull put spread.

    Short leg:
        Higher strike PUT
        Executed at BID

    Long leg:
        Lower strike PUT
        Executed at OFFER

    Credit:
        short BID - long OFFER
    """

    # --------------------------------------------------------
    # Strike relationship
    # --------------------------------------------------------

    if short_put.strike <= long_put.strike:
        return None

    # --------------------------------------------------------
    # Both legs need executable prices
    # --------------------------------------------------------

    if short_put.bid <= 0:
        return None

    if long_put.offer <= 0:
        return None

    # --------------------------------------------------------
    # Spread width
    # --------------------------------------------------------

    width = (
        short_put.strike
        - long_put.strike
    )

    if width <= 0:
        return None

    # --------------------------------------------------------
    # Executable credit
    # --------------------------------------------------------

    credit = (
        short_put.bid
        - long_put.offer
    )

    if credit <= 0:
        return None

    # --------------------------------------------------------
    # Maximum loss
    # --------------------------------------------------------

    max_loss_per_unit = (
        width - credit
    )

    if max_loss_per_unit <= 0:
        return None

    # --------------------------------------------------------
    # Profit / Loss
    # --------------------------------------------------------

    max_profit_per_unit = credit

    max_profit = (
        max_profit_per_unit
        * lot_size
    )

    max_loss = (
        max_loss_per_unit
        * lot_size
    )

    if max_profit <= 0:
        return None

    profit_to_loss = (
        max_loss
        / max_profit
    )

    # --------------------------------------------------------
    # OTM calculation
    #
    # Short PUT is the important strike.
    # --------------------------------------------------------

    otm_points = (
        spot
        - short_put.strike
    )

    if otm_points <= 0:
        return None

    otm_percent = (
        otm_points
        / spot
        * 100
    )

    return {
        "sell_strike": short_put.strike,

        "sell_bid": short_put.bid,
        "sell_offer": short_put.offer,

        "sell_bid_qty": short_put.bid_qty,
        "sell_offer_qty": short_put.offer_qty,

        "sell_oi": short_put.oi,
        "sell_volume": short_put.volume,
        "sell_ltt": short_put.ltt,

        "buy_strike": long_put.strike,

        "buy_bid": long_put.bid,
        "buy_offer": long_put.offer,

        "buy_bid_qty": long_put.bid_qty,
        "buy_offer_qty": long_put.offer_qty,

        "buy_oi": long_put.oi,
        "buy_volume": long_put.volume,
        "buy_ltt": long_put.ltt,

        "width": width,

        "credit": credit,

        "max_profit_per_unit":
            max_profit_per_unit,

        "max_loss_per_unit":
            max_loss_per_unit,

        "max_profit":
            max_profit,

        "max_loss":
            max_loss,

        "profit_to_loss":
            profit_to_loss,

        "otm_points":
            otm_points,

        "otm_percent":
            otm_percent,
    }


def scan_bps(
    puts: List[Put],
    lot_size: int = 1,
    spot: float = 0,

    min_otm_percent: float = 3.0,
    max_otm_percent: float = 8.0,

    max_spread_width: float = 200,

    min_profit_to_loss: float = 3.0,
    max_profit_to_loss: float = 5.0,

    min_oi: float = 100000,
    min_volume: float = 100000,
):
    """
    Find qualifying bull put spreads.
    """

    if spot <= 0:
        return []

    results = []

    # --------------------------------------------------------
    # Compare every higher-strike PUT with every lower-strike
    # PUT.
    # --------------------------------------------------------

    for short_put in puts:

        # ----------------------------------------------------
        # Liquidity on short leg
        # ----------------------------------------------------

        if short_put.oi < min_oi:
            continue

        if short_put.volume < min_volume:
            continue

        # ----------------------------------------------------
        # Short strike must be below spot
        # ----------------------------------------------------

        if short_put.strike >= spot:
            continue

        # ----------------------------------------------------
        # OTM
        # ----------------------------------------------------

        otm_points = (
            spot
            - short_put.strike
        )

        otm_percent = (
            otm_points
            / spot
            * 100
        )

        if otm_percent < min_otm_percent:
            continue

        if (
            max_otm_percent is not None
            and otm_percent > max_otm_percent
        ):
            continue

        for long_put in puts:

            # ------------------------------------------------
            # Long strike must be lower
            # ------------------------------------------------

            if (
                long_put.strike
                >= short_put.strike
            ):
                continue

            # ------------------------------------------------
            # Long leg liquidity
            # ------------------------------------------------

            if long_put.oi < min_oi:
                continue

            if long_put.volume < min_volume:
                continue

            # ------------------------------------------------
            # Width
            # ------------------------------------------------

            width = (
                short_put.strike
                - long_put.strike
            )

            if width <= 0:
                continue

            if width > max_spread_width:
                continue

            # ------------------------------------------------
            # Calculate
            # ------------------------------------------------

            result = calculate_bps(
                short_put,
                long_put,
                lot_size,
                spot,
            )

            if result is None:
                continue

            # ------------------------------------------------
            # Profit : Loss
            #
            # Displayed as 1:X
            #
            # Example:
            #   1:3.07
            # means max loss is 3.07 times profit.
            # ------------------------------------------------

            ratio = result[
                "profit_to_loss"
            ]

            if ratio < min_profit_to_loss:
                continue

            if ratio > max_profit_to_loss:
                continue

            results.append(result)

    # --------------------------------------------------------
    # Ranking
    #
    # 1. Far OTM
    # 2. Narrow spread
    # 3. Better Profit : Loss
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            -x["otm_percent"],
            x["width"],
            x["profit_to_loss"],
        )
    )

    return results


def print_results(
    results,
    spot,
    expiry,
    lot_size=1,
):
    """
    Display BPS results in a readable table.
    """

    print()
    print("=" * 180)
    print("BULL PUT SPREAD SCANNER")
    print("=" * 180)

    print(
        f"Spot   : ₹{spot:,.2f}"
    )

    print(
        f"Expiry : {expiry}"
    )

    print(
        f"Lot    : {lot_size}"
    )

    print()

    if not results:

        print(
            "No qualifying BPS found."
        )

        return

    header = (
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
        f"{'MAX PROFIT':>13} │ "
        f"{'MAX LOSS':>13} │ "
        f"{'P:L':>7}"
    )

    print(header)

    print("-" * 180)

    for x in results:

        print(
            f"{x['sell_strike']:>7.0f} │ "
            f"{x['sell_bid']:>8.2f} │ "
            f"{x['sell_offer']:>8.2f} │ "
            f"{x['buy_strike']:>7.0f} │ "
            f"{x['buy_bid']:>8.2f} │ "
            f"{x['buy_offer']:>8.2f} │ "
            f"{x['otm_percent']:>6.2f}% │ "
            f"{x['otm_points']:>8.0f} │ "
            f"{x['width']:>7.0f} │ "
            f"₹{x['credit']:>7.2f} │ "
            f"₹{x['max_profit']:>11,.2f} │ "
            f"₹{x['max_loss']:>11,.2f} │ "
            f"1:{x['profit_to_loss']:<5.2f}"
        )

    print()

    print("EXECUTION:")
    print(
        "  SELL leg → BID"
    )
    print(
        "  BUY leg  → OFFER"
    )
    print(
        "  CREDIT   → SELL BID − BUY OFFER"
    )
    print(
        "  Ranking  → Far OTM → Narrow spread → Better Profit:Max Loss"
    )
