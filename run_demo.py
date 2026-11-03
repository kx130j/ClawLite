import sys
from pathlib import Path

from clawlite.gateway import AgentGateway, TaskTicket

BUGGY_PRICING_ENGINE = '''"""Order Pricing & Settlement Engine (contains production bugs to be diagnosed and fixed by ClawLite)."""

TIER_DISCOUNTS = {
    "STANDARD": 0.0,
    "GOLD": 0.10,
    "PLATINUM": -0.15,  # BUG 1: Wrong sign! Should be 0.15 according to Runbook #RB-204
}


def calculate_order_settlement(
    subtotal: float,
    vip_tier: str = "STANDARD",
    coupon_amount: float = 0.0,
    tax_rate: float = 0.08,
) -> dict[str, float]:
    # BUG 2: Missing `if subtotal <= 0: raise ValueError("subtotal must be positive")`
    tier_discount = TIER_DISCOUNTS.get(vip_tier.upper(), 0.0)
    discounted_subtotal = subtotal * (1.0 - tier_discount) - coupon_amount

    # BUG 3: No floor at 0.0 and triggers ZeroDivisionError when discounted_subtotal == 0
    _margin_probe = coupon_amount / discounted_subtotal

    tax = round(discounted_subtotal * tax_rate, 2)
    total = round(discounted_subtotal + tax, 2)
    return {
        "discounted_subtotal": round(discounted_subtotal, 2),
        "tax": tax,
        "total": total,
    }
'''

TEST_PRICING_SUITE = '''import unittest
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
'''


def reset_demo_workspace(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "pricing_engine.py").write_text(BUGGY_PRICING_ENGINE, encoding="utf-8")
    (workspace_dir / "test_pricing.py").write_text(TEST_PRICING_SUITE, encoding="utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    project_root = Path(__file__).parent.resolve()
    workspace_dir = project_root / "demo_workspace"
    reset_demo_workspace(workspace_dir)

    print("=" * 76)
    print("🚀 ClawLite Multi-Agent Orchestration Engine — End-to-End Live Demo")
    print("=" * 76)
    print(f"📂 Workspace initialized at: {workspace_dir}")

    gateway = AgentGateway(project_root=project_root, workspace_root=workspace_dir)
    ticket = TaskTicket(
        ticket_id="INC-2026-1103",
        source_channel="devops_alert_webhook",
        title="order-pricing-service 线上结算异常 (ZeroDivisionError & PLATINUM 折扣错误)",
        description=(
            "线上监控告警：`order-pricing-service` 出现 ZeroDivisionError 且 PLATINUM 会员结算金额异常。\n"
            "请按 incident-diagnosis 与 tdd-verification-loop 规范：\n"
            "1. 先通过 `delegate_subagent` 委派子 Agent 查询监控日志 (`monitor_query_logs`)、检索计价知识库 Runbook (`kb_search_runbook`) 并读取 `pricing_engine.py`；\n"
            "2. 根据子 Agent 汇总的规范要求修改 `pricing_engine.py`；\n"
            "3. 确保通过 Verification Loop 全部单元测试后输出结构化复盘报告。"
        ),
        runtime_mode="local_daemon",
    )

    print(f"\n📨 Submitting Ticket [{ticket.ticket_id}] to AgentGateway...")
    session_result = gateway.submit_ticket(ticket)

    orch = session_result["orchestration_result"]
    tm = session_result["telemetry"]["token_metrics"]
    sandbox_chk = session_result["sandbox_self_check"]

    print("\n" + "-" * 76)
    print("🛡️  1. PreToolUse Sandbox Hook Self-Check:")
    print(f"   Blocked={sandbox_chk['blocked']} | {sandbox_chk['message']}")

    print("\n🧩 2. Orchestration & Verification Loop Summary:")
    print(f"   Status               : {orch['status']}")
    print(f"   Activated Skills     : {orch['activated_skills']}")
    print(f"   Orchestrator Steps   : {orch['steps']}")
    print(f"   Verification Passed  : {orch['verification_passed']} (Attempts: {orch['verification_attempts']})")
    print(f"   Total Duration       : {session_result['total_duration_ms']} ms")

    print("\n📊 3. Telemetry & Token Cost Optimization Metrics:")
    print(f"   Total LLM Calls      : {tm['llm_calls']}")
    print(f"   Prompt Tokens        : {tm['prompt_tokens']} (Cached: {tm['cached_tokens']} | Hit Rate: {tm['prompt_cache_hit_rate_pct']}%)")
    print(f"   Completion Tokens    : {tm['completion_tokens']}")
    print(f"   Sub-Agent Isolated   : {tm['subagent_isolated_tokens']} tokens (kept out of Main Context!)")

    print("\n📝 4. Final Agent Incident Resolution Report:")
    print("-" * 76)
    print(orch["final_response"])
    print("=" * 76)
    print(f"✅ Artifacts written to:\n   - {project_root / 'artifacts' / 'reports' / 'INC-2026-1103_resolution.md'}\n   - {project_root / 'artifacts' / 'reports' / 'INC-2026-1103_trace.json'}")


if __name__ == "__main__":
    main()
