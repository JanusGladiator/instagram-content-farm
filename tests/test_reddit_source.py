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
