"""9.1 独立复核：只用标准库，从原始 CSV、划分表、逐行预测和抽样索引重算最终评估的全部结果。

与 7.1 的复核同一套方法，目标划分换成最终评估集；故障注入里混入的是一条验证行。
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
STEP = ROOT / "steps/09_评估与诊断/9.1_最终评估"
OUT = STEP / "outputs"
S31 = ROOT / "steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/outputs"
FEATURES = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
            "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol"]
WINES = ("red", "white")
CANDIDATES = ("Ridge", "随机森林")
TARGET, FORBIDDEN = "final_evaluation", "validation"
TOL = 1e-10
checks: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def canonical(cell: str) -> str:
    value = Decimal(cell.strip())
    return "0" if value == 0 else format(value.normalize(), "f")


def group_id(wine: str, row: dict) -> str:
    return hashlib.sha256(f"{wine}|{'|'.join(canonical(row[f]) for f in FEATURES)}".encode("utf-8")).hexdigest()


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


def audit(preds, splits, raw, record=True) -> dict:
    ok, result = True, {}
    for wine in WINES:
        target_rows = {r for r, s in splits[wine].items() if s["split"] == TARGET}
        train_rows = {r for r, s in splits[wine].items() if s["split"] == "training"}
        median = statistics.median(raw[wine][r]["quality"] for r in sorted(train_rows))
        result[wine] = {"median": median, "candidates": {}}
        for cand in CANDIDATES:
            mine = [p for p in preds if p["wine"] == wine and p["candidate"] == cand]
            rows = Counter(p["source_row"] for p in mine)
            covered = set(rows) == target_rows and all(v == 1 for v in rows.values())
            leaked = any(splits[wine].get(p["source_row"], {}).get("split") in (FORBIDDEN, "training") for p in mine)
            truth = all(abs(p["quality"] - raw[wine][p["source_row"]]["quality"]) < TOL for p in mine if p["source_row"] in raw[wine])
            groups = all(p["feature_group_id"] == raw[wine][p["source_row"]]["group"] for p in mine if p["source_row"] in raw[wine])
            finite = all(math.isfinite(p["prediction"]) for p in mine)
            base_ok = all(abs(p["baseline_prediction"] - median) < TOL for p in mine)
            this_ok = covered and not leaked and truth and groups and finite and base_ok
            ok = ok and this_ok
            if record:
                check(f"{wine}/{cand}: 每条最终评估行恰好一条预测、无遗漏", covered, f"{len(rows)} 行")
                check(f"{wine}/{cand}: 没有训练行或验证行混入", not leaked)
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
                "by_quality": {q: (sum(e for e, p in zip(err, mine) if p["quality"] == q) / n, n) for q, n in Counter(p["quality"] for p in mine).items()},
                "rows": mine}
    result["ok"] = ok
    return result


def main() -> int:
    splits = {w: {} for w in WINES}
    with (S31 / "split_assignments.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            splits[r["wine"]][int(r["source_row"])] = {"split": r["split"], "group": r["feature_group_id"]}
    raw = {w: load_raw(w) for w in WINES}
    with (OUT / "final_predictions.csv").open(encoding="utf-8", newline="") as f:
        preds = [{**r, "source_row": int(r["source_row"]), "quality": float(r["quality"]), "prediction": float(r["prediction"]),
                  "baseline_prediction": float(r["baseline_prediction"]), "abs_error": float(r["abs_error"]),
                  "baseline_abs_error": float(r["baseline_abs_error"])} for r in csv.DictReader(f)]
    result = json.loads((OUT / "final_evaluation.json").read_text(encoding="utf-8"))
    got = audit(preds, splits, raw)
    for w in WINES:
        s = result["files"][w]
        check(f"{w}: 基线 MAE 重算一致", abs(got[w]["candidates"]["Ridge"]["base_mae"] - s["baseline"]["mae"]) < TOL)
        check(f"{w}: 基线 RMSE 重算一致", abs(got[w]["candidates"]["Ridge"]["base_rmse"] - s["baseline"]["rmse"]) < TOL)
        for cand in CANDIDATES:
            mine, theirs = got[w]["candidates"][cand], s["candidates"][cand]
            check(f"{w}/{cand}: MAE 重算一致", abs(mine["mae"] - theirs["mae"]) < TOL, f"{mine['mae']:.10f}")
            check(f"{w}/{cand}: RMSE 重算一致", abs(mine["rmse"] - theirs["rmse"]) < TOL)
            check(f"{w}/{cand}: MAE 差值一致", abs((mine["mae"] - mine["base_mae"]) - theirs["mae_minus_baseline"]) < TOL)
            check(f"{w}/{cand}: 逐行误差与真值 − 预测一致", all(abs(p["abs_error"] - abs(p["quality"] - p["prediction"])) < TOL for p in mine["rows"]))
            for q, (m, n) in mine["by_quality"].items():
                tq = s["by_quality"][str(int(q))]
                check(f"{w}/{cand}: quality={int(q)} 的行数与 MAE 一致", n == tq["rows"] and abs(m - tq[f"{cand}_mae"]) < TOL, f"{n} 行")
            still = mine["mae"] < mine["base_mae"] and theirs["mae_difference_interval"]["upper_97_5"] < 0
            check(f"{w}/{cand}: 「仍优于基线」判定一致", still == theirs["still_better_than_baseline"], "是" if still else "否")
        check(f"{w}: 各分值行数合计等于最终评估行数", sum(n for _, n in got[w]["candidates"]["Ridge"]["by_quality"].values()) == s["final_rows"])

    draws = json.loads((OUT / "bootstrap_draws.json").read_text(encoding="utf-8"))
    with (OUT / "bootstrap_mae_differences.csv").open(encoding="utf-8", newline="") as f:
        diff_file = defaultdict(dict)
        for r in csv.DictReader(f):
            diff_file[(r["wine"], r["candidate"])][int(r["draw"])] = float(r["mae_minus_baseline"])
    for w in WINES:
        ids, idx = draws["wines"][w]["ordered_feature_group_ids"], draws["wines"][w]["indices"]
        groups = sorted({s["group"] for s in splits[w].values() if s["split"] == TARGET})
        G = len(groups)
        check(f"{w}: 有序组合 ID 就是最终评估集的全部特征组合按字典序", ids == groups, f"{G} 个")
        check(f"{w}: 每次恰好抽 G 个、索引都在范围内", len(idx) == draws["draws"] and all(len(d) == G and all(0 <= i < G for i in d) for d in idx))
        pos = {g: i for i, g in enumerate(ids)}
        for cand in CANDIDATES:
            n_g, e_c, e_b = [0] * G, [0.0] * G, [0.0] * G
            for p in got[w]["candidates"][cand]["rows"]:
                k = pos[p["feature_group_id"]]
                n_g[k] += 1
                e_c[k] += abs(p["quality"] - p["prediction"])
                e_b[k] += abs(p["quality"] - p["baseline_prediction"])
            diffs = []
            for d in idx:
                times = Counter(d)
                n = sum(t * n_g[k] for k, t in times.items())
                diffs.append(sum(t * e_c[k] for k, t in times.items()) / n - sum(t * e_b[k] for k, t in times.items()) / n)
            check(f"{w}/{cand}: {len(diffs)} 次配对差逐次一致", all(abs(diffs[b] - diff_file[(w, cand)][b]) < TOL for b in range(len(diffs))))
            lo, hi = percentile_linear(diffs, 0.025), percentile_linear(diffs, 0.975)
            ci = result["files"][w]["candidates"][cand]["mae_difference_interval"]
            check(f"{w}/{cand}: 区间 [{lo:.6f}, {hi:.6f}] 一致", abs(lo - ci["lower_2_5"]) < TOL and abs(hi - ci["upper_97_5"]) < TOL)
    for rel, fp in result["inputs_before"].items():
        now = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        check(f"输入指纹当前一致：{rel}", now == fp["sha256"] == result["inputs_after"][rel]["sha256"])

    injected = []
    a = copy.deepcopy(preds)
    a.remove(next(p for p in a if p["wine"] == "red" and p["candidate"] == "Ridge"))
    injected.append({"case": "删掉红酒 Ridge 的一条预测", "rejected": not audit(a, splits, raw, record=False)["ok"]})
    b = copy.deepcopy(preds)
    next(p for p in b if p["wine"] == "white" and p["candidate"] == "随机森林")["quality"] += 1
    injected.append({"case": "把白酒随机森林一条真值加 1", "rejected": not audit(b, splits, raw, record=False)["ok"]})
    c = copy.deepcopy(preds)
    vrow = next(r for r, s in splits["red"].items() if s["split"] == FORBIDDEN)
    c.append({**next(p for p in c if p["wine"] == "red" and p["candidate"] == "Ridge"), "source_row": vrow,
              "quality": raw["red"][vrow]["quality"], "feature_group_id": raw["red"][vrow]["group"]})
    injected.append({"case": "混入一条红酒验证行的预测", "rejected": not audit(c, splits, raw, record=False)["ok"]})
    for i in injected:
        check(f"故障注入：{i['case']} → 检查器拒绝", i["rejected"])

    passed = sum(1 for c in checks if c["ok"])
    (STEP / "checks" / "verification.json").write_text(json.dumps({"generated_at_utc": datetime.now(timezone.utc).isoformat(), "passed": passed,
        "total": len(checks), "tolerance": TOL, "fault_injection": injected, "checks": checks}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{passed}/{len(checks)} 项通过")
    for c in checks:
        if not c["ok"]:
            print("  未通过：", c["name"], c["detail"])
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
