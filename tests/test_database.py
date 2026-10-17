import pytest

from giveaway_bot.db import Database


@pytest.mark.asyncio
async def test_database_survives_reopen(tmp_path):
    path = tmp_path / "giveaways.sqlite3"
    db = Database(str(path))
    await db.initialize()
    giveaway_id = await db.create_giveaway(
        guild_id=1,
        channel_id=2,
        host_id=3,
        prize="Nitro",
        description="Test",
        winner_count=1,
        ends_at=200,
        created_at=100,
    )
    assert await db.toggle_entry(giveaway_id, 42, 110) == (True, 1)
    reopened = Database(str(path))
    await reopened.initialize()
    giveaway = await reopened.get(giveaway_id)
    assert giveaway is not None
    assert giveaway.prize == "Nitro"
    assert await reopened.entries(giveaway_id) == [42]


@pytest.mark.asyncio
async def test_toggle_entry_and_finish_are_idempotent(tmp_path):
    db = Database(str(tmp_path / "db.sqlite3"))
    await db.initialize()
    gid = await db.create_giveaway(
        guild_id=1, channel_id=2, host_id=3, prize="Prize", description="",
        winner_count=1, ends_at=200, created_at=100,
    )
    assert await db.toggle_entry(gid, 10, 101) == (True, 1)
    assert await db.toggle_entry(gid, 10, 102) == (False, 0)
    assert await db.toggle_entry(gid, 10, 103) == (True, 1)
    assert await db.finish(gid, [10], 200) is True
    assert await db.finish(gid, [10], 201) is False
    with pytest.raises(ValueError):
        await db.toggle_entry(gid, 11, 202)


@pytest.mark.asyncio
async def test_toggle_entry_rejects_expired_active_giveaway(tmp_path):
    db = Database(str(tmp_path / "giveaways.sqlite3"))
    await db.initialize()
    gid = await db.create_giveaway(
        guild_id=1, channel_id=2, host_id=3, prize="Prize", description="",
        winner_count=1, ends_at=110, created_at=100,
    )

    with pytest.raises(ValueError):
        await db.toggle_entry(gid, 42, 110)

    assert await db.entry_count(gid) == 0


@pytest.mark.asyncio
async def test_recovers_active_giveaway_message_mapping(tmp_path):
    db = Database(str(tmp_path / "giveaways.sqlite3"))
    await db.initialize()
    gid = await db.create_giveaway(
        guild_id=1, channel_id=2, host_id=3, prize="Big Prize", description="",
        winner_count=1, ends_at=200, created_at=100,
    )
    await db.toggle_entry(gid, 42, 110)

    recovered = await db.find_active_for_message_recovery(1, 2, "Big Prize", 120)
    assert recovered is not None and recovered.id == gid
    await db.set_message_id(gid, 999)
    assert (await db.get_by_message(999)).id == gid
    assert await db.entries(gid) == [42]

