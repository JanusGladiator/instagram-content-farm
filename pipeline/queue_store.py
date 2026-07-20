import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

VALID_TYPES = {"post", "reel"}
VALID_SOURCES = {"original", "template", "repost"}
VALID_STATUSES = {"pending", "approved", "rejected", "posted", "failed"}
REQUIRED_FIELDS = {
    "id", "type", "source", "scheduled_date", "asset_url", "caption",
    "hashtags", "status", "created_at", "posted_at",
}


class QueueValidationError(ValueError):
    pass


def validate_item(item: dict) -> None:
    missing = REQUIRED_FIELDS - item.keys()
    if missing:
        raise QueueValidationError(f"missing fields: {sorted(missing)}")
    if item["type"] not in VALID_TYPES:
        raise QueueValidationError(f"invalid type: {item['type']!r}")
    if item["source"] not in VALID_SOURCES:
        raise QueueValidationError(f"invalid source: {item['source']!r}")
    if item["status"] not in VALID_STATUSES:
        raise QueueValidationError(f"invalid status: {item['status']!r}")


def load_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    for item in items:
        validate_item(item)
    return items


def save_queue(path: Path, items: list[dict]) -> None:
    for item in items:
        validate_item(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def new_item(*, type_: str, source: str, scheduled_date: str, asset_url: str,
             caption: str, hashtags: list[str]) -> dict:
    item = {
        "id": str(uuid.uuid4()),
        "type": type_,
        "source": source,
        "scheduled_date": scheduled_date,
        "asset_url": asset_url,
        "caption": caption,
        "hashtags": hashtags,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "posted_at": None,
    }
    validate_item(item)
    return item


def append_item(path: Path, item: dict) -> None:
    items = load_queue(path)
    items.append(item)
    save_queue(path, items)


def get_item_for_date(items: list[dict], scheduled_date: str,
                       type_: str, status: str | None = None) -> dict | None:
    for item in items:
        if item["scheduled_date"] == scheduled_date and item["type"] == type_:
            if status is None or item["status"] == status:
                return item
    return None


def update_status(path: Path, item_id: str, new_status: str,
                   posted_at: str | None = None) -> None:
    if new_status not in VALID_STATUSES:
        raise QueueValidationError(f"invalid status: {new_status!r}")
    items = load_queue(path)
    for item in items:
        if item["id"] == item_id:
            item["status"] = new_status
            if posted_at is not None:
                item["posted_at"] = posted_at
            save_queue(path, items)
            return
    raise KeyError(f"no queue item with id {item_id}")
