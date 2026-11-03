import time
from dataclasses import dataclass

from clawlite.mcp.client import MCPClient
from clawlite.telemetry import TelemetryTracer


@dataclass
class VerificationStatus:
    passed: bool
    attempt: int
    report: str
    feedback_prompt: str = ""


class VerificationLoop:
    """Automated Verification Loop that validates code changes via MCP CI runner and drives self-healing."""

    def __init__(
        self, mcp_client: MCPClient, tracer: TelemetryTracer, max_retries: int = 3
    ) -> None:
        self.mcp_client = mcp_client
        self.tracer = tracer
        self.max_retries = max_retries
        self.attempts = 0
        self.last_passed = False

    def run_verification(self, trigger_reason: str) -> VerificationStatus:
        self.attempts += 1
        t0 = time.perf_counter()
        is_err, output = self.mcp_client.call_tool(
            actor="verifier",
            tool_name="ci_run_tests",
            arguments={"test_file": "test_pricing.py"},
        )
        dt = (time.perf_counter() - t0) * 1000.0
        passed = not is_err and "OK" in output

        self.last_passed = passed
        self.tracer.record_span(
            actor="verifier",
            event_type="verification",
            duration_ms=dt,
            status="ok" if passed else "failed_check",
            attempt=self.attempts,
            trigger=trigger_reason,
        )

        if passed:
            return VerificationStatus(
                passed=True,
                attempt=self.attempts,
                report=output,
            )

        feedback = (
            f"<verification_loop_failure attempt='{self.attempts}/{self.max_retries}'>\n"
            f"Automated Verification Loop detected unit test failures after {trigger_reason}:\n"
            f"{output}\n\n"
            f"Please analyze the failure traceback, fix `pricing_engine.py` using `workspace_write_file`, "
            f"and ensure all unit tests pass before concluding.\n"
            f"</verification_loop_failure>"
        )
        return VerificationStatus(
            passed=False,
            attempt=self.attempts,
            report=output,
            feedback_prompt=feedback,
        )
