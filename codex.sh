#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

HARNESS_DIR="${HARNESS_DIR:-$ROOT/.harness}"
PROMPTS_DIR="$HARNESS_DIR/prompts"
STATE_DIR="$HARNESS_DIR/state"
LOG_DIR="$HARNESS_DIR/logs"

DISCUSS_PROMPT_FILE="${DISCUSS_PROMPT_FILE:-$PROMPTS_DIR/discuss.md}"
RUN_PROMPT_FILE="${RUN_PROMPT_FILE:-$PROMPTS_DIR/run.md}"

SPEC_FILE="${SPEC_FILE:-$STATE_DIR/spec.md}"
ARCH_FILE="${ARCH_FILE:-$STATE_DIR/architecture.md}"
FEATURE_FILE="${FEATURE_FILE:-$STATE_DIR/feature_list.json}"
PROGRESS_FILE="${PROGRESS_FILE:-$STATE_DIR/codex-progress.md}"

DISCUSS_LOCK_FILE="${DISCUSS_LOCK_FILE:-$STATE_DIR/discussion.lock}"
LAST_THREAD_FILE="${LAST_THREAD_FILE:-$STATE_DIR/last_thread_id.txt}"
DECISIONS_FILE="${DECISIONS_FILE:-$STATE_DIR/decisions-needed.md}"

MODEL="${MODEL:-gpt-5.4}"
SANDBOX="${SANDBOX:-workspace-write}"
APPROVAL="${APPROVAL:-on-failure}"
ENABLE_SEARCH="${ENABLE_SEARCH:-0}"

MAX_ITERS="${MAX_ITERS:-9999}"
BACKOFF_MIN_SECONDS="${BACKOFF_MIN_SECONDS:-60}"
BACKOFF_MAX_SECONDS="${BACKOFF_MAX_SECONDS:-3600}"
SUCCESS_PAUSE_SECONDS="${SUCCESS_PAUSE_SECONDS:-1}"
AUTO_LOCK_AFTER_DISCUSS="${AUTO_LOCK_AFTER_DISCUSS:-0}"

DECISION_GATE="${DECISION_GATE:-1}"
HARNESS_PROTECT="${HARNESS_PROTECT:-1}"
PROTECTED_FILES="${PROTECTED_FILES:-codex.sh .harness/prompts/discuss.md .harness/prompts/run.md}"
PROTECT_BASELINE_FILE="${PROTECT_BASELINE_FILE:-$STATE_DIR/harness-protected.snapshot}"
PROTECT_ALERT_FILE="${PROTECT_ALERT_FILE:-$STATE_DIR/harness-protect-alert.md}"

if [[ -n "${CODEX_HOME:-}" ]]; then
  export CODEX_HOME
elif [[ -d "$ROOT/.codex-home" ]] && [[ -n "$(find "$ROOT/.codex-home" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
  # Reuse repository-local Codex home only when it already contains state.
  export CODEX_HOME="$ROOT/.codex-home"
else
  # Fall back to the user's default Codex home so existing login can be reused.
  export CODEX_HOME="$HOME/.codex"
fi

usage() {
  cat <<'TXT'
Usage:
  bash codex.sh              # only run interactive discuss phase (default)
  bash codex.sh discuss      # only run interactive discuss phase
  bash codex.sh run          # only run continuous exec phase
  bash codex.sh status       # show harness status
  bash codex.sh unlock       # remove discuss lock
  bash codex.sh clear-decisions  # clear decision gate file
  bash codex.sh protect-refresh  # refresh harness protection baseline
  bash codex.sh reset-logs   # clear .harness/logs
TXT
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing command: $cmd" >&2
    exit 1
  fi
}

write_decisions_clear() {
  cat > "$DECISIONS_FILE" <<TXT
# Decisions Needed
status: clear
updated_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

items:
- (none)
TXT
}

bootstrap() {
  mkdir -p "$PROMPTS_DIR" "$STATE_DIR" "$LOG_DIR" "$CODEX_HOME"

  if [[ ! -f "$SPEC_FILE" ]]; then
    cat > "$SPEC_FILE" <<'TXT'
# Product Spec
- 问题定义：
- 业务目标：
- 成功指标（可量化）：
- 约束（时间/人力/技术/合规）：
- 非目标（明确不做）：
- 用户场景与主流程：
- MVP 验收标准：
TXT
  fi

  if [[ ! -f "$ARCH_FILE" ]]; then
    cat > "$ARCH_FILE" <<'TXT'
# Architecture Contract

## 1) 业务分层（必填）
- 采用分层：
- 层与职责：
  - L-Interface:
  - L-Orchestration:
  - L-Domain:
  - L-Infra:

## 2) 模块边界（必填）
- 模块清单：
- 入口文件/命令：
- 模块依赖约束（谁可以依赖谁）：

## 3) 数据与状态（必填）
- 核心数据对象：
- 持久化策略：
- 状态一致性与回滚策略：

## 4) 外部集成（可选）
- 第三方服务：
- 失败与重试策略：

## 5) 非功能性要求（必填）
- 性能：
- 稳定性：
- 安全与高风险操作边界：
- 可观测性（日志/指标）：

## 6) 实施边界（必填）
- 本轮实现范围（In）：
- 明确不做（Out）：
- 每个二级任务的完成定义模板：
  - 修改文件：
  - 验证命令：
  - 完成信号：
TXT
  fi

  if [[ ! -f "$FEATURE_FILE" ]]; then
    cat > "$FEATURE_FILE" <<'TXT'
[
  {
    "id": "CAP-001",
    "level": "L1",
    "kind": "capability",
    "title": "示例能力组：核心业务能力框架",
    "description": "用于承载可执行二级任务，不直接作为提交单位。",
    "status": "todo",
    "children": [
      "TASK-001"
    ]
  },
  {
    "id": "TASK-001",
    "level": "L2",
    "kind": "workitem",
    "parent_id": "CAP-001",
    "title": "定义并落盘真实任务，不再使用示例任务 (.harness/state/feature_list.json)",
    "objective": "用真实项目任务替换示例，确保每个二级任务都可单次会话完成并提交。",
    "scope_in": [
      "重写该文件中的任务项"
    ],
    "scope_out": [
      "实现业务代码"
    ],
    "entrypoints": [
      ".harness/state/feature_list.json"
    ],
    "changed_files": [
      ".harness/state/feature_list.json"
    ],
    "implementation_steps": [
      "删除示例 CAP/TASK",
      "按架构分层补齐 L1 能力组",
      "为每个 L1 拆分 1~4 个 L2 任务并补齐验收字段"
    ],
    "verification": [
      {
        "command": "jq . .harness/state/feature_list.json",
        "expect": "JSON 合法且字段完整"
      }
    ],
    "depends_on": [],
    "session_budget": 1,
    "status": "todo",
    "passes": false,
    "attempts": 0,
    "notes": ""
  }
]
TXT
  fi

  if [[ ! -f "$PROGRESS_FILE" ]]; then
    cat > "$PROGRESS_FILE" <<'TXT'
# Codex Progress

## Session Notes
TXT
  fi

  if [[ ! -f "$DECISIONS_FILE" ]]; then
    write_decisions_clear
  fi

  if [[ ! -f "$DISCUSS_PROMPT_FILE" ]]; then
    cat > "$DISCUSS_PROMPT_FILE" <<'TXT'
你现在是“架构优先”的需求澄清代理。先定架构与任务边界，再进入执行。

必须执行的流程（不可跳过）：
1) 先阅读并更新这些文件：
   - .harness/state/spec.md
   - .harness/state/architecture.md
   - .harness/state/feature_list.json
   - .harness/state/decisions-needed.md
2) 先用“选项式问卷”向用户澄清，不接受仅泛泛描述。每次最多问 3 个问题，每个问题都要带候选项与推荐项。
3) 所有关键问题确认后，再落盘架构与任务树；未确认项必须进入决策门控，不得假设完成。

问卷最小集合（必须覆盖）：
A. 分层模型（单选）
- A1: 三层（接口/领域/基础设施）
- A2: 四层（接口/编排/领域/基础设施）【推荐】
- A3: 六边形（端口/适配器）
- A4: 事件驱动（命令/事件/投影）
B. 模块边界（多选）
- B1: 入口层（Web/API/CLI/Worker）
- B2: 应用编排层（UseCase/Service）
- B3: 领域模型层（Domain/Policy）
- B4: 数据与集成层（DB/Cache/MQ/Third-party）
- B5: 运营与质量层（日志/监控/测试/发布）
C. 数据与状态（单选）
- C1: 文件状态为主【推荐】
- C2: SQLite
- C3: 外部服务
D. MVP 交付边界（单选）
- D1: 只做本地可用
- D2: 本地 + 最小自动化测试【推荐】
- D3: 本地 + CI

注意：
- 上述选项是“澄清脚手架”，不是项目类型假设。
- 不要把用户项目默认成 coding agent、CLI 工具或特定技术栈。

落盘要求：
1) .harness/state/spec.md：写清问题、目标、约束、非目标、MVP 验收标准（可量化）。
2) .harness/state/architecture.md：按文件模板补齐层职责、模块边界、依赖约束、状态策略、风险边界。
3) .harness/state/feature_list.json：必须是“L1 能力组 + L2 可执行任务”混合数组。

L2 任务硬约束（每条都必须满足）：
- kind 必须是 workitem，level 必须是 L2。
- title 必须包含 动词 + 对象 + 位置（文件或模块）。
- entrypoints/changed_files 至少各 1 项，且可定位。
- implementation_steps 必须是 3~7 条可执行步骤。
- verification 必须给出可执行命令与预期信号。
- session_budget 必须为 1（单次会话可完成）。
- status 初始为 todo，passes 初始为 false。

如果信息不足或冲突：
- 将 .harness/state/decisions-needed.md 写成 status: pending
- items 中写 question/options/recommendation
- 输出 DECISION_REQUIRED 并停止，不进入实现阶段
TXT
  fi

  if [[ ! -f "$RUN_PROMPT_FILE" ]]; then
    cat > "$RUN_PROMPT_FILE" <<'TXT'
你现在是连续执行代理。目标是“一轮只完成一个 L2 任务并提交”。

1) 先阅读这些文件：
   - .harness/state/spec.md
   - .harness/state/architecture.md
   - .harness/state/feature_list.json
   - .harness/state/codex-progress.md
   - .harness/state/decisions-needed.md
   - git log --oneline -n 20

2) 只允许选择一个 kind=workitem 且 level=L2 且 status=todo 的任务执行，并满足：
   - depends_on 里的任务都已 done
   - session_budget=1
   - changed_files 与 entrypoints 清晰可定位
3) 先输出本轮执行计划：目标任务 ID、涉及文件、验证命令。计划不清楚则先补全任务定义，不能硬做。
4) 仅实现该 L2 任务范围内改动，不扩散到无关任务。
5) 完成后执行该任务 verification 中定义的命令，并记录结果。
6) 验证通过后，必须执行 git add -A 和 git commit。
   - 提交信息格式：feat(<task-id>): <task-title>
   - 非新功能可用 fix/chore，但必须包含 task-id
7) 仅在“验证通过 + commit 成功”后，将该任务 status=done 且 passes=true。
8) 更新 .harness/state/codex-progress.md，记录：任务 ID、改动文件、验证命令与结果、提交哈希、下一步、阻塞点。
9) 如果任务未完成，不允许在原地空转：
   - 若是定义不清：先修正该任务字段（entrypoints/steps/verification）
   - 若是任务过大：拆成 2~4 个新的 L2 任务，并把原任务 status=blocked，notes 写明拆分原因
   - 禁止连续两轮在同一未完成任务上重复相同尝试
10) 如果需要人类决策：
   - 将 .harness/state/decisions-needed.md 写成 status: pending
   - 在 items 下列出决策问题、可选项、推荐项
   - 输出标记词 DECISION_REQUIRED
   - 本轮停止继续实现，等待人类输入
11) 不要预设项目类型（如 agent/CLI/Web/数据平台 等），执行内容必须以 spec/architecture/feature_list 的已确认信息为准。
12) 不要修改以下 harness 文件：
   - codex.sh
   - .harness/prompts/discuss.md
   - .harness/prompts/run.md
TXT
  fi
}

all_features_passed() {
  jq -e '
    type == "array"
    and length > 0
    and (
      ([.[] | select((.kind // "") == "workitem" and (.level // "") == "L2")] | length) as $l2_count
      | if $l2_count > 0 then
          all(
            .[];
            if ((.kind // "") == "workitem" and (.level // "") == "L2")
            then ((.passes // false) == true and (.status // "") == "done")
            else true
            end
          )
        else
          all(.[]; (.passes // false) == true)
        end
    )
  ' "$FEATURE_FILE" >/dev/null 2>&1
}

extract_thread_id_from_log() {
  local log_file="$1"
  grep -E '^\{"type":"thread\.started"' "$log_file" 2>/dev/null | tail -n 1 | jq -r '.thread_id' 2>/dev/null || true
}

is_retryable_error() {
  local log_file="$1"
  grep -Eqi 'rate[ -]?limit|insufficient[_ ]quota|quota|429|network error|stream disconnected|temporar|timeout|overloaded|reconnecting' "$log_file"
}

auto_commit_iteration() {
  local iteration="$1"
  local has_changes=1

  if [[ -z "$(git -C "$ROOT" status --porcelain)" ]]; then
    has_changes=0
  fi

  local ts msg
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  msg="chore(harness): checkpoint iteration $iteration @ $ts"

  if [[ "$has_changes" -eq 1 ]]; then
    git -C "$ROOT" add -A
    if git -C "$ROOT" commit -m "$msg" >/dev/null; then
      log "auto-commit succeeded: $msg"
      return 0
    fi
  else
    if git -C "$ROOT" commit --allow-empty -m "$msg (empty)" >/dev/null; then
      log "auto-commit succeeded (empty): $msg"
      return 0
    fi
  fi


  log "auto-commit failed"
  return 1
}

extract_retry_after_seconds() {
  local log_file="$1"
  local hint
  hint="$(grep -Eoi 'retry[- ]?after[^0-9]*[0-9]+' "$log_file" | tail -n 1 || true)"
  if [[ -n "$hint" ]]; then
    echo "$hint" | grep -Eo '[0-9]+' | tail -n 1
    return 0
  fi
  echo "$BACKOFF_MIN_SECONDS"
}

hash_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    echo "MISSING"
  fi
}

refresh_protect_baseline() {
  if [[ "$HARNESS_PROTECT" != "1" ]]; then
    return 0
  fi

  : > "$PROTECT_BASELINE_FILE"

  local rel
  for rel in $PROTECTED_FILES; do
    printf '%s\t%s\n' "$rel" "$(hash_file "$ROOT/$rel")" >> "$PROTECT_BASELINE_FILE"
  done

  rm -f "$PROTECT_ALERT_FILE"
}

check_harness_integrity() {
  if [[ "$HARNESS_PROTECT" != "1" ]]; then
    return 0
  fi
  if [[ ! -f "$PROTECT_BASELINE_FILE" ]]; then
    refresh_protect_baseline
    return 0
  fi

  local changed=0
  : > "$PROTECT_ALERT_FILE"

  local rel old_hash current_hash
  while IFS=$'\t' read -r rel old_hash || [[ -n "${rel:-}" ]]; do
    [[ -n "${rel:-}" ]] || continue
    current_hash="$(hash_file "$ROOT/$rel")"
    if [[ "$current_hash" != "$old_hash" ]]; then
      changed=1
      printf -- '- %s (expected: %s, current: %s)\n' "$rel" "$old_hash" "$current_hash" >> "$PROTECT_ALERT_FILE"
    fi
  done < "$PROTECT_BASELINE_FILE"

  if [[ "$changed" -eq 1 ]]; then
    {
      echo
      echo "If you intentionally changed harness files, run:"
      echo "  bash codex.sh protect-refresh"
    } >> "$PROTECT_ALERT_FILE"
    return 1
  fi

  rm -f "$PROTECT_ALERT_FILE"
  return 0
}

is_decision_pending() {
  if [[ "$DECISION_GATE" != "1" ]]; then
    return 1
  fi
  [[ -f "$DECISIONS_FILE" ]] || return 1
  grep -Eqi '^[[:space:]]*status:[[:space:]]*pending([[:space:]]|$)' "$DECISIONS_FILE"
}

decision_marker_in_log() {
  local log_file="$1"
  grep -Eqi 'DECISION_REQUIRED|awaiting user decision|needs human decision|blocked on decision' "$log_file"
}

seed_decision_file_from_log() {
  local log_file="$1"
  cat > "$DECISIONS_FILE" <<TXT
# Decisions Needed
status: pending
updated_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

items:
- question: 请查看执行日志并补充需要你拍板的决策项
  options:
    - option A
    - option B
  recommendation: option A (placeholder)

source_log: $log_file
TXT
}

run_discuss_phase() {
  if [[ -f "$DISCUSS_LOCK_FILE" ]]; then
    log "discussion already locked, skipping discuss phase"
    return 0
  fi

  log "starting discuss phase (interactive)"

  local -a cmd
  cmd=(codex -C "$ROOT" -m "$MODEL" -s "$SANDBOX" -a "$APPROVAL")
  if [[ "$ENABLE_SEARCH" == "1" ]]; then
    cmd+=(--search)
  fi
  cmd+=("$(cat "$DISCUSS_PROMPT_FILE")")

  "${cmd[@]}"

  if [[ "$AUTO_LOCK_AFTER_DISCUSS" == "1" ]]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$DISCUSS_LOCK_FILE"
    log "discussion locked automatically"
    return 0
  fi

  read -r -p "需求是否已澄清完成并锁定进入执行阶段？[y/N] " answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$DISCUSS_LOCK_FILE"
    log "discussion locked"
  else
    log "discussion not locked; you can rerun discuss later"
    return 0
  fi
}

run_exec_iteration() {
  local iteration="$1"
  local log_file="$LOG_DIR/iter-$(printf '%05d' "$iteration")-$(date +%Y%m%dT%H%M%S).log"

  log "iteration $iteration"
  log "log file: $log_file"

  local -a cmd
  # NOTE: `codex exec` does not support `-a/--ask-for-approval`.
  # Approval policy for exec should be managed via Codex config/profiles.
  cmd=(codex exec --json -C "$ROOT" -m "$MODEL" -s "$SANDBOX")
  if [[ "$ENABLE_SEARCH" == "1" ]]; then
    cmd+=(--search)
  fi
  cmd+=(-)

  set +e
  "${cmd[@]}" < "$RUN_PROMPT_FILE" 2>&1 | tee "$log_file"
  local rc=${PIPESTATUS[0]}
  set -e

  local thread_id
  thread_id="$(extract_thread_id_from_log "$log_file")"
  if [[ -n "$thread_id" ]]; then
    printf '%s\n' "$thread_id" > "$LAST_THREAD_FILE"
  fi

  if ! check_harness_integrity; then
    log "harness protection triggered; see $PROTECT_ALERT_FILE"
    return 30
  fi

  if [[ "$DECISION_GATE" == "1" ]]; then
    if decision_marker_in_log "$log_file" && ! is_decision_pending; then
      seed_decision_file_from_log "$log_file"
    fi

    if is_decision_pending; then
      log "decision gate triggered; see $DECISIONS_FILE"
      return 20
    fi
  fi

  if [[ "$rc" -eq 0 ]]; then
    if ! auto_commit_iteration "$iteration"; then
      return 1
    fi

    if all_features_passed; then
      log "all features passed"
      return 100
    fi

    log "iteration succeeded"
    return 0
  fi

  if is_retryable_error "$log_file"; then
    log "iteration failed with retryable error"
    return 10
  fi

  log "iteration failed with non-retryable error"
  return 1
}

run_exec_loop() {
  local backoff="$BACKOFF_MIN_SECONDS"
  local i=1

  if [[ "$DECISION_GATE" == "1" ]] && is_decision_pending; then
    log "decision gate already pending before run; clear $DECISIONS_FILE first"
    return 0
  fi

  refresh_protect_baseline

  while [[ "$i" -le "$MAX_ITERS" ]]; do
    if run_exec_iteration "$i"; then
      local state=0
    else
      local state=$?
    fi

    if [[ "$state" -eq 100 ]]; then
      return 0
    fi

    if [[ "$state" -eq 20 ]]; then
      log "paused for human decision"
      return 0
    fi

    if [[ "$state" -eq 30 ]]; then
      log "paused because protected harness files changed"
      return 1
    fi

    if [[ "$state" -eq 0 ]]; then
      backoff="$BACKOFF_MIN_SECONDS"
      sleep "$SUCCESS_PAUSE_SECONDS"
      i=$((i + 1))
      continue
    fi

    if [[ "$state" -eq 10 ]]; then
      local latest_log retry_after
      latest_log="$(ls -1t "$LOG_DIR"/*.log 2>/dev/null | head -n 1 || true)"

      if [[ -n "$latest_log" ]]; then
        retry_after="$(extract_retry_after_seconds "$latest_log")"
      else
        retry_after="$backoff"
      fi

      if [[ -z "$retry_after" ]]; then
        retry_after="$backoff"
      fi
      if [[ "$retry_after" -lt "$backoff" ]]; then
        retry_after="$backoff"
      fi
      if [[ "$retry_after" -gt "$BACKOFF_MAX_SECONDS" ]]; then
        retry_after="$BACKOFF_MAX_SECONDS"
      fi

      log "sleeping ${retry_after}s before retry"
      sleep "$retry_after"

      backoff=$((backoff * 2))
      if [[ "$backoff" -gt "$BACKOFF_MAX_SECONDS" ]]; then
        backoff="$BACKOFF_MAX_SECONDS"
      fi

      i=$((i + 1))
      continue
    fi

    return 1
  done

  log "reached MAX_ITERS=$MAX_ITERS"
  return 0
}

show_status() {
  local total="0"
  local passed="0"

  if [[ -f "$FEATURE_FILE" ]]; then
    total="$(jq '
      ([.[] | select((.kind // "") == "workitem" and (.level // "") == "L2")] | length) as $l2_count
      | if $l2_count > 0 then $l2_count else length end
    ' "$FEATURE_FILE" 2>/dev/null || echo 0)"
    passed="$(jq '
      ([.[] | select((.kind // "") == "workitem" and (.level // "") == "L2")] | length) as $l2_count
      | if $l2_count > 0 then
          ([.[] | select((.kind // "") == "workitem" and (.level // "") == "L2" and (.passes // false) == true and (.status // "") == "done")] | length)
        else
          ([.[] | select((.passes // false) == true)] | length)
        end
    ' "$FEATURE_FILE" 2>/dev/null || echo 0)"
  fi

  echo "ROOT=$ROOT"
  echo "CODEX_HOME=$CODEX_HOME"
  echo "SANDBOX=$SANDBOX"
  echo "APPROVAL=$APPROVAL"
  echo "LOCKED=$([[ -f "$DISCUSS_LOCK_FILE" ]] && echo yes || echo no)"
  echo "FEATURES_PASSED=${passed}/${total}"
  echo "LAST_THREAD_ID=$(cat "$LAST_THREAD_FILE" 2>/dev/null || echo '-')"
  echo "DECISION_GATE=$DECISION_GATE"
  echo "DECISION_PENDING=$([[ "$DECISION_GATE" == "1" ]] && is_decision_pending && echo yes || echo no)"
  echo "DECISIONS_FILE=$DECISIONS_FILE"
  echo "HARNESS_PROTECT=$HARNESS_PROTECT"
  echo "PROTECT_BASELINE_FILE=$PROTECT_BASELINE_FILE"
  echo "PROTECT_ALERT_FILE=$PROTECT_ALERT_FILE"
}

main() {
  local mode="${1:-discuss}"

  require_cmd codex
  require_cmd jq
  require_cmd git
  require_cmd shasum

  bootstrap

  case "$mode" in
    all)
      echo "mode 'all' is disabled. Use: bash codex.sh discuss, then bash codex.sh run" >&2
      exit 1
      ;;
    discuss)
      run_discuss_phase
      ;;
    run)
      run_exec_loop
      ;;
    status)
      show_status
      ;;
    unlock)
      rm -f "$DISCUSS_LOCK_FILE"
      log "discussion unlocked"
      ;;
    clear-decisions)
      write_decisions_clear
      log "decisions cleared"
      ;;
    protect-refresh)
      refresh_protect_baseline
      log "harness protection baseline refreshed"
      ;;
    reset-logs)
      rm -f "$LOG_DIR"/*.log 2>/dev/null || true
      log "logs cleared"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "unknown mode: $mode" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
