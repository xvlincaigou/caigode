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
