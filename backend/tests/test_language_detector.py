"""Tests for language detection — all 7 languages + code-switching."""

import pytest
from src.language.detector import detect_language, is_code_switched


@pytest.mark.parametrize("text,expected", [
    ("How do I apply for bail?", "en"),
    ("धारा 302 में bail कैसे मिलती है", "hi+en"),   # Hinglish
    ("खेती में कौन सी फसल लगाएं", "hi"),
    ("என்ன செய்வது", "ta"),
    ("ਕਣਕ ਦਾ ਭਾਅ ਕੀ ਹੈ", "pa"),
    ("నేను ఏమి చేయాలి", "te"),
    ("मराठी शेतकरी", "mr"),
    ("ગુજરાતી ભાષા", "gu"),
])
def test_detect_language(text, expected):
    result = detect_language(text)
    assert result == expected, f"Expected {expected}, got {result} for: {text!r}"


def test_hinglish_is_code_switched():
    assert is_code_switched("bail kaise milti hai yaar")


def test_pure_hindi_not_code_switched():
    # Pure Devanagari should not be flagged as code-switched
    result = is_code_switched("खेती में सिंचाई कैसे करें")
    assert not result


def test_empty_text_returns_en():
    assert detect_language("") == "en"
    assert detect_language("   ") == "en"
