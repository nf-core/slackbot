"""Tests for the DynamoDB registrations data-access layer."""

from __future__ import annotations

import pytest

HACK_ID = "hack-reg"
FORM_DATA = {"first_name": "Ada", "last_name": "Lovelace"}
PROFILE = {"email": "ada@example.com", "slack_display_name": "ada", "github_username": "ada"}


# ---------------------------------------------------------------------------
# create_registration
# ---------------------------------------------------------------------------


async def test_create_registration_without_site(ddb_table) -> None:
    from nf_core_bot.db.registrations import create_registration, get_registration

    await create_registration(HACK_ID, "u1", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)

    item = await get_registration(HACK_ID, "u1")
    assert item is not None
    assert item["user_id"] == "u1"
    assert item["site_id"] is None
    assert item["form_data"] == FORM_DATA
    assert item["profile_data"] == PROFILE
    assert "registered_at" in item
    assert "updated_at" in item
    # No GSI1 keys when site is None.
    assert "GSI1PK" not in item
    assert "GSI1SK" not in item


async def test_create_registration_with_site(ddb_table) -> None:
    from nf_core_bot.db.registrations import create_registration, get_registration

    await create_registration(HACK_ID, "u2", site_id="london", form_data=FORM_DATA, profile_data=PROFILE)

    item = await get_registration(HACK_ID, "u2")
    assert item is not None
    assert item["site_id"] == "london"
    assert item["GSI1PK"] == f"HACKATHON#{HACK_ID}#SITE#london"
    assert item["GSI1SK"] == "REG#u2"


async def test_create_registration_duplicate_raises(ddb_table) -> None:
    from nf_core_bot.db.registrations import create_registration

    await create_registration(HACK_ID, "u-dup", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)

    with pytest.raises(ValueError, match="already registered"):
        await create_registration(HACK_ID, "u-dup", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)


# ---------------------------------------------------------------------------
# get_registration
# ---------------------------------------------------------------------------


async def test_get_registration_success(ddb_table) -> None:
    from nf_core_bot.db.registrations import create_registration, get_registration

    await create_registration(HACK_ID, "u-get", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)
    result = await get_registration(HACK_ID, "u-get")
    assert result is not None
    assert result["user_id"] == "u-get"


async def test_get_registration_returns_none(ddb_table) -> None:
    from nf_core_bot.db.registrations import get_registration

    result = await get_registration(HACK_ID, "no-one")
    assert result is None


# ---------------------------------------------------------------------------
# update_registration
# ---------------------------------------------------------------------------


async def test_update_registration_success(ddb_table) -> None:
    from nf_core_bot.db.registrations import (
        create_registration,
        get_registration,
        update_registration,
    )

    await create_registration(HACK_ID, "u-upd", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)

    new_data = {"first_name": "Ada", "last_name": "Updated"}
    await update_registration(HACK_ID, "u-upd", site_id="berlin", form_data=new_data)

    item = await get_registration(HACK_ID, "u-upd")
    assert item is not None
    assert item["form_data"] == new_data
    assert item["site_id"] == "berlin"
    assert item["GSI1PK"] == f"HACKATHON#{HACK_ID}#SITE#berlin"


async def test_update_registration_missing_raises(ddb_table) -> None:
    from nf_core_bot.db.registrations import update_registration

    with pytest.raises(ValueError, match="not found"):
        await update_registration(HACK_ID, "ghost", site_id=None, form_data={})


# ---------------------------------------------------------------------------
# delete_registration
# ---------------------------------------------------------------------------


async def test_delete_registration_success(ddb_table) -> None:
    from nf_core_bot.db.registrations import (
        create_registration,
        delete_registration,
        get_registration,
    )

    await create_registration(HACK_ID, "u-del", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)
    await delete_registration(HACK_ID, "u-del")

    result = await get_registration(HACK_ID, "u-del")
    assert result is None


async def test_delete_registration_missing_raises(ddb_table) -> None:
    from nf_core_bot.db.registrations import delete_registration

    with pytest.raises(ValueError, match="not found"):
        await delete_registration(HACK_ID, "ghost")


# ---------------------------------------------------------------------------
# list_registrations
# ---------------------------------------------------------------------------


async def test_list_registrations(ddb_table) -> None:
    from nf_core_bot.db.registrations import create_registration, list_registrations

    await create_registration(HACK_ID, "u-a", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "u-b", site_id="paris", form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "u-c", site_id="london", form_data=FORM_DATA, profile_data=PROFILE)

    regs = await list_registrations(HACK_ID)
    user_ids = {r["user_id"] for r in regs}
    assert user_ids == {"u-a", "u-b", "u-c"}


async def test_list_registrations_empty(ddb_table) -> None:
    from nf_core_bot.db.registrations import list_registrations

    regs = await list_registrations(HACK_ID)
    assert regs == []


# ---------------------------------------------------------------------------
# list_registrations_by_site (GSI1)
# ---------------------------------------------------------------------------


async def test_list_registrations_by_site(ddb_table) -> None:
    from nf_core_bot.db.registrations import (
        create_registration,
        list_registrations_by_site,
    )

    await create_registration(HACK_ID, "site-u1", site_id="london", form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "site-u2", site_id="london", form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "site-u3", site_id="paris", form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "online-u", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)

    london_regs = await list_registrations_by_site(HACK_ID, "london")
    london_ids = {r["user_id"] for r in london_regs}
    assert london_ids == {"site-u1", "site-u2"}

    paris_regs = await list_registrations_by_site(HACK_ID, "paris")
    assert len(paris_regs) == 1
    assert paris_regs[0]["user_id"] == "site-u3"


async def test_list_registrations_by_site_empty(ddb_table) -> None:
    from nf_core_bot.db.registrations import list_registrations_by_site

    result = await list_registrations_by_site(HACK_ID, "empty-site")
    assert result == []


# ---------------------------------------------------------------------------
# count_registrations / count_registrations_by_site
# ---------------------------------------------------------------------------


async def test_count_registrations(ddb_table) -> None:
    from nf_core_bot.db.registrations import count_registrations, create_registration

    assert await count_registrations(HACK_ID) == 0

    await create_registration(HACK_ID, "cnt-1", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "cnt-2", site_id=None, form_data=FORM_DATA, profile_data=PROFILE)

    assert await count_registrations(HACK_ID) == 2


async def test_count_registrations_by_site(ddb_table) -> None:
    from nf_core_bot.db.registrations import (
        count_registrations_by_site,
        create_registration,
    )

    await create_registration(HACK_ID, "cs-1", site_id="berlin", form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "cs-2", site_id="berlin", form_data=FORM_DATA, profile_data=PROFILE)
    await create_registration(HACK_ID, "cs-3", site_id="paris", form_data=FORM_DATA, profile_data=PROFILE)

    assert await count_registrations_by_site(HACK_ID, "berlin") == 2
    assert await count_registrations_by_site(HACK_ID, "paris") == 1
    assert await count_registrations_by_site(HACK_ID, "nowhere") == 0
