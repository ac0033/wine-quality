"""Read-only profile of the original Wine Quality CSV files."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验"
DATA = ROOT / "data"
INPUTS = [DATA / "winequality-red.csv", DATA / "winequality-white.csv", DATA / "winequality.names"]
EXPECTED = [
    "fixed acidity", "volatile acidity", "citric acid", "residual sugar",
    "chlorides", "free sulfur dioxide", "total sulfur dioxide", "density",
    "pH", "sulphates", "alcohol", "quality",
]


def fingerprint(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def profile_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=";", strict=True)
        header = next(reader)
        empty = Counter({name: 0 for name in header})
        invalid_numeric = Counter({name: 0 for name in header})
        nonfinite = Counter({name: 0 for name in header})
        ranges = {name: [None, None] for name in header}
        widths = Counter()
        quality = Counter()
        seen = set()
        duplicate_rows = 0
        invalid_quality = 0
        rows = 0
        for row in reader:
            rows += 1
            widths[len(row)] += 1
            if tuple(row) in seen:
                duplicate_rows += 1
            seen.add(tuple(row))
            for idx, name in enumerate(header):
                if idx >= len(row):
                    empty[name] += 1
                    continue
                value = row[idx].strip()
                if not value:
                    empty[name] += 1
                    continue
                try:
                    numeric = Decimal(value)
                except InvalidOperation:
                    invalid_numeric[name] += 1
                    continue
                if not numeric.is_finite():
                    nonfinite[name] += 1
                    continue
                bounds = ranges[name]
                bounds[0] = numeric if bounds[0] is None else min(bounds[0], numeric)
                bounds[1] = numeric if bounds[1] is None else max(bounds[1], numeric)
            if len(row) > len(header):
                pass  # captured in row_width_counts
            if len(row) > 11:
                try:
                    q = Decimal(row[11].strip())
                    if q.is_finite() and q == q.to_integral_value() and 0 <= q <= 10:
                        quality[str(int(q))] += 1
                    else:
                        invalid_quality += 1
                except InvalidOperation:
                    invalid_quality += 1
            else:
                invalid_quality += 1
    return {
        "path": str(path), "rows": rows, "header": header,
        "header_matches_names": header == EXPECTED,
        "row_width_counts": dict(sorted(widths.items())),
        "empty_by_field": dict(empty),
        "invalid_numeric_by_field": dict(invalid_numeric),
        "nonfinite_by_field": dict(nonfinite),
        "quality_invalid_or_outside_0_10_rows": invalid_quality,
        "exact_duplicate_rows_beyond_first": duplicate_rows,
        "distinct_exact_rows": len(seen),
        "ranges": {name: {"min": str(pair[0]) if pair[0] is not None else None,
                           "max": str(pair[1]) if pair[1] is not None else None}
                   for name, pair in ranges.items()},
        "quality_distribution": {
            key: {"rows": count, "share_of_all_rows": count / rows if rows else None}
            for key, count in sorted(quality.items(), key=lambda item: int(item[0]))
        },
        "quality_count_sum": sum(quality.values()),
    }


def main() -> None:
    before = {path.name: fingerprint(path) for path in INPUTS}
    names = (DATA / "winequality.names").read_text(encoding="utf-8")
    name_fields = []
    for line in names.splitlines():
        line = line.strip()
        if " - " in line and line.split(" - ", 1)[0].isdigit():
            name_fields.append(line.split(" - ", 1)[1].split(" (")[0])
    profiles = {label: profile_csv(DATA / f"winequality-{label}.csv") for label in ("red", "white")}
    after = {path.name: fingerprint(path) for path in INPUTS}
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs_before": before, "inputs_after": after,
        "inputs_unchanged": before == after,
        "names_fields": name_fields,
        "names_fields_match_expected": name_fields == EXPECTED,
        "files": profiles,
    }
    output = STEP / "outputs" / "data_profile.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log = {
        "at_utc": datetime.now(timezone.utc).isoformat(), "action": "profile",
        "command": f"& '{sys.executable}' 'steps/01_数据预处理/1.1_原始数据理解与质量核验/src/profile.py'",
        "python": sys.version.split()[0], "platform": platform.platform(),
        "parameters": {"delimiter": ";", "encoding": "utf-8-sig", "duplicate_definition": "all 12 fields exactly equal"},
        "inputs_before": before, "inputs_after": after,
        "output": str(output), "status": "success" if before == after else "input_changed",
    }
    with (STEP / "execution.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(log, ensure_ascii=False) + "\n")
    if before != after:
        raise SystemExit("Original input changed during profiling")
    print(json.dumps({"output": str(output), "rows": {k: v["rows"] for k, v in profiles.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
