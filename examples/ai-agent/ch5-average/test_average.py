import pytest
from average import average


def test_integer_values():
    assert average([2, 4]) == 3


def test_decimal_values():
    assert average([1.5, 2.5]) == 2


def test_empty_input_has_explicit_error():
    with pytest.raises(ValueError, match="values must not be empty"):
        average([])
