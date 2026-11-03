import subprocess
import sys
import json
import time
from pathlib import Path
from typing import Any

from clawlite.hooks import HookPipeline
from clawlite.mcp.server import DevOpsMCPServer
from clawlite.telemetry import TelemetryTracer


class MCPClient:
    """MCP Client supporting both stdio subprocess transport and direct JSON-RPC dispatch."""

    def __init__(
        self,
        workspace_root: Path,
        hook_pipeline: HookPipeline,
        tracer: TelemetryTracer,
        use_stdio_subprocess: bool = True,
        runtime_mode: str = "local_daemon",
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.hook_pipeline = hook_pipeline
        self.tracer = tracer
        self.use_stdio_subprocess = use_stdio_subprocess
        self._req_id = 0
        self._proc: subprocess.Popen[str] | None = None
        self._direct_server = DevOpsMCPServer(self.workspace_root, runtime_mode=runtime_mode)
        if self.use_stdio_subprocess:
            self._start_stdio_server()
        self.initialize()

    def _start_stdio_server(self) -> None:
        server_script = Path(__file__).parent / "server.py"
        self._proc = subprocess.Popen(
            [sys.executable, str(server_script), str(self.workspace_root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def _send_rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params or {},
        }
        if self.use_stdio_subprocess and self._proc and self._proc.stdin and self._proc.stdout:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            raw_line = self._proc.stdout.readline()
            if raw_line:
                return json.loads(raw_line)
        return self._direct_server.handle_jsonrpc(payload)

    def initialize(self) -> dict[str, Any]:
        resp = self._send_rpc("initialize", {"clientInfo": {"name": "clawlite-host"}})
        return resp.get("result", {})

    def get_openai_tools(self, allowed_names: set[str] | None = None) -> list[dict[str, Any]]:
        resp = self._send_rpc("tools/list")
        mcp_tools = resp.get("result", {}).get("tools", [])
        openai_tools = []
        for t in mcp_tools:
            if allowed_names and t["name"] not in allowed_names:
                continue
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["inputSchema"],
                    },
                }
            )
        return openai_tools

    def call_tool(
        self, actor: str, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[bool, str]:
        # 1. PreToolUse Hook Check (Sandbox & Security Policy)
        decision = self.hook_pipeline.run_pre_hooks(actor, tool_name, arguments)
        if not decision.allowed:
            return True, decision.reason

        # 2. Dispatch JSON-RPC 2.0 `tools/call` to MCP Server
        t0 = time.perf_counter()
        resp = self._send_rpc(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )
        dt = (time.perf_counter() - t0) * 1000.0
        result = resp.get("result") or {}
        is_error = bool(result.get("isError", False))
        raw_content = str(result.get("content", ""))

        # 3. PostToolUse Hook Pipeline (Redaction & Output Compaction)
        final_content = self.hook_pipeline.run_post_hooks(
            actor, tool_name, arguments, raw_content
        )
        self.tracer.record_span(
            actor=actor,
            event_type="tool_call",
            duration_ms=dt,
            status="error" if is_error else "ok",
            tool=tool_name,
        )
        return is_error, final_content

    def close(self) -> None:
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                if self._proc.stdout:
                    self._proc.stdout.close()
                if self._proc.stderr:
                    self._proc.stderr.close()
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None
