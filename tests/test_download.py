import pytest

from drive_reliability.download import parse_quarter, quarter_range, quarter_url


def test_quarter_url():
    assert quarter_url(2024, 1).endswith("/data_Q1_2024.zip")


@pytest.mark.parametrize("year, quarter", [(2024, 0), (2024, 5), (2015, 1)])
def test_quarter_url_rejects_invalid(year, quarter):
    with pytest.raises(ValueError):
        quarter_url(year, quarter)


@pytest.mark.parametrize("text", ["2024Q1", "2024-q1", " 2024Q1 "])
def test_parse_quarter(text):
    assert parse_quarter(text) == (2024, 1)


def test_quarter_range_crosses_year():
    assert quarter_range("2024Q3", "2025Q2") == [(2024, 3), (2024, 4), (2025, 1), (2025, 2)]


def test_quarter_range_rejects_reversed():
    with pytest.raises(ValueError):
        quarter_range("2025Q1", "2024Q4")
