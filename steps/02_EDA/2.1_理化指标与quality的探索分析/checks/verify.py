"""Independent raw-line and standard-library checks of the exploration output."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/02_EDA/2.1_理化指标与quality的探索分析"
DATA = ROOT / "data"
FIRST = ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验"
INPUTS = [DATA / "winequality-red.csv", DATA / "winequality-white.csv", DATA / "winequality.names",
          FIRST / "outputs" / "data_profile.json", FIRST / "acceptance.md"]
FIELDS = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
          "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol"]
SELECTED = {"red": ["alcohol", "volatile acidity", "residual sugar"],
            "white": ["alcohol", "density", "citric acid"]}
eda = json.loads((STEP / "outputs" / "eda.json").read_text(encoding="utf-8"))
first = json.loads((FIRST / "outputs" / "data_profile.json").read_text(encoding="utf-8"))
checks = []


def check(name: str, actual, expected, tolerance: float | None = None) -> None:
    passed = (math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance)
              if tolerance is not None else actual == expected)
    actual_logged = sorted(actual) if isinstance(actual, set) else actual
    expected_logged = sorted(expected) if isinstance(expected, set) else expected
    checks.append({"check": name, "pass": passed, "actual": actual_logged, "expected": expected_logged,
                   "tolerance": tolerance})


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2)


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def ranks(values: list[float]) -> list[float]:
    ranked = [0.0] * len(values)
    ordered_indexes = sorted(range(len(values)), key=values.__getitem__)
    start = 0
    while start < len(values):
        stop = start + 1
        while stop < len(values) and values[ordered_indexes[stop]] == values[ordered_indexes[start]]:
            stop += 1
        rank = (start + 1 + stop) / 2
        for index in ordered_indexes[start:stop]:
            ranked[index] = rank
        start = stop
    return ranked


def pearson(a: list[float], b: list[float]) -> float:
    mean_a, mean_b = statistics.fmean(a), statistics.fmean(b)
    centered_a = [v - mean_a for v in a]
    centered_b = [v - mean_b for v in b]
    numerator = sum(x * y for x, y in zip(centered_a, centered_b))
    denominator = math.sqrt(sum(x * x for x in centered_a) * sum(y * y for y in centered_b))
    return numerator / denominator


for path in INPUTS:
    raw = path.read_bytes()
    key = str(path.relative_to(ROOT))
    saved = eda["inputs_before"][key]
    check(f"{key}: path", str(path), saved["path"])
    check(f"{key}: bytes", len(raw), saved["bytes"])
    check(f"{key}: SHA256", hashlib.sha256(raw).hexdigest(), saved["sha256"])
    check(f"{key}: unchanged", eda["inputs_after"][key], saved)

for wine in ("red", "white"):
    raw_lines = (DATA / f"winequality-{wine}.csv").read_bytes().decode("utf-8-sig").splitlines()
    header = [piece.strip('"') for piece in raw_lines[0].split(";")]
    cells = [line.split(";") for line in raw_lines[1:]]
    rows = [[float(value) for value in row] for row in cells]
    scores = [int(row[-1]) for row in rows]
    counts = {str(score): count for score, count in sorted(Counter(scores).items())}
    result = eda["files"][wine]
    check(f"{wine}: header", header, result["header"])
    check(f"{wine}: 12 fields", header, FIELDS + ["quality"])
    check(f"{wine}: all row widths", set(map(len, cells)), {12})
    check(f"{wine}: rows", len(rows), result["rows"])
    check(f"{wine}: first-step rows", len(rows), first["files"][wine]["rows"])
    check(f"{wine}: quality counts", counts, result["quality_counts"])
    check(f"{wine}: first-step quality counts", counts,
          {k: v["rows"] for k, v in first["files"][wine]["quality_distribution"].items()})
    check(f"{wine}: quality total", sum(counts.values()), len(rows))
    unique_rows = len(set(raw_lines[1:]))
    seen_raw = set()
    unique_indexes = []
    for index, line in enumerate(raw_lines[1:]):
        if line not in seen_raw:
            seen_raw.add(line)
            unique_indexes.append(index)
    check(f"{wine}: sensitivity all rows", len(rows), result["sensitivity"]["all_rows"])
    check(f"{wine}: sensitivity unique rows", unique_rows, result["sensitivity"]["unique_rows"])
    check(f"{wine}: duplicate rows", len(rows) - unique_rows,
          result["sensitivity"]["duplicate_rows_beyond_first"])
    check(f"{wine}: all 11 indicators", set(result["indicators"]), set(FIELDS))
    check(f"{wine}: all pairwise rows", set(result["inter_indicator_spearman"]), set(FIELDS))
    for name in FIELDS:
        index = header.index(name)
        values = [row[index] for row in rows]
        distribution = result["indicators"][name]["distribution"]
        for key, actual in {
            "valid_rows": len(values), "min": min(values), "q1": quantile(values, .25),
            "median": median(values), "q3": quantile(values, .75), "max": max(values),
            "mean": statistics.fmean(values),
        }.items():
            check(f"{wine}: {name}: {key}", actual, distribution[key],
                  None if key == "valid_rows" else 1e-10)
        groups = result["indicators"][name]["by_quality"]
        check(f"{wine}: {name}: group keys", set(groups), set(counts))
        check(f"{wine}: {name}: group row total", sum(group["rows"] for group in groups.values()), len(rows))
        for method in ("pearson_quality", "spearman_quality"):
            value = result["indicators"][name][method]
            check(f"{wine}: {name}: {method} finite in range", math.isfinite(value) and -1 <= value <= 1, True)
        check(f"{wine}: {name}: pairwise columns", set(result["inter_indicator_spearman"][name]), set(FIELDS))
        unique_values = [values[index] for index in unique_indexes]
        unique_scores = [scores[index] for index in unique_indexes]
        unique_spearman = pearson(ranks(unique_values), ranks(unique_scores))
        check(f"{wine}: {name}: sensitivity Spearman", unique_spearman,
              result["sensitivity"]["by_indicator"][name]["spearman_quality_unique_rows"], 1e-10)
        difference = unique_spearman - result["indicators"][name]["spearman_quality"]
        check(f"{wine}: {name}: sensitivity difference", difference,
              result["sensitivity"]["by_indicator"][name]["difference_unique_minus_all"], 1e-10)
        if name in SELECTED[wine]:
            grouped = defaultdict(list)
            for row, score in zip(rows, scores):
                grouped[str(score)].append(row[index])
            for score, group in grouped.items():
                check(f"{wine}: {name}: quality {score} rows", len(group), groups[score]["rows"])
                check(f"{wine}: {name}: quality {score} median", median(group), groups[score]["median"], 1e-10)
            observed = pearson(ranks(values), ranks(scores))
            check(f"{wine}: {name}: Spearman", observed,
                  result["indicators"][name]["spearman_quality"], 1e-10)
            check(f"{wine}: {name}: Pearson", pearson(values, scores),
                  result["indicators"][name]["pearson_quality"], 1e-10)
    for name in FIELDS:
        for other in FIELDS:
            coefficient = result["inter_indicator_spearman"][name][other]
            check(f"{wine}: pair {name} vs {other} finite in range",
                  math.isfinite(coefficient) and -1 <= coefficient <= 1, True)
            check(f"{wine}: pair {name} vs {other} symmetry", coefficient,
                  result["inter_indicator_spearman"][other][name], 1e-10)

namespace = {"svg": "http://www.w3.org/2000/svg"}
quality_svg = ET.parse(STEP / "figures" / "quality_distribution.svg")
quality_bars = [node for node in quality_svg.findall(".//svg:rect", namespace) if "data-score" in node.attrib]
check("quality figure bar count", len(quality_bars), 14)
for bar in quality_bars:
    wine, score = bar.attrib["data-wine"], bar.attrib["data-score"]
    count = eda["files"][wine]["quality_counts"].get(score, 0)
    check(f"quality figure {wine} {score} rows", int(bar.attrib["data-rows"]), count)
    check(f"quality figure {wine} {score} share", float(bar.attrib["data-share"]),
          count / eda["files"][wine]["rows"], 1e-15)
relation_svg = ET.parse(STEP / "figures" / "spearman_quality.svg")
relation_bars = [node for node in relation_svg.findall(".//svg:rect", namespace) if "data-correlation" in node.attrib]
check("relationship figure bar count", len(relation_bars), 22)
for bar in relation_bars:
    wine, name = bar.attrib["data-wine"], bar.attrib["data-indicator"]
    check(f"relationship figure {wine} {name}", float(bar.attrib["data-correlation"]),
          eda["files"][wine]["indicators"][name]["spearman_quality"], 1e-15)

verification = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "method": "Independent raw-line parsing and standard-library sorting, ranks, covariance; SVG XML attributes checked against JSON",
                "selected_by_wine": SELECTED, "passed": all(item["pass"] for item in checks),
                "passed_checks": sum(item["pass"] for item in checks), "total_checks": len(checks),
                "checks": checks}
output = STEP / "checks" / "verification.json"
output.write_text(json.dumps(verification, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
with (STEP / "execution.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"at_utc": datetime.now(timezone.utc).isoformat(), "action": "independent_verify",
                             "command": f"& '{sys.executable}' 'steps/02_EDA/2.1_理化指标与quality的探索分析/checks/verify.py'",
                             "status": "success" if verification["passed"] else "failed",
                             "input": str(STEP / "outputs" / "eda.json"), "output": str(output),
                             "selected_by_wine": SELECTED, "passed_checks": verification["passed_checks"],
                             "total_checks": len(checks)}, ensure_ascii=False) + "\n")
print(json.dumps({"passed": verification["passed"], "passed_checks": verification["passed_checks"],
                  "total_checks": len(checks)}))
if not verification["passed"]:
    raise SystemExit(1)
