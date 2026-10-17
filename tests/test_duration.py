import pytest

from giveaway_bot.duration import parse_duration


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("10m", 600), ("2h 30m", 9000), ("1 day", 86400), ("1week 2days", 777600)],
)
def test_parse_duration(value, seconds):
    assert parse_duration(value) == seconds


@pytest.mark.parametrize("value", ["", "soon", "9s", "1h nonsense", "366d"])
def test_invalid_duration(value):
    with pytest.raises(ValueError):
        parse_duration(value)

