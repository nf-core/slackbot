"""Tests for the DynamoDB sites and organisers data-access layer."""

from __future__ import annotations

import pytest

HACK_ID = "hack-sites"


# ---------------------------------------------------------------------------
# add_site
# ---------------------------------------------------------------------------


async def test_add_site_success(ddb_table) -> None:
    from nf_core_bot.db.sites import add_site, get_site

    await add_site(HACK_ID, "stockholm", "Stockholm", "Stockholm", "SE")

    item = await get_site(HACK_ID, "stockholm")
    assert item is not None
    assert item["site_id"] == "stockholm"
    assert item["name"] == "Stockholm"
    assert item["city"] == "Stockholm"
    assert item["country"] == "SE"
    assert "created_at" in item


async def test_add_site_duplicate_raises(ddb_table) -> None:
    from nf_core_bot.db.sites import add_site

    await add_site(HACK_ID, "london", "London", "London", "GB")

    with pytest.raises(ValueError, match="already exists"):
        await add_site(HACK_ID, "london", "London 2", "London", "GB")


# ---------------------------------------------------------------------------
# remove_site
# ---------------------------------------------------------------------------


async def test_remove_site_success(ddb_table) -> None:
    from nf_core_bot.db.sites import add_site, get_site, remove_site

    await add_site(HACK_ID, "paris", "Paris", "Paris", "FR")
    await remove_site(HACK_ID, "paris")

    result = await get_site(HACK_ID, "paris")
    assert result is None


async def test_remove_site_missing_raises(ddb_table) -> None:
    from nf_core_bot.db.sites import remove_site

    with pytest.raises(ValueError, match="not found"):
        await remove_site(HACK_ID, "nonexistent")


# ---------------------------------------------------------------------------
# get_site
# ---------------------------------------------------------------------------


async def test_get_site_returns_data(ddb_table) -> None:
    from nf_core_bot.db.sites import add_site, get_site

    await add_site(HACK_ID, "berlin", "Berlin", "Berlin", "DE")
    result = await get_site(HACK_ID, "berlin")
    assert result is not None
    assert result["name"] == "Berlin"


async def test_get_site_returns_none_for_missing(ddb_table) -> None:
    from nf_core_bot.db.sites import get_site

    result = await get_site(HACK_ID, "does-not-exist")
    assert result is None


# ---------------------------------------------------------------------------
# list_sites
# ---------------------------------------------------------------------------


async def test_list_sites_returns_only_site_records(ddb_table) -> None:
    """list_sites must return site records but NOT organiser records."""
    from nf_core_bot.db.sites import add_organiser, add_site, list_sites

    await add_site(HACK_ID, "s1", "Site One", "City1", "US")
    await add_site(HACK_ID, "s2", "Site Two", "City2", "GB")
    # Add an organiser — this creates an SK like SITE#s1#ORG#u1
    await add_organiser(HACK_ID, "s1", "u1")

    sites = await list_sites(HACK_ID)
    site_ids = {s["site_id"] for s in sites}
    assert site_ids == {"s1", "s2"}
    # Verify no organiser records leaked in.
    for s in sites:
        assert "#ORG#" not in s["SK"]


async def test_list_sites_empty(ddb_table) -> None:
    from nf_core_bot.db.sites import list_sites

    sites = await list_sites(HACK_ID)
    assert sites == []


# ---------------------------------------------------------------------------
# add_organiser / remove_organiser / list_organisers
# ---------------------------------------------------------------------------


async def test_add_organiser_success(ddb_table) -> None:
    from nf_core_bot.db.sites import add_organiser, add_site, list_organisers

    await add_site(HACK_ID, "org-site", "Org Site", "City", "US")
    await add_organiser(HACK_ID, "org-site", "user-abc")

    orgs = await list_organisers(HACK_ID, "org-site")
    assert len(orgs) == 1
    assert orgs[0]["user_id"] == "user-abc"
    assert orgs[0]["site_id"] == "org-site"
    assert "created_at" in orgs[0]


async def test_add_organiser_duplicate_raises(ddb_table) -> None:
    from nf_core_bot.db.sites import add_organiser, add_site

    await add_site(HACK_ID, "dup-site", "Dup Site", "City", "US")
    await add_organiser(HACK_ID, "dup-site", "user-x")

    with pytest.raises(ValueError, match="already an organiser"):
        await add_organiser(HACK_ID, "dup-site", "user-x")


async def test_remove_organiser_success(ddb_table) -> None:
    from nf_core_bot.db.sites import (
        add_organiser,
        add_site,
        list_organisers,
        remove_organiser,
    )

    await add_site(HACK_ID, "rm-site", "RM Site", "City", "US")
    await add_organiser(HACK_ID, "rm-site", "user-y")
    await remove_organiser(HACK_ID, "rm-site", "user-y")

    orgs = await list_organisers(HACK_ID, "rm-site")
    assert orgs == []


async def test_remove_organiser_missing_raises(ddb_table) -> None:
    from nf_core_bot.db.sites import remove_organiser

    with pytest.raises(ValueError, match="not found"):
        await remove_organiser(HACK_ID, "any-site", "ghost-user")


async def test_list_organisers_multiple(ddb_table) -> None:
    from nf_core_bot.db.sites import add_organiser, add_site, list_organisers

    await add_site(HACK_ID, "multi-org", "Multi Org Site", "City", "US")
    await add_organiser(HACK_ID, "multi-org", "u1")
    await add_organiser(HACK_ID, "multi-org", "u2")
    await add_organiser(HACK_ID, "multi-org", "u3")

    orgs = await list_organisers(HACK_ID, "multi-org")
    user_ids = {o["user_id"] for o in orgs}
    assert user_ids == {"u1", "u2", "u3"}


async def test_list_organisers_empty(ddb_table) -> None:
    from nf_core_bot.db.sites import add_site, list_organisers

    await add_site(HACK_ID, "empty-org", "Empty Org", "City", "US")
    orgs = await list_organisers(HACK_ID, "empty-org")
    assert orgs == []
