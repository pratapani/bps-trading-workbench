from dataclasses import dataclass
from typing import List
import math
from datetime import datetime
from zoneinfo import ZoneInfo


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
    bid_iv: float = 0.0
    offer_iv: float = 0.0



# ============================================================
# IMPLIED VOLATILITY
# ============================================================

RISK_FREE_RATE = 0.06
DIVIDEND_YIELD = 0.0
IST = ZoneInfo("Asia/Kolkata")


def normal_cdf(x):
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_put_price(
    spot,
    strike,
    time_to_expiry,
    volatility,
    risk_free_rate=RISK_FREE_RATE,
    dividend_yield=DIVIDEND_YIELD,
):
    """Calculate European put value using Black-Scholes."""

    if spot <= 0 or strike <= 0 or time_to_expiry <= 0 or volatility <= 0:
        return max(strike - spot, 0.0)

    sqrt_t = math.sqrt(time_to_expiry)

    d1 = (
        math.log(spot / strike)
        + (
            risk_free_rate
            - dividend_yield
            + 0.5 * volatility * volatility
        ) * time_to_expiry
    ) / (volatility * sqrt_t)

    d2 = d1 - volatility * sqrt_t

    return (
        strike * math.exp(-risk_free_rate * time_to_expiry) * normal_cdf(-d2)
        - spot * math.exp(-dividend_yield * time_to_expiry) * normal_cdf(-d1)
    )


def calculate_time_to_expiry(expiry):
    """Years remaining until 3:30 PM IST on expiry date."""
    try:
        expiry_text = expiry
        if isinstance(expiry, str) and expiry[4:5] == "-":
            expiry_text = expiry[:10]
        expiry_dt = datetime.strptime(
            expiry_text,
            "%Y-%m-%d" if isinstance(expiry_text, str) and expiry_text[4:5] == "-" else "%d-%b-%Y",
        ).replace(
            hour=15, minute=30, second=0, microsecond=0, tzinfo=IST
        )
        now = datetime.now(IST)
        seconds = (expiry_dt - now).total_seconds()
        return max(seconds / (365.0 * 24.0 * 60.0 * 60.0), 0.0)
    except Exception:
        return 0.0


def calculate_put_iv(
    option_price,
    spot,
    strike,
    expiry,
    risk_free_rate=RISK_FREE_RATE,
    dividend_yield=DIVIDEND_YIELD,
):
    """
    Calculate implied volatility for a European put.

    SELL leg: use BID.
    BUY leg: use OFFER.

    Returns IV as a percentage, e.g. 24.5 means 24.5%.
    """
    try:
        option_price = float(option_price)
        spot = float(spot)
        strike = float(strike)
    except (TypeError, ValueError):
        return 0.0

    if option_price <= 0 or spot <= 0 or strike <= 0:
        return 0.0

    time_to_expiry = calculate_time_to_expiry(expiry)
    if time_to_expiry <= 0:
        return 0.0

    lower_bound = max(
        strike * math.exp(-risk_free_rate * time_to_expiry)
        - spot * math.exp(-dividend_yield * time_to_expiry),
        0.0,
    )

    if option_price < lower_bound:
        return 0.0

    low = 0.0001
    high = 5.0

    low_price = black_scholes_put_price(
        spot, strike, time_to_expiry, low,
        risk_free_rate, dividend_yield
    )
    high_price = black_scholes_put_price(
        spot, strike, time_to_expiry, high,
        risk_free_rate, dividend_yield
    )

    if option_price < low_price or option_price > high_price:
        return 0.0

    for _ in range(100):
        mid = (low + high) / 2.0
        mid_price = black_scholes_put_price(
            spot, strike, time_to_expiry, mid,
            risk_free_rate, dividend_yield
        )

        if abs(mid_price - option_price) < 0.000001:
            return mid * 100.0

        if mid_price < option_price:
            low = mid
        else:
            high = mid

    return ((low + high) / 2.0) * 100.0


def calculate_bps(
    short_put: Put,
    long_put: Put,
    lot_size: int,
    spot: float,
    expiry=None,
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
    # EXECUTION PRICING
    #
    # Bull Put Spread:
    #   SELL higher-strike PE -> BID
    #   BUY  lower-strike PE  -> OFFER
    #
    # Therefore the scanner must use the executable-side
    # prices, not the opposite sides of the market.
    # --------------------------------------------------------

    sell_execution_price = short_put.bid
    buy_execution_price = long_put.offer

    credit = (
        sell_execution_price
        - buy_execution_price
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

    if expiry:
        short_put.bid_iv = calculate_put_iv(
            short_put.bid,
            spot,
            short_put.strike,
            expiry,
        )
        long_put.offer_iv = calculate_put_iv(
            long_put.offer,
            spot,
            long_put.strike,
            expiry,
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
        "sell_iv": short_put.bid_iv,

        "buy_strike": long_put.strike,

        "buy_bid": long_put.bid,
        "buy_offer": long_put.offer,

        "buy_bid_qty": long_put.bid_qty,
        "buy_offer_qty": long_put.offer_qty,

        "buy_oi": long_put.oi,
        "buy_volume": long_put.volume,
        "buy_ltt": long_put.ltt,
        "buy_iv": long_put.offer_iv,

        "width": width,

        # Prices actually used to calculate the scanner credit.
        "execution_sell_price": sell_execution_price,
        "execution_buy_price": buy_execution_price,

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
    expiry=None,

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
                expiry=expiry,
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
    # 2. Higher short-leg IV
    # 3. Narrow spread
    # 4. Better Profit : Loss
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            -x["otm_percent"],
            -x["sell_iv"],
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
        f"{'S-IV':>7} │ "
        f"{'B-IV':>7} │ "
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
            f"{x['sell_iv']:>7.2f} │ "
            f"{x['buy_iv']:>7.2f} │ "
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
        "  Ranking  → Far OTM → Higher sell IV → Narrow spread → Better Profit:Max Loss"
    )