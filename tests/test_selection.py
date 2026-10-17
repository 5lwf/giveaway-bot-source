from giveaway_bot.selection import select_winners


def test_random_selection_is_unique_and_from_entries():
    result = select_winners([1, 2, 2, 3], 3)
    assert len(result) == 3
    assert len(set(result)) == 3
    assert set(result) <= {1, 2, 3}


def test_manual_winner_is_first_and_fills_remaining_randomly():
    result = select_winners([1, 2, 3], 2, manual_winner_id=99)
    assert result[0] == 99
    assert len(result) == 2
    assert result[1] in {1, 2, 3}


def test_manual_winner_is_not_duplicated():
    result = select_winners([7, 8], 2, manual_winner_id=7)
    assert result.count(7) == 1
    assert result == [7, 8]


def test_multiple_manual_winners_are_kept_in_order():
    result = select_winners([1, 2, 3], 3, manual_winner_id=[90, 91])
    assert result[:2] == [90, 91]
    assert result[2] in {1, 2, 3}

