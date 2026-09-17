# AGENTS.md（DSFlow 被管项目）

本项目用 DSFlow 追踪：**文件是唯一事实来源**，平台只读取、核对和展示，你写完文件切回浏览器就是最新状态。完整说明见 DSFlow 仓库的 `docs/agent-guide.md`。在本目录里运行 dsflow 命令用：`uv run dsflow <子命令>`。

**动手之前先运行 `uv run dsflow next . --json`**：它告诉你项目在哪一步、这一步处于哪个环节、本轮目录还缺哪些文件、该跑哪条命令。

## 一轮的五个环节（每个步骤、每一轮都一样）

| 环节 | 谁 | 落哪些文件 | 注册表 `lifecycle/steps.json` 的状态 |
|---|---|---|---|
| 1 制定计划 | 主 agent | `plan.md`：为什么做、输入、处理办法、产物、验收标准、停止条件 | 主 agent 改为 `pending_approval` |
| 2 用户评估 | 用户 | `approval_record.md`（由平台或 `dsflow approve` 写，不要手写） | 平台改为 `in_progress` |
| 3 执行 | 执行 agent | `nb_<步骤>.ipynb`（公共代码放 `src/`）、每次运行用 `dsflow run` 记录、`report.md`（用户报告）、`step_card.yaml`（说明卡）、`guide.yaml`（讲解初稿） | 执行 agent 在 validate 与 check 通过后改为 `awaiting_acceptance` |
| 4 验收 | 主 agent | `acceptance.md`：从实际产物独立核对操作、数据变化、关键结果与验收标准，说明为什么通过或未通过；同时运行 `guide check` 与 `guide lint` 核对讲解 | 不变 |
| 5 用户确认 | 用户 | `approval_record.md` 再追加一条 | 平台改为 `done`（退回则 `in_progress`） |

- 没有审批不执行；没有用户确认不改为 `done`、不进入下一步。**等审批的办法**：主 agent 交完计划（或验收报告）后运行 `uv run dsflow await . <步骤> --timeout 7200`（能后台运行的 agent 放后台，命令退出即被唤醒；不能的前台等，`--timeout 540` 分段等），用户在平台点了按钮它就退出：退出码 0 通过 / 确认，3 退回，4 超时。用户在对话里表态时，由主 agent 运行 `uv run dsflow approve / reject / confirm . <步骤> --note "<原话>"` 记录，平台改状态；不要手写 `approval_record.md`。
- 主 agent 不自行派发执行 agent；只有用户明确委托时，才由主 agent 安排独立的执行 agent，并把本文件交给它。
- **改 `lifecycle/steps.json` 之前必须重新读取文件**：平台可能刚改过状态。只改本步的 `status`（有轮次的连当前轮次一起改），别的字段原样保留。
- 每步只留上面这些文件。`plan_user.md`、`plan_original.md`、`report_rewrite.md` 这类自用文件不要再产生；平台不读它们。
- 返工开新轮次 `revisions/rNN_日期_说明/`，在 `revisions[].summary` 写明相对上一轮递进了什么，并在 `revision_loops` 登记原因；历史不覆盖。**新轮次必须是递进、优化或新方向；只是替代 / 覆盖上一轮的内容，就更新原轮次，不新增。**

## 三份要写给人看的文件

- **`report.md` 用户报告**：写给不看代码的读者。开头一句说做完了吗、最重要的业务结果、能否继续；正文按读者要弄明白的一到三个问题组织，每个问题走 输入 → 关键操作 → 实际输出 → 业务上意味着什么；至少给一个真实可核对的例子（输入记录 → 规则 → 输出记录 → 所在产物）。
- **`guide.yaml` 讲解**：写给懂业务、能读代码、没做过数据科学的负责人。只讲 notebook 里真实的单元格：每格「做什么 / 为什么 / 输出结果讲解」，不复述用户报告。开头五段 背景 / 目的 / 结论 / 操作 / 下一步，各一句；结论最多一个数字。执行 agent 起草，主 agent 验收时核对。用 `uv run dsflow guide init . <步骤>` 生成骨架；写完 `guide check`（引用与数字回 notebook 输出核对）和 `guide lint`（用词、句子、篇幅、照搬）都要通过，本项目 `.claude/settings.json` 里的 hook 会在你每次改 guide.yaml 时自动跑 lint，不通过会退回。
- **`step_card.yaml` 说明卡**：只有四样——一句话结论 `headline`、能否继续 `can_continue`、核心数字 `core_numbers`（每个写 `source`，平台从产物重算核对）、产物 `artifacts`（能出图就登记 `kind: figure`，看板直接显示）。模板见 DSFlow 的 `templates/step_card.yaml`。

## 每句话都要能单独看懂

主语 + 动词 + 具体宾语（表名、列名、文件、术语、数字）+ 结果，以句号结尾。不用口语缩略动词（对上、合上、钉死、站住、跑通……），抽象词（口径、主线……）没在术语表登记就不用。**不造新概念**：只用 `vocabulary.json` 登记过、或数据表字段里有的说法；新术语先登记（写明出处）再用，同一个东西始终用同一个说法。规则与禁用词见 DSFlow 的 `docs/讲解写法.md`。

## 汇报规则

首屏只回答四件事：做完了吗、能否继续；核心数字（处理前 / 变化 / 处理后，写清是记录数还是不同值个数、期间、范围）；用直白的话说主要操作；只列会影响判断的例外。其余放在后面。必须写明产物路径。

## 登记数据与模型

- 产物只算有用的最终文件：后续要用的表、给业务看的报告和图、模型。产出的表用 SDK `run.log_output(...)` 或 `uv run dsflow data add` 登记，旧表被替代时写 `replaces`；中间结果和核对清单不登记。
- 只读没改的表：走 `dsflow run` 的步骤自动记录；否则 `uv run dsflow data link . <表名> --step <步骤> --role 核对`。
- 模型：训练脚本里 `run.log_model(文件, "模型名")`，登记为候选；不覆盖已登记的模型文件。

## 不要做的事

- 不修改 `data/raw/`（原始数据只读，平台会告警）。
- 不删除运行记录；不替用户审批计划、裁定待决事项、把步骤改为 `done`、把模型标为已验收 / 已交付。
- 依赖要在 `steps.json` 显式登记，不按编号推导；不在历史轮次上直接改。

## 常用命令

```
uv run dsflow next . --json                              # 在哪一步、缺什么、下一步做什么
uv run dsflow await . <步骤> --timeout 7200               # 等用户在平台审批 / 确认（退出码 0 通过、3 退回、4 超时）
uv run dsflow approve . <步骤> --note "<原话>"             # 用户在对话里通过了计划；reject 退回；confirm 确认完成
uv run dsflow validate .                                 # 注册表校验
uv run dsflow check . --step <步骤>                      # 交接前核对：告警 + 数字核对 + 术语检查
uv run dsflow run <步骤> -p . -- python -m dsflow.tracking.notebook <本轮目录>/nb_<步骤>.ipynb
uv run dsflow guide init . <步骤>                        # 按 notebook 真实单元格生成讲解骨架
uv run dsflow guide check . --step <步骤>                # 核对讲解：引用与数字
uv run dsflow guide lint . --step <步骤>                 # 体检讲解：用词、句子、篇幅、照搬
uv run dsflow data add . <文件> --name <表名> --stage processed --produced-by <步骤> --replaces <旧表名>
uv run dsflow delivery init . <模型名>                    # 生成 / 刷新交付清单
```

## 本项目的约定

- 数据表就叫数据里的名字：`红酒`、`白酒`、`quality`、11 个理化指标用原列名；三份数据叫训练集 / 验证集 / 最终评估集（不叫测试集）。术语见 `vocabulary.json`。
- 1.1～3.1 是历史步骤：执行用 `src/*.py` 脚本，独立复核在 `checks/verify.py`，运行日志在 `execution.jsonl`。7.1 起用 notebook + `dsflow run`，并保留同样的 `checks/verify.py` 独立复核。
- 最终评估集只在 9.1 评估一次；任何步骤不得用它拟合、选模型或调参。
