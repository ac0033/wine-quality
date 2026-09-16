"""Exploratory analysis of both original wine CSVs; original inputs are read only."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/02_EDA/2.1_理化指标与quality的探索分析"
DATA = ROOT / "data"
FIRST = ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验"
INPUTS = [DATA / "winequality-red.csv", DATA / "winequality-white.csv", DATA / "winequality.names",
          FIRST / "outputs" / "data_profile.json", FIRST / "acceptance.md"]
FIELDS = ["fixed acidity", "volatile acidity", "citric acid", "residual sugar", "chlorides",
          "free sulfur dioxide", "total sulfur dioxide", "density", "pH", "sulphates", "alcohol"]


def fingerprint(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def log(event: dict) -> None:
    event = {"at_utc": datetime.now(timezone.utc).isoformat(), **event}
    with (STEP / "execution.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def finite_corr(a: pd.Series, b: pd.Series, method: str) -> float:
    if method == "spearman":
        # Pearson on average ranks is Spearman, without pandas' optional scipy dependency.
        value = float(a.rank(method="average").corr(b.rank(method="average"), method="pearson"))
    else:
        value = float(a.corr(b, method=method))
    if not math.isfinite(value) or not -1.0000000001 <= value <= 1.0000000001:
        raise ValueError(f"Invalid {method} correlation: {value}")
    return max(-1.0, min(1.0, value))


def analyze_one(path: Path, baseline: dict) -> dict:
    frame = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=float)
    expected_header = FIELDS + ["quality"]
    if list(frame.columns) != expected_header or list(frame.columns) != baseline["header"]:
        raise ValueError(f"Header mismatch: {path}")
    if len(frame) != baseline["rows"] or frame.isna().any().any() or not np.isfinite(frame.to_numpy()).all():
        raise ValueError(f"Rows, missing or nonfinite values disagree: {path}")
    counts = {str(int(k)): int(v) for k, v in frame["quality"].value_counts().sort_index().items()}
    baseline_counts = {k: v["rows"] for k, v in baseline["quality_distribution"].items()}
    if counts != baseline_counts:
        raise ValueError(f"quality frequencies disagree: {path}")
    indicators = {}
    for name in FIELDS:
        column = frame[name]
        groups = frame.groupby("quality", sort=True)[name]
        indicators[name] = {
            "distribution": {
                "valid_rows": int(column.notna().sum()), "min": float(column.min()),
                "q1": float(column.quantile(.25, interpolation="linear")),
                "median": float(column.median()),
                "q3": float(column.quantile(.75, interpolation="linear")),
                "max": float(column.max()), "mean": float(column.mean()),
            },
            "pearson_quality": finite_corr(column, frame["quality"], "pearson"),
            "spearman_quality": finite_corr(column, frame["quality"], "spearman"),
            "by_quality": {str(int(score)): {"rows": int(groups.count()[score]),
                                              "median": float(groups.median()[score])}
                           for score in sorted(frame["quality"].unique())},
        }
    pairwise = {a: {b: finite_corr(frame[a], frame[b], "spearman") for b in FIELDS} for a in FIELDS}
    # Equality is defined by all twelve original CSV field strings, not float conversion.
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.reader(stream, delimiter=";"))[1:]
    if len(raw_rows) != len(frame):
        raise ValueError(f"Raw row count mismatch: {path}")
    seen = set()
    first_indexes = []
    for index, row in enumerate(raw_rows):
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            first_indexes.append(index)
    unique = frame.iloc[first_indexes]
    sensitivity = {}
    flags = []
    for name in FIELDS:
        coefficient = finite_corr(unique[name], unique["quality"], "spearman")
        original = indicators[name]["spearman_quality"]
        difference = coefficient - original
        direction_change = (original < 0 < coefficient) or (coefficient < 0 < original)
        flagged = direction_change or abs(difference) >= .10
        sensitivity[name] = {"spearman_quality_unique_rows": coefficient,
                             "difference_unique_minus_all": difference,
                             "direction_changed": direction_change,
                             "absolute_difference_at_least_0_10": abs(difference) >= .10}
        if flagged:
            flags.append(name)
    return {
        "path": str(path), "rows": len(frame), "header": list(frame.columns),
        "quality_counts": counts, "indicators": indicators,
        "inter_indicator_spearman": pairwise,
        "sensitivity": {"all_rows": len(frame), "unique_rows": len(unique),
                        "duplicate_rows_beyond_first": len(frame) - len(unique),
                        "by_indicator": sensitivity, "flagged_indicators": flags},
    }


def svg_quality(files: dict, path: Path) -> None:
    width, height = 940, 460
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#1f2937}.title{font-size:20px;font-weight:bold}.label{font-size:13px}.small{font-size:11px}</style>',
             '<text x="28" y="32" class="title">quality distribution within each wine file</text>',
             '<text x="28" y="52" class="small">Bars show percent of all rows in that file; exact rows are in eda.json.</text>']
    for panel, (wine, data) in enumerate(files.items()):
        x0 = 30 + panel * 465
        y0 = 90
        parts.append(f'<text x="{x0}" y="{y0}" class="label">{wine.title()} wine (n={data["rows"]})</text>')
        for score in range(3, 10):
            count = data["quality_counts"].get(str(score), 0)
            pct = count / data["rows"] * 100
            y = 120 + (score - 3) * 45
            bar_width = pct * 7.3
            color = "#9b2c50" if wine == "red" else "#a88a25"
            parts.extend([
                f'<text x="{x0}" y="{y+16}" class="label">{score}</text>',
                f'<rect x="{x0+28}" y="{y}" width="{bar_width:.4f}" height="20" fill="{color}" data-wine="{wine}" data-score="{score}" data-rows="{count}" data-share="{count/data["rows"]:.17g}"/>',
                f'<text x="{x0+36+bar_width:.2f}" y="{y+16}" class="small">{pct:.1f}% ({count})</text>',
            ])
    parts.append('</svg>')
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def svg_relationship(files: dict, path: Path) -> None:
    width, height = 1000, 535
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#1f2937}.title{font-size:20px;font-weight:bold}.label{font-size:13px}.small{font-size:11px}</style>',
             '<text x="22" y="31" class="title">Spearman correlation with quality (all original rows)</text>',
             '<text x="22" y="53" class="small">A correlation is descriptive, not a cause or prediction score. Full precision and Pearson results are in eda.json.</text>',
             '<rect x="720" y="29" width="12" height="12" fill="#9b2c50"/><text x="738" y="40" class="small">Red</text>',
             '<rect x="789" y="29" width="12" height="12" fill="#a88a25"/><text x="807" y="40" class="small">White</text>',
             '<line x1="610" y1="75" x2="610" y2="510" stroke="#64748b"/>']
    for idx, name in enumerate(FIELDS):
        y = 85 + idx * 39
        parts.append(f'<text x="22" y="{y+13}" class="label">{escape(name)}</text>')
        for offset, (wine, data) in enumerate(files.items()):
            value = data["indicators"][name]["spearman_quality"]
            scale = 470
            x = 610 + min(0, value * scale)
            bar_width = abs(value * scale)
            color = "#9b2c50" if wine == "red" else "#a88a25"
            parts.append(f'<rect x="{x:.4f}" y="{y+offset*13}" width="{bar_width:.4f}" height="10" fill="{color}" data-wine="{wine}" data-indicator="{escape(name)}" data-correlation="{value:.17g}"/>')
    parts.append('</svg>')
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    before = {str(path.relative_to(ROOT)): fingerprint(path) for path in INPUTS}
    command = f"& '{sys.executable}' 'steps/02_EDA/2.1_理化指标与quality的探索分析/src/analyze.py'"
    try:
        baseline = json.loads((FIRST / "outputs" / "data_profile.json").read_text(encoding="utf-8"))
        files = {wine: analyze_one(DATA / f"winequality-{wine}.csv", baseline["files"][wine])
                 for wine in ("red", "white")}
        after = {str(path.relative_to(ROOT)): fingerprint(path) for path in INPUTS}
        if before != after:
            raise ValueError("Read-only input fingerprints changed during analysis")
        output = STEP / "outputs" / "eda.json"
        figures = STEP / "figures"
        output.parent.mkdir(parents=True, exist_ok=True)
        figures.mkdir(parents=True, exist_ok=True)
        result = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "definitions": {"main_rows": "all original rows", "q1_q3": "linear interpolation at positions (n-1)*p",
                            "median": "middle pair averaged when n even", "spearman_ties": "average ranks",
                            "duplicate_rows": "all 12 field values equal; first row retained only for sensitivity"},
            "inputs_before": before, "inputs_after": after, "inputs_unchanged": before == after,
            "files": files,
            "figures": ["figures/quality_distribution.svg", "figures/spearman_quality.svg"],
        }
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        svg_quality(files, figures / "quality_distribution.svg")
        svg_relationship(files, figures / "spearman_quality.svg")
        log({"action": "analyze", "command": command, "status": "success", "python": sys.version.split()[0],
             "pandas": pd.__version__, "numpy": np.__version__, "platform": platform.platform(),
             "parameters": result["definitions"], "inputs_before": before, "inputs_after": after,
             "output": str(output), "figures": [str(figures / p) for p in ("quality_distribution.svg", "spearman_quality.svg")]})
        print(json.dumps({"rows": {k: v["rows"] for k, v in files.items()}, "output": str(output)}))
    except Exception as exc:
        log({"action": "analyze", "command": command, "status": "failed", "error": repr(exc),
             "inputs_before": before,
             "inputs_after": {str(path.relative_to(ROOT)): fingerprint(path) for path in INPUTS}})
        raise


if __name__ == "__main__":
    main()
