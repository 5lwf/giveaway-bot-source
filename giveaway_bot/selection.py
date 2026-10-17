from __future__ import annotations

import secrets


def select_winners(
    entrants: list[int], count: int, manual_winner_id: int | list[int] | None = None
) -> list[int]:
    unique = list(dict.fromkeys(entrants))
    manual = manual_winner_id if isinstance(manual_winner_id, list) else ([manual_winner_id] if manual_winner_id is not None else [])
    winners = list(dict.fromkeys(manual))[:count]
    unique = [user_id for user_id in unique if user_id not in winners]
    remaining = min(max(0, count - len(winners)), len(unique))
    if remaining:
        winners.extend(secrets.SystemRandom().sample(unique, remaining))
    return winners

