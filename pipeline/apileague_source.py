import hashlib
import json
from pathlib import Path

import requests

APILEAGUE_API_BASE = "https://api.apileague.com"


class ApileagueSourceError(RuntimeError):
    pass


def fetch_random_meme(api_key: str, *, session=None) -> dict:
    session = session or requests.Session()
    try:
        response = session.get(
            f"{APILEAGUE_API_BASE}/retrieve-random-meme",
            headers={"X-API-Key": api_key},
            timeout=30,
        )
        body = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        raise ApileagueSourceError(f"random meme fetch failed: {exc}") from exc
    if response.status_code != 200:
        raise ApileagueSourceError(f"random meme fetch failed: status {response.status_code}, body={body}")
    return body


def meme_id(meme: dict) -> str:
    return hashlib.sha256(meme["url"].encode("utf-8")).hexdigest()


def pick_unique_meme(api_key: str, *, seen_ids: set[str], max_attempts: int = 5,
                      session=None) -> dict | None:
    for _ in range(max_attempts):
        meme = fetch_random_meme(api_key, session=session)
        if meme_id(meme) not in seen_ids:
            return meme
    return None


def download_media(meme: dict, out_path: Path, *, session=None) -> Path:
    session = session or requests.Session()
    try:
        response = session.get(meme["url"], timeout=60)
    except requests.exceptions.RequestException as exc:
        raise ApileagueSourceError(f"failed to download media {meme['url']!r}: {exc}") from exc
    if response.status_code != 200:
        raise ApileagueSourceError(
            f"failed to download media {meme['url']!r}: status {response.status_code}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(response.content)
    return out_path


def load_seen_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def mark_seen(path: Path, meme_id_value: str) -> None:
    seen = load_seen_ids(path)
    seen.add(meme_id_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")
