import json
import sys
from pathlib import Path
from typing import Any

# Ensure package root is importable when executed as a standalone stdio MCP server script
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clawlite.config import SandboxConfig
from clawlite.runtime import create_runtime


class DevOpsMCPServer:
    """Standard JSON-RPC 2.0 MCP Server connecting Agent to Internal Logs, Knowledge Base, Workspace, and CI."""

    def __init__(self, workspace_root: Path, runtime_mode: str = "local_daemon") -> None:
        self.workspace_root = workspace_root.resolve()
        self.sandbox_cfg = SandboxConfig(
            runtime_mode=runtime_mode, workspace_root=self.workspace_root
        )
        self.runtime = create_runtime(self.sandbox_cfg)
        self._init_mock_enterprise_systems()

    def _init_mock_enterprise_systems(self) -> None:
        self._logs_db = [
            {
                "service": "order-pricing-service",
                "level": "ERROR",
                "timestamp": "2026-11-03T11:42:10Z",
                "trace_id": "tr-99812a",
                "message": (
                    "ZeroDivisionError in calculate_Order_Settlement: "
                    "discount_rate=1.0 caused division by zero when computing net_margin_ratio; "
                    "additionally VIP tier 'PLATINUM' applied negative fee instead of 15% discount."
                ),
                "file": "pricing_engine.py",
            },
            {
                "service": "order-pricing-service",
                "level": "WARN",
                "timestamp": "2026-11-03T11:40:01Z",
                "trace_id": "tr-99801b",
                "message": "High latency warning on /api/v1/settlement batch endpoint.",
                "file": "pricing_engine.py",
            },
        ]
        self._kb_runbooks = {
            "pricing": (
                "【内部知识库 Runbook #RB-204: 订单计价与结算规范】\n"
                "1. VIP 等级折扣率 (tier_discount): STANDARD=0.0, GOLD=0.10, PLATINUM=0.15。\n"
                "2. 折后金额计算公式: discounted_subtotal = subtotal * (1.0 - tier_discount) - coupon_amount，且最低不能小于 0.0。\n"
                "3. 税费计算: tax = round(discounted_subtotal * tax_rate, 2)，最终应付 total = round(discounted_subtotal + tax, 2)。\n"
                "4. 边界防御要求: 当 subtotal <= 0 时直接抛出 ValueError('subtotal must be positive')；严禁出现除零异常。"
            ),
            "ci": (
                "【内部知识库 Runbook #RB-101: CI 验证门禁】\n"
                "所有代码修改后必须调用 `ci_run_tests` 工具通过全部单元测试，严禁未验证直接结单。"
            ),
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "monitor_query_logs",
                "description": "Query internal monitoring & error logs by service name or keyword.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Service name filter"},
                        "level": {"type": "string", "description": "Log level (ERROR, WARN, INFO)"},
                    },
                },
            },
            {
                "name": "kb_search_runbook",
                "description": "Search internal engineering knowledge base and business specification runbooks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keyword to search (e.g. 'pricing', 'ci')"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "workspace_read_file",
                "description": "Read source code or test file inside the workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative file path inside workspace"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "workspace_write_file",
                "description": "Write updated source code to a file inside the workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative file path inside workspace"},
                        "content": {"type": "string", "description": "Full file content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "ci_run_tests",
                "description": "Run unit test suite in sandboxed runtime and return pass/fail report.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "test_file": {
                            "type": "string",
                            "description": "Relative test file path (default: test_pricing.py)",
                        }
                    },
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "monitor_query_logs":
                level = (arguments.get("level") or "").upper()
                results = [
                    log
                    for log in self._logs_db
                    if not level or log["level"] == level
                ]
                return {"isError": False, "content": json.dumps(results, ensure_ascii=False, indent=2)}

            if name == "kb_search_runbook":
                q = (arguments.get("query") or "").lower()
                matched = [
                    v for k, v in self._kb_runbooks.items() if k in q or q in v.lower()
                ]
                if not matched:
                    matched = list(self._kb_runbooks.values())
                return {"isError": False, "content": "\n\n".join(matched)}

            if name == "workspace_read_file":
                rel_path = arguments["path"]
                target = self.runtime.resolve_safe_path(rel_path)
                if not target.exists():
                    return {"isError": True, "content": f"File not found: {rel_path}"}
                return {"isError": False, "content": target.read_text(encoding="utf-8")}

            if name == "workspace_write_file":
                rel_path = arguments["path"]
                content = arguments["content"]
                target = self.runtime.resolve_safe_path(rel_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return {
                    "isError": False,
                    "content": f"Successfully wrote {len(content)} bytes to {rel_path}.",
                }

            if name == "ci_run_tests":
                test_file = arguments.get("test_file") or "test_pricing.py"
                res = self.runtime.run_command([sys.executable, "-m", "unittest", test_file, "-v"])
                combined = (
                    f"[Runtime: {res.runtime_mode} | ExitCode: {res.exit_code} | {res.duration_ms:.1f}ms]\n"
                    f"{res.stdout}\n{res.stderr}"
                ).strip()
                return {"isError": res.exit_code != 0, "content": combined}

            return {"isError": True, "content": f"Unknown MCP tool: {name}"}
        except Exception as exc:
            return {"isError": True, "content": f"MCP Tool Execution Error: {exc}"}

    def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "clawlite-devops-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": self.list_tools()}
        elif method == "tools/call":
            result = self.call_tool(params.get("name", ""), params.get("arguments") or {})
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def serve_stdio(self) -> None:
        """Standard MCP stdio loop for external hosts (e.g. Claude Code / Cursor)."""
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            resp = self.handle_jsonrpc(req)
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    DevOpsMCPServer(ws).serve_stdio()
