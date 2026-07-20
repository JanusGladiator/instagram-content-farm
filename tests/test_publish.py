from datetime import date
import pytest
from pipeline import publish, queue_store, graph_api


def _seed_approved_item(queue_path, item_type, scheduled_date="2026-07-20"):
    item = queue_store.new_item(
        type_=item_type, source="original", scheduled_date=scheduled_date,
        asset_url="https://example.com/a.jpg", caption="cap", hashtags=["h"],
    )
    item["status"] = "approved"
    queue_store.save_queue(queue_path, [item])
    return item


def test_publish_today_raises_publish_skipped_when_no_approved_item(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue_store.save_queue(queue_path, [])

    with pytest.raises(publish.PublishSkipped):
        publish.publish_today(
            item_type="post", queue_path=queue_path,
            ig_business_id="ig1", access_token="token",
            today=date(2026, 7, 20),
        )


def test_publish_today_dry_run_does_not_call_graph_api(tmp_path, monkeypatch, capsys):
    queue_path = tmp_path / "queue.json"
    _seed_approved_item(queue_path, "post")

    called = []
    monkeypatch.setattr(graph_api, "create_image_container", lambda *a, **k: called.append("create") or "cid")

    publish.publish_today(
        item_type="post", queue_path=queue_path,
        ig_business_id="ig1", access_token="token",
        today=date(2026, 7, 20), dry_run=True,
    )

    assert called == []
    assert "dry-run" in capsys.readouterr().out


def test_publish_today_posts_image_and_updates_status(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    item = _seed_approved_item(queue_path, "post")

    monkeypatch.setattr(graph_api, "create_image_container", lambda *a, **k: "cid")
    monkeypatch.setattr(graph_api, "publish_container", lambda *a, **k: "mid")

    result = publish.publish_today(
        item_type="post", queue_path=queue_path,
        ig_business_id="ig1", access_token="token", today=date(2026, 7, 20),
    )

    assert result["id"] == item["id"]
    reloaded = queue_store.load_queue(queue_path)
    assert reloaded[0]["status"] == "posted"
    assert reloaded[0]["posted_at"] is not None


def test_publish_today_posts_reel_and_waits_for_ready(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    _seed_approved_item(queue_path, "reel")

    waited = []
    monkeypatch.setattr(graph_api, "create_reel_container", lambda *a, **k: "cid")
    monkeypatch.setattr(graph_api, "wait_for_container_ready", lambda *a, **k: waited.append("waited"))
    monkeypatch.setattr(graph_api, "publish_container", lambda *a, **k: "mid")

    publish.publish_today(
        item_type="reel", queue_path=queue_path,
        ig_business_id="ig1", access_token="token", today=date(2026, 7, 20),
    )

    assert waited == ["waited"]


def test_publish_today_propagates_graph_error_and_leaves_status_approved(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    _seed_approved_item(queue_path, "post")

    def raise_error(*a, **k):
        raise graph_api.GraphAPIError("token expired")

    monkeypatch.setattr(graph_api, "create_image_container", raise_error)

    with pytest.raises(graph_api.GraphAPIError):
        publish.publish_today(
            item_type="post", queue_path=queue_path,
            ig_business_id="ig1", access_token="token", today=date(2026, 7, 20),
        )

    reloaded = queue_store.load_queue(queue_path)
    assert reloaded[0]["status"] == "approved"
