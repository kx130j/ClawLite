import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clawlite.config import ClawLiteConfig
from clawlite.hooks import HookPipeline
from clawlite.llm import LLMClient
from clawlite.mcp.client import MCPClient
from clawlite.orchestrator import MultiAgentOrchestrator
from clawlite.skills import SkillRegistry
from clawlite.telemetry import TelemetryTracer


@dataclass
class TaskTicket:
    ticket_id: str
    source_channel: str  # e.g., "devops_alert_webhook", "cli_daemon"
    title: str
    description: str
    runtime_mode: str = "local_daemon"


class AgentGateway:
    """Unified Agent Gateway handling Task Ingestion, Session Persistence, Runtime Routing & Write-back."""

    def __init__(
        self,
        project_root: Path,
        workspace_root: Path,
        config: ClawLiteConfig | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.config = config or ClawLiteConfig()
        self.config.sandbox.workspace_root = self.workspace_root
        self.sessions_dir = self.project_root / "artifacts" / "sessions"
        self.reports_dir = self.project_root / "artifacts" / "reports"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def submit_ticket(self, ticket: TaskTicket) -> dict[str, Any]:
        session_id = f"sess-{ticket.ticket_id.lower()}"
        self.config.sandbox.runtime_mode = ticket.runtime_mode
        tracer = TelemetryTracer(session_id=session_id)
        t0 = time.perf_counter()

        hook_pipeline = HookPipeline(self.config.sandbox, tracer)
        mcp_client = MCPClient(
            workspace_root=self.workspace_root,
            hook_pipeline=hook_pipeline,
            tracer=tracer,
            use_stdio_subprocess=True,
            runtime_mode=ticket.runtime_mode,
        )
        try:
            skill_registry = SkillRegistry(self.project_root / "skills")
            llm_client = LLMClient(self.config.llm, tracer)
            orchestrator = MultiAgentOrchestrator(
                config=self.config,
                llm=llm_client,
                mcp_client=mcp_client,
                skill_registry=skill_registry,
                tracer=tracer,
            )

            # Demonstrate PreToolUse Sandbox Hook blocking a simulated dangerous probe
            hook_demo_err, hook_demo_msg = mcp_client.call_tool(
                actor="gateway:security_self_check",
                tool_name="workspace_read_file",
                arguments={"path": "../../.env.production"},
            )

            result = orchestrator.execute_task(
                f"[{ticket.ticket_id}] {ticket.title}\n{ticket.description}"
            )
            total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            session_payload = {
                "session_id": session_id,
                "ticket": asdict(ticket),
                "sandbox_self_check": {
                    "blocked": hook_demo_err,
                    "message": hook_demo_msg,
                },
                "orchestration_result": result,
                "total_duration_ms": total_ms,
                "telemetry": tracer.summary_dict(),
            }
            self._persist_and_writeback(ticket, session_payload, tracer)
            return session_payload
        finally:
            mcp_client.close()

    def _persist_and_writeback(
        self,
        ticket: TaskTicket,
        session_payload: dict[str, Any],
        tracer: TelemetryTracer,
    ) -> None:
        # 1. Persist Session State
        session_file = self.sessions_dir / f"{session_payload['session_id']}.json"
        session_file.write_text(
            json.dumps(session_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 2. Export Telemetry Trace
        trace_file = self.reports_dir / f"{ticket.ticket_id}_trace.json"
        tracer.export_json(trace_file)

        # 3. Result Write-back (Markdown Resolution Report)
        res = session_payload["orchestration_result"]
        tm = session_payload["telemetry"]["token_metrics"]
        report_md = (
            f"# Incident Resolution Write-Back: `{ticket.ticket_id}`\n\n"
            f"- **Session ID**: `{session_payload['session_id']}`\n"
            f"- **Runtime Mode**: `{ticket.runtime_mode}`\n"
            f"- **Status**: `{res['status']}` (Verification Passed: `{res['verification_passed']}` in `{res['verification_attempts']}` attempt(s))\n"
            f"- **Activated Skills**: `{', '.join(res['activated_skills'])}`\n"
            f"- **Total Duration**: `{session_payload['total_duration_ms']} ms`\n"
            f"- **Token Economics**: Total `{tm['total_tokens']}` tokens | "
            f"Prompt Cache Hit Rate: `{tm['prompt_cache_hit_rate_pct']}%` | "
            f"Sub-agent Isolated Tokens: `{tm['subagent_isolated_tokens']}`\n\n"
            f"## Agent Resolution Summary\n\n"
            f"{res['final_response']}\n"
        )
        report_file = self.reports_dir / f"{ticket.ticket_id}_resolution.md"
        report_file.write_text(report_md, encoding="utf-8")
