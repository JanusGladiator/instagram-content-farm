import json
from pathlib import Path

import requests

IMGUR_API_BASE = "https://api.imgur.com/3"


class ImgurSourceError(RuntimeError):
    pass


def fetch_tag_gallery(tag: str, client_id: str, *, sort: str = "top",
                       window: str = "week", page: int = 0, session=None) -> list[dict]:
    session = session or requests.Session()
    response = session.get(
        f"{IMGUR_API_BASE}/gallery/t/{tag}/{sort}/{window}/{page}",
        headers={"Authorization": f"Client-ID {client_id}"},
        timeout=30,
    )
    body = response.json()
    if response.status_code != 200 or not body.get("success"):
        raise ImgurSourceError(f"imgur gallery fetch failed for tag={tag!r}: {body}")
    return body["data"]


def pick_post(posts: list[dict], *, media_kind: str, min_score: int,
              seen_ids: set[str]) -> dict | None:
    for post in posts:
        if post["id"] in seen_ids:
            continue
        if post.get("is_album"):
            continue
        if post.get("nsfw") is not False:
            continue
        if (post.get("score") or 0) < min_score:
            continue
        is_video = bool(post.get("animated"))
        if media_kind == "image" and not is_video:
            return post
        if media_kind == "video" and is_video:
            return post
    return None


def download_media(post: dict, out_path: Path, *, session=None) -> Path:
    session = session or requests.Session()
    response = session.get(post["link"], timeout=60)
    if response.status_code != 200:
        raise ImgurSourceError(
            f"failed to download media for post {post['id']}: status {response.status_code}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(response.content)
    return out_path


def load_seen_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def mark_seen(path: Path, post_id: str) -> None:
    seen = load_seen_ids(path)
    seen.add(post_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")
