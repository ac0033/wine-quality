"""Fixed grouped stratified split and train-median validation baseline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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


def fingerprint(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def record_log(event: dict) -> None:
    event = {"at_utc": datetime.now(timezone.utc).isoformat(), **event}
    with (STEP / "execution.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def canonical_numeric(cell: str) -> str:
    try:
        value = Decimal(cell.strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric feature: {cell!r}") from exc
    if not value.is_finite():
        raise ValueError(f"Nonfinite numeric feature: {cell!r}")
    return "0" if value == 0 else format(value.normalize(), "f")


def feature_text(key: tuple[str, ...]) -> str:
    return "|".join(key)


def group_id(wine: str, key: tuple[str, ...]) -> str:
    return hashlib.sha256(f"{wine}|{feature_text(key)}".encode("utf-8")).hexdigest()


def order_hash(wine: str, score: int, key: tuple[str, ...]) -> str:
    return hashlib.sha256(f"{SEED}|{wine}|{score}|{feature_text(key)}".encode("utf-8")).hexdigest()


def load_wine(wine: str, first_profile: dict) -> tuple[list[dict], dict]:
    path = DATA / f"winequality-{wine}.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=";", strict=True)
        header = next(reader)
        if header != FIELDS or header != first_profile["files"][wine]["header"]:
            raise ValueError(f"Header mismatch: {path}")
        records = []
        counts = Counter()
        for row_number, row in enumerate(reader, start=1):
            if len(row) != len(FIELDS):
                raise ValueError(f"Wrong column count: {path}:{row_number}")
            key = tuple(canonical_numeric(cell) for cell in row[:11])
            score_text = canonical_numeric(row[11])
            score_decimal = Decimal(score_text)
            if score_decimal != score_decimal.to_integral_value() or not 0 <= score_decimal <= 10:
                raise ValueError(f"Invalid quality: {path}:{row_number}")
            score = int(score_decimal)
            records.append({"wine": wine, "source_row": row_number, "key": key, "quality": score})
            counts[str(score)] += 1
    baseline = first_profile["files"][wine]
    expected_counts = {score: detail["rows"] for score, detail in baseline["quality_distribution"].items()}
    if len(records) != baseline["rows"] or dict(counts) != expected_counts:
        raise ValueError(f"Rows or quality frequencies disagree with step 1: {wine}")
    return records, {"header": header, "quality_counts": dict(sorted(counts.items(), key=lambda item: int(item[0])))}


def split_wine(wine: str, records: list[dict]) -> tuple[list[dict], dict, dict]:
    groups = defaultdict(list)
    for record in records:
        groups[record["key"]].append(record)
    expected_groups = {"red": 1359, "white": 3961}[wine]
    if len(groups) != expected_groups:
        raise ValueError(f"Distinct feature group count changed: {wine}: {len(groups)} != {expected_groups}")
    strata = defaultdict(list)
    for key, members in groups.items():
        scores = {item["quality"] for item in members}
        if len(scores) != 1:
            raise ValueError(f"Feature group has multiple quality values: {wine} {group_id(wine, key)}")
        strata[next(iter(scores))].append(key)
    for score, keys in strata.items():
        if len(keys) < 5:
            raise ValueError(f"quality {score} has fewer than five feature groups: {wine}")
    group_split = {}
    by_quality = {}
    for score, keys in sorted(strata.items()):
        sorted_keys = sorted(keys, key=lambda key: (order_hash(wine, score, key), feature_text(key)))
        allocation = math.ceil(.20 * len(sorted_keys))
        if len(sorted_keys) - 2 * allocation < 1:
            raise ValueError(f"Empty training stratum: {wine} quality {score}")
        for rank, key in enumerate(sorted_keys):
            group_split[key] = ("final_evaluation" if rank < allocation
                                else "validation" if rank < 2 * allocation else "training")
        by_quality[str(score)] = {"feature_groups": {}, "rows": {}}
        for split in SPLITS:
            assigned = [key for key in sorted_keys if group_split[key] == split]
            by_quality[str(score)]["feature_groups"][split] = len(assigned)
            by_quality[str(score)]["rows"][split] = sum(len(groups[key]) for key in assigned)
    assignments = [{"wine": wine, "source_row": record["source_row"],
                    "feature_group_id": group_id(wine, record["key"]),
                    "split": group_split[record["key"]]} for record in records]
    group_splits = defaultdict(set)
    for assignment in assignments:
        group_splits[assignment["feature_group_id"]].add(assignment["split"])
    crossing = sum(len(splits) > 1 for splits in group_splits.values())
    if crossing:
        raise ValueError(f"Feature group crosses splits: {wine}")
    totals = {"feature_groups": {split: sum(row["feature_groups"][split] for row in by_quality.values())
                                  for split in SPLITS},
              "rows": {split: sum(row["rows"][split] for row in by_quality.values()) for split in SPLITS}}
    summary = {"all_rows": len(records), "all_feature_groups": len(groups),
               "quality_counts": {score: sum(detail["rows"].values()) for score, detail in by_quality.items()},
               "by_quality": by_quality, "totals": totals,
               "cross_split_feature_groups": crossing, "conflicting_quality_feature_groups": 0,
               "all_strata_have_three_splits": all(all(value > 0 for value in detail["feature_groups"].values())
                                               for detail in by_quality.values())}
    training_scores = [record["quality"] for record in records if group_split[record["key"]] == "training"]
    validation_scores = [record["quality"] for record in records if group_split[record["key"]] == "validation"]
    # Final-evaluation quality is used for stratification and row-count audit only.
    baseline_constant = float(statistics.median(training_scores))
    errors = [score - baseline_constant for score in validation_scores]
    baseline = {"training_rows": len(training_scores), "validation_rows": len(validation_scores),
                "training_quality_median_prediction": baseline_constant,
                "validation_mae": sum(abs(error) for error in errors) / len(errors),
                "validation_rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
                "unit": "quality score points"}
    return assignments, summary, baseline


def main() -> None:
    command = f"& '{sys.executable}' 'steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/src/prepare.py'"
    before = {str(path.relative_to(ROOT)): fingerprint(path) for path in INPUTS}
    try:
        first_profile = json.loads((ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验/outputs/data_profile.json").read_text(encoding="utf-8"))
        all_assignments = []
        summaries = {}
        baselines = {}
        for wine in ("red", "white"):
            records, observed = load_wine(wine, first_profile)
            assignments, summary, baseline = split_wine(wine, records)
            summary.update(observed)
            all_assignments.extend(assignments)
            summaries[wine] = summary
            baselines[wine] = baseline
        after = {str(path.relative_to(ROOT)): fingerprint(path) for path in INPUTS}
        if after != before:
            raise ValueError("Read-only input fingerprints changed during preparation")
        output_dir = STEP / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        assignments_path = output_dir / "split_assignments.csv"
        with assignments_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["wine", "source_row", "feature_group_id", "split"])
            writer.writeheader()
            writer.writerows(all_assignments)
        definition = {"seed": SEED, "wine_order": ["red", "white"],
                      "feature_fields": FIELDS[:11],
                      "canonical_numeric": "Decimal numeric equality; zero to 0, otherwise normalize then fixed-point string",
                      "feature_serialization": "11 canonical values joined by | in CSV column order",
                      "feature_group_id": "SHA256(wine|feature_serialization) in lowercase hex",
                      "strata": "within wine by unique feature-group quality; stop on conflicting quality or fewer than 5 groups",
                      "order": "SHA256(seed|wine|quality|feature_serialization), then feature_serialization",
                      "allocation": "sorted groups: first ceil(0.2*n) final_evaluation, next ceil(0.2*n) validation, remaining training",
                      "baseline": "median training quality, constant prediction on validation rows only"}
        split_result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "inputs_before": before, "inputs_after": after, "inputs_unchanged": before == after,
                        "definition": definition, "assignments_path": str(assignments_path),
                        "assignment_rows": len(all_assignments), "files": summaries}
        summary_path = output_dir / "split_summary.json"
        summary_path.write_text(json.dumps(split_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        baseline_result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
                           "scope": "training fit and validation evaluation only; no final-evaluation prediction or metric",
                           "primary_metric": "MAE", "auxiliary_metric": "RMSE", "files": baselines}
        baseline_path = output_dir / "baseline_validation.json"
        baseline_path.write_text(json.dumps(baseline_result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        record_log({"action": "prepare", "command": command, "status": "success",
                    "python": sys.version.split()[0], "platform": platform.platform(),
                    "parameters": definition, "inputs_before": before, "inputs_after": after,
                    "outputs": [str(assignments_path), str(summary_path), str(baseline_path)]})
        print(json.dumps({"assignment_rows": len(all_assignments),
                          "rows": {wine: summary["totals"]["rows"] for wine, summary in summaries.items()},
                          "validation": {wine: {"mae": result["validation_mae"], "rmse": result["validation_rmse"]}
                                         for wine, result in baselines.items()}}))
    except Exception as exc:
        record_log({"action": "prepare", "command": command, "status": "failed", "error": repr(exc),
                    "inputs_before": before,
                    "inputs_after": {str(path.relative_to(ROOT)): fingerprint(path) for path in INPUTS}})
        raise


if __name__ == "__main__":
    main()
