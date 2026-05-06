# Architecture Contract

## 1) 业务分层（必填）
- 采用分层：
  - A1 三层：接口层 / 领域层 / 基础设施层。
- 层与职责：
  - L-Interface:
    - 承接多子命令 CLI 入口、REPL 会话循环、参数解析、用户交互输出。
    - 承接 B2 应用编排模块，负责将一次用户输入编排为领域决策、模型调用、工具执行和状态落盘。
    - 计划中的主要模块：`src/caigode/cli.py`、`src/caigode/interface/repl.py`、`src/caigode/interface/handlers/`、`src/caigode/application/`。
  - L-Orchestration:
    - 本项目不设独立编排层。
    - B2 以逻辑模块形式存在于接口层内部的 `application` 包中，避免与 A1 冲突。
  - L-Domain:
    - 定义会话、消息、任务计划、工作项、工具调用、验证结果、交付产物等核心对象。
    - 定义规则：状态转移、工具权限、验证结论、交付材料拼装规则。
    - 计划中的主要模块：`src/caigode/domain/session.py`、`src/caigode/domain/task.py`、`src/caigode/domain/policies.py`.
  - L-Infra:
    - 提供 OpenAI 兼容 API 客户端、文件状态仓储、工作区文件读写、shell 执行、git 信息采集、日志与测试支撑。
    - 计划中的主要模块：`src/caigode/infra/openai_client.py`、`src/caigode/infra/state_store.py`、`src/caigode/infra/workspace.py`、`src/caigode/infra/shell.py`、`src/caigode/infra/review_artifacts.py`.

## 2) 模块边界（必填）
- 模块清单：
  - B1 入口层：CLI 子命令、参数与交互适配。
  - B2 应用编排层：聊天会话服务、单次运行服务、状态查询服务、交付摘要服务。
  - B3 领域模型层：会话状态、消息、工具调用、验证报告、交付材料等对象与策略。
  - B4 数据与集成层：OpenAI 兼容 API、文件状态存储、工作区访问、shell、git。
  - B5 运营与质量层：日志、夹具、自动化测试、开发文档。
- 入口文件/命令：
  - 产品入口不使用 `codex.sh`。
  - 新产品入口定义为 Python CLI：
    - `uv run python -m caigode.cli chat`
    - `uv run python -m caigode.cli run`
    - `uv run python -m caigode.cli status`
    - `uv run python -m caigode.cli review`
  - 后续如提供可执行脚本，统一指向 `src/caigode/cli.py`。
- 模块依赖约束（谁可以依赖谁）：
  - 接口层可依赖领域层和基础设施层暴露的抽象与适配器。
  - 接口层中的 `application` 编排模块可以组合领域对象与基础设施服务，但不得把基础设施细节泄漏给领域层。
  - 领域层不得依赖 CLI、HTTP、文件系统、shell 或 git 具体实现。
  - 基础设施层不得承载业务策略，只实现端点访问、状态读写和外部副作用。
  - 运营与质量层可引用任意层进行测试和观测，但不反向参与运行时领域决策。

## 3) 数据与状态（必填）
- 核心数据对象：
  - `AgentConfig`：模型、URL、API Key、工作区、会话目录、默认验证命令。
  - `SessionState`：会话 ID、当前模式、消息历史、计划、最近动作、错误状态。
  - `TaskIntent`：用户任务、约束、目标文件、交付要求。
  - `ToolAction`：文件读取、文件修改、shell 执行、git 摘要、review 产物写入。
  - `VerificationResult`：命令、退出码、摘要、时间戳。
  - `ReviewArtifact`：变更摘要、验证摘要、提交说明草稿、后续风险。
- 持久化策略：
  - C1 文件状态为主。
  - 运行时状态写入工作区内 `.caigode/` 目录。
  - Python 依赖、锁文件与脚本执行由 `uv` 管理，锁文件应纳入仓库。
  - 推荐文件布局：
    - `pyproject.toml`
    - `uv.lock`
    - `.caigode/config.snapshot.json`
    - `.caigode/sessions/<session-id>.json`
    - `.caigode/logs/<session-id>.log`
    - `.caigode/artifacts/<session-id>-review.md`
    - `.caigode/artifacts/<session-id>-commit.txt`
- 状态一致性与回滚策略：
  - 状态文件采用“临时文件写入 + 原子替换”策略。
  - 文件修改前后均记录摘要；失败命令不回滚工作区，但必须记录到会话状态与日志。
  - 对高风险 shell 指令和批量文件改动，接口层应要求显式确认或启用安全策略。

## 4) 外部集成（可选）
- 第三方服务：
  - 唯一批准的外部网络集成是 OpenAI 兼容 API 端点。
  - API 端点必须支持自定义 `base_url`、`model` 和鉴权信息。
  - 不把 `codex` CLI 作为模型引擎依赖。
- 失败与重试策略：
  - 模型请求失败时保留原始错误上下文，并返回可读诊断。
  - 对网络超时、429、5xx 可配置有限重试；默认重试次数应保守。
  - 本地命令执行只按退出码判定成功与否，不做隐式重放。

## 5) 非功能性要求（必填）
- 性能：
  - 目标为单用户本地使用，不追求高并发。
  - CLI 冷启动应仅完成配置装载与必要初始化，避免非必要扫描全仓库。
- 稳定性：
  - 任一子命令失败时返回非零退出码，并在日志或终端给出可定位原因。
  - 最小自动化测试至少覆盖配置装载、CLI 入口、会话状态持久化、模型客户端适配和 review 产物输出。
  - 本地开发、测试与运行命令统一通过 `uv run` 执行，避免环境漂移。
- 安全与高风险操作边界：
  - shell 执行范围限制在用户指定工作区。
  - 不默认允许跨工作区写入、系统级目录写入或任意外部服务访问。
  - API Key 不写入 review 产物与普通日志；如需快照，仅保留脱敏信息。
- 可观测性（日志/指标）：
  - 运行日志写入 `.caigode/logs/`。
  - `status` 子命令应能读取最近会话状态、最近验证结果与最近错误。
  - MVP 不强制引入指标平台，但日志字段需要支撑问题定位。

## 6) 实施边界（必填）
- 本轮实现范围（In）：
  - 新建独立 Python 项目骨架与多子命令 CLI。
  - 建立基于 `uv` 的依赖管理、锁文件与执行命令约定。
  - 实现交互式会话主路径、文件状态持久化、OpenAI 兼容 API 客户端、本地工具适配。
  - 实现最小 review/交付材料输出。
  - 编写本地最小自动化测试。
- 明确不做（Out）：
  - 改写 `codex.sh` 成为产品主入口。
  - 接入数据库、浏览器自动化、远程 CI 托管、插件系统、多代理协作。
  - 实现远程 PR 创建、代码托管平台发布或多工作区集中调度。
- 每个二级任务的完成定义模板：
  - 修改文件：限定到单一能力闭环内的明确文件集合。
  - 验证命令：必须可直接在仓库根目录执行。
  - 完成信号：退出码为 `0`，并出现对应 CLI/测试/产物文件信号。
