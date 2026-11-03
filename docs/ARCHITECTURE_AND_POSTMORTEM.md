# ClawLite 架构设计说明书与工程演进复盘 (Design & Postmortem)

## 1. 设计背景与核心目标

在构建面向研发与运维场景的 Coding Agent 时，单智能体（Monolithic Agent）架构往往面临三大痛点：
1. **Context Rot（上下文腐化）与高昂 Token 成本**：将海量监控日志、Runbook 知识库与源码文件直接塞入主对话窗口，导致中间信息迷失（Lost-in-the-middle），且后续每轮推理都需为历史噪声重复计费。
2. **工具调用缺乏安全边界**：Agent 直接执行本地命令或文件读写时，容易发生目录穿越（Path Traversal）、误删文件或将密钥（API Key）带入上下文。
3. **缺乏确定性验证闭环（Verification Loop）**：模型修改代码后容易产生“虚假自信”，未通过测试即宣布任务完成。

`ClawLite` 参考 OpenClaw 与 Claude Code 的工程范式，围绕 **Gateway、Sessions、Skills、Sub-agent、MCP 与 Verification Loop** 进行了轻量化自研实现。

---

## 2. 核心机制拆解

### 2.1 上下文管理与 Prompt Cache 优化
- **静态前缀分离（Immutable Prefix）**：[`MultiAgentOrchestrator`](../clawlite/orchestrator.py) 将 System Prompt 严格锁定为“基础角色声明 + `<available_skills>` 轻量级目录索引”，不在 System Prompt 中拼接动态时间戳或全量文档。
- **渐进式披露（Progressive Disclosure）**：[`SkillRegistry`](../clawlite/skills.py) 先解析 `skills/*/SKILL.md` 的 YAML Frontmatter，仅当任务命中 `triggers` 时才将对应 Skill 正文按需注入 User Turn。实测多轮调用中 **Prompt Cache 命中率达 80.51%**（`9,388 / 11,661` Prompt Tokens 命中缓存）。

### 2.2 子 Agent 委派与异构模型路由
- **上下文隔离（Context Isolation）**：主编排器通过 `delegate_subagent` 将高噪侦察任务委派给 [`SubAgentRunner`](../clawlite/orchestrator.py)。子 Agent 运行在完全独立的临时 `messages` 上下文中，仅挂载只读 MCP 工具集（`monitor_query_logs`、`kb_search_runbook`、`workspace_read_file`）。
- **异构大小模型协同**：主 Agent 默认采用推理能力强、支持前缀缓存的 `Atria-Dawn`；子 Agent 默认路由至高吞吐低延迟的 `qwen3.8-27b`，在保证代码修复质量的同时显著降低端到端延迟。

### 2.3 MCP (Model Context Protocol) 协议实现与双 Runtime
- **JSON-RPC 2.0 `stdio` 通信**：[`clawlite/mcp/`](../clawlite/mcp/) 实现了标准 `initialize`、`tools/list`、`tools/call` 协议握手，将内部监控、知识库与 CI 单测封装为标准 MCP 工具。
- **双 Runtime 与 Hook 管道**：[`clawlite/runtime.py`](../clawlite/runtime.py) 抽象了 `LocalDaemonRuntime` 与 `CloudContainerRuntime`；[`HookPipeline`](../clawlite/hooks.py) 在工具执行前（`PreToolUse`）拦截高危命令与目录越界，在执行后（`PostToolUse`）执行正则脱敏与超长输出截断。

### 2.4 Automated Verification Loop（自动化验证回路）
- **写后即测（Post-Edit Gate）**：当主 Agent 调用 `workspace_write_file` 修改 `.py` 代码后，编排器自动触发 [`VerificationLoop`](../clawlite/verification.py) 调用 MCP `ci_run_tests`。
- **结单前门禁（Pre-Completion Gate）**：若单测未通过，系统自动将断言失败堆栈封装为 `<verification_loop_failure>` 反馈打回主对话流，驱动 Agent 自愈重修，直至全部单测通过或达到最大重试熔断阈值。

---

## 3. 工程踩坑与调优复盘 (Engineering Postmortem)

1. **子 Agent 单轮并发重复 Tool Call 问题**：
   - **现象**：部分模型在单轮响应中会并发生成多个相同参数的 `kb_search_runbook` 调用，导致多份重复文档同时写入上下文引发超时。
   - **解法**：在 `SubAgentRunner` 中引入基于 `tool_name + sorted_args_json` 的回合内签名去重（`seen_calls`），重复调用直接返回轻量级 `[Deduplicated]` 标记，避免无效 I/O 与上下文膨胀。
2. **Windows 环境下 MCP `stdio` 管道编码与孙进程句柄继承**：
   - **现象**：Windows 下默认 `stdin/stdout` 编码非 UTF-8 导致 JSON-RPC 传输中文日志时报错 `OSError: [Errno 22] Invalid argument`；同时 `ci_run_tests` 启动 `unittest` 子进程时若未隔离标准输入，会继承 MCP Server 的 `stdin` 管道导致阻塞。
   - **解法**：在 `serve_stdio` 入口显式调用 `reconfigure(encoding="utf-8")` 并改用逐行 `readline()`，同时在 `LocalDaemonRuntime.run_command` 中强制指定 `stdin=subprocess.DEVNULL`。
