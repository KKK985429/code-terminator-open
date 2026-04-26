# Contributing Guide

感谢你为 `code-terminator` 做出贡献。提交变更前，请先确认你的工作
已关联明确的问题描述，并且可以被其他开发者复现、审查和验证。

## 如何提交 Issue

所有开发工作都应从 Issue 开始。请先搜索现有 Issue，避免重复提交。

### Bug Report

Bug Report 请至少包含以下内容：

- 标题：`[Bug]` + 一句话概述问题
- 版本信息：提交 SHA、运行环境、Python 或 Node 版本
- 复现步骤：按顺序列出最小复现步骤
- 预期结果：说明正确行为
- 实际结果：说明错误现象、报错信息或截图
- 影响范围：是否阻塞主流程、是否存在回退方案
- 附加信息：日志、截图、配置差异、相关链接

示例：

```text
[Bug] Worker runtime fails when Docker image is unavailable

Version
- commit: abcdef1
- OS: Ubuntu 24.04
- Python: 3.11

Steps to reproduce
1. Set CODEX_WORKER_DOCKER_IMAGE to a non-existing image
2. Run uv run python scripts/dispatch_real_worker_task.py

Expected result
- The CLI returns a clear configuration error

Actual result
- The process exits with an uncaught exception
```

### Feature Request

Feature Request 请至少包含以下内容：

- 标题：`[Feature]` + 一句话概述需求
- 背景问题：当前流程的缺口或痛点
- 目标收益：该功能解决什么问题、服务谁
- 建议方案：核心设计、接口变化、约束条件
- 备选方案：是否评估过其他实现方式
- 验收标准：可以量化的完成条件
- 附加上下文：相关 Issue、设计稿、日志或讨论链接

示例：

```text
[Feature] Add reviewer approval status to leader event stream

Background
- The UI cannot show whether a task is waiting for review

Proposal
- Add a reviewer status field in the event payload
- Persist the field in the checkpoint snapshot

Acceptance criteria
- Backend exposes reviewer status in history API
- Web UI renders the latest reviewer state
```

## 分支命名规范

请在独立分支上开发，不要直接在 `main` 分支提交。

默认分支前缀如下：

- `feature/<issue-id>-<short-description>`：新功能或非紧急增强
- `bugfix/<issue-id>-<short-description>`：缺陷修复
- `hotfix/<issue-id>-<short-description>`：线上紧急修复

命名要求：

- 使用小写字母和 `kebab-case`
- `issue-id` 必须对应已存在的 Issue 编号
- `short-description` 保持简短，建议不超过 5 个单词

示例：

```text
feature/123-add-reviewer-status
bugfix/456-fix-history-pagination
hotfix/789-recover-worker-dispatch
```

如果维护者为纯文档改动单独指定分支名，例如
`docs/contributing-guide`，以对应 Issue 或 reviewer 要求为准；
未特别说明时，仍按 `feature/`、`bugfix/`、`hotfix/` 规则执行。

## PR 提交流程

所有 Pull Request 都必须关联 Issue，并通过代码审查后才能合并到
`main`。默认流程如下：

1. 创建或认领一个 Issue，并确认验收标准。
2. 从最新 `main` 拉出独立分支进行开发。
3. 完成代码、文档和测试更新，并自行检查改动范围。
4. 提交 PR，在描述中关联 Issue，例如 `Closes #123`。
5. 至少获得 1 个 reviewer 批准后再合并。

PR 描述建议包含以下内容：

- 变更背景与目标
- 主要实现说明
- 风险点与回滚方式
- 验证方式与执行结果
- 关联 Issue 编号

### 代码审查检查清单

提交 PR 前，请确认以下检查项全部完成：

- 已关联 Issue，并在 PR 描述中写明 `Closes #<id>`
- 变更范围聚焦单一主题，没有混入无关修改
- 已补充或更新必要文档
- 已补充或更新与改动匹配的测试
- 本地执行过相关验证命令，结果通过
- 未提交密钥、令牌、个人配置或临时调试代码
- 若存在破坏性变更，已在 PR 描述中明确说明

## 提交信息规范

提交信息使用 Angular 风格：

```text
type(scope): subject
```

规则：

- `type` 使用小写，常用值包括
  `feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`ci`
- `scope` 可选，建议填写模块名，例如 `api`、`worker`、`web`
- `subject` 使用祈使句，简洁说明本次改动，不以句号结尾

示例：

```text
feat(api): add reviewer status to history response
fix(worker): handle missing docker image gracefully
docs(readme): clarify local runtime requirements
test(app): cover invalid plan state transitions
```

建议：

- 一个 commit 只处理一个明确目标
- 避免使用 `update`、`fix stuff` 之类无信息量描述
- 大改动请拆分为多个可审查的 commit

## 代码风格与测试要求

请优先遵循仓库现有代码结构、命名方式和模块边界，不要为单次需求
引入额外复杂度。

代码风格要求：

- Python 代码兼容项目要求的 `Python >= 3.11`
- 保持函数职责单一，避免无关重构混入功能修改
- 新增接口、状态字段或配置项时，同步更新相关文档
- 前后端变更需保持接口字段、类型定义和文档一致

测试要求：

- 功能修复和新功能默认都要附带测试或说明无法补测的原因
- Python 相关改动至少运行：

```bash
uv run pytest
```

- 若只影响特定模块，可补充执行最相关的测试文件，例如：

```bash
uv run pytest tests/test_leader_event_runtime.py tests/test_leader_query_set.py
```

- 若改动涉及真实 Docker Worker / Kimi 集成链路，优先补充并执行本地集成验证：

```bash
uv run --python python3.12 python scripts/run_kimi_local_integration.py
```

- 若需要把真实 Kimi 集成用例纳入 pytest，请显式打开：

```bash
RUN_KIMI_LOCAL_INTEGRATION=1 \
OPENAI_BASE_URL="https://your-openai-compatible-endpoint" \
OPENAI_API_KEY="your-api-key" \
uv run --python python3.12 pytest -q tests/test_kimi_local_integration.py
```

- 提交前建议同步检查：

```text
docs/kimi-local-integration-checklist.md
docs/kimi-local-integration-troubleshooting.md
```

- 涉及 Web 或联调改动时，至少确认开发环境可以正常启动：

```bash
npm run dev
```

在测试、文档和代码审查要求都满足后，再发起合并请求。
