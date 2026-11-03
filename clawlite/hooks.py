import re
from dataclasses import dataclass
from typing import Any, Callable

from clawlite.config import SandboxConfig
from clawlite.telemetry import TelemetryTracer


@dataclass
class HookDecision:
    allowed: bool
    reason: str = ""
    modified_payload: Any = None


PreToolHookFn = Callable[[str, dict[str, Any]], HookDecision]
PostToolHookFn = Callable[[str, dict[str, Any], str], str]


class HookPipeline:
    """Manages PreToolUse and PostToolUse lifecycle hooks for safety, compliance, and context compaction."""

    def __init__(self, sandbox_cfg: SandboxConfig, tracer: TelemetryTracer) -> None:
        self.sandbox_cfg = sandbox_cfg
        self.tracer = tracer
        self._pre_hooks: list[tuple[str, PreToolHookFn]] = []
        self._post_hooks: list[tuple[str, PostToolHookFn]] = []
        self._register_builtin_hooks()

    def _register_builtin_hooks(self) -> None:
        self.add_pre_hook("sandbox_security_guard", self._security_guard_hook)
        self.add_pre_hook("workspace_boundary_guard", self._workspace_boundary_hook)
        self.add_post_hook("sensitive_secret_redactor", self._secret_redaction_hook)
        self.add_post_hook("output_token_compactor", self._output_compaction_hook)

    def add_pre_hook(self, name: str, fn: PreToolHookFn) -> None:
        self._pre_hooks.append((name, fn))

    def add_post_hook(self, name: str, fn: PostToolHookFn) -> None:
        self._post_hooks.append((name, fn))

    def run_pre_hooks(
        self, actor: str, tool_name: str, tool_args: dict[str, Any]
    ) -> HookDecision:
        for hook_name, fn in self._pre_hooks:
            decision = fn(tool_name, tool_args)
            if not decision.allowed:
                self.tracer.record_span(
                    actor=actor,
                    event_type="hook_intercept",
                    duration_ms=0.1,
                    status="blocked",
                    hook=hook_name,
                    tool=tool_name,
                    reason=decision.reason,
                )
                return decision
        return HookDecision(allowed=True)

    def run_post_hooks(
        self, actor: str, tool_name: str, tool_args: dict[str, Any], raw_output: str
    ) -> str:
        output = raw_output
        for _, fn in self._post_hooks:
            output = fn(tool_name, tool_args, output)
        return output

    def _security_guard_hook(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> HookDecision:
        serialized = f"{tool_name} {tool_args}".lower()
        for pattern in self.sandbox_cfg.blocked_patterns:
            if pattern.lower() in serialized:
                return HookDecision(
                    allowed=False,
                    reason=(
                        f"[Sandbox Security Hook Blocked] Tool '{tool_name}' triggered "
                        f"high-risk policy rule: forbidden pattern '{pattern}'."
                    ),
                )
        return HookDecision(allowed=True)

    def _workspace_boundary_hook(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> HookDecision:
        path_arg = tool_args.get("path") or tool_args.get("file_path")
        if path_arg and isinstance(path_arg, str):
            if ".." in path_arg or path_arg.startswith(("/etc", "C:\\Windows")):
                return HookDecision(
                    allowed=False,
                    reason=(
                        f"[Sandbox Boundary Hook Blocked] Path traversal or system path "
                        f"access denied: '{path_arg}'."
                    ),
                )
        return HookDecision(allowed=True)

    def _secret_redaction_hook(
        self, tool_name: str, tool_args: dict[str, Any], output: str
    ) -> str:
        # Redact potential API keys or bearer tokens from tool output before entering LLM context
        return re.sub(
            r"(sk-[a-zA-Z0-9]{16,}|Bearer\s+[a-zA-Z0-9_\-\.]{16,})",
            "[REDACTED_SECRET]",
            output,
        )

    def _output_compaction_hook(
        self, tool_name: str, tool_args: dict[str, Any], output: str
    ) -> str:
        limit = self.sandbox_cfg.max_output_chars
        if len(output) > limit:
            half = limit // 2
            return (
                f"{output[:half]}\n"
                f"... [PostToolUse Hook Compacted {len(output) - limit} chars to save Context Window] ...\n"
                f"{output[-half:]}"
            )
        return output
