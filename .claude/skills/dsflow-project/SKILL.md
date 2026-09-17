---
name: dsflow-project
description: 在这个用 DSFlow 追踪的数据科学项目里推进任何一步之前先调用：写计划、执行步骤、写讲解或说明卡、验收、改 lifecycle/steps.json 的状态、等用户审批，都按这里的顺序做。它告诉你怎样查看当前进度、每个环节要落哪些文件、谁改状态。
---

# 在 DSFlow 被管项目里工作

1. **先读本目录的 `AGENTS.md`**，它是跨 agent 的唯一工作规则；本 skill 只补 Claude Code 里怎么操作。
2. **动手之前运行** `uv run dsflow next . --json`，按返回的 `phase` 做事，只做当前环节的事：
   - `plan`：主 agent 写 `plan.md`，改注册表状态为 `pending_approval`，然后用 Bash 工具的**后台方式**运行 `uv run dsflow await . <步骤> --timeout 7200`，再**停下来向用户汇报**"计划已提交，等你在平台或对话里审批"。不要接着执行。
   - `await_approval`：等用户。用户在平台点了「通过 / 退回」，后台的 `await` 命令会退出并把结果交给你：退出码 0 表示通过（读输出里的 `entry.note` 原话，再按第 3 条安排执行），退出码 3 表示退回（按原话改计划，改完重新 `await`）。用户在对话里直接表态时，主 agent 运行 `uv run dsflow approve . <步骤> --note "<原话>"` 或 `uv run dsflow reject . <步骤> --note "<原话>"` 记录，平台会改状态，不要手写 `approval_record.md`。
   - `execute`：执行 agent 执行 notebook（`dsflow run` 记录每次运行）、写 `report.md`、`step_card.yaml`、`guide.yaml`，登记产出的表；`validate` 与 `check` 通过后改状态为 `awaiting_acceptance`。
   - `acceptance`：主 agent 独立核对后写 `acceptance.md`，运行 `guide check` 与 `guide lint` 核对讲解；然后后台运行 `uv run dsflow await . <步骤> --timeout 7200`，停下来向用户汇报结果。
   - `await_confirmation`：等用户确认。平台上点了「确认完成」`await` 就退出（退出码 0，状态已是 `done`）；对话里表态用 `uv run dsflow confirm . <步骤> --note "<原话>"` 记录。状态变成 `done` 之后才为下一步制定计划。
3. **主 agent 不自行派发执行 agent**。用户明确说"委托你安排执行"时，用子 agent 执行，并把 `AGENTS.md` 的内容和本步 `plan.md` 交给它；用户没有委托时，写完计划就等用户安排。
4. **改 `lifecycle/steps.json` 之前先重新读文件**（平台可能刚改过状态），只改本步的 `status`（有轮次时连当前轮次一起改），其余字段原样写回。
5. **讲解 `guide.yaml` 由执行 agent 起草**，每次用 Write / Edit 改它，本项目的 hook 会自动跑 `guide lint`，不通过会把清单退回给你，改到通过为止；主 agent 验收时再跑一次 `guide check` 与 `guide lint`。
6. **向用户汇报**按 结果与能否继续 → 核心数字 → 主要操作 → 只影响判断的例外 的顺序，每句话带具体宾语并以句号结尾。
