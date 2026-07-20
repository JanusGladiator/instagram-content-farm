# Instagram Content Farm Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automated pipeline that generates a week of Instagram content (original AI-generated, broad relatable/internet-culture humor, 1 post + 1 reel per day), lets the user approve the whole week in one sitting, then publishes autonomously via the official Meta Graph API with no further human interaction that week.

**Architecture:** Two scheduled phases sharing a flat-file queue (`content/queue.json`). A weekly Generate routine creates 14 content items and a review Artifact page. A daily Publish routine (fires twice: image at 12:00, reel at 20:00) posts whatever is approved for that day via the Instagram Graph API. See `docs/superpowers/specs/2026-07-19-instagram-content-farm-design.md` for the approved design.

**Tech Stack:** Python 3.11+, `requests`, `anthropic` SDK, system `ffmpeg` binary, `pytest`, git/GitHub (public repo, raw-URL asset hosting), Claude Code scheduled routines, Artifact state capability.

## Global Constraints

- Official Meta Graph API only — no unofficial/private IG API libraries, no browser automation (spec: "Hard Constraint: Official API Only").
- Image generation via Pollinations.ai (free, no key) — no paid image-gen API.
- Reel audio must be royalty-free (Pixabay Audio / YouTube Audio Library or equivalent) — never pulled from Instagram's in-app audio library (unreachable via API anyway).
- Secrets (`IG_ACCESS_TOKEN`, `IG_BUSINESS_ID`, GitHub push credentials, `ANTHROPIC_API_KEY`) are environment variables only — never hardcoded, never committed. `.gitignore` already excludes `.env*`.
- `content/queue.json` is the single source of truth for what gets published; nothing auto-posts without `status == "approved"` on the correct `scheduled_date`.
- A `pending` item at its scheduled publish time is skipped and logged, never force-posted, never re-prompted.
- No test may hit a live external API (Pollinations, Anthropic, Graph API) or perform a real `git push` — all external calls are injected via a `session`/`runner`/`client` parameter and replaced with fakes in tests.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `pipeline/__init__.py`
- Create: `content/queue.json`
- Create: `content/assets/.gitkeep`
- Create: `.env.example`

**Interfaces:**
- Produces: `pipeline` package importable as `pipeline.*` from repo root; `content/queue.json` seeded as `[]`.

- [ ] **Step 1: Create the package and data directories**

```bash
mkdir -p pipeline tests content/assets
```

- [ ] **Step 2: Write `pipeline/__init__.py`**

```python
```

(empty file — marks `pipeline/` as a package)

- [ ] **Step 3: Write `requirements.txt`**

```
requests>=2.31
anthropic>=0.40
pytest>=8.0
```

- [ ] **Step 4: Seed the empty queue**

Write `content/queue.json`:

```json
[]
```

- [ ] **Step 5: Create `content/assets/.gitkeep`**

```
```

(empty file — keeps the otherwise-empty directory in git)

- [ ] **Step 6: Write `.env.example`**

```
IG_ACCESS_TOKEN=
IG_BUSINESS_ID=
ANTHROPIC_API_KEY=
GITHUB_REPO_OWNER=
GITHUB_REPO_NAME=
```

- [ ] **Step 7: Install dependencies and verify pytest collects cleanly**

Run: `pip install -r requirements.txt && pytest`
Expected: `no tests ran` (0 collected, exit code 0 — some pytest versions report `no tests ran` with exit code 5, which is fine at this stage)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt pipeline/__init__.py content/queue.json content/assets/.gitkeep .env.example
git commit -m "chore: scaffold pipeline package and content directories"
```

---

### Task 2: Queue store module

**Files:**
- Create: `pipeline/queue_store.py`
- Test: `tests/test_queue_store.py`

**Interfaces:**
- Produces:
  - `QueueValidationError(ValueError)`
  - `validate_item(item: dict) -> None`
  - `load_queue(path: Path) -> list[dict]`
  - `save_queue(path: Path, items: list[dict]) -> None`
  - `new_item(*, type_: str, scheduled_date: str, asset_url: str, caption: str, hashtags: list[str]) -> dict`
  - `append_item(path: Path, item: dict) -> None`
  - `get_item_for_date(items: list[dict], scheduled_date: str, type_: str, status: str | None = None) -> dict | None`
  - `update_status(path: Path, item_id: str, new_status: str, posted_at: str | None = None) -> None`

- [ ] **Step 1: Write failing tests**

Create `tests/test_queue_store.py`:

```python
import json
import pytest
from pipeline import queue_store


def test_new_item_has_pending_status_and_uuid_id():
    item = queue_store.new_item(
        type_="post", scheduled_date="2026-07-20",
        asset_url="https://example.com/a.jpg",
        caption="caption", hashtags=["a", "b"],
    )
    assert item["status"] == "pending"
    assert item["type"] == "post"
    assert item["scheduled_date"] == "2026-07-20"
    assert item["posted_at"] is None
    assert item["id"]


def test_validate_item_rejects_missing_field():
    item = queue_store.new_item(
        type_="post", scheduled_date="2026-07-20",
        asset_url="u", caption="c", hashtags=[],
    )
    del item["caption"]
    with pytest.raises(queue_store.QueueValidationError):
        queue_store.validate_item(item)


def test_validate_item_rejects_bad_type():
    item = queue_store.new_item(
        type_="post", scheduled_date="2026-07-20",
        asset_url="u", caption="c", hashtags=[],
    )
    item["type"] = "story"
    with pytest.raises(queue_store.QueueValidationError):
        queue_store.validate_item(item)


def test_load_queue_returns_empty_list_when_file_missing(tmp_path):
    result = queue_store.load_queue(tmp_path / "queue.json")
    assert result == []


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "queue.json"
    item = queue_store.new_item(
        type_="reel", scheduled_date="2026-07-21",
        asset_url="u", caption="c", hashtags=["x"],
    )
    queue_store.append_item(path, item)

    loaded = queue_store.load_queue(path)
    assert len(loaded) == 1
    assert loaded[0]["id"] == item["id"]


def test_get_item_for_date_filters_by_type_date_and_status():
    items = [
        queue_store.new_item(type_="post", scheduled_date="2026-07-20",
                              asset_url="u1", caption="c", hashtags=[]),
        queue_store.new_item(type_="reel", scheduled_date="2026-07-20",
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
        type_="post", scheduled_date="2026-07-20",
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_queue_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.queue_store'` (or `ImportError`)

- [ ] **Step 3: Implement `pipeline/queue_store.py`**

```python
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

VALID_TYPES = {"post", "reel"}
VALID_STATUSES = {"pending", "approved", "rejected", "posted", "failed"}
REQUIRED_FIELDS = {
    "id", "type", "scheduled_date", "asset_url", "caption",
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


def new_item(*, type_: str, scheduled_date: str, asset_url: str,
             caption: str, hashtags: list[str]) -> dict:
    item = {
        "id": str(uuid.uuid4()),
        "type": type_,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_queue_store.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/queue_store.py tests/test_queue_store.py
git commit -m "feat: add queue_store module for content/queue.json"
```

---

### Task 3: Pollinations image client

**Files:**
- Create: `pipeline/image_gen.py`
- Test: `tests/test_image_gen.py`

**Interfaces:**
- Produces: `ImageGenError(RuntimeError)`, `generate_image(prompt: str, out_path: Path, *, max_retries: int = 3, backoff_seconds: float = 15.0, session=None) -> Path`

- [ ] **Step 1: Write failing tests**

Create `tests/test_image_gen.py`:

```python
import pytest
from pipeline import image_gen


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return self.responses.pop(0)


def test_generate_image_writes_file_on_200(tmp_path):
    session = FakeSession([FakeResponse(200, content=b"fake-image-bytes")])
    out_path = tmp_path / "out.jpg"

    result = image_gen.generate_image("a cat", out_path, session=session)

    assert result == out_path
    assert out_path.read_bytes() == b"fake-image-bytes"
    assert session.calls == 1


def test_generate_image_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(image_gen.time, "sleep", lambda seconds: None)
    session = FakeSession([FakeResponse(429), FakeResponse(200, content=b"ok")])
    out_path = tmp_path / "out.jpg"

    result = image_gen.generate_image("a cat", out_path, max_retries=3, session=session)

    assert result == out_path
    assert session.calls == 2


def test_generate_image_raises_after_max_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(image_gen.time, "sleep", lambda seconds: None)
    session = FakeSession([FakeResponse(429), FakeResponse(429)])
    out_path = tmp_path / "out.jpg"

    with pytest.raises(image_gen.ImageGenError):
        image_gen.generate_image("a cat", out_path, max_retries=2, session=session)


def test_generate_image_raises_immediately_on_non_retryable_error(tmp_path):
    session = FakeSession([FakeResponse(500)])
    out_path = tmp_path / "out.jpg"

    with pytest.raises(image_gen.ImageGenError):
        image_gen.generate_image("a cat", out_path, max_retries=3, session=session)

    assert session.calls == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_image_gen.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/image_gen.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_image_gen.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/image_gen.py tests/test_image_gen.py
git commit -m "feat: add Pollinations.ai image_gen client with 429 backoff"
```

---

### Task 4: Reel builder (ffmpeg)

**Files:**
- Create: `pipeline/reel_builder.py`
- Test: `tests/test_reel_builder.py`

**Interfaces:**
- Produces: `ReelBuildError(RuntimeError)`, `build_ffmpeg_command(image_paths: list[Path], audio_path: Path, text: str, out_path: Path, *, duration_seconds: int = 8, hook_seconds: int = 3) -> list[str]`, `build_reel(image_paths: list[Path], audio_path: Path, text: str, out_path: Path, *, duration_seconds: int = 8, hook_seconds: int = 3, runner=subprocess.run) -> Path`

Reels quick-cut across `image_paths` (a "setup" shot and a "punchline" shot per the content strategy) and overlay `text` only during `[0, hook_seconds]` — the algorithm decides whether to distribute a Reel based on the first 1-3 seconds, so the hook must land immediately rather than fading in over the whole clip.

- [ ] **Step 1: Write failing tests**

Create `tests/test_reel_builder.py`:

```python
from pathlib import Path
import pytest
from pipeline import reel_builder


def test_build_ffmpeg_command_includes_all_image_inputs_and_output():
    command = reel_builder.build_ffmpeg_command(
        [Path("setup.jpg"), Path("punchline.jpg")], Path("audio.mp3"),
        "hello world", Path("out.mp4"),
    )
    assert command[0] == "ffmpeg"
    assert "setup.jpg" in command
    assert "punchline.jpg" in command
    assert "audio.mp3" in command
    assert command[-1] == "out.mp4"


def test_build_ffmpeg_command_escapes_special_chars_in_text():
    command = reel_builder.build_ffmpeg_command(
        [Path("img.jpg")], Path("audio.mp3"), "it's 5:00", Path("out.mp4"),
    )
    filter_arg = command[command.index("-filter_complex") + 1]
    assert r"\:" in filter_arg
    assert r"\'" in filter_arg


def test_build_ffmpeg_command_restricts_text_to_hook_window():
    command = reel_builder.build_ffmpeg_command(
        [Path("img.jpg")], Path("audio.mp3"), "hook", Path("out.mp4"),
        hook_seconds=3,
    )
    filter_arg = command[command.index("-filter_complex") + 1]
    assert "enable='between(t,0,3)'" in filter_arg


def test_build_ffmpeg_command_raises_on_empty_image_list():
    with pytest.raises(ValueError):
        reel_builder.build_ffmpeg_command(
            [], Path("audio.mp3"), "hook", Path("out.mp4"),
        )


class FakeCompletedProcess:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_build_reel_returns_out_path_on_success(tmp_path):
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append(command)
        return FakeCompletedProcess(returncode=0)

    out_path = tmp_path / "out.mp4"
    result = reel_builder.build_reel(
        [tmp_path / "setup.jpg", tmp_path / "punchline.jpg"],
        tmp_path / "audio.mp3", "caption", out_path,
        runner=fake_runner,
    )

    assert result == out_path
    assert len(calls) == 1
    assert calls[0][0] == "ffmpeg"


def test_build_reel_raises_on_nonzero_returncode(tmp_path):
    def fake_runner(command, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="boom")

    with pytest.raises(reel_builder.ReelBuildError, match="boom"):
        reel_builder.build_reel(
            [tmp_path / "img.jpg"], tmp_path / "audio.mp3", "caption",
            tmp_path / "out.mp4", runner=fake_runner,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reel_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/reel_builder.py`**

```python
import subprocess
from pathlib import Path


class ReelBuildError(RuntimeError):
    pass


def build_ffmpeg_command(image_paths: list[Path], audio_path: Path, text: str,
                          out_path: Path, *, duration_seconds: int = 8,
                          hook_seconds: int = 3) -> list[str]:
    if not image_paths:
        raise ValueError("image_paths must contain at least one image")

    per_image_seconds = duration_seconds / len(image_paths)
    escaped_text = text.replace(":", r"\:").replace("'", r"\'")

    command = ["ffmpeg", "-y"]
    for image_path in image_paths:
        command += ["-loop", "1", "-t", str(per_image_seconds), "-i", str(image_path)]
    command += ["-i", str(audio_path)]

    video_labels = "".join(f"[{i}:v]" for i in range(len(image_paths)))
    drawtext = (
        f"drawtext=text='{escaped_text}':fontcolor=white:fontsize=48:"
        f"x=(w-text_w)/2:y=h-th-60:box=1:boxcolor=black@0.5:boxborderw=10:"
        f"enable='between(t,0,{hook_seconds})'"
    )
    filter_complex = (
        f"{video_labels}concat=n={len(image_paths)}:v=1:a=0[vcat];"
        f"[vcat]{drawtext}[vout]"
    )
    audio_index = len(image_paths)

    command += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", f"{audio_index}:a",
        "-t", str(duration_seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    return command


def build_reel(image_paths: list[Path], audio_path: Path, text: str, out_path: Path,
                *, duration_seconds: int = 8, hook_seconds: int = 3,
                runner=subprocess.run) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(image_paths, audio_path, text, out_path,
                                    duration_seconds=duration_seconds,
                                    hook_seconds=hook_seconds)
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ReelBuildError(f"ffmpeg failed: {result.stderr}")
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reel_builder.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reel_builder.py tests/test_reel_builder.py
git commit -m "feat: add ffmpeg-based reel_builder module"
```

---

### Task 5: Caption/hashtag generator

**Files:**
- Create: `pipeline/captions.py`
- Test: `tests/test_captions.py`

**Interfaces:**
- Produces: `CaptionGenError(RuntimeError)`, `generate_caption(concept: str, *, client=None, model: str = "claude-sonnet-5") -> dict` returning `{"caption": str, "hashtags": list[str]}`

- [ ] **Step 1: Write failing tests**

Create `tests/test_captions.py`:

```python
import pytest
from pipeline import captions


class FakeTextBlock:
    def __init__(self, text):
        self.text = text


class FakeMessage:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


class FakeMessages:
    def __init__(self, response_text):
        self.response_text = response_text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return FakeMessage(self.response_text)


class FakeClient:
    def __init__(self, response_text):
        self.messages = FakeMessages(response_text)


def test_generate_caption_parses_valid_json():
    client = FakeClient('{"caption": "lol", "hashtags": ["cyber", "meme"]}')

    result = captions.generate_caption("a red team meme", client=client)

    assert result == {"caption": "lol", "hashtags": ["cyber", "meme"]}
    assert client.messages.last_kwargs["model"] == "claude-sonnet-5"


def test_generate_caption_raises_on_invalid_json():
    client = FakeClient("not json")

    with pytest.raises(captions.CaptionGenError):
        captions.generate_caption("a red team meme", client=client)


def test_generate_caption_raises_on_missing_keys():
    client = FakeClient('{"caption": "lol"}')

    with pytest.raises(captions.CaptionGenError):
        captions.generate_caption("a red team meme", client=client)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_captions.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/captions.py`**

```python
import json

from anthropic import Anthropic

CAPTION_PROMPT = """Write an Instagram caption and hashtags for this content idea.
Concept: {concept}

Optimize for one thing: would a specific person send this to a specific
friend in a DM? That's the top distribution signal on Instagram right now —
write like you're describing a moment a reader will recognize and want to
tag someone in, not a generic joke. Keep it broadly relatable (daily life,
work, phone habits, group chats) — not tied to any specialist subject.

Respond with ONLY valid JSON: {{"caption": "...", "hashtags": ["...", ...]}}
Caption should be short (1-2 sentences), punchy, no hashtags inside it.
Provide 5-10 relevant hashtags without the # symbol."""


class CaptionGenError(RuntimeError):
    pass


def generate_caption(concept: str, *, client=None, model: str = "claude-sonnet-5") -> dict:
    client = client or Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user", "content": CAPTION_PROMPT.format(concept=concept)}],
    )
    raw = message.content[0].text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CaptionGenError(f"model did not return valid JSON: {raw!r}") from exc

    if "caption" not in data or "hashtags" not in data:
        raise CaptionGenError(f"missing keys in model response: {data!r}")

    return {"caption": data["caption"], "hashtags": list(data["hashtags"])}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_captions.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/captions.py tests/test_captions.py
git commit -m "feat: add Claude-backed caption/hashtag generator"
```

---

### Task 6: Asset hosting (git push helper)

**Files:**
- Create: `pipeline/asset_host.py`
- Test: `tests/test_asset_host.py`

**Interfaces:**
- Produces: `AssetPublishError(RuntimeError)`, `raw_url(repo_owner: str, repo_name: str, branch: str, relative_path: str) -> str`, `publish_asset(local_path: Path, repo_root: Path, relative_dest: str, *, repo_owner: str, repo_name: str, branch: str = "master", runner=subprocess.run) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_asset_host.py`:

```python
from pathlib import Path
import pytest
from pipeline import asset_host


def test_raw_url_builds_expected_url():
    url = asset_host.raw_url("me", "instagram-farm", "master", "content/assets/a.jpg")
    assert url == "https://raw.githubusercontent.com/me/instagram-farm/master/content/assets/a.jpg"


class FakeCompletedProcess:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_publish_asset_copies_file_runs_git_and_returns_url(tmp_path):
    local_path = tmp_path / "source" / "img.jpg"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"image-bytes")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    calls = []

    def fake_runner(command, cwd, capture_output, text):
        calls.append((command, cwd))
        return FakeCompletedProcess(returncode=0)

    url = asset_host.publish_asset(
        local_path, repo_root, "content/assets/img.jpg",
        repo_owner="me", repo_name="instagram-farm", runner=fake_runner,
    )

    assert url == "https://raw.githubusercontent.com/me/instagram-farm/master/content/assets/img.jpg"
    assert (repo_root / "content/assets/img.jpg").read_bytes() == b"image-bytes"
    assert [c[0][:2] for c in calls] == [["git", "add"], ["git", "commit"], ["git", "push"]]


def test_publish_asset_raises_on_git_failure(tmp_path):
    local_path = tmp_path / "img.jpg"
    local_path.write_bytes(b"x")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(command, cwd, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="add failed")

    with pytest.raises(asset_host.AssetPublishError, match="add failed"):
        asset_host.publish_asset(
            local_path, repo_root, "content/assets/img.jpg",
            repo_owner="me", repo_name="instagram-farm", runner=fake_runner,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_asset_host.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/asset_host.py`**

```python
import subprocess
from pathlib import Path


class AssetPublishError(RuntimeError):
    pass


def raw_url(repo_owner: str, repo_name: str, branch: str, relative_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{relative_path}"


def publish_asset(local_path: Path, repo_root: Path, relative_dest: str, *,
                   repo_owner: str, repo_name: str, branch: str = "master",
                   runner=subprocess.run) -> str:
    dest_path = repo_root / relative_dest
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(local_path.read_bytes())

    add = runner(["git", "add", relative_dest], cwd=repo_root,
                 capture_output=True, text=True)
    if add.returncode != 0:
        raise AssetPublishError(f"git add failed: {add.stderr}")

    commit = runner(["git", "commit", "-m", f"content: add {relative_dest}"],
                     cwd=repo_root, capture_output=True, text=True)
    if commit.returncode != 0:
        raise AssetPublishError(f"git commit failed: {commit.stderr}")

    push = runner(["git", "push"], cwd=repo_root, capture_output=True, text=True)
    if push.returncode != 0:
        raise AssetPublishError(f"git push failed: {push.stderr}")

    return raw_url(repo_owner, repo_name, branch, relative_dest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_asset_host.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/asset_host.py tests/test_asset_host.py
git commit -m "feat: add git-push-based public asset hosting helper"
```

---

### Task 7: Weekly generate orchestrator

**Files:**
- Create: `pipeline/generate.py`
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: `queue_store.new_item`, `queue_store.append_item` (Task 2); `image_gen.generate_image` (Task 3); `reel_builder.build_reel(image_paths: list[Path], audio_path, text, out_path, **kw)` (Task 4); `captions.generate_caption` (Task 5); `asset_host.publish_asset` (Task 6)
- Produces: `THEMES: list[str]`, `pick_theme(day_index: int) -> str`, `generate_week(*, start_date: date, queue_path: Path, work_dir: Path, repo_root: Path, repo_owner: str, repo_name: str, audio_path: Path) -> list[dict]`

Themes are broad, general relatable-humor concepts (daily life, work, phone/group-chat moments) — not a subject-matter niche like cybersecurity — per the design doc's Content Model. Each reel gets two images generated from the same theme (a "setup" shot and a "punchline" shot) for `reel_builder.build_reel`'s quick-cut.

- [ ] **Step 1: Write failing tests**

Create `tests/test_generate.py`:

```python
from datetime import date
from pathlib import Path

from pipeline import generate, queue_store


def test_pick_theme_cycles_through_themes():
    assert generate.pick_theme(0) == generate.THEMES[0]
    assert generate.pick_theme(len(generate.THEMES)) == generate.THEMES[0]


def test_generate_week_creates_14_items_with_correct_dates_and_types(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    work_dir = tmp_path / "work"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"a")

    monkeypatch.setattr(generate.image_gen, "generate_image",
                         lambda prompt, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reel_builder, "build_reel",
                         lambda image_paths, audio_path, text, out_path, **kw: out_path)
    monkeypatch.setattr(generate.captions, "generate_caption",
                         lambda concept, **kw: {"caption": "cap", "hashtags": ["h"]})
    monkeypatch.setattr(generate.asset_host, "publish_asset",
                         lambda local_path, repo_root, relative_dest, **kw:
                             f"https://raw.githubusercontent.com/me/repo/master/{relative_dest}")

    created = generate.generate_week(
        start_date=date(2026, 7, 20),
        queue_path=queue_path, work_dir=work_dir, repo_root=repo_root,
        repo_owner="me", repo_name="repo", audio_path=audio_path,
    )

    assert len(created) == 14
    loaded = queue_store.load_queue(queue_path)
    assert len(loaded) == 14

    post_dates = sorted(i["scheduled_date"] for i in loaded if i["type"] == "post")
    reel_dates = sorted(i["scheduled_date"] for i in loaded if i["type"] == "reel")
    assert post_dates == reel_dates == [
        "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26",
    ]
    assert all(i["status"] == "pending" for i in loaded)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/generate.py`**

```python
from datetime import date, timedelta
from pathlib import Path

from pipeline import asset_host, captions, image_gen, queue_store, reel_builder

THEMES = [
    "Monday morning alarm going off, exaggerated dread reaction",
    "phone battery hitting 1% at the worst possible moment, cinematic panic",
    "group chat going silent after someone sends a risky text, tense pause",
    "pretending to pay attention in a boring meeting, deadpan stare",
    "finally understanding a joke three days late, delayed realization",
    "a friend cancels plans last minute, mixed relief and betrayal",
    "trying to adult before coffee, chaotic exhausted energy",
]

REEL_SHOT_VARIANTS = ("setup shot", "punchline reaction shot")


def pick_theme(day_index: int) -> str:
    return THEMES[day_index % len(THEMES)]


def generate_week(*, start_date: date, queue_path: Path, work_dir: Path,
                   repo_root: Path, repo_owner: str, repo_name: str,
                   audio_path: Path) -> list[dict]:
    work_dir.mkdir(parents=True, exist_ok=True)
    created = []

    for offset in range(7):
        day = start_date + timedelta(days=offset)
        theme = pick_theme(offset)

        post_image = work_dir / f"{day.isoformat()}-post.jpg"
        image_gen.generate_image(theme, post_image)
        post_caption = captions.generate_caption(theme)
        post_relative = f"content/assets/{post_image.name}"
        post_url = asset_host.publish_asset(
            post_image, repo_root, post_relative,
            repo_owner=repo_owner, repo_name=repo_name,
        )
        post_item = queue_store.new_item(
            type_="post", scheduled_date=day.isoformat(), asset_url=post_url,
            caption=post_caption["caption"], hashtags=post_caption["hashtags"],
        )
        queue_store.append_item(queue_path, post_item)
        created.append(post_item)

        reel_image_paths = []
        for shot_index, variant in enumerate(REEL_SHOT_VARIANTS):
            reel_image = work_dir / f"{day.isoformat()}-reel-{shot_index}.jpg"
            image_gen.generate_image(f"{theme}, {variant}", reel_image)
            reel_image_paths.append(reel_image)

        reel_caption = captions.generate_caption(theme + ", short video reel")
        reel_video = work_dir / f"{day.isoformat()}-reel.mp4"
        reel_builder.build_reel(reel_image_paths, audio_path,
                                 reel_caption["caption"], reel_video)
        reel_relative = f"content/assets/{reel_video.name}"
        reel_url = asset_host.publish_asset(
            reel_video, repo_root, reel_relative,
            repo_owner=repo_owner, repo_name=repo_name,
        )
        reel_item = queue_store.new_item(
            type_="reel", scheduled_date=day.isoformat(), asset_url=reel_url,
            caption=reel_caption["caption"], hashtags=reel_caption["hashtags"],
        )
        queue_store.append_item(queue_path, reel_item)
        created.append(reel_item)

    return created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/generate.py tests/test_generate.py
git commit -m "feat: add weekly generate orchestrator"
```

---

### Task 8: Graph API client

**Files:**
- Create: `pipeline/graph_api.py`
- Test: `tests/test_graph_api.py`

**Interfaces:**
- Produces: `GraphAPIError(RuntimeError)`, `create_image_container(ig_business_id, image_url, caption, access_token, *, session=None) -> str`, `create_reel_container(ig_business_id, video_url, caption, access_token, *, session=None) -> str`, `wait_for_container_ready(container_id, access_token, *, session=None, max_attempts=20, poll_seconds=5.0) -> None`, `publish_container(ig_business_id, creation_id, access_token, *, session=None) -> str`, `verify_credentials(ig_business_id, access_token, *, session=None) -> dict`

- [ ] **Step 1: Write failing tests**

Create `tests/test_graph_api.py`:

```python
import pytest
from pipeline import graph_api


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.post_calls = []
        self.get_calls = []

    def post(self, url, data, timeout=None):
        self.post_calls.append((url, data))
        return self.responses.pop(0)

    def get(self, url, params, timeout=None):
        self.get_calls.append((url, params))
        return self.responses.pop(0)


def test_create_image_container_returns_id_on_success():
    session = FakeSession([FakeResponse(200, {"id": "container-1"})])
    result = graph_api.create_image_container("ig1", "http://x/img.jpg", "cap", "token", session=session)
    assert result == "container-1"


def test_create_image_container_raises_on_error_body():
    session = FakeSession([FakeResponse(400, {"error": {"message": "bad"}})])
    with pytest.raises(graph_api.GraphAPIError):
        graph_api.create_image_container("ig1", "http://x/img.jpg", "cap", "token", session=session)


def test_create_reel_container_sends_media_type_reels():
    session = FakeSession([FakeResponse(200, {"id": "container-2"})])
    graph_api.create_reel_container("ig1", "http://x/reel.mp4", "cap", "token", session=session)
    _, data = session.post_calls[0]
    assert data["media_type"] == "REELS"
    assert data["video_url"] == "http://x/reel.mp4"


def test_wait_for_container_ready_returns_when_finished(monkeypatch):
    monkeypatch.setattr(graph_api.time, "sleep", lambda s: None)
    session = FakeSession([
        FakeResponse(200, {"status_code": "IN_PROGRESS"}),
        FakeResponse(200, {"status_code": "FINISHED"}),
    ])
    graph_api.wait_for_container_ready("container-2", "token", session=session)
    assert len(session.get_calls) == 2


def test_wait_for_container_ready_raises_on_error_status(monkeypatch):
    monkeypatch.setattr(graph_api.time, "sleep", lambda s: None)
    session = FakeSession([FakeResponse(200, {"status_code": "ERROR"})])
    with pytest.raises(graph_api.GraphAPIError):
        graph_api.wait_for_container_ready("container-2", "token", session=session)


def test_wait_for_container_ready_raises_after_max_attempts(monkeypatch):
    monkeypatch.setattr(graph_api.time, "sleep", lambda s: None)
    session = FakeSession([FakeResponse(200, {"status_code": "IN_PROGRESS"})] * 3)
    with pytest.raises(graph_api.GraphAPIError):
        graph_api.wait_for_container_ready("container-2", "token", session=session, max_attempts=3)


def test_publish_container_returns_id_on_success():
    session = FakeSession([FakeResponse(200, {"id": "media-1"})])
    result = graph_api.publish_container("ig1", "container-1", "token", session=session)
    assert result == "media-1"


def test_publish_container_raises_on_failure():
    session = FakeSession([FakeResponse(400, {"error": {"message": "bad"}})])
    with pytest.raises(graph_api.GraphAPIError):
        graph_api.publish_container("ig1", "container-1", "token", session=session)


def test_verify_credentials_returns_body_on_success():
    session = FakeSession([FakeResponse(200, {"username": "myfarmacct"})])
    result = graph_api.verify_credentials("ig1", "token", session=session)
    assert result["username"] == "myfarmacct"


def test_verify_credentials_raises_on_failure():
    session = FakeSession([FakeResponse(401, {"error": {"message": "bad token"}})])
    with pytest.raises(graph_api.GraphAPIError):
        graph_api.verify_credentials("ig1", "token", session=session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph_api.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/graph_api.py`**

```python
import time

import requests

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class GraphAPIError(RuntimeError):
    pass


def create_image_container(ig_business_id: str, image_url: str, caption: str,
                            access_token: str, *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        f"{GRAPH_API_BASE}/{ig_business_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": access_token},
        timeout=60,
    )
    body = response.json()
    if response.status_code != 200 or "id" not in body:
        raise GraphAPIError(f"image container creation failed: {body}")
    return body["id"]


def create_reel_container(ig_business_id: str, video_url: str, caption: str,
                           access_token: str, *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        f"{GRAPH_API_BASE}/{ig_business_id}/media",
        data={
            "video_url": video_url,
            "caption": caption,
            "media_type": "REELS",
            "access_token": access_token,
        },
        timeout=60,
    )
    body = response.json()
    if response.status_code != 200 or "id" not in body:
        raise GraphAPIError(f"reel container creation failed: {body}")
    return body["id"]


def wait_for_container_ready(container_id: str, access_token: str, *, session=None,
                              max_attempts: int = 20, poll_seconds: float = 5.0) -> None:
    session = session or requests.Session()
    for _ in range(max_attempts):
        response = session.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        body = response.json()
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise GraphAPIError(f"container {container_id} failed processing: {body}")
        time.sleep(poll_seconds)
    raise GraphAPIError(f"container {container_id} not ready after {max_attempts} polls")


def publish_container(ig_business_id: str, creation_id: str, access_token: str,
                       *, session=None) -> str:
    session = session or requests.Session()
    response = session.post(
        f"{GRAPH_API_BASE}/{ig_business_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    body = response.json()
    if response.status_code != 200 or "id" not in body:
        raise GraphAPIError(f"publish failed: {body}")
    return body["id"]


def verify_credentials(ig_business_id: str, access_token: str, *, session=None) -> dict:
    session = session or requests.Session()
    response = session.get(
        f"{GRAPH_API_BASE}/{ig_business_id}",
        params={"fields": "username", "access_token": access_token},
        timeout=30,
    )
    body = response.json()
    if response.status_code != 200 or "username" not in body:
        raise GraphAPIError(f"credential check failed: {body}")
    return body


if __name__ == "__main__":
    import os
    result = verify_credentials(os.environ["IG_BUSINESS_ID"], os.environ["IG_ACCESS_TOKEN"])
    print(f"OK - connected as @{result['username']}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_graph_api.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/graph_api.py tests/test_graph_api.py
git commit -m "feat: add Instagram Graph API client"
```

---

### Task 9: Daily publish orchestrator

**Files:**
- Create: `pipeline/publish.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `queue_store.load_queue`, `queue_store.get_item_for_date`, `queue_store.update_status` (Task 2); `graph_api.create_image_container`, `graph_api.create_reel_container`, `graph_api.wait_for_container_ready`, `graph_api.publish_container` (Task 8)
- Produces: `PublishSkipped(Exception)`, `publish_today(*, item_type: str, queue_path: Path, ig_business_id: str, access_token: str, today: date | None = None, dry_run: bool = False) -> dict`, CLI `main()`

- [ ] **Step 1: Write failing tests**

Create `tests/test_publish.py`:

```python
from datetime import date
import pytest
from pipeline import publish, queue_store, graph_api


def _seed_approved_item(queue_path, item_type, scheduled_date="2026-07-20"):
    item = queue_store.new_item(
        type_=item_type, scheduled_date=scheduled_date,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publish.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/publish.py`**

```python
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
    queue_store.update_status(queue_path, item["id"], "posted", posted_at=posted_at)
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


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_publish.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/publish.py tests/test_publish.py
git commit -m "feat: add daily publish orchestrator with dry-run support"
```

---

### Task 10: Meta Developer App + long-lived access token

**Files:** None (external setup + verification using Task 8's `verify_credentials`)

**Interfaces:**
- Consumes: `graph_api.verify_credentials` (Task 8)
- Produces: working `IG_ACCESS_TOKEN` and `IG_BUSINESS_ID` values for use by Tasks 9, 12, 13

- [ ] **Step 1: Create the Meta App**

Go to `developers.facebook.com/apps` → Create App → type "Business" → name it (e.g. the account's handle). Note the App ID.

- [ ] **Step 2: Add the Instagram Graph API product**

In the App dashboard, add product "Instagram Graph API". Confirm the target IG account is Business/Creator and linked to the Facebook Page it's already connected to (per design doc — already true for this account).

- [ ] **Step 3: Generate a token with the required permissions**

Via Graph API Explorer (or a System User under Business Settings), generate a User or System User token with: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`. Copy the short-lived token.

- [ ] **Step 4: Exchange for a long-lived token**

```bash
curl -s "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=<APP_ID>&client_secret=<APP_SECRET>&fb_exchange_token=<SHORT_LIVED_TOKEN>"
```

Expected: JSON body with `access_token` and `expires_in` (~5184000 seconds ≈ 60 days). This is `IG_ACCESS_TOKEN`.

- [ ] **Step 5: Look up the IG Business Account ID**

```bash
curl -s "https://graph.facebook.com/v21.0/<PAGE_ID>?fields=instagram_business_account&access_token=<IG_ACCESS_TOKEN>"
```

Expected: JSON body with `instagram_business_account.id` — this is `IG_BUSINESS_ID`.

- [ ] **Step 6: Store credentials as environment variables (not in any file that gets committed)**

Set `IG_ACCESS_TOKEN` and `IG_BUSINESS_ID` locally for smoke-testing now; Task 12 configures the same values in the scheduled routine's secret store.

- [ ] **Step 7: Verify with Task 8's client**

Run: `python -m pipeline.graph_api`
Expected: `OK - connected as @<your account username>`

- [ ] **Step 8: Note the token expiry**

Long-lived tokens expire ~60 days. There is no code task for renewal in this plan (YAGNI at this stage) — the Publish routine fails loudly with a `GraphAPIError` on an expired token (per Global Constraints), which is the signal to redo Steps 3–5.

---

### Task 11: Review Artifact page

**Files:**
- Create: `review_page.html` (source file passed to the Artifact tool)

**Interfaces:**
- Consumes: the week's `content/queue.json` (fetched client-side via its public raw-URL, since the repo is public per the design doc)
- Produces: a published Artifact URL where the user approves/rejects the week's 14 items; approve/reject decisions must end up reflected in `content/queue.json`'s `status` field before Task 12's Publish routine reads it

- [ ] **Step 1: Load the `artifact-capabilities` skill**

This is required before writing any capability declaration or `window.claude.*` runtime code — invoke it now via the Skill tool. Its current contract determines the exact API for shared/persisted state; do not hand-write that API from memory.

- [ ] **Step 2: Write the static page structure**

`review_page.html` fetches `https://raw.githubusercontent.com/<owner>/<repo>/master/content/queue.json`, groups the 14 items by `scheduled_date`, and renders each with: a thumbnail (`<img>` for `type=post`, `<video controls>` for `type=reel`) pointed at `asset_url`, the `caption`, the `hashtags` list, and Approve/Reject buttons. Style it plainly — this is a private single-user utility page, not a polished product.

- [ ] **Step 3: Wire Approve/Reject to persisted state**

Following the loaded `artifact-capabilities` skill's current guidance, wire each button to write that item's decision (`approved`/`rejected`) to the artifact's persisted state, keyed by item `id`. Do not guess at capability names or call signatures not confirmed by the skill.

- [ ] **Step 4: Publish the artifact**

Use the Artifact tool with `file_path` set to `review_page.html`, an appropriate `favicon`, a `description`, and the `capabilities` object the loaded skill specifies.

- [ ] **Step 5: Verify manually**

Open the published URL. Approve one item and reject another. Confirm (using the loaded skill's guidance for reading state back) that both decisions are readable — this is what Task 12's approval-sync step will read.

---

### Task 12: Scheduled routines

**Files:** None (configuration via the `schedule` skill, not source files in this repo)

**Interfaces:**
- Consumes: `pipeline.generate.generate_week` (Task 7), `pipeline.publish.main` (Task 9), the review Artifact's persisted state (Task 11)

- [ ] **Step 1: Load the `schedule` skill**

Use it to create the scheduled cloud agents below — do not hand-write cron config from memory.

- [ ] **Step 2: Create the weekly Generate routine**

Cron: weekly, Sunday 07:00. Prompt instructs the agent to: run `generate.generate_week(...)` for the coming Mon–Sun with this repo's `repo_owner`/`repo_name`, then (re)publish the Task 11 review Artifact for the new week's `content/queue.json`, then send the user a push notification that the week's batch is ready for review.

- [ ] **Step 3: Create the daily Publish routine — image, 12:00**

Cron: daily, 12:00. Prompt instructs the agent to: first sync approval decisions from the Task 11 Artifact's persisted state into `content/queue.json` (calling `queue_store.update_status` for any item whose stored decision differs from its current `status`), then run `python -m pipeline.publish --type post`.

- [ ] **Step 4: Create the daily Publish routine — reel, 20:00**

Same as Step 3 but `python -m pipeline.publish --type reel`. The approval-sync only needs to run once per day in practice, but repeating it in both routines is simpler and harmless (idempotent — re-writing the same status is a no-op).

- [ ] **Step 5: Store secrets in the routines' secret configuration**

`IG_ACCESS_TOKEN`, `IG_BUSINESS_ID`, `ANTHROPIC_API_KEY`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME`, and git push credentials for the asset repo — per the loaded `schedule` skill's mechanism for routine secrets. Never in a committed file.

- [ ] **Step 6: Verify routines are listed**

Use `schedule`'s list capability to confirm all three routines (1 weekly, 2 daily) exist with the correct cron expressions and next-run times.

---

### Task 13: End-to-end dry-run and manual smoke test

**Files:** None (verification only)

- [ ] **Step 1: Dry-run the full generate → review → publish loop locally**

```bash
python -c "
from datetime import date
from pathlib import Path
from pipeline import generate
generate.generate_week(
    start_date=date.today(), queue_path=Path('content/queue.json'),
    work_dir=Path('.work'), repo_root=Path('.'),
    repo_owner='<owner>', repo_name='<repo>', audio_path=Path('<royalty-free-audio.mp3>'),
)
"
```

Expected: 14 new entries in `content/queue.json`, 14 new files under `content/assets/`, all pushed to the public GitHub repo.

- [ ] **Step 2: Manually approve one post item**

Open the Task 11 Artifact, approve today's `post` item, reject or ignore the rest.

- [ ] **Step 3: Dry-run publish**

```bash
python -m pipeline.publish --type post --dry-run
```

Expected: `[dry-run] would publish post id=... asset=... caption=...` — confirms the sync + selection logic picks the right item without calling the live Graph API.

- [ ] **Step 4: One real manual post**

```bash
python -m pipeline.publish --type post
```

Expected: item status becomes `posted` in `content/queue.json`, and the post is visible on the actual Instagram account. This is the one live-API call in this entire plan that isn't behind a test double — verify it by checking the app, not just the exit code.

- [ ] **Step 5: Confirm the full week runs unattended for the remainder of the current week**

No further action — the two daily Publish routines should now post the remaining approved items on schedule. Check back in a few days that `content/queue.json` shows `posted` entries advancing day by day.

---

## Self-Review Notes

- **Spec coverage:** every design-doc section maps to a task — content model (Tasks 3–5), architecture/two-phase split (Tasks 7, 9, 12), asset hosting (Task 6), credentials (Task 10), review Artifact (Task 11), error handling (Tasks 8–9's `GraphAPIError` propagation + Global Constraints), testing (`--dry-run` in Task 9, smoke test in Task 13), setup scope (Task 10).
- **Placeholder scan:** no TBD/TODO; Tasks 11 and 12 intentionally defer exact capability/cron syntax to their respective skills per those skills' own "load before writing" requirement — this is delegation, not an unresolved placeholder, and every other step in those tasks has concrete content.
- **Type consistency:** checked `queue_store`, `image_gen`, `reel_builder`, `captions`, `asset_host`, `graph_api`, `generate`, and `publish` signatures across all "Consumes"/"Produces" blocks — names and parameters match where each module is used by a later task.
