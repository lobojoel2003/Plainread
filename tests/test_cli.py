import json
import shutil

import pytest

from plainread import __version__
from plainread.cli import main

from .conftest import COURT_LETTER, EVAL_LETTERS


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_explain_json(tmp_path, capsys):
    letter = tmp_path / "letter.txt"
    letter.write_text(COURT_LETTER, encoding="utf-8")
    ics = tmp_path / "dates.ics"
    assert main(["explain", str(letter), "--json", "--today", "2026-03-02", "--ics", str(ics)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["letter_type"] == "court"
    assert "source_text" not in data
    assert ics.read_text().count("BEGIN:VEVENT") == 2


def test_explain_pretty_in_spanish(tmp_path, capsys):
    letter = tmp_path / "letter.txt"
    letter.write_text(COURT_LETTER, encoding="utf-8")
    assert (
        main(["explain", str(letter), "--lang", "es", "--today", "2026-03-02", "--width", "100"])
        == 0
    )
    out = capsys.readouterr().out
    assert "Fechas importantes" in out
    assert "SC-2026-004512" in out


def test_explain_missing_file(capsys):
    assert main(["explain", "/no/such/file.jpg"]) == 2


def test_languages(capsys):
    assert main(["languages"]) == 0
    out = capsys.readouterr().out
    assert "Español" in out
    assert "العربية" in out


def test_doctor(capsys, monkeypatch):
    monkeypatch.setenv("PLAINREAD_AI", "off")
    assert main(["doctor"]) == 0
    assert "Plainread" in capsys.readouterr().out


def test_eval_command_on_a_small_set(tmp_path, capsys):
    for name in ("court-small-claims", "utility-shutoff"):
        for suffix in (".txt", ".json"):
            shutil.copy(EVAL_LETTERS / f"{name}{suffix}", tmp_path / f"{name}{suffix}")
    report = tmp_path / "report.json"
    assert main(["eval", "--letters", str(tmp_path), "--json", str(report)]) == 0
    data = json.loads(report.read_text())
    assert data["letters"] == 2
    assert data["metrics"]["grounding"] == 1.0
    assert main(["eval", "--letters", str(tmp_path / "missing")]) == 2
