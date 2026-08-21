"""Smoke tests — import pipeline + verify key parse helpers."""
import importlib
import os
import sys

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_pipeline_imports():
    mod = importlib.import_module("parkrun_pipeline")
    assert hasattr(mod, "parse_time_raw")
    assert hasattr(mod, "clean")
    assert hasattr(mod, "parse_date")

def test_parse_time_raw():
    from parkrun_pipeline import parse_time_raw
    assert parse_time_raw("12:34:56") == 45296
    assert parse_time_raw("1:02:03") == 3723

def test_clean():
    from parkrun_pipeline import clean
    assert clean("  hello world ") == "hello world"
    assert clean("") == ""
    assert clean(None) == ""
