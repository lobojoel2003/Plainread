"""The labelled sample letters are part of the test suite: quality is a test."""

import pytest

from plainread.evaluation import THRESHOLDS, evaluate

from .conftest import EVAL_LETTERS


def test_text_mode_meets_quality_thresholds():
    report = evaluate(EVAL_LETTERS)
    assert report.letters >= 20
    assert report.failures() == []
    assert report.metrics()["grounding"] == 1.0


@pytest.mark.ocr
@pytest.mark.slow
def test_ocr_mode_meets_quality_thresholds():
    report = evaluate(EVAL_LETTERS, ocr=True)
    assert report.failures() == [], report.metrics()


def test_thresholds_are_strict_enough():
    assert THRESHOLDS["text"]["grounding"] == 1.0
    assert THRESHOLDS["text"]["dates_f1"] >= 0.9
