import json
import pytest
from pipeline import queue_store


def test_new_item_has_pending_status_and_uuid_id():
    item = queue_store.new_item(
        type_="post", source="original", scheduled_date="2026-07-20",
        asset_url="https://example.com/a.jpg",
        caption="caption", hashtags=["a", "b"],
    )
    assert item["status"] == "pending"
    assert item["type"] == "post"
    assert item["source"] == "original"
    assert item["scheduled_date"] == "2026-07-20"
    assert item["posted_at"] is None
    assert item["id"]


def test_validate_item_rejects_missing_field():
    item = queue_store.new_item(
        type_="post", source="original", scheduled_date="2026-07-20",
        asset_url="u", caption="c", hashtags=[],
    )
    del item["caption"]
    with pytest.raises(queue_store.QueueValidationError):
        queue_store.validate_item(item)


def test_validate_item_rejects_bad_type():
    item = queue_store.new_item(
        type_="post", source="original", scheduled_date="2026-07-20",
        asset_url="u", caption="c", hashtags=[],
    )
    item["type"] = "story"
    with pytest.raises(queue_store.QueueValidationError):
        queue_store.validate_item(item)


def test_validate_item_rejects_bad_source():
    item = queue_store.new_item(
        type_="post", source="original", scheduled_date="2026-07-20",
        asset_url="u", caption="c", hashtags=[],
    )
    item["source"] = "stolen"
    with pytest.raises(queue_store.QueueValidationError):
        queue_store.validate_item(item)


def test_load_queue_returns_empty_list_when_file_missing(tmp_path):
    result = queue_store.load_queue(tmp_path / "queue.json")
    assert result == []


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "queue.json"
    item = queue_store.new_item(
        type_="reel", source="repost", scheduled_date="2026-07-21",
        asset_url="u", caption="c", hashtags=["x"],
    )
    queue_store.append_item(path, item)

    loaded = queue_store.load_queue(path)
    assert len(loaded) == 1
    assert loaded[0]["id"] == item["id"]
    assert loaded[0]["source"] == "repost"


def test_get_item_for_date_filters_by_type_date_and_status():
    items = [
        queue_store.new_item(type_="post", source="original", scheduled_date="2026-07-20",
                              asset_url="u1", caption="c", hashtags=[]),
        queue_store.new_item(type_="reel", source="template", scheduled_date="2026-07-20",
                              asset_url="u2", caption="c", hashtags=[]),
    ]
    items[0]["status"] = "approved"

    found = queue_store.get_item_for_date(items, "2026-07-20", "post", status="approved")
    assert found["asset_url"] == "u1"

    not_found = queue_store.get_item_for_date(items, "2026-07-20", "reel", status="approved")
    assert not_found is None


def test_update_status_updates_existing_item_and_persists(tmp_path):
    path = tmp_path / "queue.json"
    item = queue_store.new_item(
        type_="post", source="original", scheduled_date="2026-07-20",
        asset_url="u", caption="c", hashtags=[],
    )
    queue_store.append_item(path, item)

    queue_store.update_status(path, item["id"], "posted", posted_at="2026-07-20T12:00:00+00:00")

    reloaded = queue_store.load_queue(path)
    assert reloaded[0]["status"] == "posted"
    assert reloaded[0]["posted_at"] == "2026-07-20T12:00:00+00:00"


def test_update_status_raises_for_unknown_id(tmp_path):
    path = tmp_path / "queue.json"
    queue_store.save_queue(path, [])
    with pytest.raises(KeyError):
        queue_store.update_status(path, "does-not-exist", "posted")
