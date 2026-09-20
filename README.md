# Wine Quality：理化指标预测葡萄酒评分

用 11 项理化指标估计葡萄酒的专家评分（quality），红酒与白酒各训练一个随机森林模型。
数据来自 [UCI Wine Quality Dataset](https://archive.ics.uci.edu/dataset/186/wine+quality)。

本仓库的重点不只是模型本身，而是**一条可复现、可验收、可追溯的数据科学工作流**：
每个步骤都有计划（plan）、执行记录、独立校验（checks）与验收结论（acceptance），
数据与模型文件全部以 SHA256 登记，任何一步都能凭哈希还原。

## 结果

| 模型 | 最终评估 MAE | 中位数基线 | 相对提升 | 评估集规模 |
|---|---|---|---|---|
| 红酒 quality 随机森林 | **0.4963** | 0.6855 | **−27.6%** | 318 行（训练 950 行） |
| 白酒 quality 随机森林 | **0.5752** | 0.6469 | **−11.1%** | 994 行（训练 2,921 行） |

最终评估集只在步骤 9.1 评一次，训练与调参全程不接触，避免评估泄漏。

## 工作流

| 阶段 | 步骤 | 产出 |
|---|---|---|
| 01 数据预处理 | 1.1 原始数据理解与质量核验 | 数据画像、质量问题清单 |
| 02 EDA | 2.1 理化指标与 quality 的探索分析 | 相关性与分布分析 |
| 03 数据划分 | 3.1 预测任务定义、固定划分与验证基线 | `split_assignments.csv`（哈希登记） |
| 07 模型选择与训练 | 7.1 候选模型比较 | 候选模型与比较结论 |
| 09 评估与诊断 | 9.1 最终评估 | 一次性最终评估报告 |
| 10 可解释性 | 10.1 指标贡献 | 特征贡献分析 |
| 11 部署与交付 | 11.1 模型登记与交付清单 | 模型登记、`predict.py`、交付清单 |

每个步骤目录下包含 `plan.md`（做什么、怎么验）、`nb_*.ipynb`（执行）、
`checks/`（独立校验脚本与结果）、`report.md`（结论）、`acceptance.md`（验收记录）。

## 目录

| 路径 | 内容 |
|---|---|
| [steps/](steps/) | 各阶段的计划、执行、校验与报告 |
| [delivery/](delivery/) | 两个模型的交付清单（含复现命令与指标口径） |
| [reviews/](reviews/) | 报告评审记录与验证脚本 |
| [data/](data/) | UCI 原始数据（红酒 / 白酒 / 字段说明） |
| [lifecycle/](lifecycle/) | 生命周期步骤定义 |
| `.dsflow/` | 数据集与模型登记、运行记录 |

## 复现

```bash
uv sync                                   # 按 uv.lock 还原依赖
uv run dsflow data verify . data/winequality-red.csv <sha256>
uv run dsflow run 11.1 -- python -X utf8 -m dsflow.tracking.notebook \
    steps/11_部署与交付/11.1_模型登记与交付清单/nb_11.1.ipynb
```

完整复现步骤与各文件的 SHA256 见 [delivery/](delivery/) 下的交付清单。

推理：

```bash
uv run python steps/11_部署与交付/11.1_模型登记与交付清单/src/predict.py \
    red <输入CSV，11个理化指标列> <输出CSV>
```

## 数据来源与声明

- 研究性交付，不面向生产场景；模型给出的是 quality 的连续估计值，不是分级判定。
- 数据来自 UCI Machine Learning Repository（Cortez et al., 2009），遵循其 CC BY 4.0 许可。
- 本仓库中由本人编写的代码与文档以 [MIT License](LICENSE) 授权。
