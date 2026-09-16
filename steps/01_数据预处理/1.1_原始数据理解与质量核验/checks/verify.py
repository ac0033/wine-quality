"""Independent raw-line recount against data_profile.json; does not import profile.py."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
STEP = ROOT / "steps/01_数据预处理/1.1_原始数据理解与质量核验"
DATA = ROOT / "data"
INPUTS = [DATA / f"winequality-{name}.csv" for name in ("red", "white")] + [DATA / "winequality.names"]
profile = json.loads((STEP / "outputs" / "data_profile.json").read_text(encoding="utf-8"))
checks = []


def check(label: str, actual, expected) -> None:
    checks.append({"check": label, "pass": actual == expected, "actual": actual, "expected": expected})


for path in INPUTS:
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    saved = profile["inputs_before"][path.name]
    check(f"{path.name}: path", str(path), saved["path"])
    check(f"{path.name}: bytes", len(raw), saved["bytes"])
    check(f"{path.name}: SHA256", actual_hash, saved["sha256"])
    check(f"{path.name}: unchanged after primary run", profile["inputs_after"][path.name], saved)

for label in ("red", "white"):
    raw_lines = (DATA / f"winequality-{label}.csv").read_bytes().decode("utf-8-sig").splitlines()
    header = [part.strip('"') for part in raw_lines[0].split(";")]
    rows = [line.split(";") for line in raw_lines[1:]]
    widths = Counter(map(len, rows))
    empty = Counter({field: 0 for field in header})
    invalid = Counter({field: 0 for field in header})
    nonfinite = Counter({field: 0 for field in header})
    quality = Counter()
    invalid_quality = 0
    for row in rows:
        for col, field in enumerate(header):
            cell = row[col].strip() if col < len(row) else ""
            if not cell:
                empty[field] += 1
                continue
            try:
                number = float(cell)
            except ValueError:
                invalid[field] += 1
                continue
            if not math.isfinite(number):
                nonfinite[field] += 1
        try:
            score = float(row[11].strip())
            if math.isfinite(score) and score.is_integer() and 0 <= score <= 10:
                quality[str(int(score))] += 1
            else:
                invalid_quality += 1
        except (IndexError, ValueError):
            invalid_quality += 1
    expected = profile["files"][label]
    check(f"{label}: header", header, expected["header"])
    check(f"{label}: rows", len(rows), expected["rows"])
    check(f"{label}: row widths", {str(k): v for k, v in sorted(widths.items())}, expected["row_width_counts"])
    check(f"{label}: empty by field", dict(empty), expected["empty_by_field"])
    check(f"{label}: invalid numeric by field", dict(invalid), expected["invalid_numeric_by_field"])
    check(f"{label}: nonfinite by field", dict(nonfinite), expected["nonfinite_by_field"])
    check(f"{label}: invalid quality", invalid_quality, expected["quality_invalid_or_outside_0_10_rows"])
    check(f"{label}: quality frequencies", dict(quality), {k: v["rows"] for k, v in expected["quality_distribution"].items()})
    check(f"{label}: quality frequency sum", sum(quality.values()), expected["quality_count_sum"])
    check(f"{label}: complete quality distribution", sum(quality.values()) == len(rows), True)
    check(f"{label}: duplicate rows", len(rows) - len(set(raw_lines[1:])), expected["exact_duplicate_rows_beyond_first"])
    check(f"{label}: distinct rows", len(set(raw_lines[1:])), expected["distinct_exact_rows"])
    for score, count in quality.items():
        check(f"{label}: quality {score} share", count / len(rows), expected["quality_distribution"][score]["share_of_all_rows"])

result = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "method": "Raw bytes, splitlines and semicolon split; independent from csv.reader and Decimal primary code",
    "passed": all(item["pass"] for item in checks),
    "passed_checks": sum(item["pass"] for item in checks),
    "total_checks": len(checks),
    "checks": checks,
}
output = STEP / "checks" / "verification.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
with (STEP / "execution.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({
        "at_utc": datetime.now(timezone.utc).isoformat(), "action": "independent_verify",
        "command": f"& '{sys.executable}' 'steps/01_数据预处理/1.1_原始数据理解与质量核验/checks/verify.py'",
        "python": sys.version.split()[0], "input_profile": str(STEP / "outputs" / "data_profile.json"),
        "output": str(output), "status": "success" if result["passed"] else "failed",
        "passed_checks": result["passed_checks"], "total_checks": len(checks),
    }, ensure_ascii=False) + "\n")
print(json.dumps({"passed": result["passed"], "passed_checks": result["passed_checks"], "total_checks": len(checks)}))
if not result["passed"]:
    raise SystemExit(1)
