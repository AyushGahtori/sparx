import pytest

from app.utils.phone import normalize_phone_number


def test_normalize_phone_number_keeps_valid_e164():
    assert normalize_phone_number("+919999999999") == "+919999999999"


def test_normalize_phone_number_converts_common_spacing():
    assert normalize_phone_number("+91 99999 99999") == "+919999999999"


def test_normalize_phone_number_rejects_invalid_values():
    with pytest.raises(ValueError):
        normalize_phone_number("1234")
