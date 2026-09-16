"""7.1 独立复核：只用标准库，从原始 CSV、划分表、逐行预测和抽样索引重算全部结果，不导入 notebook 里的代码。

核对：预测表里的真值和特征组合 ID 与原始 CSV 一致；每个候选对每条验证行恰好一条预测、没有最终评估行；
MAE / RMSE / 差值 / 按分值误差从逐行预测重算；基线只从训练行重算；2,000 次重抽样差值与区间从抽样索引重算。
再用内存副本做三处故障注入，确认检查器会拒绝。结果写到 checks/verification.json，不改任何权威产物。
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/07_模型选择与训练/7.1_候选模型比较"
OUT = STEP / "outputs"
S31 = ROOT / "steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/outputs"
FEATURES = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
            "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol"]
WINES = ("red", "white")
CANDIDATES = ("Ridge", "随机森林")
TOL = 1e-10

checks: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def canonical(cell: str) -> str:
    value = Decimal(cell.strip())
    return "0" if value == 0 else format(value.normalize(), "f")


def group_id(wine: str, row: dict) -> str:
    text = "|".join(canonical(row[f]) for f in FEATURES)
    return hashlib.sha256(f"{wine}|{text}".encode("utf-8")).hexdigest()


def load_raw(wine: str) -> dict[int, dict]:
    with (ROOT / f"data/winequality-{wine}.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    return {i + 1: {"quality": float(r["quality"]), "group": group_id(wine, r)} for i, r in enumerate(rows)}


def percentile_linear(values: list[float], p: float) -> float:
    xs = sorted(values)
    pos = (len(xs) - 1) * p
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def audit(preds: list[dict], splits: dict[str, dict[int, dict]], raw: dict[str, dict[int, dict]], record: bool = True) -> dict:
    """返回每类酒、每候选的重算结果；record=False 时只判断是否通过（故障注入用）。"""
    ok = True
    result: dict = {}
    for wine in WINES:
        valid_rows = {r for r, s in splits[wine].items() if s["split"] == "validation"}
        train_rows = {r for r, s in splits[wine].items() if s["split"] == "training"}
        median = statistics.median(raw[wine][r]["quality"] for r in sorted(train_rows))
        result[wine] = {"median": median, "candidates": {}}
        for cand in CANDIDATES:
            mine = [p for p in preds if p["wine"] == wine and p["candidate"] == cand]
            rows = Counter(p["source_row"] for p in mine)
            covered = set(rows) == valid_rows and all(v == 1 for v in rows.values())
            sealed = any(splits[wine].get(p["source_row"], {}).get("split") == "final_evaluation" for p in mine)
            truth = all(abs(p["quality"] - raw[wine][p["source_row"]]["quality"]) < TOL for p in mine if p["source_row"] in raw[wine])
            groups = all(p["feature_group_id"] == raw[wine][p["source_row"]]["group"] for p in mine if p["source_row"] in raw[wine])
            finite = all(math.isfinite(p["prediction"]) for p in mine)
            base_ok = all(abs(p["baseline_prediction"] - median) < TOL for p in mine)
            this_ok = covered and not sealed and truth and groups and finite and base_ok
            ok = ok and this_ok
            if record:
                check(f"{wine}/{cand}: 每条验证行恰好一条预测、无遗漏", covered, f"{len(rows)} 行")
                check(f"{wine}/{cand}: 没有最终评估行", not sealed)
                check(f"{wine}/{cand}: 预测表真值与原始 CSV 一致", truth)
                check(f"{wine}/{cand}: 特征组合 ID 与原始 CSV 重建一致", groups)
                check(f"{wine}/{cand}: 预测全部有限", finite)
                check(f"{wine}/{cand}: 基线预测等于训练集中位数", base_ok, f"中位数 {median}")
            if not this_ok:
                continue
            err = [abs(p["quality"] - p["prediction"]) for p in mine]
            berr = [abs(p["quality"] - median) for p in mine]
            result[wine]["candidates"][cand] = {
                "mae": sum(err) / len(err), "rmse": math.sqrt(sum(e * e for e in err) / len(err)),
                "base_mae": sum(berr) / len(berr), "base_rmse": math.sqrt(sum(e * e for e in berr) / len(berr)),
                "by_quality": {q: (sum(e for e, p in zip(err, mine) if p["quality"] == q) / n, n)
                               for q, n in Counter(p["quality"] for p in mine).items()},
                "rows": mine,
            }
    result["ok"] = ok
    return result


def main() -> int:
    splits: dict[str, dict[int, dict]] = {w: {} for w in WINES}
    with (S31 / "split_assignments.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            splits[r["wine"]][int(r["source_row"])] = {"split": r["split"], "group": r["feature_group_id"]}
    raw = {w: load_raw(w) for w in WINES}
    for w in WINES:
        check(f"{w}: 划分表覆盖全部原始行", set(splits[w]) == set(raw[w]), f"{len(splits[w])} 行")
        check(f"{w}: 划分表的特征组合 ID 与原始 CSV 重建一致", all(splits[w][r]["group"] == raw[w][r]["group"] for r in raw[w]))

    with (OUT / "validation_predictions.csv").open(encoding="utf-8", newline="") as f:
        preds = [{**r, "source_row": int(r["source_row"]), "quality": float(r["quality"]), "prediction": float(r["prediction"]),
                  "baseline_prediction": float(r["baseline_prediction"]), "abs_error": float(r["abs_error"]),
                  "baseline_abs_error": float(r["baseline_abs_error"])} for r in csv.DictReader(f)]
    comparison = json.loads((OUT / "model_comparison.json").read_text(encoding="utf-8"))
    baseline_ref = json.loads((S31 / "baseline_validation.json").read_text(encoding="utf-8"))

    got = audit(preds, splits, raw)
    for w in WINES:
        s = comparison["files"][w]
        check(f"{w}: 基线 MAE 与 3.1 一致", abs(got[w]["candidates"]["Ridge"]["base_mae"] - baseline_ref["files"][w]["validation_mae"]) < TOL)
        check(f"{w}: 基线 RMSE 与 3.1 一致", abs(got[w]["candidates"]["Ridge"]["base_rmse"] - baseline_ref["files"][w]["validation_rmse"]) < TOL)
        for cand in CANDIDATES:
            mine, theirs = got[w]["candidates"][cand], s["candidates"][cand]
            check(f"{w}/{cand}: MAE 重算一致", abs(mine["mae"] - theirs["mae"]) < TOL, f"{mine['mae']:.10f}")
            check(f"{w}/{cand}: RMSE 重算一致", abs(mine["rmse"] - theirs["rmse"]) < TOL, f"{mine['rmse']:.10f}")
            check(f"{w}/{cand}: MAE 差值一致", abs((mine["mae"] - mine["base_mae"]) - theirs["mae_minus_baseline"]) < TOL)
            check(f"{w}/{cand}: 预测表里的逐行误差与真值 − 预测一致",
                  all(abs(p["abs_error"] - abs(p["quality"] - p["prediction"])) < TOL for p in mine["rows"]))
            for q, (m, n) in mine["by_quality"].items():
                theirs_q = s["by_quality"][str(int(q))]
                check(f"{w}/{cand}: quality={int(q)} 的行数与 MAE 一致", n == theirs_q["rows"] and abs(m - theirs_q[f"{cand}_mae"]) < TOL, f"{n} 行")
            meets = mine["mae"] < mine["base_mae"] and theirs["mae_difference_interval"]["upper_97_5"] < 0 and mine["rmse"] <= mine["base_rmse"]
            check(f"{w}/{cand}: 登记判定按门槛重算一致", meets == theirs["meets_threshold"], "满足" if meets else "不满足")
        check(f"{w}: 各分值行数合计等于验证行数", sum(n for _, n in got[w]["candidates"]["Ridge"]["by_quality"].values()) == s["validation_rows"])

    # 重抽样区间：从抽样索引重算全部差值
    draws = json.loads((OUT / "bootstrap_draws.json").read_text(encoding="utf-8"))
    with (OUT / "bootstrap_mae_differences.csv").open(encoding="utf-8", newline="") as f:
        diff_file = defaultdict(dict)
        for r in csv.DictReader(f):
            diff_file[(r["wine"], r["candidate"])][int(r["draw"])] = float(r["mae_minus_baseline"])
    for w in WINES:
        ids = draws["wines"][w]["ordered_feature_group_ids"]
        idx = draws["wines"][w]["indices"]
        valid_groups = sorted({splits[w][r]["group"] for r, s in splits[w].items() if s["split"] == "validation"})
        G = len(valid_groups)
        check(f"{w}: 有序组合 ID 就是验证集的全部特征组合按字典序", ids == valid_groups, f"{G} 个")
        check(f"{w}: 每次恰好抽 G 个、索引都在范围内", len(idx) == draws["draws"] and all(len(d) == G and all(0 <= i < G for i in d) for d in idx))
        pos = {g: i for i, g in enumerate(ids)}
        for cand in CANDIDATES:
            rows = got[w]["candidates"][cand]["rows"]
            n_g = [0] * G
            e_c = [0.0] * G
            e_b = [0.0] * G
            for p in rows:
                k = pos[p["feature_group_id"]]
                n_g[k] += 1
                e_c[k] += abs(p["quality"] - p["prediction"])
                e_b[k] += abs(p["quality"] - p["baseline_prediction"])
            diffs = []
            for d in idx:
                times = Counter(d)
                n = sum(t * n_g[k] for k, t in times.items())
                diffs.append(sum(t * e_c[k] for k, t in times.items()) / n - sum(t * e_b[k] for k, t in times.items()) / n)
            same = all(abs(diffs[b] - diff_file[(w, cand)][b]) < TOL for b in range(len(diffs)))
            check(f"{w}/{cand}: {len(diffs)} 次配对差逐次一致", same)
            lo, hi = percentile_linear(diffs, 0.025), percentile_linear(diffs, 0.975)
            ci = comparison["files"][w]["candidates"][cand]["mae_difference_interval"]
            check(f"{w}/{cand}: 区间 [{lo:.6f}, {hi:.6f}] 一致", abs(lo - ci["lower_2_5"]) < TOL and abs(hi - ci["upper_97_5"]) < TOL)

    # 输入指纹
    for rel, fp in comparison["inputs_before"].items():
        now = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        check(f"输入指纹当前一致：{rel}", now == fp["sha256"] == comparison["inputs_after"][rel]["sha256"])

    # 故障注入（内存副本）
    injected = []
    a = copy.deepcopy(preds)
    a.remove(next(p for p in a if p["wine"] == "red" and p["candidate"] == "Ridge" and p["source_row"] == 1))
    injected.append({"case": "删掉红酒 Ridge 对第 1 行的预测", "rejected": not audit(a, splits, raw, record=False)["ok"]})
    b = copy.deepcopy(preds)
    next(p for p in b if p["wine"] == "white" and p["candidate"] == "随机森林")["quality"] += 1
    injected.append({"case": "把白酒随机森林一条真值加 1", "rejected": not audit(b, splits, raw, record=False)["ok"]})
    c = copy.deepcopy(preds)
    sealed_row = next(r for r, s in splits["red"].items() if s["split"] == "final_evaluation")
    c.append({**next(p for p in c if p["wine"] == "red" and p["candidate"] == "Ridge"), "source_row": sealed_row,
              "quality": raw["red"][sealed_row]["quality"], "feature_group_id": raw["red"][sealed_row]["group"]})
    injected.append({"case": "混入一条红酒最终评估行的预测", "rejected": not audit(c, splits, raw, record=False)["ok"]})
    for i in injected:
        check(f"故障注入：{i['case']} → 检查器拒绝", i["rejected"])

    passed = sum(1 for c in checks if c["ok"])
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "passed": passed, "total": len(checks),
              "tolerance": TOL, "fault_injection": injected, "checks": checks}
    (STEP / "checks" / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{passed}/{len(checks)} 项通过")
    for c in checks:
        if not c["ok"]:
            print("  未通过：", c["name"], c["detail"])
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
