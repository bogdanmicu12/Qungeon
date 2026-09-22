"""Runnable checks for level validation and safe position parsing (QUN-6).

Pure Python: no pygame/unitary needed. Run with `python tests/test_level_validation.py`.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from scripts.level_validation import validate_level, parse_pos, LevelError

FIXTURES = os.path.join(HERE, "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def test_parse_pos_ok():
    assert parse_pos("(3,4)") == (3, 4)
    assert parse_pos("(5, 4)") == (5, 4)


def test_parse_pos_rejects_bad():
    for bad in ["(1,2,3)", "(a,b)", "(1,)", "hello", "()"]:
        try:
            parse_pos(bad)
        except LevelError:
            continue
        raise AssertionError(f"parse_pos({bad!r}) should have raised LevelError")


def test_malformed_fixtures_raise():
    for name in ("no_start.json", "bad_position.json",
                 "unknown_gate.json", "missing_key.json"):
        data = _load(name)
        try:
            validate_level(data, name)
        except LevelError as err:
            assert name in str(err), f"error should name the file: {err}"
            continue
        raise AssertionError(f"{name} should have raised LevelError")


def test_real_levels_pass():
    for path in sorted(glob.glob(os.path.join(ROOT, "levels", "*.json"))):
        with open(path) as f:
            validate_level(json.load(f), path)  # must not raise


if __name__ == "__main__":
    test_parse_pos_ok()
    test_parse_pos_rejects_bad()
    test_malformed_fixtures_raise()
    test_real_levels_pass()
    print("level validation checks passed")
