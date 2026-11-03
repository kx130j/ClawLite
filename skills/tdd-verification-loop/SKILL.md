---
name: tdd-verification-loop
description: Enforces automated Test-Driven Verification Loop after every code modification.
triggers: 修复, fix, test, 测试, 代码, pricing_engine, 结算
---
# Skill: Automated Verification Loop (验证回路规范)

1. **Mandatory Verification Gate**:
   - Every time `workspace_write_file` is executed to modify source code, the system or agent MUST verify the change against unit tests (`ci_run_tests`).
2. **Self-Healing Reflection**:
   - If unit tests fail, inspect the assertion error or traceback, revise the implementation, and re-verify until all tests pass (`OK`).
3. **Safety Compliance**:
   - Never bypass unit tests or delete existing test cases to fake a pass.
