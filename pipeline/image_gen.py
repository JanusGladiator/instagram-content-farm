import time
import urllib.parse
from pathlib import Path

import requests

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


class ImageGenError(RuntimeError):
    pass


def generate_image(prompt: str, out_path: Path, *, max_retries: int = 3,
                    backoff_seconds: float = 15.0, session=None) -> Path:
    session = session or requests.Session()
    url = f"{POLLINATIONS_BASE}/{urllib.parse.quote(prompt)}"
    last_error = None

    for attempt in range(max_retries):
        response = session.get(url, timeout=60)
        if response.status_code == 200:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.content)
            return out_path

        last_error = f"status {response.status_code}"
        if response.status_code == 429 and attempt < max_retries - 1:
            time.sleep(backoff_seconds)
            continue
        break

    raise ImageGenError(f"image generation failed for prompt={prompt!r}: {last_error}")
