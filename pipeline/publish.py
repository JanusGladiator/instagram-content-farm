import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline import graph_api, queue_store


class PublishSkipped(Exception):
    pass


def publish_today(*, item_type: str, queue_path: Path, ig_business_id: str,
                   access_token: str, today: date | None = None,
                   dry_run: bool = False) -> dict:
    today = today or date.today()
    items = queue_store.load_queue(queue_path)
    item = queue_store.get_item_for_date(items, today.isoformat(), item_type, status="approved")

    if item is None:
        raise PublishSkipped(f"no approved {item_type} scheduled for {today.isoformat()}")

    if dry_run:
        print(f"[dry-run] would publish {item_type} id={item['id']} "
              f"asset={item['asset_url']} caption={item['caption']!r}")
        return item

    if item_type == "post":
        creation_id = graph_api.create_image_container(
            ig_business_id, item["asset_url"], item["caption"], access_token,
        )
    else:
        creation_id = graph_api.create_reel_container(
            ig_business_id, item["asset_url"], item["caption"], access_token,
        )
        graph_api.wait_for_container_ready(creation_id, access_token)

    graph_api.publish_container(ig_business_id, creation_id, access_token)

    posted_at = datetime.now(timezone.utc).isoformat()
    try:
        queue_store.update_status(queue_path, item["id"], "posted", posted_at=posted_at)
    except Exception:
        print(
            f"CRITICAL: item id={item['id']} WAS published to Instagram but the local "
            f"status update failed — manual verification required to avoid a duplicate post"
        )
        raise
    item["status"] = "posted"
    item["posted_at"] = posted_at
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["post", "reel"], required=True)
    parser.add_argument("--queue", default="content/queue.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        publish_today(
            item_type=args.type,
            queue_path=Path(args.queue),
            ig_business_id=os.environ["IG_BUSINESS_ID"],
            access_token=os.environ["IG_ACCESS_TOKEN"],
            dry_run=args.dry_run,
        )
    except PublishSkipped as exc:
        print(f"skip: {exc}")
    except graph_api.GraphAPIError as exc:
        print(f"ERROR: publish failed for --type={args.type} queue={args.queue}: {exc}")
        raise


if __name__ == "__main__":
    main()
