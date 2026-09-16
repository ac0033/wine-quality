# 10.1 报告：模型主要靠哪些理化指标

**本步执行通过。** 在验证集上把一个理化指标打乱、看模型误差变差多少：四个候选里三个最依赖 `alcohol`（红酒随机森林打乱后 MAE 增加 **0.1161**，白酒随机森林 **0.1872**）；白酒 Ridge 例外，最依赖 `density` 和 `residual sugar`，这两个指标和 `alcohol` 高度相关，重要性在它们之间互相分担。模型没有重训，最终评估集没碰。

## 每个模型最依赖哪三个指标？

对每类酒的每个候选，在验证行（红酒 331、白酒 983）上先算原 MAE，再把某一个指标的列随机打乱 20 次（固定种子），其余列不动，重新预测；「打乱后 MAE − 原 MAE」的平均就是这个指标的重要性。结果在[指标贡献表](outputs/importance.csv)和[汇总](outputs/importance.json)，由 [notebook](nb_10.1.ipynb) 复现。

| 模型 | 第 1 | 第 2 | 第 3 |
|---|---|---|---|
| 红酒 Ridge | alcohol（+0.1032） | volatile acidity（+0.0406） | total sulfur dioxide（+0.0262） |
| 红酒 随机森林 | alcohol（+0.1161） | sulphates（+0.0513） | volatile acidity（+0.0264） |
| 白酒 Ridge | density（+0.1514） | residual sugar（+0.1372） | alcohol（+0.0919） |
| 白酒 随机森林 | alcohol（+0.1872） | volatile acidity（+0.0580） | free sulfur dioxide（+0.0437） |

红酒两个候选的头三名都在 2.1 观察到的关系里：`alcohol` 正向（Spearman +0.4785）、`volatile acidity` 负向（−0.3806）、`sulphates` 正向（+0.3771）。白酒随机森林同样以 `alcohol` 为主（+0.4404）。

## 白酒 Ridge 为什么不一样？

白酒里 `density` 与 `alcohol` 的 Spearman 是 **−0.8219**（2.1 的发现），`residual sugar` 又和 `density` 高度相关：三个指标说的很大程度是同一件事。线性模型把这份信息分到了 `density`（标准化系数 −0.3696）和 `residual sugar`（+0.3707）上，`alcohol` 退到第三；随机森林则直接用 `alcohol`。所以「白酒 Ridge 最依赖 density」不是发现了新的规律，是同一份信息换了个承载的列。两处需要留意的地方也来自这里：`residual sugar` 在 2.1 里和 quality 的 Spearman 只有 −0.082，却排第 2；白酒随机森林的 `free sulfur dioxide` 排第 3，2.1 的 Spearman 只有 +0.024。它们的重要性是「和别的指标搭配着用」得来的，单看和 quality 的关系看不出。

## 证据与边界

[独立复核](checks/verify.py)重新加载 7.1 的模型文件，用同样的种子、顺序重算全部 44 个置换重要性和 Ridge 系数，与产物在 1e-10 容差内一致；[复核结果](checks/verification.json)记录项数。输入指纹执行前后一致。

这里解释的是模型的行为：打乱某列误差变大，说明模型在用它，不说明这个指标决定酒的好坏，也不说明改变它会改变评分。重要性是在验证集上算的，和 7.1 的候选筛选用的是同一批行。
