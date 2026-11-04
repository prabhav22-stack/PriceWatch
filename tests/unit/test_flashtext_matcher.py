"""Unit tests for FlashText-based supplement entity extraction."""

import pytest
from pricewatch.services.flashtext_matcher import flashtext_matcher


def test_flashtext_unflavoured_detection():
    # Various raw/unflavoured forms
    assert flashtext_matcher.is_unflavoured("AS-IT-IS Whey Concentrate 80% Raw Unflavoured") is True
    assert flashtext_matcher.is_unflavoured("Amul Raw Whey Protein Concentrate 80%") is True
    assert flashtext_matcher.is_unflavoured("Nakpro Platinum Whey Isolate Plain") is True
    assert flashtext_matcher.is_unflavoured("Nutrabay 100% Unflavoured WPC") is True

    # Flavoured wheys should be False
    assert flashtext_matcher.is_unflavoured("MuscleBlaze Biozyme Double Rich Chocolate") is False
    assert flashtext_matcher.is_unflavoured("Nakpro Gold Malai Kulfi") is False


def test_flashtext_exclusion_checks():
    # Nakpro Impact must be excluded
    is_ok, reason, pct = flashtext_matcher.check_quality_whey("Nakpro Impact Whey Protein Chocolate")
    assert is_ok is False
    assert "Nakpro Impact" in reason
    assert pct <= 50.0

    # Mass Gainers must be excluded
    is_ok, reason, pct = flashtext_matcher.check_quality_whey("Serious Mass Gainer 3kg")
    assert is_ok is False
    assert "Gainer" in reason


def test_flashtext_quality_whey_pass():
    # AS-IT-IS 80% Raw WPC passes with >=65% protein
    is_ok, reason, pct = flashtext_matcher.check_quality_whey("AS-IT-IS Whey Concentrate 80% Raw Unflavoured")
    assert is_ok is True
    assert pct >= 80.0

    # Platinum Isolate passes
    is_ok, reason, pct = flashtext_matcher.check_quality_whey("Nakpro Platinum Isolate Unflavoured")
    assert is_ok is True
    assert pct >= 85.0
