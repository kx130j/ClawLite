---
name: incident-diagnosis
description: Standardized SOP for diagnosing线上故障, querying MCP monitoring logs & runbooks via Sub-agent delegation.
triggers: 故障, 报错, bug, error, pricing, 结算, 计价, 异常, incident
---
# Skill: Incident Diagnosis & Sub-Agent Reconnaissance SOP

1. **Context Isolation Principle (上下文隔离原则)**:
   - Do NOT read all logs, runbooks, and source files directly in the Main Orchestrator if a `delegate_subagent` tool is available.
   - Delegate log querying (`monitor_query_logs`), runbook lookup (`kb_search_runbook`), and initial code reading (`workspace_read_file`) to the `recon_researcher` Sub-agent.
2. **Root Cause Alignment**:
   - Always cross-check error logs against the internal Knowledge Base Runbook specification before modifying code.
3. **Structured Output**:
   - Conclude the task with a clear summary covering: Root Cause (根因分析), Code Fix (修复变更), and Verification Result (验证结论).
