"""给新的理化指标记录估计 quality。

用法：python steps/11_部署与交付/11.1_模型登记与交付清单/src/predict.py <red|white> <输入 CSV> <输出 CSV>

输入 CSV 要有 11 个理化指标列（列名与原始数据一致，分号或逗号分隔都行）；
输出 = 原始列 + quality_估计（连续值，不取整）。红酒用红酒的模型，白酒用白酒的模型，不混用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
MODELS = ROOT / "steps/07_模型选择与训练/7.1_候选模型比较/outputs/models"
FEATURES = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
            "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol"]
MODEL_FILE = {"red": "red_随机森林.joblib", "white": "white_随机森林.joblib"}


def score(wine: str, frame: pd.DataFrame) -> pd.DataFrame:
    if wine not in MODEL_FILE:
        raise SystemExit("酒类只能是 red 或 white")
    missing = [f for f in FEATURES if f not in frame.columns]
    if missing:
        raise SystemExit(f"输入缺少理化指标列：{'、'.join(missing)}")
    bundle = joblib.load(MODELS / MODEL_FILE[wine])
    X = frame[FEATURES].astype(float).to_numpy()
    out = frame.copy()
    out["quality_估计"] = bundle["model"].predict(X)
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    wine, src, dst = argv[1], Path(argv[2]), Path(argv[3])
    frame = pd.read_csv(src, sep=None, engine="python")
    result = score(wine, frame)
    result.to_csv(dst, index=False)
    print(f"{wine}：{len(result)} 行已打分 → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
