"""Unit tests for Indian currency normalization and formatting."""

import pytest
from pricewatch.validation.normalizer import format_paise_to_inr, parse_inr_to_paise


@pytest.mark.parametrize(
    "raw_input, expected_paise",
    [
        ("₹ 1,24,999.50", 12499950),
        ("₹1,499.00", 149900),
        ("Rs. 499", 49900),
        ("rs 499", 49900),
        ("1,499", 149900),
        ("1499", 149900),
        (1499, 149900),
        (1499.5, 149950),
        ("₹ 99.99", 9999),
        ("INR 2,500", 250000),
        ("  ₹  3,100  ", 310000),
        ("", None),
        ("   ", None),
        ("invalid", None),
        (None, None),
    ],
)
def test_parse_inr_to_paise(raw_input, expected_paise):
    assert parse_inr_to_paise(raw_input) == expected_paise


@pytest.mark.parametrize(
    "paise, include_symbol, expected_str",
    [
        (12499950, True, "₹1,24,999.50"),
        (149900, True, "₹1,499"),
        (49900, True, "₹499"),
        (49950, True, "₹499.50"),
        (100, True, "₹1"),
        (99, True, "₹0.99"),
        (149900, False, "1,499"),
        (None, True, "N/A"),
    ],
)
def test_format_paise_to_inr(paise, include_symbol, expected_str):
    assert format_paise_to_inr(paise, include_symbol=include_symbol) == expected_str
