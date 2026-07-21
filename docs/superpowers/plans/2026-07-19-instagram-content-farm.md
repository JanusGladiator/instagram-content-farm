# Instagram Content Farm Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automated pipeline that generates a week of Instagram content (broad relatable/internet-culture humor, mixed across original AI-generated / meme-template / apileague.com-repost sources, 1 post + 1 reel per day), lets the user approve the whole week in one sitting, then publishes autonomously via the official Meta Graph API with no further human interaction that week.

**Architecture:** Two scheduled phases sharing a flat-file queue (`content/queue.json`). A weekly Generate routine creates 14 content items — each assigned a `source` (`original | template | repost`, repost restricted to post slots only) from a fixed rotation — and a review Artifact page. A daily Publish routine (fires twice: image at 12:00, reel at 20:00) posts whatever is approved for that day via the Instagram Graph API, identically regardless of source. See `docs/superpowers/specs/2026-07-19-instagram-content-farm-design.md` for the approved design.

**Tech Stack:** Python 3.11+, `requests`, system `ffmpeg` binary, `pytest`, git/GitHub (public repo, raw-URL asset hosting), apileague.com Random Meme API (`X-API-Key` header), Imgflip public template API, Claude Code scheduled routines (the Generate routine's own reasoning does caption/hashtag/meme-text writing — no `anthropic` SDK dependency), Artifact `downloads` capability.

## Global Constraints

- Official Meta Graph API only — no unofficial/private IG API libraries, no browser automation (spec: "Hard Constraint: Official API Only").
- `original` images via Pollinations.ai (free, no key). `template` blanks via Imgflip's public `get_memes` endpoint (free, no key). `repost` via apileague.com's free-tier Random Meme API (`X-API-Key` header, 50 requests/day).
- Reel audio (for `original`/`template` sources) must be royalty-free (Pixabay Audio / YouTube Audio Library or equivalent) — never pulled from Instagram's in-app audio library (unreachable via API anyway). `repost` items are always post slots, never reels, so this doesn't apply to them.
- `SOURCE_PLAN = ["repost","original","original","template","template","original","repost","template","original","original","template","template","repost","original"]` (14 entries, exact) — `repost` only ever lands on an even index (a post slot, per `source_for_slot`'s `day_index*2 + (0 if post else 1)` formula); posts are 3 repost/2 original/2 template, reels are 4 original/3 template. Do not rebalance without updating this plan.
- `repost` has **no server-side NSFW filter** (the API exposes no such field) — content safety for this source relies entirely on the existing weekly human review step, not automated filtering. A `repost` meme whose `type` isn't `image/*` is rejected (marked seen, slot falls back to `original`) rather than posted with a wrong extension.
- No `ANTHROPIC_API_KEY`/Anthropic SDK dependency anywhere in `pipeline/` — the weekly Generate routine is itself a Claude Code agent, and writes every slot's caption/hashtags (plus top/bottom meme text for `template`-planned slots) itself as part of its own turn, following `pipeline/captions.py`'s guideline constants, then passes the result to `generate.generate_week(..., content_plan=...)`. `content_plan` must have an entry for **every** one of the 14 slots, including `repost`-planned ones (needed as their `original` fallback) — `generate_week` raises `KeyError` on a missing entry, by design, rather than silently skipping a slot. `repost` items' captions are the fetched meme's own description, not part of `content_plan` and not LLM-rewritten (unknown until runtime fetch; skipping the rewrite also removes that path's prompt-injection surface entirely rather than merely mitigating it).
- `reddit_source.py` and `imgur_source.py` are dormant (both platforms closed API registration for this use case — see spec's "Repost Sourcing history"), fully tested, kept in the codebase; `generate.py` imports and calls neither.
- Secrets (`IG_ACCESS_TOKEN`, `IG_BUSINESS_ID`, `APILEAGUE_API_KEY`, GitHub push credentials) are environment variables only — never hardcoded, never committed. `.gitignore` already excludes `.env*`. (`REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`IMGUR_CLIENT_ID` are also not used by the active pipeline.)
- `content/queue.json` is the single source of truth for what gets published; nothing auto-posts without `status == "approved"` on the correct `scheduled_date`. `publish.py` treats every source identically, active or dormant — it only ever reads `asset_url` and `caption`.
- A `pending` item at its scheduled publish time is skipped and logged, never force-posted, never re-prompted.
- No test may hit a live external API (Pollinations, Imgflip, apileague.com, Graph API) or perform a real `git push`/`ffmpeg` binary invocation — all external calls are injected via a `session`/`runner`/`client` parameter and replaced with fakes in tests.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `pipeline/__init__.py`
- Create: `content/queue.json`
- Create: `content/assets/.gitkeep`
- Create: `content/reddit_seen.json`
- Create: `.env.example`

**Interfaces:**
- Produces: `pipeline` package importable as `pipeline.*` from repo root; `content/queue.json` and `content/reddit_seen.json` seeded as `[]`.

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

- [ ] **Step 4: Seed the empty queue and the Reddit dedupe list**

Write `content/queue.json`:

```json
[]
```

Write `content/reddit_seen.json`:

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
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=
```

- [ ] **Step 7: Install dependencies and verify pytest collects cleanly**

Run: `pip install -r requirements.txt && pytest`
Expected: `no tests ran` (0 collected, exit code 0 — some pytest versions report `no tests ran` with exit code 5, which is fine at this stage)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt pipeline/__init__.py content/queue.json content/reddit_seen.json content/assets/.gitkeep .env.example
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
  - `new_item(*, type_: str, source: str, scheduled_date: str, asset_url: str, caption: str, hashtags: list[str]) -> dict`
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_queue_store.py -v`
Expected: PASS (9 passed)

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

Used by the `original` source (2 AI shots: setup + punchline) and the `template` source (same rendered template image passed twice). Not used by `repost` — a repost video is used directly as the reel asset. Text is overlaid only during `[0, hook_seconds]` — the algorithm decides whether to distribute a Reel based on the first 1-3 seconds, so the hook must land immediately rather than fading in over the whole clip.

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

### Task 5: Caption, hashtag, and meme-text generator

**Files:**
- Create: `pipeline/captions.py`
- Test: `tests/test_captions.py`

**Interfaces:**
- Produces: `CaptionGenError(RuntimeError)`, `generate_caption(concept: str, *, client=None, model: str = "claude-sonnet-5") -> dict` returning `{"caption": str, "hashtags": list[str]}`; `generate_meme_text(concept: str, *, client=None, model: str = "claude-sonnet-5") -> dict` returning `{"top": str, "bottom": str}`

`generate_caption` is used by every source (the IG caption below the post). `generate_meme_text` is used only by the `template` source (the text baked onto the meme image itself). For `repost`, the caller passes `generate_caption` a concept string built from the Reddit post's own title (polished for shareability, meaning preserved) rather than a `THEMES` entry — no code change needed here, just how Task 9 invokes it.

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
    client = FakeClient('{"caption": "lol", "hashtags": ["relatable", "meme"]}')

    result = captions.generate_caption("a relatable moment", client=client)

    assert result == {"caption": "lol", "hashtags": ["relatable", "meme"]}
    assert client.messages.last_kwargs["model"] == "claude-sonnet-5"


def test_generate_caption_raises_on_invalid_json():
    client = FakeClient("not json")

    with pytest.raises(captions.CaptionGenError):
        captions.generate_caption("a relatable moment", client=client)


def test_generate_caption_raises_on_missing_keys():
    client = FakeClient('{"caption": "lol"}')

    with pytest.raises(captions.CaptionGenError):
        captions.generate_caption("a relatable moment", client=client)


def test_generate_meme_text_parses_valid_json():
    client = FakeClient('{"top": "when the alarm goes off", "bottom": "and it is monday"}')

    result = captions.generate_meme_text("monday dread", client=client)

    assert result == {"top": "when the alarm goes off", "bottom": "and it is monday"}


def test_generate_meme_text_raises_on_missing_keys():
    client = FakeClient('{"top": "only top"}')

    with pytest.raises(captions.CaptionGenError):
        captions.generate_meme_text("monday dread", client=client)
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

MEME_TEXT_PROMPT = """Write top and bottom text for a meme image about this concept.
Concept: {concept}

Respond with ONLY valid JSON: {{"top": "...", "bottom": "..."}}
Keep each line short (under 8 words), classic meme format (setup on top,
punchline on bottom)."""


class CaptionGenError(RuntimeError):
    pass


def _generate_json(prompt: str, *, client=None, model: str, max_tokens: int,
                    required_keys: set[str]) -> dict:
    client = client or Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CaptionGenError(f"model did not return valid JSON: {raw!r}") from exc

    missing = required_keys - data.keys()
    if missing:
        raise CaptionGenError(f"missing keys in model response: {data!r}")

    return data


def generate_caption(concept: str, *, client=None, model: str = "claude-sonnet-5") -> dict:
    data = _generate_json(
        CAPTION_PROMPT.format(concept=concept), client=client, model=model,
        max_tokens=300, required_keys={"caption", "hashtags"},
    )
    return {"caption": data["caption"], "hashtags": list(data["hashtags"])}


def generate_meme_text(concept: str, *, client=None, model: str = "claude-sonnet-5") -> dict:
    data = _generate_json(
        MEME_TEXT_PROMPT.format(concept=concept), client=client, model=model,
        max_tokens=150, required_keys={"top", "bottom"},
    )
    return {"top": data["top"], "bottom": data["bottom"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_captions.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/captions.py tests/test_captions.py
git commit -m "feat: add Claude-backed caption, hashtag, and meme-text generator"
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

### Task 7: Template source (Imgflip)

**Files:**
- Create: `pipeline/template_source.py`
- Test: `tests/test_template_source.py`

**Interfaces:**
- Produces: `TemplateSourceError(RuntimeError)`, `list_templates(*, session=None) -> list[dict]`, `pick_template(templates: list[dict], day_index: int) -> dict`, `download_template_image(template: dict, out_path: Path, *, session=None) -> Path`, `render_caption_on_template(template_image: Path, top_text: str, bottom_text: str, out_path: Path, *, runner=subprocess.run) -> Path`

- [ ] **Step 1: Write failing tests**

Create `tests/test_template_source.py`:

```python
from pathlib import Path
import pytest
from pipeline import template_source


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, url, timeout=None):
        return self.responses.pop(0)


def test_list_templates_returns_meme_list_on_success():
    body = {"success": True, "data": {"memes": [{"id": "1", "url": "http://x/1.jpg"}]}}
    session = FakeSession([FakeResponse(200, body=body)])

    result = template_source.list_templates(session=session)

    assert result == [{"id": "1", "url": "http://x/1.jpg"}]


def test_list_templates_raises_on_failure():
    session = FakeSession([FakeResponse(200, body={"success": False})])

    with pytest.raises(template_source.TemplateSourceError):
        template_source.list_templates(session=session)


def test_pick_template_cycles_by_day_index():
    templates = [{"id": "1"}, {"id": "2"}]

    assert template_source.pick_template(templates, 0)["id"] == "1"
    assert template_source.pick_template(templates, 1)["id"] == "2"
    assert template_source.pick_template(templates, 2)["id"] == "1"


def test_pick_template_raises_on_empty_list():
    with pytest.raises(template_source.TemplateSourceError):
        template_source.pick_template([], 0)


def test_download_template_image_writes_file(tmp_path):
    session = FakeSession([FakeResponse(200, content=b"blank-template-bytes")])
    out_path = tmp_path / "blank.jpg"

    result = template_source.download_template_image(
        {"id": "1", "url": "http://x/1.jpg"}, out_path, session=session,
    )

    assert result == out_path
    assert out_path.read_bytes() == b"blank-template-bytes"


def test_download_template_image_raises_on_failure(tmp_path):
    session = FakeSession([FakeResponse(404)])

    with pytest.raises(template_source.TemplateSourceError):
        template_source.download_template_image(
            {"id": "1", "url": "http://x/1.jpg"}, tmp_path / "blank.jpg", session=session,
        )


class FakeCompletedProcess:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_render_caption_on_template_returns_out_path_on_success(tmp_path):
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append(command)
        return FakeCompletedProcess(returncode=0)

    out_path = tmp_path / "out.jpg"
    result = template_source.render_caption_on_template(
        tmp_path / "blank.jpg", "top text", "bottom text", out_path, runner=fake_runner,
    )

    assert result == out_path
    assert calls[0][0] == "ffmpeg"


def test_render_caption_on_template_raises_on_nonzero_returncode(tmp_path):
    def fake_runner(command, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="render boom")

    with pytest.raises(template_source.TemplateSourceError, match="render boom"):
        template_source.render_caption_on_template(
            tmp_path / "blank.jpg", "top", "bottom", tmp_path / "out.jpg", runner=fake_runner,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_template_source.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/template_source.py`**

```python
import subprocess
from pathlib import Path

import requests

IMGFLIP_TEMPLATES_URL = "https://api.imgflip.com/get_memes"


class TemplateSourceError(RuntimeError):
    pass


def list_templates(*, session=None) -> list[dict]:
    session = session or requests.Session()
    response = session.get(IMGFLIP_TEMPLATES_URL, timeout=30)
    body = response.json()
    if response.status_code != 200 or not body.get("success"):
        raise TemplateSourceError(f"imgflip template list failed: {body}")
    return body["data"]["memes"]


def pick_template(templates: list[dict], day_index: int) -> dict:
    if not templates:
        raise TemplateSourceError("no templates available")
    return templates[day_index % len(templates)]


def download_template_image(template: dict, out_path: Path, *, session=None) -> Path:
    session = session or requests.Session()
    response = session.get(template["url"], timeout=60)
    if response.status_code != 200:
        raise TemplateSourceError(
            f"failed to download template {template['id']}: status {response.status_code}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(response.content)
    return out_path


def render_caption_on_template(template_image: Path, top_text: str, bottom_text: str,
                                out_path: Path, *, runner=subprocess.run) -> Path:
    def _escape(text: str) -> str:
        return text.replace(":", r"\:").replace("'", r"\'").upper()

    top_draw = (
        f"drawtext=text='{_escape(top_text)}':fontcolor=white:fontsize=48:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=20"
    )
    bottom_draw = (
        f"drawtext=text='{_escape(bottom_text)}':fontcolor=white:fontsize=48:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-th-20"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-i", str(template_image),
        "-vf", f"{top_draw},{bottom_draw}",
        "-frames:v", "1",
        str(out_path),
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise TemplateSourceError(f"template render failed: {result.stderr}")
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_template_source.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/template_source.py tests/test_template_source.py
git commit -m "feat: add Imgflip-backed template_source module"
```

---

### Task 8: Reddit source (repost sourcing)

**Files:**
- Create: `pipeline/reddit_source.py`
- Test: `tests/test_reddit_source.py`

**Interfaces:**
- Produces: `RedditSourceError(RuntimeError)`, `get_access_token(client_id: str, client_secret: str, user_agent: str, *, session=None) -> str`, `fetch_top_posts(subreddit: str, access_token: str, user_agent: str, *, limit: int = 25, timeframe: str = "week", session=None) -> list[dict]`, `pick_post(posts: list[dict], *, media_kind: str, min_upvotes: int, seen_ids: set[str]) -> dict | None`, `download_image_post(post: dict, out_path: Path, *, session=None) -> Path`, `download_video_post(post: dict, out_path: Path, *, session=None, runner=subprocess.run) -> Path`, `load_seen_ids(path: Path) -> set[str]`, `mark_seen(path: Path, post_id: str) -> None`

`media_kind` is `"image"` or `"video"` — Task 9 passes `"image"` for post slots and `"video"` for reel slots.

- [ ] **Step 1: Write failing tests**

Create `tests/test_reddit_source.py`:

```python
from pathlib import Path
import pytest
from pipeline import reddit_source


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


def test_get_access_token_returns_token_on_success():
    session = FakeSession([FakeResponse(200, body={"access_token": "tok123"})])

    token = reddit_source.get_access_token("id", "secret", "ua/1.0", session=session)

    assert token == "tok123"


def test_get_access_token_raises_on_failure():
    session = FakeSession([FakeResponse(401, body={"error": "bad"})])

    with pytest.raises(reddit_source.RedditSourceError):
        reddit_source.get_access_token("id", "secret", "ua/1.0", session=session)


def test_fetch_top_posts_returns_children_data():
    body = {"data": {"children": [{"data": {"id": "a"}}, {"data": {"id": "b"}}]}}
    session = FakeSession([FakeResponse(200, body=body)])

    posts = reddit_source.fetch_top_posts("memes", "tok", "ua/1.0", session=session)

    assert posts == [{"id": "a"}, {"id": "b"}]


def test_fetch_top_posts_raises_on_error_status():
    session = FakeSession([FakeResponse(403, body={"error": "forbidden"})])

    with pytest.raises(reddit_source.RedditSourceError):
        reddit_source.fetch_top_posts("memes", "tok", "ua/1.0", session=session)


def _post(id_, *, ups=1000, over_18=False, post_hint="image", is_video=False):
    return {"id": id_, "ups": ups, "over_18": over_18, "post_hint": post_hint, "is_video": is_video}


def test_pick_post_skips_seen_ids():
    posts = [_post("a"), _post("b")]
    result = reddit_source.pick_post(posts, media_kind="image", min_upvotes=0, seen_ids={"a"})
    assert result["id"] == "b"


def test_pick_post_skips_nsfw():
    posts = [_post("a", over_18=True), _post("b")]
    result = reddit_source.pick_post(posts, media_kind="image", min_upvotes=0, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_skips_below_min_upvotes():
    posts = [_post("a", ups=10), _post("b", ups=1000)]
    result = reddit_source.pick_post(posts, media_kind="image", min_upvotes=500, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_filters_by_media_kind_video():
    posts = [
        _post("a", post_hint="image", is_video=False),
        _post("b", post_hint="hosted:video", is_video=True),
    ]
    result = reddit_source.pick_post(posts, media_kind="video", min_upvotes=0, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_returns_none_when_no_match():
    posts = [_post("a", ups=0)]
    result = reddit_source.pick_post(posts, media_kind="image", min_upvotes=500, seen_ids=set())
    assert result is None


def test_download_image_post_writes_file(tmp_path):
    session = FakeSession([FakeResponse(200, content=b"image-bytes")])
    out_path = tmp_path / "post.jpg"

    result = reddit_source.download_image_post(
        {"id": "a", "url": "http://x/a.jpg"}, out_path, session=session,
    )

    assert result == out_path
    assert out_path.read_bytes() == b"image-bytes"


class FakeCompletedProcess:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_download_video_post_merges_audio_when_present(tmp_path):
    session = FakeSession([
        FakeResponse(200, content=b"video-bytes"),
        FakeResponse(200, content=b"audio-bytes"),
    ])
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append(command)
        Path(command[-1]).write_bytes(b"merged")
        return FakeCompletedProcess(returncode=0)

    post = {
        "id": "a",
        "media": {"reddit_video": {"fallback_url": "http://v.redd.it/a/DASH_720.mp4"}},
    }
    out_path = tmp_path / "post.mp4"

    result = reddit_source.download_video_post(post, out_path, session=session, runner=fake_runner)

    assert result == out_path
    assert len(calls) == 1
    assert calls[0][0] == "ffmpeg"


def test_download_video_post_falls_back_to_video_only_when_no_audio(tmp_path):
    session = FakeSession([
        FakeResponse(200, content=b"video-bytes"),
        FakeResponse(404),
    ])
    post = {
        "id": "a",
        "media": {"reddit_video": {"fallback_url": "http://v.redd.it/a/DASH_720.mp4"}},
    }
    out_path = tmp_path / "post.mp4"

    result = reddit_source.download_video_post(post, out_path, session=session)

    assert result == out_path
    assert out_path.read_bytes() == b"video-bytes"


def test_load_seen_ids_empty_when_missing(tmp_path):
    assert reddit_source.load_seen_ids(tmp_path / "seen.json") == set()


def test_mark_seen_persists_and_dedupes(tmp_path):
    path = tmp_path / "seen.json"

    reddit_source.mark_seen(path, "a")
    reddit_source.mark_seen(path, "b")
    reddit_source.mark_seen(path, "a")

    assert reddit_source.load_seen_ids(path) == {"a", "b"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reddit_source.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/reddit_source.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reddit_source.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reddit_source.py tests/test_reddit_source.py
git commit -m "feat: add Reddit-backed repost sourcing module"
```

---

### Task 9: Weekly generate orchestrator

**Files:**
- Create: `pipeline/generate.py`
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: `queue_store.new_item`, `queue_store.append_item` (Task 2); `image_gen.generate_image` (Task 3); `reel_builder.build_reel(image_paths, audio_path, text, out_path, **kw)` (Task 4); `captions.generate_caption`, `captions.generate_meme_text` (Task 5); `asset_host.publish_asset` (Task 6); `template_source.list_templates`, `template_source.pick_template`, `template_source.download_template_image`, `template_source.render_caption_on_template` (Task 7); `reddit_source.fetch_top_posts`, `reddit_source.load_seen_ids`, `reddit_source.pick_post`, `reddit_source.download_image_post`, `reddit_source.download_video_post`, `reddit_source.mark_seen` (Task 8)
- Produces: `THEMES: list[str]`, `SOURCE_PLAN: list[str]`, `SUBREDDITS: list[str]`, `MIN_UPVOTES: int`, `pick_theme(day_index: int) -> str`, `source_for_slot(day_index: int, slot_type: str) -> str`, `generate_week(*, start_date: date, queue_path: Path, work_dir: Path, repo_root: Path, repo_owner: str, repo_name: str, audio_path: Path, reddit_access_token: str, reddit_user_agent: str, seen_path: Path) -> list[dict]`

Themes are broad, general relatable-humor concepts (daily life, work, phone/group-chat moments) — not a subject-matter niche. `SOURCE_PLAN` is the exact 14-slot rotation from Global Constraints. Each weekly slot's `source` picks which producer builds its asset; a `repost` slot that finds no qualifying Reddit post falls back to `original` for that slot (Global Constraints).

- [ ] **Step 1: Write failing tests**

Create `tests/test_generate.py`:

```python
from datetime import date
from pathlib import Path

from pipeline import generate, queue_store


def test_pick_theme_cycles_through_themes():
    assert generate.pick_theme(0) == generate.THEMES[0]
    assert generate.pick_theme(len(generate.THEMES)) == generate.THEMES[0]


def test_source_for_slot_matches_source_plan():
    assert generate.source_for_slot(0, "post") == "original"
    assert generate.source_for_slot(0, "reel") == "template"
    assert generate.source_for_slot(1, "post") == "repost"


def _patch_all_producers(monkeypatch, *, repost_post):
    monkeypatch.setattr(generate.image_gen, "generate_image",
                         lambda prompt, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reel_builder, "build_reel",
                         lambda image_paths, audio_path, text, out_path, **kw: out_path)
    monkeypatch.setattr(generate.captions, "generate_caption",
                         lambda concept, **kw: {"caption": "cap", "hashtags": ["h"]})
    monkeypatch.setattr(generate.captions, "generate_meme_text",
                         lambda concept, **kw: {"top": "T", "bottom": "B"})
    monkeypatch.setattr(generate.template_source, "list_templates",
                         lambda **kw: [{"id": "1", "url": "http://x/blank.jpg"}])
    monkeypatch.setattr(generate.template_source, "pick_template",
                         lambda templates, day_index: templates[0])
    monkeypatch.setattr(generate.template_source, "download_template_image",
                         lambda template, out_path, **kw: out_path)
    monkeypatch.setattr(generate.template_source, "render_caption_on_template",
                         lambda blank_path, top, bottom, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reddit_source, "fetch_top_posts",
                         lambda subreddit, token, ua, **kw: [{"id": "abc", "title": "funny thing"}])
    monkeypatch.setattr(generate.reddit_source, "load_seen_ids", lambda path: set())
    monkeypatch.setattr(
        generate.reddit_source, "pick_post",
        lambda posts, *, media_kind, min_upvotes, seen_ids: (posts[0] if repost_post else None),
    )
    monkeypatch.setattr(generate.reddit_source, "download_image_post",
                         lambda post, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reddit_source, "download_video_post",
                         lambda post, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reddit_source, "mark_seen", lambda path, post_id: None)
    monkeypatch.setattr(
        generate.asset_host, "publish_asset",
        lambda local_path, repo_root, relative_dest, **kw:
            f"https://raw.githubusercontent.com/me/repo/master/{relative_dest}",
    )


def _run_generate_week(tmp_path):
    return generate.generate_week(
        start_date=date(2026, 7, 20),
        queue_path=tmp_path / "queue.json",
        work_dir=tmp_path / "work",
        repo_root=tmp_path / "repo",
        repo_owner="me", repo_name="repo",
        audio_path=tmp_path / "audio.mp3",
        reddit_access_token="token", reddit_user_agent="ua/1.0",
        seen_path=tmp_path / "reddit_seen.json",
    )


def test_generate_week_creates_14_items_with_correct_sources_and_dates(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_post=True)

    created = _run_generate_week(tmp_path)

    assert len(created) == 14
    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert len(loaded) == 14

    ordered = sorted(loaded, key=lambda i: (i["scheduled_date"], i["type"] == "reel"))
    assert [i["source"] for i in ordered] == generate.SOURCE_PLAN

    post_dates = sorted(i["scheduled_date"] for i in loaded if i["type"] == "post")
    assert post_dates == [
        "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26",
    ]
    assert all(i["status"] == "pending" for i in loaded)


def test_generate_week_falls_back_to_original_when_repost_unavailable(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_post=False)

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)
    expected_original_count = (
        generate.SOURCE_PLAN.count("original") + generate.SOURCE_PLAN.count("repost")
    )
    assert sum(1 for i in loaded if i["source"] == "original") == expected_original_count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/generate.py`**

```python
from datetime import date, timedelta
from pathlib import Path

from pipeline import (
    asset_host,
    captions,
    image_gen,
    queue_store,
    reddit_source,
    reel_builder,
    template_source,
)

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

SUBREDDITS = ["memes", "funny", "wholesomememes", "AdviceAnimals", "mildlyinteresting"]
MIN_UPVOTES = 500

# 14 slots = 7 days x (post, reel). 5 original / 5 template / 4 repost.
SOURCE_PLAN = [
    "original", "template", "repost", "original", "template",
    "repost", "original", "template", "repost", "original",
    "template", "repost", "original", "template",
]


def pick_theme(day_index: int) -> str:
    return THEMES[day_index % len(THEMES)]


def source_for_slot(day_index: int, slot_type: str) -> str:
    slot_index = day_index * 2 + (0 if slot_type == "post" else 1)
    return SOURCE_PLAN[slot_index % len(SOURCE_PLAN)]


def _produce_original(*, slot_type: str, theme: str, work_dir: Path,
                       day_label: str, audio_path: Path) -> tuple[Path, dict]:
    caption = captions.generate_caption(theme)

    if slot_type == "post":
        image_path = work_dir / f"{day_label}-post-original.jpg"
        image_gen.generate_image(theme, image_path)
        return image_path, caption

    reel_image_paths = []
    for shot_index, variant in enumerate(REEL_SHOT_VARIANTS):
        reel_image = work_dir / f"{day_label}-reel-original-{shot_index}.jpg"
        image_gen.generate_image(f"{theme}, {variant}", reel_image)
        reel_image_paths.append(reel_image)

    reel_video = work_dir / f"{day_label}-reel-original.mp4"
    reel_builder.build_reel(reel_image_paths, audio_path, caption["caption"], reel_video)
    return reel_video, caption


def _produce_template(*, slot_type: str, theme: str, work_dir: Path, day_label: str,
                       audio_path: Path, templates: list[dict], day_index: int) -> tuple[Path, dict]:
    caption = captions.generate_caption(theme)
    meme_text = captions.generate_meme_text(theme)
    chosen_template = template_source.pick_template(templates, day_index)

    blank_path = work_dir / f"{day_label}-{slot_type}-template-blank.jpg"
    template_source.download_template_image(chosen_template, blank_path)

    rendered_path = work_dir / f"{day_label}-{slot_type}-template.jpg"
    template_source.render_caption_on_template(
        blank_path, meme_text["top"], meme_text["bottom"], rendered_path,
    )

    if slot_type == "post":
        return rendered_path, caption

    reel_video = work_dir / f"{day_label}-reel-template.mp4"
    reel_builder.build_reel([rendered_path, rendered_path], audio_path,
                             caption["caption"], reel_video)
    return reel_video, caption


def _produce_repost(*, slot_type: str, work_dir: Path, day_label: str, subreddit: str,
                     access_token: str, user_agent: str, seen_path: Path) -> tuple[Path, dict] | None:
    posts = reddit_source.fetch_top_posts(subreddit, access_token, user_agent)
    seen_ids = reddit_source.load_seen_ids(seen_path)
    media_kind = "image" if slot_type == "post" else "video"
    post = reddit_source.pick_post(posts, media_kind=media_kind,
                                    min_upvotes=MIN_UPVOTES, seen_ids=seen_ids)
    if post is None:
        return None

    caption = captions.generate_caption(
        "polish this into a punchy shareable caption without changing its "
        f"meaning: {post['title']}"
    )

    if slot_type == "post":
        asset_path = work_dir / f"{day_label}-post-repost.jpg"
        reddit_source.download_image_post(post, asset_path)
    else:
        asset_path = work_dir / f"{day_label}-reel-repost.mp4"
        reddit_source.download_video_post(post, asset_path)

    reddit_source.mark_seen(seen_path, post["id"])
    return asset_path, caption


def generate_week(*, start_date: date, queue_path: Path, work_dir: Path,
                   repo_root: Path, repo_owner: str, repo_name: str,
                   audio_path: Path, reddit_access_token: str,
                   reddit_user_agent: str, seen_path: Path) -> list[dict]:
    work_dir.mkdir(parents=True, exist_ok=True)
    created = []
    templates = template_source.list_templates()

    for offset in range(7):
        day = start_date + timedelta(days=offset)
        day_label = day.isoformat()
        theme = pick_theme(offset)
        subreddit = SUBREDDITS[offset % len(SUBREDDITS)]

        for slot_type in ("post", "reel"):
            source = source_for_slot(offset, slot_type)
            result = None

            if source == "template":
                result = _produce_template(
                    slot_type=slot_type, theme=theme, work_dir=work_dir,
                    day_label=day_label, audio_path=audio_path,
                    templates=templates, day_index=offset,
                )
            elif source == "repost":
                result = _produce_repost(
                    slot_type=slot_type, work_dir=work_dir, day_label=day_label,
                    subreddit=subreddit, access_token=reddit_access_token,
                    user_agent=reddit_user_agent, seen_path=seen_path,
                )
                if result is None:
                    source = "original"

            if source == "original":
                result = _produce_original(
                    slot_type=slot_type, theme=theme, work_dir=work_dir,
                    day_label=day_label, audio_path=audio_path,
                )

            asset_local_path, caption = result
            relative_dest = f"content/assets/{asset_local_path.name}"
            asset_url = asset_host.publish_asset(
                asset_local_path, repo_root, relative_dest,
                repo_owner=repo_owner, repo_name=repo_name,
            )
            item = queue_store.new_item(
                type_=slot_type, source=source, scheduled_date=day_label,
                asset_url=asset_url, caption=caption["caption"],
                hashtags=caption["hashtags"],
            )
            queue_store.append_item(queue_path, item)
            created.append(item)

    return created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/generate.py tests/test_generate.py
git commit -m "feat: add weekly generate orchestrator with source dispatch"
```

---

### Task 10: Graph API client

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
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/graph_api.py tests/test_graph_api.py
git commit -m "feat: add Instagram Graph API client"
```

---

### Task 11: Daily publish orchestrator

**Files:**
- Create: `pipeline/publish.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `queue_store.load_queue`, `queue_store.get_item_for_date`, `queue_store.update_status`, `queue_store.new_item` (Task 2); `graph_api.create_image_container`, `graph_api.create_reel_container`, `graph_api.wait_for_container_ready`, `graph_api.publish_container` (Task 10)
- Produces: `PublishSkipped(Exception)`, `publish_today(*, item_type: str, queue_path: Path, ig_business_id: str, access_token: str, today: date | None = None, dry_run: bool = False) -> dict`, CLI `main()`

`publish_today` is source-agnostic — it never reads or branches on `source`; both `create_image_container`/`create_reel_container` calls use whatever `asset_url` is on the approved queue item, regardless of whether that asset came from Pollinations, Imgflip, or Reddit.

- [ ] **Step 1: Write failing tests**

Create `tests/test_publish.py`:

```python
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

### Task 12: Meta Developer App + long-lived access token

**Files:** None (external setup + verification using Task 10's `verify_credentials`)

**Interfaces:**
- Consumes: `graph_api.verify_credentials` (Task 10)
- Produces: working `IG_ACCESS_TOKEN` and `IG_BUSINESS_ID` values for use by Tasks 11, 15, 16

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

Set `IG_ACCESS_TOKEN` and `IG_BUSINESS_ID` locally for smoke-testing now; Task 15 configures the same values in the scheduled routine's secret store.

- [ ] **Step 7: Verify with Task 10's client**

Run: `python -m pipeline.graph_api`
Expected: `OK - connected as @<your account username>`

- [ ] **Step 8: Note the token expiry**

Long-lived tokens expire ~60 days. There is no code task for renewal in this plan (YAGNI at this stage) — the Publish routine fails loudly with a `GraphAPIError` on an expired token (per Global Constraints), which is the signal to redo Steps 3–5.

---

### Task 13: Reddit API app setup — DROPPED

Reddit closed new-app registration on its legacy Data API to moderation-only
use cases in late 2025; this project doesn't qualify and isn't pursuing it
further (see spec's "Imgur Sourcing" section). Superseded by Task 17/18
(Imgur). Kept below as a historical record; do not execute.

**Files:** None (external setup + verification using Task 8's `get_access_token`/`fetch_top_posts`)

**Interfaces:**
- Consumes: `reddit_source.get_access_token`, `reddit_source.fetch_top_posts` (Task 8)
- Produces: working `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` values for use by Tasks 9, 15, 16

- [ ] **Step 1: Create a Reddit script app**

Go to `reddit.com/prefs/apps` (logged into any Reddit account — a personal account is fine, this is read-only) → "create another app..." → type **script** → name it (e.g. the IG account's handle) → redirect URI can be `http://localhost` (unused for `client_credentials`).

- [ ] **Step 2: Collect the credentials**

The string under the app name is `REDDIT_CLIENT_ID`; "secret" is `REDDIT_CLIENT_SECRET`. Set `REDDIT_USER_AGENT` to a descriptive string per Reddit's API rules, e.g. `instagram-content-farm/1.0 by u/<your-reddit-username>`.

- [ ] **Step 3: Verify with Task 8's client**

```bash
python -c "
import os
from pipeline import reddit_source
token = reddit_source.get_access_token(
    os.environ['REDDIT_CLIENT_ID'], os.environ['REDDIT_CLIENT_SECRET'],
    os.environ['REDDIT_USER_AGENT'],
)
posts = reddit_source.fetch_top_posts('memes', token, os.environ['REDDIT_USER_AGENT'], limit=5)
print(f'OK - fetched {len(posts)} posts, first title: {posts[0][\"title\"]!r}')
"
```

Expected: `OK - fetched 5 posts, first title: '...'`

---

### Task 14: Review Artifact page — COMPLETE (built with a revised mechanism, see below)

**Files:**
- Create: `review_page.html` (source file passed to the Artifact tool; not git-tracked — Artifact publishing is separate from this repo's file set)

**What was actually built, and why it differs from the original plan:** the original Interfaces
line below assumed an Artifact "persisted state" capability that a scheduled routine could read
back automatically. Verified against the real runtime capability contract while building this
task: no such capability exists (only `downloads` and `mcp` are available; no GitHub connector is
connected in this environment for `mcp` to use). See the design doc's "Why not automatic approval
sync" section. The page instead uses `localStorage` for in-browser persistence across reloads,
plus a `downloads`-capability Export button that downloads a copy of `queue.json` with `status`
fields patched from the user's approve/reject clicks. The user hands that exported file back in a
live chat session; Claude commits it over `content/queue.json`. Task 15's routines were revised
accordingly (no sync step).

**Interfaces:**
- Consumes: the week's `content/queue.json` (fetched client-side via its public raw-URL, once the
  content repo exists — the `QUEUE_URL` constant near the top of `review_page.html`'s script needs
  updating from its `OWNER_PLACEHOLDER/REPO_PLACEHOLDER` value to the real `repo_owner`/`repo_name`
  once the GitHub repo is set up, then the artifact republished)
- Produces: a published Artifact URL where the user approves/rejects the week's 14 items; an
  Export button that downloads the patched `queue.json` for manual handoff

Steps actually followed: loaded `artifact-capabilities` (mandatory before any capability code) and
`artifact-design` (layout guidance); wrote the page (thumbnail/video preview, caption, hashtags,
`source` label, grouped by `scheduled_date`, Approve/Reject/reset controls, summary counts, Export
button, graceful empty/unreachable-queue state, light/dark theme support); declared only
`{"downloads": true}` (no `mcp`, since no connector could be observed); published with `favicon`
📋. See `.superpowers/sdd/task-14-report.md` for full detail including the capability-contract
verification.

---

### Task 15: Scheduled routines

**Files:** None (configuration via the `schedule` skill, not source files in this repo)

**Interfaces:**
- Consumes: `pipeline.generate.generate_week` (Task 9), `pipeline.publish.main` (Task 11)

No approval-sync step exists (see Task 14) — by the time the Publish routines run, `content/queue.json` already has final `approved`/`rejected` statuses baked in, because that file *is* the one the user exported and Claude committed. If the user hasn't finished reviewing yet when a Publish run fires, items are still `status=pending` and are correctly skipped (existing behavior in `publish.py`, no special-casing needed here).

**Discovered while building this task, not caught earlier:** cloud routines each run from a fresh git clone — there is no persistent local filesystem between runs. `generate_week`/`publish_today` both write `content/queue.json` (and `generate_week` also writes `content/apileague_seen.json`) as plain local file writes; `asset_host.publish_asset` commits generated *assets*, but nothing in the existing code commits `content/queue.json` itself. Without an explicit `git add/commit/push` of that file at the end of every routine run (Generate and both Publish fires), each run's state changes would silently vanish the moment the session ends, and the next run would see stale data. Every routine's prompt below includes this step explicitly — it is not optional.

**Also discovered:** there is currently no documented/discoverable secrets-store for Claude Code cloud routines (checked both GitHub's repo-level Environments — a different, unrelated system — and claude.ai's own environment settings, per the `schedule` skill's guidance). The only mechanism available is embedding secret values directly in each routine's prompt text, which the `schedule` skill's `RemoteTrigger create` call stores as part of the routine's private config. This is a real, accepted deviation from "never hardcode secrets" — explicit user decision, made because no alternative currently exists on this platform. Revisit if Anthropic adds a proper secrets mechanism for routines.

- [ ] **Step 1: Load the `schedule` skill**

Use it to create the scheduled cloud agents below — do not hand-write cron config from memory.

- [ ] **Step 2: Create the weekly Generate routine**

Cron: weekly, Sunday 07:00. The prompt for this routine must instruct the agent (itself, on that future run) to do all of the following, in order — this is the one routine that requires real reasoning, not just running a script:

1. Read `pipeline/generate.py`'s `THEMES` and `SOURCE_PLAN`, and `pipeline/captions.py`'s `CAPTION_GUIDELINES`/`MEME_TEXT_GUIDELINES`.
2. For each of the 14 slots (`slot_index` 0-13, `day_index = slot_index // 2`, post if `slot_index` is even else reel), write a caption + 5-10 hashtags per `CAPTION_GUIDELINES`, based on `THEMES[day_index % 7]` — do this for **every** slot, including `repost`-planned ones (their entry is the fallback used only if that slot's live fetch fails; it still must exist).
3. For every `slot_index` where `SOURCE_PLAN[slot_index] == "template"`, additionally write top/bottom meme text per `MEME_TEXT_GUIDELINES`, based on the same theme.
4. Ensure `content/audio/background.mp3` exists in the repo (reels need some audio track to mux). If it's missing, generate a short silent placeholder with `ffmpeg -f lavfi -i anullsrc=r=44100:cl=stereo -t 8 -q:a 9 -acodec libmp3lame content/audio/background.mp3` and commit it once — it's reused every week. Note in the run summary that the user can replace this with a real royalty-free track (Pixabay Audio / YouTube Audio Library) anytime by committing over the same path.
5. Assemble the written content into a `content_plan` dict (`{slot_index: {"caption": ..., "hashtags": [...], **({"top": ..., "bottom": ...} if template-planned else {})}}`) and call `generate.generate_week(..., content_plan=content_plan)` for the coming Mon–Sun with this repo's `repo_owner`/`repo_name` and `audio_path=Path('content/audio/background.mp3')`.
6. `git add content/queue.json content/apileague_seen.json && git commit -m "content: weekly batch for <week start date>" && git push` — required, see the note above this step list.
7. (Re)publish the Task 14 review Artifact for the new week's `content/queue.json` (redeploy `review_page.html` to the same Artifact URL — same `file_path` keeps the URL stable).
8. Send the user a push notification that the week's batch is ready for review.

- [ ] **Step 3: Create the daily Publish routine — image, 12:00**

Cron: daily, 12:00. Prompt instructs the agent to run `python -m pipeline.publish --type post` with `IG_ACCESS_TOKEN`/`IG_BUSINESS_ID` set inline (no OS-level env var mechanism exists for routines — see the secrets note above this step list). If the command prints `skip: ...`, nothing was approved for today — that's expected, not an error, stop here. If it succeeds, `git add content/queue.json && git commit -m "publish: mark today's post as posted" && git push` — required, or the status update is lost at session end. If the command raises an error (not the `skip:` case), do not retry silently — report the exact error in the run summary (likely an expired `IG_ACCESS_TOKEN`, ~60 day lifetime).

- [ ] **Step 4: Create the daily Publish routine — reel, 20:00**

Same as Step 3 but `--type reel` and commit message `"publish: mark today's reel as posted"`.

- [ ] **Step 5: Embed secrets in each routine's prompt**

No routine-level secrets store exists (see the note above this step list) — `IG_ACCESS_TOKEN`, `IG_BUSINESS_ID`, `APILEAGUE_API_KEY`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME` are embedded as literal values in each routine's prompt text where needed (Generate needs `APILEAGUE_API_KEY`/`GITHUB_REPO_OWNER`/`GITHUB_REPO_NAME`; both Publish routines need `IG_ACCESS_TOKEN`/`IG_BUSINESS_ID`). No `ANTHROPIC_API_KEY` needed (see Global Constraints). Git push access is provided by the routine's own repo connection (the `sources: git_repository` the routine is configured against) — no separate GitHub token needed unless that turns out not to include write access, in which case add one here too.

- [ ] **Step 6: Verify routines are listed**

Use `schedule`'s list capability to confirm all three routines (1 weekly, 2 daily) exist with the correct cron expressions and next-run times.

- [ ] **Step 7: Document the weekly handoff step**

This isn't a one-time build step but a standing operational instruction: whenever the user says they've reviewed the week's batch and provides the exported `queue.json` (pasted, attached, or described), commit it over `content/queue.json` in the repo before the next Publish fire. Note this doesn't need new code — it's something to remember when picking this project back up in a future session (worth a quick project memory note).

---

### Task 16: End-to-end dry-run and manual smoke test

**Files:** None (verification only)

- [ ] **Step 1: Dry-run the full generate → review → publish loop locally**

This step is run by the agent doing the smoke test (i.e., interactively, not a bare script — writing `content_plan` requires the same reasoning Task 15 Step 2 describes). Build a `content_plan` covering all 14 slots per that step's rules (theme-based caption+hashtags for every slot, top/bottom for template-planned ones), then:

```python
import os
from datetime import date
from pathlib import Path
from pipeline import generate

generate.generate_week(
    start_date=date.today(), queue_path=Path('content/queue.json'),
    work_dir=Path('.work'), repo_root=Path('.'),
    repo_owner='<owner>', repo_name='<repo>', audio_path=Path('<royalty-free-audio.mp3>'),
    apileague_api_key=os.environ['APILEAGUE_API_KEY'],
    seen_path=Path('content/apileague_seen.json'),
    content_plan=content_plan,  # the dict just written, all 14 slot_index keys present
)
```

Expected: 14 new entries in `content/queue.json` (verify with a quick read that all three `source` values appear at least once across the week), 14 new asset files under `content/assets/`, all pushed to the public GitHub repo.

- [ ] **Step 2: Manually approve one post item and hand off the export**

Open the Task 14 Artifact (after its `QUEUE_URL` has been updated to the real repo and republished), approve today's `post` item, reject or ignore the rest. Confirm the approved item's `source` in the review UI matches what you expect (spot-check that `template` and `repost` items render correctly, not just `original`). Click Export, then commit the downloaded file over `content/queue.json` in the repo (this replaces the manual-sync step the original design assumed would happen automatically — see Task 14/15).

- [ ] **Step 3: Dry-run publish**

```bash
python -m pipeline.publish --type post --dry-run
```

Expected: `[dry-run] would publish post id=... asset=... caption=...` — confirms the selection logic picks the right item without calling the live Graph API.

- [ ] **Step 4: One real manual post**

```bash
python -m pipeline.publish --type post
```

Expected: item status becomes `posted` in `content/queue.json`, and the post is visible on the actual Instagram account. This is the one live-API call in this entire plan that isn't behind a test double — verify it by checking the app, not just the exit code.

- [ ] **Step 5: Confirm the full week runs unattended for the remainder of the current week**

No further action — the two daily Publish routines should now post the remaining approved items on schedule. Check back in a few days that `content/queue.json` shows `posted` entries advancing day by day, across all three sources.

---

### Task 17: Imgur source (repost sourcing, replaces Reddit as the active source)

**Files:**
- Create: `pipeline/imgur_source.py`
- Test: `tests/test_imgur_source.py`

**Interfaces:**
- Produces: `ImgurSourceError(RuntimeError)`, `fetch_tag_gallery(tag: str, client_id: str, *, sort: str = "top", window: str = "week", page: int = 0, session=None) -> list[dict]`, `pick_post(posts: list[dict], *, media_kind: str, min_ups: int, seen_ids: set[str]) -> dict | None`, `download_media(post: dict, out_path: Path, *, session=None) -> Path`, `load_seen_ids(path: Path) -> set[str]`, `mark_seen(path: Path, post_id: str) -> None`

Auth is a `Client-ID` header, not OAuth — simpler than Reddit's flow (no token to fetch, no client secret). Imgur serves animated/video content as a single playable file at `link`, so `download_media` handles both images and videos with one code path — no DASH-style audio/video merge like `reddit_source.download_video_post` needed.

- [ ] **Step 1: Write failing tests**

Create `tests/test_imgur_source.py`:

```python
from pathlib import Path
import pytest
from pipeline import imgur_source


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_fetch_tag_gallery_returns_data_list_on_success():
    body = {"data": [{"id": "a"}, {"id": "b"}], "success": True, "status": 200}
    session = FakeSession([FakeResponse(200, body=body)])

    posts = imgur_source.fetch_tag_gallery("memes", "client123", session=session)

    assert posts == [{"id": "a"}, {"id": "b"}]
    url, kwargs = session.calls[0]
    assert url == "https://api.imgur.com/3/gallery/t/memes/top/week/0"
    assert kwargs["headers"]["Authorization"] == "Client-ID client123"


def test_fetch_tag_gallery_raises_on_error_status():
    session = FakeSession([FakeResponse(403, body={"success": False, "data": {"error": "bad client id"}})])

    with pytest.raises(imgur_source.ImgurSourceError):
        imgur_source.fetch_tag_gallery("memes", "bad-client", session=session)


def _post(id_, *, ups=1000, nsfw=False, is_album=False, animated=False):
    return {"id": id_, "ups": ups, "nsfw": nsfw, "is_album": is_album, "animated": animated}


def test_pick_post_skips_seen_ids():
    posts = [_post("a"), _post("b")]
    result = imgur_source.pick_post(posts, media_kind="image", min_ups=0, seen_ids={"a"})
    assert result["id"] == "b"


def test_pick_post_skips_nsfw_unless_explicitly_false():
    posts = [_post("a", nsfw=True), _post("b", nsfw=None), _post("c", nsfw=False)]
    result = imgur_source.pick_post(posts, media_kind="image", min_ups=0, seen_ids=set())
    assert result["id"] == "c"


def test_pick_post_skips_albums():
    posts = [_post("a", is_album=True), _post("b")]
    result = imgur_source.pick_post(posts, media_kind="image", min_ups=0, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_skips_below_min_ups():
    posts = [_post("a", ups=10), _post("b", ups=1000)]
    result = imgur_source.pick_post(posts, media_kind="image", min_ups=500, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_filters_by_media_kind_video():
    posts = [_post("a", animated=False), _post("b", animated=True)]
    result = imgur_source.pick_post(posts, media_kind="video", min_ups=0, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_returns_none_when_no_match():
    posts = [_post("a", ups=0)]
    result = imgur_source.pick_post(posts, media_kind="image", min_ups=500, seen_ids=set())
    assert result is None


def test_download_media_writes_file(tmp_path):
    session = FakeSession([FakeResponse(200, content=b"media-bytes")])
    out_path = tmp_path / "post.jpg"

    result = imgur_source.download_media({"id": "a", "link": "http://x/a.jpg"}, out_path, session=session)

    assert result == out_path
    assert out_path.read_bytes() == b"media-bytes"


def test_download_media_raises_on_failure(tmp_path):
    session = FakeSession([FakeResponse(404)])

    with pytest.raises(imgur_source.ImgurSourceError):
        imgur_source.download_media(
            {"id": "a", "link": "http://x/a.jpg"}, tmp_path / "post.jpg", session=session,
        )


def test_load_seen_ids_empty_when_missing(tmp_path):
    assert imgur_source.load_seen_ids(tmp_path / "seen.json") == set()


def test_mark_seen_persists_and_dedupes(tmp_path):
    path = tmp_path / "seen.json"
    imgur_source.mark_seen(path, "a")
    imgur_source.mark_seen(path, "b")
    imgur_source.mark_seen(path, "a")
    assert imgur_source.load_seen_ids(path) == {"a", "b"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_imgur_source.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline/imgur_source.py`**

```python
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


def pick_post(posts: list[dict], *, media_kind: str, min_ups: int,
              seen_ids: set[str]) -> dict | None:
    for post in posts:
        if post["id"] in seen_ids:
            continue
        if post.get("is_album"):
            continue
        if post.get("nsfw") is not False:
            continue
        if post.get("ups", 0) < min_ups:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_imgur_source.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/imgur_source.py tests/test_imgur_source.py
git commit -m "feat: add Imgur-backed repost sourcing module (replaces Reddit)"
```

---

### Task 18: Swap generate.py's repost dispatch from Reddit to Imgur

**Files:**
- Modify: `pipeline/generate.py`
- Modify: `tests/test_generate.py`

**Interfaces:**
- Consumes: `imgur_source.fetch_tag_gallery`, `imgur_source.pick_post`, `imgur_source.download_media`, `imgur_source.load_seen_ids`, `imgur_source.mark_seen`, `imgur_source.ImgurSourceError` (Task 17)
- Produces: revised `generate_week(*, start_date: date, queue_path: Path, work_dir: Path, repo_root: Path, repo_owner: str, repo_name: str, audio_path: Path, imgur_client_id: str, seen_path: Path) -> list[dict]` — drops the `reddit_client_id`/`reddit_client_secret`/`reddit_user_agent` parameters entirely (Imgur needs only `imgur_client_id`, no token acquisition step); `SUBREDDITS` renamed/replaced by `IMGUR_TAGS = ["memes", "funny", "wholesomememes", "me_irl", "relatable"]`; `MIN_UPVOTES` renamed `MIN_UPS` (same value, 500)

This is a direct swap of `_produce_repost`'s internals and `generate_week`'s repost dispatch — same shape as the resilience pattern already reviewed for the Reddit version (any `ImgurSourceError` during the fetch/pick/download chain results in `result = None`, which the existing `if result is None: source = "original"` fallback logic already handles unchanged). Since Imgur has no separate auth step to fail before the fetch call, there's no separate "pre-check token" step like the Reddit version had — just wrap the whole `_produce_repost` call in `try/except imgur_source.ImgurSourceError: result = None`, same as the narrow per-call catch already established.

- [ ] **Step 1: Update `tests/test_generate.py`**

In `_patch_all_producers`, replace every `generate.reddit_source.*` monkeypatch with the equivalent `generate.imgur_source.*` one:
- `reddit_source.fetch_top_posts` → `imgur_source.fetch_tag_gallery`, faked as `lambda tag, client_id, **kw: [{"id": "abc", "title": "funny thing", "link": "http://x/img.jpg"}]`
- `reddit_source.load_seen_ids` → `imgur_source.load_seen_ids`
- `reddit_source.pick_post` → `imgur_source.pick_post`, faked as `lambda posts, *, media_kind, min_ups, seen_ids: (posts[0] if repost_post else None)`
- `reddit_source.download_image_post` / `download_video_post` → both collapse into one `imgur_source.download_media`, faked as `lambda post, out_path, **kw: out_path`
- `reddit_source.mark_seen` → `imgur_source.mark_seen`

Update `_run_generate_week` to pass `imgur_client_id="client123"` instead of `reddit_access_token`/`reddit_client_id`/`reddit_client_secret`/`reddit_user_agent`.

Run `pytest tests/test_generate.py -v` — expect these to fail (current `generate.py` still imports/calls `reddit_source`, not `imgur_source`) before proceeding to Step 2.

- [ ] **Step 2: Update `pipeline/generate.py`**

- Replace the `reddit_source` import with `imgur_source`.
- Replace `SUBREDDITS` with `IMGUR_TAGS = ["memes", "funny", "wholesomememes", "me_irl", "relatable"]`.
- Replace `MIN_UPVOTES = 500` with `MIN_UPS = 500`.
- Change `generate_week`'s signature: drop `reddit_client_id`, `reddit_client_secret`, `reddit_user_agent`; add `imgur_client_id: str`.
- Remove the `get_access_token` try/except preamble entirely (no longer applicable).
- In `_produce_repost`, rename to use Imgur calls: `imgur_source.fetch_tag_gallery(tag, imgur_client_id)`, `imgur_source.pick_post(posts, media_kind=media_kind, min_ups=MIN_UPS, seen_ids=seen_ids)`, single `imgur_source.download_media(post, asset_path)` call for both post and reel slot types (replacing the separate `download_image_post`/`download_video_post` branch), `imgur_source.mark_seen(seen_path, post["id"])`.
- In the per-slot dispatch loop, replace the two-step "check token is None, else try/except around `_produce_repost`" with a single `try: result = _produce_repost(...) except imgur_source.ImgurSourceError: result = None`.

Run `pytest tests/test_generate.py -v` and `pytest -q` (full suite) to confirm everything passes.

- [ ] **Step 3: Commit**

```bash
git add pipeline/generate.py tests/test_generate.py
git commit -m "refactor: swap generate.py's repost dispatch from Reddit to Imgur"
```

---

## Self-Review Notes

- **Spec coverage:** every design-doc section maps to a task — content sourcing mix (Tasks 3, 5, 7, 8, 9), reel hook structure (Task 4), asset hosting (Task 6), Graph API + publish (Tasks 10-11), credentials (Tasks 12-13), review Artifact (Task 14), scheduling (Task 15), error handling / fallback-to-original (Task 9's `_produce_repost` + `generate_week` dispatch, Global Constraints), testing (`--dry-run` in Task 11, smoke test in Task 16), repost non-crediting (spec's "Repost Legal Posture", reflected in Task 9's caption generation using only the polished title, no attribution field anywhere in the schema).
- **Placeholder scan:** no TBD/TODO; Tasks 14 and 15 intentionally defer exact capability/cron syntax to their respective skills per those skills' own "load before writing" requirement — this is delegation, not an unresolved placeholder, and every other step in those tasks has concrete content.
- **Type consistency:** checked `queue_store`, `image_gen`, `reel_builder`, `captions`, `asset_host`, `template_source`, `reddit_source`, `graph_api`, `generate`, and `publish` signatures across all "Consumes"/"Produces" blocks — names and parameters match where each module is used by a later task. In particular, `queue_store.new_item` now requires `source` everywhere it's called (Tasks 2, 9, 11's test fixture), and `generate.generate_week`'s `reddit_client_id`/`reddit_client_secret`/`reddit_user_agent`/`seen_path` parameters (revised post-Task-9 by the Reddit-resilience fix, which moved token acquisition inside `generate_week` so an unapproved/denied Reddit app degrades to `original` instead of crashing the batch) are threaded through consistently in Tasks 9, 15, and 16.
