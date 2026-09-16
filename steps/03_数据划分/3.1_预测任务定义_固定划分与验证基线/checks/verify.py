"""Independently rebuild grouped split and validation-only baseline from raw CSV."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线"
DATA = ROOT / "data"
INPUTS = [DATA / "winequality-red.csv", DATA / "winequality-white.csv", DATA / "winequality.names",
          ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验/outputs/data_profile.json",
          ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验/acceptance.md",
          ROOT / "steps/02_EDA/2.1_理化指标与quality的探索分析/outputs/eda.json",
          ROOT / "steps/02_EDA/2.1_理化指标与quality的探索分析/acceptance.md"]
FIELDS = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
          "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol", "quality"]
SEED = 20260914
SPLITS = ("training", "validation", "final_evaluation")
summary = json.loads((STEP / "outputs/split_summary.json").read_text(encoding="utf-8"))
baseline = json.loads((STEP / "outputs/baseline_validation.json").read_text(encoding="utf-8"))
first = json.loads((ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验/outputs/data_profile.json").read_text(encoding="utf-8"))
checks = []


def check(label: str, actual, expected, tolerance: float | None = None) -> None:
    passed = (math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance)
              if tolerance is not None else actual == expected)
    checks.append({"check": label, "pass": passed, "actual": actual, "expected": expected,
                   "tolerance": tolerance})


def canonical(cell: str) -> str:
    number = Decimal(cell.strip())
    if not number.is_finite():
        raise ValueError("nonfinite input")
    if number == 0:
        return "0"
    fixed = format(number, "f")
    return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed


def median(scores: list[int]) -> float:
    values = sorted(scores)
    mid = len(values) // 2
    return float(values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2)


with (STEP / "outputs/split_assignments.csv").open("r", encoding="utf-8", newline="") as stream:
    reader = csv.DictReader(stream)
    check("assignment fields", reader.fieldnames, ["wine", "source_row", "feature_group_id", "split"])
    assigned_rows = list(reader)
check("assignment rows", len(assigned_rows), summary["assignment_rows"])
check("assignment rows total", len(assigned_rows), 6497)
actual_assignments = {}
for record in assigned_rows:
    identity = (record["wine"], int(record["source_row"]))
    check(f"assignment {identity} split valid", record["split"] in SPLITS, True)
    if identity in actual_assignments:
        checks.append({"check": f"duplicate assignment {identity}", "pass": False,
                       "actual": identity, "expected": "unique", "tolerance": None})
    actual_assignments[identity] = record
check("assignment unique identities", len(actual_assignments), len(assigned_rows))

for path in INPUTS:
    raw = path.read_bytes()
    key = str(path.relative_to(ROOT))
    expected = summary["inputs_before"][key]
    check(f"{key}: path", str(path), expected["path"])
    check(f"{key}: bytes", len(raw), expected["bytes"])
    check(f"{key}: SHA256", hashlib.sha256(raw).hexdigest(), expected["sha256"])
    check(f"{key}: unchanged", summary["inputs_after"][key], expected)

for wine in ("red", "white"):
    path = DATA / f"winequality-{wine}.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=";", strict=True)
        header = next(reader)
        raw_rows = list(reader)
    check(f"{wine}: header", header, FIELDS)
    check(f"{wine}: first-step header", header, first["files"][wine]["header"])
    check(f"{wine}: row widths", set(map(len, raw_rows)), {12})
    check(f"{wine}: row count", len(raw_rows), first["files"][wine]["rows"])
    check(f"{wine}: summary row count", len(raw_rows), summary["files"][wine]["all_rows"])
    groups = defaultdict(list)
    original_counts = Counter()
    for row_number, row in enumerate(raw_rows, start=1):
        feature = tuple(canonical(value) for value in row[:11])
        score = int(Decimal(row[11]))
        groups[feature].append((row_number, score))
        original_counts[str(score)] += 1
    check(f"{wine}: first-step quality counts", dict(original_counts),
          {k: v["rows"] for k, v in first["files"][wine]["quality_distribution"].items()})
    check(f"{wine}: summary quality counts", dict(original_counts), summary["files"][wine]["quality_counts"])
    check(f"{wine}: feature groups", len(groups), summary["files"][wine]["all_feature_groups"])
    check(f"{wine}: expected feature groups", len(groups), 1359 if wine == "red" else 3961)
    strata = defaultdict(list)
    conflicts = 0
    for feature, members in groups.items():
        scores = {score for _, score in members}
        if len(scores) != 1:
            conflicts += 1
        else:
            strata[next(iter(scores))].append(feature)
    check(f"{wine}: conflicting quality groups", conflicts, 0)
    check(f"{wine}: minimum stratum size", min(map(len, strata.values())) >= 5, True)
    mapping = {}
    expected_by_quality = {}
    for score, features in sorted(strata.items()):
        def sort_key(feature):
            serialized = "|".join(feature)
            digest = hashlib.sha256(f"{SEED}|{wine}|{score}|{serialized}".encode("utf-8")).hexdigest()
            return (digest, serialized)
        ordered = sorted(features, key=sort_key)
        count = len(ordered)
        allocation = (count + 4) // 5  # ceil(20% of group count)
        check(f"{wine}: quality {score} three nonempty splits", count - 2 * allocation >= 1, True)
        for position, feature in enumerate(ordered):
            split = "final_evaluation" if position < allocation else ("validation" if position < 2 * allocation else "training")
            mapping[feature] = split
        expected_by_quality[str(score)] = {
            "feature_groups": {split: sum(mapping[feature] == split for feature in ordered) for split in SPLITS},
            "rows": {split: sum(len(groups[feature]) for feature in ordered if mapping[feature] == split) for split in SPLITS}}
    check(f"{wine}: by-quality split counts", expected_by_quality, summary["files"][wine]["by_quality"])
    expected_totals = {"feature_groups": {split: sum(v["feature_groups"][split] for v in expected_by_quality.values()) for split in SPLITS},
                       "rows": {split: sum(v["rows"][split] for v in expected_by_quality.values()) for split in SPLITS}}
    check(f"{wine}: split totals", expected_totals, summary["files"][wine]["totals"])
    check(f"{wine}: all rows assigned", sum(expected_totals["rows"].values()), len(raw_rows))
    check(f"{wine}: all groups assigned", sum(expected_totals["feature_groups"].values()), len(groups))
    group_splits = defaultdict(set)
    for feature, members in groups.items():
        serialized = "|".join(feature)
        expected_id = hashlib.sha256(f"{wine}|{serialized}".encode("utf-8")).hexdigest()
        expected_split = mapping[feature]
        for row_number, _ in members:
            identity = (wine, row_number)
            actual = actual_assignments.get(identity)
            check(f"{wine}: source row {row_number} exists", actual is not None, True)
            if actual is not None:
                check(f"{wine}: source row {row_number} group id", actual["feature_group_id"], expected_id)
                check(f"{wine}: source row {row_number} split", actual["split"], expected_split)
                group_splits[actual["feature_group_id"]].add(actual["split"])
    crossing = sum(len(splits) > 1 for splits in group_splits.values())
    check(f"{wine}: cross-split groups", crossing, 0)
    check(f"{wine}: summary cross-split groups", crossing, summary["files"][wine]["cross_split_feature_groups"])
    check(f"{wine}: all strata have three splits", all(all(v > 0 for v in detail["feature_groups"].values())
                                                for detail in expected_by_quality.values()), True)
    # Quality in final_evaluation was used only above for split integrity, never for baseline metrics.
    training_scores = [score for feature, members in groups.items() if mapping[feature] == "training"
                       for _, score in members]
    validation_scores = [score for feature, members in groups.items() if mapping[feature] == "validation"
                         for _, score in members]
    constant = median(training_scores)
    mae = sum(abs(score - constant) for score in validation_scores) / len(validation_scores)
    rmse = math.sqrt(sum((score - constant) ** 2 for score in validation_scores) / len(validation_scores))
    reported = baseline["files"][wine]
    check(f"{wine}: baseline fields", set(reported), {"training_rows", "validation_rows", "training_quality_median_prediction",
                                               "validation_mae", "validation_rmse", "unit"})
    check(f"{wine}: baseline training rows", len(training_scores), reported["training_rows"])
    check(f"{wine}: baseline validation rows", len(validation_scores), reported["validation_rows"])
    check(f"{wine}: baseline constant", constant, reported["training_quality_median_prediction"], 1e-12)
    check(f"{wine}: validation MAE", mae, reported["validation_mae"], 1e-12)
    check(f"{wine}: validation RMSE", rmse, reported["validation_rmse"], 1e-12)

verification = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "method": "Independent CSV/Decimal reconstruction of group keys, hash order, assignment rows and training-median validation metrics",
                "final_evaluation_scope": "Only stratum, group and row-count integrity; no predictions or errors computed",
                "passed": all(item["pass"] for item in checks),
                "passed_checks": sum(item["pass"] for item in checks), "total_checks": len(checks),
                "checks": checks}
output = STEP / "checks/verification.json"
output.write_text(json.dumps(verification, ensure_ascii=False, indent=2, default=lambda value: sorted(value) if isinstance(value, set) else str(value)) + "\n", encoding="utf-8")
with (STEP / "execution.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"at_utc": datetime.now(timezone.utc).isoformat(),
                             "action": "independent_verify",
                             "command": f"& '{sys.executable}' 'steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/checks/verify.py'",
                             "status": "success" if verification["passed"] else "failed",
                             "output": str(output), "passed_checks": verification["passed_checks"],
                             "total_checks": len(checks)}, ensure_ascii=False) + "\n")
print(json.dumps({"passed": verification["passed"], "passed_checks": verification["passed_checks"],
                  "total_checks": len(checks)}))
if not verification["passed"]:
    raise SystemExit(1)
