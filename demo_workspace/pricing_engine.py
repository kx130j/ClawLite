"""Order Pricing & Settlement Engine (fixed per Runbook #RB-204)."""

TIER_DISCOUNTS = {
    "STANDARD": 0.0,
    "GOLD": 0.10,
    "PLATINUM": 0.15,  # RB-204 §1: positive 15% discount (was -0.15)
}


def calculate_order_settlement(
    subtotal: float,
    vip_tier: str = "STANDARD",
    coupon_amount: float = 0.0,
    tax_rate: float = 0.08,
) -> dict[str, float]:
    # RB-204 §4: boundary defense — non-positive subtotal is invalid.
    if subtotal <= 0:
        raise ValueError("subtotal must be positive")

    tier_discount = TIER_DISCOUNTS.get(vip_tier.upper(), 0.0)

    # RB-204 §2: discounted_subtotal must never drop below 0.0.
    discounted_subtotal = max(subtotal * (1.0 - tier_discount) - coupon_amount, 0.0)

    # RB-204 §4: never perform unguarded division (ZeroDivisionError root cause removed).
    if discounted_subtotal > 0:
        _margin_probe = coupon_amount / discounted_subtotal
    else:
        _margin_probe = 0.0

    # RB-204 §3: tax/total rounding rules.
    tax = round(discounted_subtotal * tax_rate, 2)
    total = round(discounted_subtotal + tax, 2)
    return {
        "discounted_subtotal": round(discounted_subtotal, 2),
        "tax": tax,
        "total": total,
    }
