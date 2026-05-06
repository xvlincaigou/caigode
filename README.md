# codex-harness-template

一个可直接复制的 Codex Harness 模板，核心目标：

1. 先做“架构契约”再做实现。
2. 把任务拆成 L1/L2，执行阶段每轮只完成 1 个 L2 并提交。
3. 避免模型在同一模糊子任务上反复空转。
4. 需要你拍板时自动暂停。
5. 默认保护 harness 关键文件不被误改。

## 设计原则

- 架构优先：先落盘 `.harness/state/architecture.md`，再开始编码。
- 问卷澄清：讨论阶段必须使用选项式问题，不接受泛泛需求。
- 任务分层：
  - `L1 capability`：能力组（不直接作为提交单位）
  - `L2 workitem`：可执行任务（必须单会话可完成）
- 单轮单任务：每轮只做一个 `L2`，验证通过后提交，再标记完成。
- 失败不空转：同一未完成任务不能连续重复相同尝试；必要时强制拆分。

## 目录

```text
.
├── codex.sh
└── .harness/
    ├── prompts/
    │   ├── discuss.md
    │   └── run.md
    ├── state/
    │   ├── spec.md
    │   ├── architecture.md
    │   ├── feature_list.json
    │   ├── codex-progress.md
    │   └── decisions-needed.md
    └── logs/
```

## 快速开始

1. 进入仓库

```bash
cd ~/workspace/codex-harness-template
```

2. 登录 Codex（首次）

```bash
codex login
```

3. 需求澄清（架构问卷 + 任务树）

```bash
bash codex.sh discuss
```

4. 连续执行

```bash
bash codex.sh run
```

## 常用命令

```bash
bash codex.sh discuss          # 只进行需求澄清
bash codex.sh run              # 只进行连续执行
bash codex.sh status           # 查看状态
bash codex.sh unlock           # 解锁讨论阶段（重新讨论）
bash codex.sh clear-decisions  # 清空决策门控（恢复执行）
bash codex.sh protect-refresh  # 刷新保护基线（你有意改了 harness 后执行）
bash codex.sh reset-logs       # 清理日志
```

## 任务结构（feature_list.json）

必须是数组，且混合两类对象：

- `L1 capability`：`kind=capability`，用于组织能力组。
- `L2 workitem`：`kind=workitem`，用于执行与提交。

`L2 workitem` 最小字段要求：

- `id`, `level=L2`, `kind=workitem`, `parent_id`
- `title`（动词 + 对象 + 位置）
- `entrypoints`, `changed_files`
- `implementation_steps`（3~7 条）
- `verification`（命令 + 预期）
- `session_budget=1`
- `status`（初始 `todo`）, `passes`（初始 `false`）

## 关键环境变量

```bash
MODEL=gpt-5.4
SANDBOX=workspace-write
RUN_SANDBOX=danger-full-access
APPROVAL=on-failure
ENABLE_SEARCH=0

MAX_ITERS=9999
BACKOFF_MIN_SECONDS=60
BACKOFF_MAX_SECONDS=3600
SUCCESS_PAUSE_SECONDS=1
AUTO_LOCK_AFTER_DISCUSS=0

DECISION_GATE=1
HARNESS_PROTECT=1
PROTECTED_FILES="codex.sh .harness/prompts/discuss.md .harness/prompts/run.md"

CODEX_HOME=~/.codex
```

## 权限行为说明

- `RUN_SANDBOX=danger-full-access`（默认）：`run` 阶段使用全权限沙箱，允许写入 `.git/` 以完成自动提交。
- `SANDBOX=workspace-write`：`discuss` 阶段在工作区内读写可执行，越界操作会受限。
- `APPROVAL=on-failure`（默认）：先自动执行，失败后再请求你授权。
- `APPROVAL=on-request`：模型可主动请求你审批。
- `APPROVAL=never`：不请求审批（风险最高）。

## 登录行为说明

- `codex.sh` 会按如下顺序决定 `CODEX_HOME`：
  1. 你显式设置的 `CODEX_HOME`
  2. 仓库内非空 `.codex-home`
  3. `~/.codex`（默认）
- 如果你在终端已登录 Codex，通常会复用 `~/.codex`，不会再次强制登录。

## 决策门控（Decision Gate）

开启 `DECISION_GATE=1` 时：

- 代理需要你决策时，会将 `.harness/state/decisions-needed.md` 写成 `status: pending`。
- Harness 检测到后自动暂停循环。
- 你补充后执行：

```bash
bash codex.sh clear-decisions
bash codex.sh run
```

## Harness 保护（Harness Protect）

开启 `HARNESS_PROTECT=1` 时：

- 每轮执行后校验受保护文件是否被改动。
- 如被改动会暂停并生成告警：`.harness/state/harness-protect-alert.md`。
- 如果改动是你故意做的，执行：

```bash
bash codex.sh protect-refresh
```

## 建议实践

- 讨论阶段先把 `architecture.md` 填完整，再生成 L1/L2 任务树。
- 每个 L2 必须能在单轮会话内完成并 commit。
- 执行失败不要只写“未完成”；要么补齐任务定义，要么拆分任务。

## 参考

- https://www.anthropic.com/engineering/harness-design-long-running-apps
- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- https://openai.com/zh-Hans-CN/index/harness-engineering/
