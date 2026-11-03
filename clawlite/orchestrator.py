import json
from typing import Any

from clawlite.config import ClawLiteConfig
from clawlite.llm import LLMClient
from clawlite.mcp.client import MCPClient
from clawlite.skills import SkillRegistry
from clawlite.telemetry import TelemetryTracer
from clawlite.verification import VerificationLoop


class SubAgentRunner:
    """Executes an isolated Sub-agent with read-only MCP tools to prevent Main Context pollution."""

    READONLY_TOOLS = {"monitor_query_logs", "kb_search_runbook", "workspace_read_file"}

    def __init__(
        self,
        config: ClawLiteConfig,
        llm: LLMClient,
        mcp_client: MCPClient,
        tracer: TelemetryTracer,
    ) -> None:
        self.config = config
        self.llm = llm
        self.mcp_client = mcp_client
        self.tracer = tracer

    def run(self, role: str, objective: str) -> str:
        actor = f"subagent:{role}"
        tools = self.mcp_client.get_openai_tools(allowed_names=self.READONLY_TOOLS)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"You are Specialized Sub-Agent '{role}'. Your job is to gather facts using "
                    "read-only MCP tools (logs, knowledge base runbooks, source files) and return "
                    "a concise, structured technical summary to the Main Orchestrator. "
                    "Be thorough: check error logs, search the pricing runbook, and inspect `pricing_engine.py`."
                ),
            },
            {"role": "user", "content": objective},
        ]

        for _ in range(self.config.max_subagent_steps):
            msg = self.llm.chat(
                actor=actor,
                messages=messages,
                tools=tools,
                model=self.config.llm.subagent_model,
            )
            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return str(msg.get("content") or "Sub-agent finished with no summary.")

            seen_calls: set[str] = set()
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                raw_args = tc["function"].get("arguments") or "{}"
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                sig = f"{fn_name}:{json.dumps(args, sort_keys=True)}"
                if sig in seen_calls:
                    tool_output = "[Deduplicated: identical tool call already executed in this turn]"
                else:
                    seen_calls.add(sig)
                    _, tool_output = self.mcp_client.call_tool(actor, fn_name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": tool_output,
                    }
                )

        # Final synthesis call if max tool steps reached
        final_msg = self.llm.chat(
            actor=actor,
            messages=messages
            + [
                {
                    "role": "user",
                    "content": "Summarize all findings (logs, runbook rules, and code bugs) concisely now.",
                }
            ],
            tools=None,
            model=self.config.llm.subagent_model,
        )
        return str(final_msg.get("content") or "")


class MultiAgentOrchestrator:
    """Main Orchestrator coordinating Skills, Sub-agent Delegation, MCP Tools, and Verification Loop."""

    def __init__(
        self,
        config: ClawLiteConfig,
        llm: LLMClient,
        mcp_client: MCPClient,
        skill_registry: SkillRegistry,
        tracer: TelemetryTracer,
    ) -> None:
        self.config = config
        self.llm = llm
        self.mcp_client = mcp_client
        self.skill_registry = skill_registry
        self.tracer = tracer
        self.verifier = VerificationLoop(
            mcp_client=mcp_client,
            tracer=tracer,
            max_retries=config.max_verification_retries,
        )
        self.subagent_runner = SubAgentRunner(config, llm, mcp_client, tracer)

    def _build_tools(self) -> list[dict[str, Any]]:
        mcp_tools = self.mcp_client.get_openai_tools()
        delegate_tool = {
            "type": "function",
            "function": {
                "name": "delegate_subagent",
                "description": (
                    "Delegate reconnaissance (log querying, runbook search, file reading) to an "
                    "isolated Sub-agent so raw outputs do not pollute the Main Orchestrator context."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role": {
                            "type": "string",
                            "description": "Sub-agent role name, e.g. 'recon_researcher'",
                        },
                        "objective": {
                            "type": "string",
                            "description": "Clear instructions on what logs, runbooks, and files to inspect",
                        },
                    },
                    "required": ["role", "objective"],
                },
            },
        }
        return [delegate_tool] + mcp_tools

    def _maybe_compact_context(self, messages: list[dict[str, Any]]) -> None:
        total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        if total_chars <= self.config.context_compaction_threshold_chars:
            return
        # Preserve index 0 (immutable system prompt for prefix caching) and recent messages
        compacted_count = 0
        for m in messages[2:-3]:
            if m.get("role") == "tool" and len(str(m.get("content", ""))) > 400:
                m["content"] = (
                    str(m["content"])[:200] + "\n...[Compacted Historical Tool Output]..."
                )
                compacted_count += 1
        if compacted_count > 0:
            self.tracer.tokens.compactions_triggered += 1
            self.tracer.record_span(
                actor="orchestrator",
                event_type="compaction",
                duration_ms=0.2,
                status="ok",
                compacted_messages=compacted_count,
            )

    def execute_task(self, user_task: str) -> dict[str, Any]:
        # 1. Immutable System Prompt Prefix (maximizes Prompt Cache Hit Rate)
        system_prompt = (
            "You are ClawLite Orchestrator, an enterprise AI Coding & DevOps Agent.\n"
            "Follow active skills strictly. Prefer delegating initial log/runbook/codebase "
            "reconnaissance to `delegate_subagent` first, then fix the code using `workspace_write_file`, "
            "and ensure the Automated Verification Loop passes all unit tests before finishing.\n\n"
            f"{self.skill_registry.build_catalog_prompt()}"
        )

        # 2. On-demand Skill Activation (Progressive Disclosure)
        active_skills = self.skill_registry.match_and_load_skills(user_task)
        skill_block = "\n\n".join(
            f"<activated_skill name='{s.name}'>\n{s.body}\n</activated_skill>"
            for s in active_skills
        )
        initial_user_content = (
            f"{skill_block}\n\n<user_task>\n{user_task}\n</user_task>"
            if skill_block
            else user_task
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_user_content},
        ]
        tools = self._build_tools()

        for step in range(1, self.config.max_orchestrator_steps + 1):
            self._maybe_compact_context(messages)
            msg = self.llm.chat(
                actor="orchestrator",
                messages=messages,
                tools=tools,
                model=self.config.llm.orchestrator_model,
            )
            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # Final Verification Gate before allowing task completion
                if not self.verifier.last_passed and self.verifier.attempts < self.config.max_verification_retries:
                    v_status = self.verifier.run_verification("pre_completion_gate")
                    if not v_status.passed:
                        messages.append({"role": "user", "content": v_status.feedback_prompt})
                        continue
                return {
                    "status": "completed" if self.verifier.last_passed else "completed_unverified",
                    "steps": step,
                    "activated_skills": [s.name for s in active_skills],
                    "verification_passed": self.verifier.last_passed,
                    "verification_attempts": self.verifier.attempts,
                    "final_response": msg.get("content") or "",
                }

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                raw_args = tc["function"].get("arguments") or "{}"
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

                if fn_name == "delegate_subagent":
                    role = args.get("role", "recon_researcher")
                    objective = args.get("objective", user_task)
                    sub_summary = self.subagent_runner.run(role=role, objective=objective)
                    tool_result_text = (
                        f"[Sub-Agent '{role}' Distilled Report (Isolated Context)]:\n{sub_summary}"
                    )
                else:
                    _, tool_result_text = self.mcp_client.call_tool(
                        "orchestrator", fn_name, args
                    )
                    # Automated Post-Edit Verification Loop
                    if fn_name == "workspace_write_file" and str(args.get("path", "")).endswith(".py"):
                        v_status = self.verifier.run_verification(
                            f"edit:{args.get('path')}"
                        )
                        if v_status.passed:
                            tool_result_text += (
                                f"\n\n[Automated Verification Loop PASSED (Attempt #{v_status.attempt})]:\n"
                                f"{v_status.report}"
                            )
                        else:
                            tool_result_text += f"\n\n{v_status.feedback_prompt}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": tool_result_text,
                    }
                )

        return {
            "status": "max_steps_exceeded",
            "steps": self.config.max_orchestrator_steps,
            "activated_skills": [s.name for s in active_skills],
            "verification_passed": self.verifier.last_passed,
            "verification_attempts": self.verifier.attempts,
            "final_response": "Reached max orchestrator steps.",
        }
