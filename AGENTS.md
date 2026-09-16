# AGENTS.md（DSFlow 被管项目）

本项目用 DSFlow 追踪：文件是唯一事实来源，平台只读取、核对和展示。完整说明见 DSFlow 仓库的 `docs/agent-guide.md`。

## 工作顺序（每个步骤、每一轮都一样）

1. **计划**：写 `plan.md`（执行版）和 `plan_user.md`（给用户看的版本），等用户审批；审批原话记在 `approval_record.md`。未经审批不执行。
2. **执行**：本步的 notebook（`nb_<步骤>.ipynb`，代码多时把公共部分放 `src/`），每次运行都用 SDK 或 `dsflow run` 记录——写清假设、结论和有效性（有效 / 无效 / 无结论）。**失败、无效、无结论的尝试同样要记。**
3. **写讲解、说明卡与报告**：本轮目录下的 `guide.yaml`（notebook 导读，步骤页默认打开的就是它）、`step_card.yaml`（格式见 DSFlow 的 `templates/step_card.yaml`）和 `report.md`。导读围绕 notebook 的真实单元格讲「在做什么 / 为什么这样做 / 输出怎么读」，写给懂业务、能读代码但没做过数据科学的负责人看，不复述报告；数字照输出原样写，平台会逐个回到输出里核对。
4. **自查**：`uv run dsflow validate .` 和 `uv run dsflow check .`，退出码为 0 才交接。
5. **验收**：主验收写在 `acceptance/<日期>_<说明>/report.md`。
6. **用户确认后**才把 `lifecycle/steps.json` 里的状态改为 `done`，进入下一步。返工开新轮次 `revisions/rNN_日期_说明/`，在 `revisions[].summary` 写明相对上一轮递进了什么，并在 `revision_loops` 登记原因；历史不覆盖。**新轮次必须是递进、优化或新方向；只是替代 / 覆盖上一轮的内容，就更新原轮次，不新增。**
7. **登记产物**：产物只算有用的最终文件（后续要用的表、给业务看的报告、模型）。产出的表用 SDK `log_output` 或 `dsflow data add` 登记，旧表被替代时写 `replaces`；中间结果和核对清单不登记。

## 汇报规则

- 首屏只回答四件事：做完了吗、能否继续；核心数字（处理前 / 变化 / 处理后，写清口径：记录数还是不同值个数、期间、范围）；用直白的话说主要操作；只列会影响判断的例外。其余放在后面。
- 必须写明产物路径，并在讲解中引用；主动给真实、可追溯的例子（输入记录 → 规则 → 输出记录 → 所在产物）。
- 说明卡里的核心数字写 `source`（`产物路径#取值方式`），让平台能从产物重算核对。
- **不造新概念**：只用 `vocabulary.json` 登记过、或数据表字段里有的术语；新术语先登记（写明出处）再用，同一个东西始终用同一个说法。

## 不要做的事

- 不修改 `data/raw/`（原始数据只读，平台会告警）。
- 不覆盖已登记的模型文件：重新训练的结果登记为新版本。
- 不删除运行记录；不替用户裁定待决事项、不替用户把模型标为已验收 / 已交付。
- 依赖要在 `steps.json` 显式登记，不按编号推导。

## 常用命令

```
uv run dsflow validate .                              # 注册表校验
uv run dsflow check .                                 # 交接前核对：告警 + 数字核对 + 术语检查
uv run dsflow data add . data/raw/x.csv --name x_raw  # 登记数据（只记路径与哈希）
uv run dsflow data replace . x_clean --old x_raw      # 新表替代旧表：旧表退出数据层的「后存量」
uv run dsflow run 1.2 -p . -- python -m dsflow.tracking.notebook steps/…/nb_1.2.ipynb
uv run dsflow guide init . 1.2                        # 按 notebook 真实单元格生成导读骨架
uv run dsflow guide check .                           # 核对导读：引用与数字
uv run dsflow delivery init . <模型名>                 # 生成 / 刷新交付清单
uv run dsflow delivery check . <模型名>
```

## 本项目的约定

- 数据表就叫数据里的名字：`红酒`、`白酒`、`quality`、11 个理化指标用原列名；三份数据叫训练集 / 验证集 / 最终评估集（不叫测试集）。术语见 `vocabulary.json`。
- 1.1～3.1 是历史步骤：执行用 `src/*.py` 脚本，独立复核在 `checks/verify.py`，运行日志在 `execution.jsonl`。7.1 起用 notebook + `dsflow run`，并保留同样的 `checks/verify.py` 独立复核。
- 最终评估集只在 9.1 评估一次；任何步骤不得用它拟合、选模型或调参。
