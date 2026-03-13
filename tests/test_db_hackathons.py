"""Tests for the DynamoDB hackathons data-access layer."""

from __future__ import annotations

import pytest
from moto import mock_aws


@pytest.fixture
async def ddb_table():
    """Create a mocked DynamoDB table for testing."""
    with mock_aws():
        from nf_core_bot.db import client as db_client

        # Reset singleton so moto intercepts the real AWS calls.
        db_client._table = None
        db_client.init(table_name="test-table", endpoint_url=None, region="us-east-1")
        yield db_client.get_table()
        db_client._table = None


# ---------------------------------------------------------------------------
# create_hackathon
# ---------------------------------------------------------------------------


async def test_create_hackathon_success(ddb_table) -> None:
    from nf_core_bot.db.hackathons import create_hackathon, get_hackathon

    await create_hackathon("hack-1", "March 2026", "2026-march.yaml")

    item = await get_hackathon("hack-1")
    assert item is not None
    assert item["hackathon_id"] == "hack-1"
    assert item["title"] == "March 2026"
    assert item["form_yaml"] == "2026-march.yaml"
    assert item["status"] == "draft"
    assert "created_at" in item
    assert "updated_at" in item


async def test_create_hackathon_duplicate_raises(ddb_table) -> None:
    from nf_core_bot.db.hackathons import create_hackathon

    await create_hackathon("hack-dup", "First", "first.yaml")

    with pytest.raises(ValueError, match="already exists"):
        await create_hackathon("hack-dup", "Second", "second.yaml")


# ---------------------------------------------------------------------------
# get_hackathon
# ---------------------------------------------------------------------------


async def test_get_hackathon_returns_data(ddb_table) -> None:
    from nf_core_bot.db.hackathons import create_hackathon, get_hackathon

    await create_hackathon("hack-get", "Get Test", "get.yaml")
    result = await get_hackathon("hack-get")
    assert result is not None
    assert result["title"] == "Get Test"


async def test_get_hackathon_returns_none_for_missing(ddb_table) -> None:
    from nf_core_bot.db.hackathons import get_hackathon

    result = await get_hackathon("does-not-exist")
    assert result is None


# ---------------------------------------------------------------------------
# list_hackathons
# ---------------------------------------------------------------------------


async def test_list_hackathons_returns_all(ddb_table) -> None:
    from nf_core_bot.db.hackathons import create_hackathon, list_hackathons

    await create_hackathon("h1", "Hackathon 1", "h1.yaml")
    await create_hackathon("h2", "Hackathon 2", "h2.yaml")
    await create_hackathon("h3", "Hackathon 3", "h3.yaml")

    result = await list_hackathons()
    ids = {item["hackathon_id"] for item in result}
    assert ids == {"h1", "h2", "h3"}


async def test_list_hackathons_empty(ddb_table) -> None:
    from nf_core_bot.db.hackathons import list_hackathons

    result = await list_hackathons()
    assert result == []


# ---------------------------------------------------------------------------
# get_active_hackathon
# ---------------------------------------------------------------------------


async def test_get_active_hackathon_returns_open(ddb_table) -> None:
    from nf_core_bot.db.hackathons import (
        create_hackathon,
        get_active_hackathon,
        update_hackathon_status,
    )

    await create_hackathon("draft-h", "Draft", "d.yaml")
    await create_hackathon("open-h", "Open", "o.yaml")
    await update_hackathon_status("open-h", "open")

    result = await get_active_hackathon()
    assert result is not None
    assert result["hackathon_id"] == "open-h"
    assert result["status"] == "open"


async def test_get_active_hackathon_returns_none_when_none_open(ddb_table) -> None:
    from nf_core_bot.db.hackathons import create_hackathon, get_active_hackathon

    await create_hackathon("draft-only", "Draft", "d.yaml")

    result = await get_active_hackathon()
    assert result is None


# ---------------------------------------------------------------------------
# update_hackathon_status
# ---------------------------------------------------------------------------


async def test_update_hackathon_status_success(ddb_table) -> None:
    from nf_core_bot.db.hackathons import (
        create_hackathon,
        get_hackathon,
        update_hackathon_status,
    )

    await create_hackathon("status-h", "Status Test", "s.yaml")
    await update_hackathon_status("status-h", "open")

    item = await get_hackathon("status-h")
    assert item is not None
    assert item["status"] == "open"


async def test_update_hackathon_status_missing_raises(ddb_table) -> None:
    from nf_core_bot.db.hackathons import update_hackathon_status

    with pytest.raises(ValueError, match="not found"):
        await update_hackathon_status("ghost", "open")


async def test_update_hackathon_status_invalid_status_raises(ddb_table) -> None:
    from nf_core_bot.db.hackathons import create_hackathon, update_hackathon_status

    await create_hackathon("inv-h", "Invalid", "i.yaml")

    with pytest.raises(ValueError, match="Invalid status"):
        await update_hackathon_status("inv-h", "bogus")
