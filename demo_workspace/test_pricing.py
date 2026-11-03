import unittest
from pricing_engine import calculate_order_settlement


class TestOrderPricingSettlement(unittest.TestCase):
    def test_platinum_vip_discount(self):
        # 100.0 * (1 - 0.15) - 5.0 = 80.0; tax = 6.40; total = 86.40
        res = calculate_order_settlement(100.0, vip_tier="PLATINUM", coupon_amount=5.0, tax_rate=0.08)
        self.assertEqual(res["discounted_subtotal"], 80.0)
        self.assertEqual(res["tax"], 6.4)
        self.assertEqual(res["total"], 86.4)

    def test_full_coupon_no_zero_division(self):
        # 50.0 * (1 - 0.0) - 60.0 -> clamped to 0.0 without ZeroDivisionError
        res = calculate_order_settlement(50.0, vip_tier="STANDARD", coupon_amount=60.0, tax_rate=0.08)
        self.assertEqual(res["discounted_subtotal"], 0.0)
        self.assertEqual(res["tax"], 0.0)
        self.assertEqual(res["total"], 0.0)

    def test_invalid_subtotal_raises_value_error(self):
        with self.assertRaises(ValueError):
            calculate_order_settlement(0.0, vip_tier="GOLD")
        with self.assertRaises(ValueError):
            calculate_order_settlement(-10.0, vip_tier="STANDARD")


if __name__ == "__main__":
    unittest.main()
