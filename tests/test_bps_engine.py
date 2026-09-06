import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "scanner"))

from bps_engine import (
    Put,
    black_scholes_put_price,
    calculate_bps,
    normal_cdf,
    scan_bps,
)


def put(strike, bid, offer, oi=100_000, volume=100_000):
    return Put(
        strike=strike,
        bid=bid,
        offer=offer,
        bid_qty=10,
        offer_qty=10,
        oi=oi,
        volume=volume,
        ltt="2026-09-06T10:00:00",
    )


class BpsEngineTests(unittest.TestCase):
    def test_normal_cdf_standard_values(self):
        self.assertAlmostEqual(normal_cdf(0), 0.5)
        self.assertAlmostEqual(normal_cdf(1.9599639845), 0.975, places=4)
        self.assertAlmostEqual(normal_cdf(-1.9599639845), 0.025, places=4)

    def test_black_scholes_put_price_is_positive(self):
        price = black_scholes_put_price(100, 100, 1, 0.2)
        self.assertGreater(price, 0)
        self.assertLess(price, 100)

    def test_calculate_bps_uses_executable_prices(self):
        result = calculate_bps(put(100, 8, 8.5), put(80, 2, 2.5), 10, 110)
        self.assertIsNotNone(result)
        self.assertEqual(result["credit"], 5.5)
        self.assertEqual(result["execution_sell_price"], 8)
        self.assertEqual(result["execution_buy_price"], 2.5)
        self.assertEqual(result["max_profit"], 55)
        self.assertEqual(result["max_loss"], 145)
        self.assertAlmostEqual(result["profit_to_loss"], 145 / 55)
        self.assertAlmostEqual(result["otm_percent"], 10 / 110 * 100)

    def test_calculate_bps_rejects_invalid_strike_order(self):
        self.assertIsNone(calculate_bps(put(80, 8, 8.5), put(100, 2, 2.5), 10, 110))

    def test_calculate_bps_rejects_non_positive_credit(self):
        self.assertIsNone(calculate_bps(put(100, 2, 3), put(80, 2, 2.5), 10, 110))

    def test_scan_bps_filters_liquidity_and_otm(self):
        puts = [
            put(100, 8, 8.5),
            put(80, 2, 2.5),
            put(70, 1, 1.5, oi=10),
        ]
        results = scan_bps(
            puts,
            lot_size=10,
            spot=110,
            min_otm_percent=5,
            max_otm_percent=15,
            max_spread_width=25,
            min_profit_to_loss=0,
            max_profit_to_loss=100,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["sell_strike"], 100)
        self.assertEqual(results[0]["buy_strike"], 80)

    def test_scan_bps_returns_empty_for_invalid_spot(self):
        self.assertEqual(scan_bps([put(100, 8, 8.5)], spot=0), [])

    def test_scan_bps_ranks_farther_otm_first(self):
        puts = [
            put(100, 12, 12.5),
            put(90, 7, 7.5),
            put(80, 2, 2.5),
        ]
        results = scan_bps(
            puts,
            lot_size=1,
            spot=110,
            min_otm_percent=0,
            max_otm_percent=30,
            max_spread_width=40,
            min_profit_to_loss=0,
            max_profit_to_loss=100,
        )
        self.assertGreaterEqual(len(results), 2)
        self.assertGreaterEqual(results[0]["otm_percent"], results[1]["otm_percent"])


if __name__ == "__main__":
    unittest.main()
