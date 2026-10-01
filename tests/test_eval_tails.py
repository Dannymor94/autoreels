"""Tests for scripts/eval_tails.py — parser and metrics only.

Hermetic: no real files read, CSV written to tmp.
"""
from __future__ import annotations
import csv, io, sys, textwrap
from pathlib import Path

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import eval_tails


# ── _parse_owner_choice ──────────────────────────────────────────────────────

def _row(**kw) -> dict:
    defaults = {"owner_choice": "", "A_s": "10.000", "B_s": "10.100", "C_s": ""}
    return {**defaults, **kw}


def test_parse_empty_returns_none():
    assert eval_tails._parse_owner_choice(_row(owner_choice="")) is None


def test_parse_letter_A():
    r = _row(owner_choice="A", A_s="5.500")
    assert eval_tails._parse_owner_choice(r) == pytest.approx(5.5)


def test_parse_letter_B():
    r = _row(owner_choice="B", B_s="6.250")
    assert eval_tails._parse_owner_choice(r) == pytest.approx(6.25)


def test_parse_letter_C():
    r = _row(owner_choice="C", C_s="7.123")
    assert eval_tails._parse_owner_choice(r) == pytest.approx(7.123)


def test_parse_letter_case_insensitive():
    r = _row(owner_choice="b", B_s="3.000")
    assert eval_tails._parse_owner_choice(r) == pytest.approx(3.0)


def test_parse_numeric_string():
    r = _row(owner_choice="12.345")
    assert eval_tails._parse_owner_choice(r) == pytest.approx(12.345)


def test_parse_letter_missing_value_returns_none():
    r = _row(owner_choice="C", C_s="")
    assert eval_tails._parse_owner_choice(r) is None


# ── _stats ───────────────────────────────────────────────────────────────────

def test_stats_empty():
    s = eval_tails._stats([], [])
    assert s["n"] == 0
    assert s["mean"] is None


def test_stats_basic():
    errors = [50.0, 100.0, 200.0, 25.0]   # ms
    cuts   = [True, False, True, False]
    s = eval_tails._stats(errors, cuts)
    assert s["n"] == 4
    assert s["mean"] == pytest.approx(93.75)
    assert s["within_50"] == pytest.approx(0.5)   # 50 and 25
    assert s["within_100"] == pytest.approx(0.75)
    assert s["within_200"] == pytest.approx(1.0)
    assert s["cut"] == 2
    assert s["extra"] == 2


# ── run() on no-answers CSV ───────────────────────────────────────────────────

def test_run_no_answers(tmp_path, capsys):
    csv_path = tmp_path / "answers.csv"
    rows = [
        {"case": "x_r01", "stem": "x", "reel": "r01", "last_word": "foo",
         "A_s": "1.0", "B_s": "1.1", "C_s": "", "render_end_s": "1.1",
         "next_onset_s": "1.5", "gap_type": "silence",
         "owner_choice": "", "notes": ""},
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    eval_tails.run(csv_path)
    out = capsys.readouterr().out
    assert "no answers" in out.lower() or "No answers" in out


# ── run() with one answered row ───────────────────────────────────────────────

def test_run_one_answer(tmp_path, capsys):
    csv_path = tmp_path / "answers.csv"
    rows = [
        {"case": "x_r01", "stem": "x", "reel": "r01", "last_word": "foo",
         "A_s": "1.000", "B_s": "1.100", "C_s": "", "render_end_s": "1.100",
         "next_onset_s": "1.500", "gap_type": "silence",
         "owner_choice": "A", "notes": ""},
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    eval_tails.run(csv_path)
    out = capsys.readouterr().out
    # Should print table with method A having n=1 and mean=0
    assert "Answered:" in out
    assert "A" in out
