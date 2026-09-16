"""10.1 独立复核：重新加载 7.1 的模型文件，用同样的种子与顺序重算置换重要性和 Ridge 系数，对照 outputs/importance.csv。

需要 numpy / pandas / scikit-learn（模型要能预测），但不导入 notebook 里的任何代码。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/10_可解释性/10.1_指标贡献"
OUT = STEP / "outputs"
S31 = ROOT / "steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/outputs"
S71 = ROOT / "steps/07_模型选择与训练/7.1_候选模型比较/outputs"
FEATURES = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
            "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol"]
WINES = ("red", "white")
CANDIDATES = ("Ridge", "随机森林")
SEED, REPEATS, TOL = 20260914, 20, 1e-10
checks: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def main() -> int:
    imp = pd.read_csv(OUT / "importance.csv")
    summary = json.loads((OUT / "importance.json").read_text(encoding="utf-8"))
    splits = pd.read_csv(S31 / "split_assignments.csv")
    for rel, fp in summary["inputs_before"].items():
        check(f"输入指纹当前一致：{rel}", hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == fp["sha256"] == summary["inputs_after"][rel]["sha256"])
    for w in WINES:
        raw = pd.read_csv(ROOT / f"data/winequality-{w}.csv", sep=";")
        raw["source_row"] = np.arange(1, len(raw) + 1)
        rows = splits[(splits["wine"] == w) & (splits["split"] == "validation")]["source_row"]
        valid = raw[raw["source_row"].isin(rows)].sort_values("source_row")
        X, y = valid[FEATURES].to_numpy(float), valid["quality"].to_numpy(float)
        check(f"{w}: 只用了验证行", len(valid) == int((splits["wine"] == w).sum() and (splits[(splits['wine'] == w)]["split"] == "validation").sum()), f"{len(valid)} 行")
        for cand in CANDIDATES:
            m = joblib.load(S71 / "models" / f"{w}_{cand}.joblib")
            predict = (lambda A, m=m: m["model"].predict((A - m["scaler"]["mean"]) / m["scaler"]["std"])) if "scaler" in m else (lambda A, m=m: m["model"].predict(A))
            base = float(np.abs(y - predict(X)).mean())
            rng = np.random.Generator(np.random.PCG64(SEED))
            mine = {}
            for j, feat in enumerate(FEATURES):
                worse = []
                for _ in range(REPEATS):
                    Xp = X.copy()
                    Xp[:, j] = X[rng.permutation(len(X)), j]
                    worse.append(float(np.abs(y - predict(Xp)).mean()) - base)
                mine[feat] = float(np.mean(worse))
            theirs = imp[(imp["wine"] == w) & (imp["candidate"] == cand)].set_index("feature")
            check(f"{w}/{cand}: 验证 MAE 一致", abs(base - theirs["validation_mae"].iloc[0]) < TOL, f"{base:.6f}")
            check(f"{w}/{cand}: 11 个指标的置换重要性逐个一致", all(abs(mine[f] - theirs.loc[f, "mae_increase_when_shuffled"]) < TOL for f in FEATURES))
            ranked = sorted(FEATURES, key=lambda f: -mine[f])[:3]
            check(f"{w}/{cand}: 前三名一致", ranked == summary["top3"][f"{'红酒' if w == 'red' else '白酒'}_{cand}"], "、".join(ranked))
            if cand == "Ridge":
                check(f"{w}: Ridge 标准化系数与模型文件一致", all(abs(m["model"].coef_[j] - theirs.loc[f, "ridge_standardized_coef"]) < TOL for j, f in enumerate(FEATURES)))
    passed = sum(1 for c in checks if c["ok"])
    (STEP / "checks" / "verification.json").write_text(json.dumps({"generated_at_utc": datetime.now(timezone.utc).isoformat(), "passed": passed,
        "total": len(checks), "tolerance": TOL, "checks": checks}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{passed}/{len(checks)} 项通过")
    for c in checks:
        if not c["ok"]:
            print("  未通过：", c["name"], c["detail"])
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
