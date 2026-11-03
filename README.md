# ClawLite: Multi-Agent Orchestration Engine with MCP, Sandbox Hooks & Verification Loop

`ClawLite` 是一个轻量级、模块化的多 Agent 编排与执行运行时框架，参考 OpenClaw 与 Claude Code 的工程架构，实现了从 **Gateway 任务接入、Session 持久化、Skills 渐进式披露、Sub-agent 上下文隔离、MCP Server/Client (`stdio` JSON-RPC 2.0)、Sandbox 安全 Hook 到 Automated Verification Loop（自动化验证回路）** 的完整闭环。

---

## 1. 核心架构

```mermaid
flowchart TD
    Ticket["外部告警/任务工单 (TaskTicket)"] --> GW["AgentGateway (Gateway & Session Manager)"]
    GW --> SR["SkillRegistry (SKILL.md 渐进式披露)"]
    GW --> Orch["MultiAgentOrchestrator (主编排器)"]
    
    Orch -->|1. 委派信息搜集 (上下文隔离)| Sub["SubAgentRunner (只读侦察子 Agent)"]
    Sub -->|JSON-RPC 2.0 (stdio)| MCP["DevOpsMCPServer (监控/知识库/代码库/CI)"]
    Sub -->|仅返回提炼后的根因摘要| Orch
    
    Orch -->|2. 修改代码 workspace_write_file| Hook["HookPipeline (Pre/Post-ToolUse 沙箱与脱敏)"]
    Hook --> MCP
    
    Orch -->|3. 自动触发验证门禁| Verifier["VerificationLoop (自动化验证回路)"]
    Verifier -->|调用 ci_run_tests| Runtime["AgentRuntime (LocalDaemon / CloudContainer)"]
    Verifier -->|失败则注入 Traceback 驱动自愈| Orch
    
    GW --> WriteBack["结果回写 (Resolution Report & Telemetry Trace)"]
```

---

## 2. 核心特性与模块说明

| 模块 | 代码路径 | 核心设计亮点 |
| :--- | :--- | :--- |
| **Gateway & Sessions** | [`clawlite/gateway.py`](./clawlite/gateway.py) | 统一 `TaskTicket` 接入、JSON 会话状态持久化、自动化生成 Markdown 结单报告与分布式 Trace。 |
| **Multi-Agent & Sub-agent** | [`clawlite/orchestrator.py`](./clawlite/orchestrator.py) | 主从 Agent 异构模型路由与上下文隔离；子 Agent 仅挂载只读 MCP 工具集，避免原始日志污染主上下文。 |
| **Dual Runtime & Sandbox** | [`clawlite/runtime.py`](./clawlite/runtime.py)<br>[`clawlite/hooks.py`](./clawlite/hooks.py) | 支持 `local_daemon` 与 `cloud_container` 两种执行环境；通过 `PreToolUse` / `PostToolUse` 钩子实现路径穿越拦截、高危命令阻断、敏感凭据脱敏与超长输出自动折叠。 |
| **MCP Server / Client** | [`clawlite/mcp/server.py`](./clawlite/mcp/server.py)<br>[`clawlite/mcp/client.py`](./clawlite/mcp/client.py) | 原生实现 JSON-RPC 2.0 `stdio` 传输协议，打通 `monitor_query_logs`、`kb_search_runbook`、`ci_run_tests` 等内部工具。 |
| **Skills & Verification Loop** | [`clawlite/skills.py`](./clawlite/skills.py)<br>[`clawlite/verification.py`](./clawlite/verification.py) | `SKILL.md` YAML Frontmatter 渐进式披露（保障高 Prompt Cache 命中率）；代码修改后自动触发单测验证闭环。 |
| **Telemetry & Cost Tracker** | [`clawlite/telemetry.py`](./clawlite/telemetry.py) | 实时追踪每次调用耗时、`prompt_tokens`、`cached_tokens`（前缀缓存命中率）及子 Agent 隔离 Token 指标。 |

详细架构设计与踩坑复盘请参阅：[`docs/ARCHITECTURE_AND_POSTMORTEM.md`](./docs/ARCHITECTURE_AND_POSTMORTEM.md)。

---

## 3. 快速开始

### 3.1 环境配置
复制 `.env.example` 为 `.env` 并填入兼容 OpenAI 接口规范的 API Key：
```bash
cp .env.example .env
```

### 3.2 运行架构单元测试
```bash
python -m unittest discover -s tests -v
```

### 3.3 运行端到端线上故障自愈 Demo
```bash
python run_demo.py
```

运行完成后，自动生成的结单报告与可观测性追踪文件位于：
- [`artifacts/reports/INC-2026-1103_resolution.md`](./artifacts/reports/INC-2026-1103_resolution.md)
- [`artifacts/reports/INC-2026-1103_trace.json`](./artifacts/reports/INC-2026-1103_trace.json)
