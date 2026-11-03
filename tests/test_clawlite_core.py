import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clawlite.config import SandboxConfig
from clawlite.hooks import HookPipeline
from clawlite.mcp.client import MCPClient
from clawlite.skills import SkillRegistry
from clawlite.telemetry import TelemetryTracer


class TestClawLiteArchitecture(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.workspace_root = self.project_root / "demo_workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.tracer = TelemetryTracer(session_id="test-session")
        self.sandbox_cfg = SandboxConfig(workspace_root=self.workspace_root)
        self.hooks = HookPipeline(self.sandbox_cfg, self.tracer)

    def test_sandbox_pre_tool_hooks_block_dangerous_calls(self) -> None:
        # 1. Block high-risk pattern
        d1 = self.hooks.run_pre_hooks(
            "orchestrator", "bash", {"cmd": "rm -rf /important"}
        )
        self.assertFalse(d1.allowed)
        self.assertIn("rm -rf", d1.reason)

        # 2. Block workspace path traversal
        d2 = self.hooks.run_pre_hooks(
            "orchestrator", "workspace_read_file", {"path": "../../.env.production"}
        )
        self.assertFalse(d2.allowed)

    def test_post_tool_hooks_redact_secrets_and_compact_output(self) -> None:
        leaked = "Token is sk-1234567890abcdef1234567890abcdef and " + ("X" * 5000)
        cleaned = self.hooks.run_post_hooks("orchestrator", "log_tool", {}, leaked)
        self.assertIn("[REDACTED_SECRET]", cleaned)
        self.assertNotIn("sk-1234567890abcdef1234567890abcdef", cleaned)
        self.assertIn("PostToolUse Hook Compacted", cleaned)

    def test_skills_progressive_disclosure(self) -> None:
        registry = SkillRegistry(self.project_root / "skills")
        self.assertGreaterEqual(len(registry.skills), 2)
        catalog = registry.build_catalog_prompt()
        self.assertIn("incident-diagnosis", catalog)
        matched = registry.match_and_load_skills("线上结算报错 ZeroDivisionError")
        self.assertTrue(any(s.name == "incident-diagnosis" for s in matched))

    def test_mcp_stdio_server_and_client_protocol(self) -> None:
        client = MCPClient(
            workspace_root=self.workspace_root,
            hook_pipeline=self.hooks,
            tracer=self.tracer,
            use_stdio_subprocess=True,
        )
        try:
            tools = client.get_openai_tools()
            tool_names = {t["function"]["name"] for t in tools}
            self.assertIn("monitor_query_logs", tool_names)
            self.assertIn("kb_search_runbook", tool_names)
            self.assertIn("ci_run_tests", tool_names)

            is_err, logs = client.call_tool(
                "test_actor", "monitor_query_logs", {"level": "ERROR"}
            )
            self.assertFalse(is_err)
            self.assertIn("ZeroDivisionError", logs)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
