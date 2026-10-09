"""固定合成题集回归：20 份样本的漏检 / 误报测量。"""
import json
from pathlib import Path

from pii_review.pipeline import run_regression

ROOT = Path(__file__).resolve().parents[1]


def test_regression_20_samples():
    gt = json.loads((ROOT / "data" / "ground_truth.json").read_text(encoding="utf-8"))
    result = run_regression(ROOT / "data" / "samples", gt)
    assert result["total_positive"] == 17
    assert result["recall"] == 1.0, result["misses"]
    assert result["false_positive_rate"] == 0.0, result["false_positives"]
