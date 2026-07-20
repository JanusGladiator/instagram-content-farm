import json
import subprocess
from pathlib import Path

import requests

REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"


class RedditSourceError(RuntimeError):
    pass


def get_access_token(client_id: str, client_secret: str, user_agent: str,
                      *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        REDDIT_AUTH_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    body = response.json()
    if response.status_code != 200 or "access_token" not in body:
        raise RedditSourceError(f"reddit auth failed: {body}")
    return body["access_token"]


def fetch_top_posts(subreddit: str, access_token: str, user_agent: str, *,
                     limit: int = 25, timeframe: str = "week", session=None) -> list[dict]:
    session = session or requests.Session()
    response = session.get(
        f"{REDDIT_API_BASE}/r/{subreddit}/top",
        params={"limit": limit, "t": timeframe},
        headers={"Authorization": f"bearer {access_token}", "User-Agent": user_agent},
        timeout=30,
    )
    body = response.json()
    if response.status_code != 200:
        raise RedditSourceError(f"reddit listing fetch failed for r/{subreddit}: {body}")
    return [child["data"] for child in body["data"]["children"]]


def pick_post(posts: list[dict], *, media_kind: str, min_upvotes: int,
              seen_ids: set[str]) -> dict | None:
    for post in posts:
        if post["id"] in seen_ids:
            continue
        if post.get("over_18"):
            continue
        if post.get("ups", 0) < min_upvotes:
            continue
        if media_kind == "image" and post.get("post_hint") == "image":
            return post
        if media_kind == "video" and post.get("is_video"):
            return post
    return None


def download_image_post(post: dict, out_path: Path, *, session=None) -> Path:
    session = session or requests.Session()
    response = session.get(post["url"], timeout=60)
    if response.status_code != 200:
        raise RedditSourceError(
            f"failed to download image for post {post['id']}: status {response.status_code}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(response.content)
    return out_path


def download_video_post(post: dict, out_path: Path, *, session=None,
                         runner=subprocess.run) -> Path:
    session = session or requests.Session()
    video_url = post["media"]["reddit_video"]["fallback_url"]
    video_response = session.get(video_url, timeout=60)
    if video_response.status_code != 200:
        raise RedditSourceError(
            f"failed to download video for post {post['id']}: "
            f"status {video_response.status_code}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    video_temp = out_path.with_suffix(".video.mp4")
    video_temp.write_bytes(video_response.content)

    audio_url = video_url.rsplit("/", 1)[0] + "/DASH_audio.mp4"
    audio_response = session.get(audio_url, timeout=60)
    if audio_response.status_code != 200:
        video_temp.replace(out_path)
        return out_path

    audio_temp = out_path.with_suffix(".audio.mp4")
    audio_temp.write_bytes(audio_response.content)

    result = runner(
        ["ffmpeg", "-y", "-i", str(video_temp), "-i", str(audio_temp),
         "-c", "copy", "-map", "0:v:0", "-map", "1:a:0", str(out_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RedditSourceError(f"ffmpeg merge failed for post {post['id']}: {result.stderr}")
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
