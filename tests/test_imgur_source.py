from pathlib import Path
import pytest
import requests
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


class RaisingSession:
    def __init__(self, exc):
        self._exc = exc

    def get(self, url, **kwargs):
        raise self._exc


class BadJsonResponse:
    status_code = 200

    def json(self):
        raise ValueError("not valid json")


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


def test_fetch_tag_gallery_wraps_network_error_as_imgur_source_error():
    session = RaisingSession(requests.exceptions.ConnectionError("network down"))

    with pytest.raises(imgur_source.ImgurSourceError):
        imgur_source.fetch_tag_gallery("memes", "client123", session=session)


def test_fetch_tag_gallery_wraps_bad_json_as_imgur_source_error():
    session = FakeSession([BadJsonResponse()])

    with pytest.raises(imgur_source.ImgurSourceError):
        imgur_source.fetch_tag_gallery("memes", "client123", session=session)


def _post(id_, *, score=1000, nsfw=False, is_album=False, animated=False):
    return {"id": id_, "score": score, "nsfw": nsfw, "is_album": is_album, "animated": animated}


def test_pick_post_skips_seen_ids():
    posts = [_post("a"), _post("b")]
    result = imgur_source.pick_post(posts, media_kind="image", min_score=0, seen_ids={"a"})
    assert result["id"] == "b"


def test_pick_post_skips_nsfw_unless_explicitly_false():
    posts = [_post("a", nsfw=True), _post("b", nsfw=None), _post("c", nsfw=False)]
    result = imgur_source.pick_post(posts, media_kind="image", min_score=0, seen_ids=set())
    assert result["id"] == "c"


def test_pick_post_skips_albums():
    posts = [_post("a", is_album=True), _post("b")]
    result = imgur_source.pick_post(posts, media_kind="image", min_score=0, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_skips_below_min_score():
    posts = [_post("a", score=10), _post("b", score=1000)]
    result = imgur_source.pick_post(posts, media_kind="image", min_score=500, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_treats_null_score_as_zero():
    # Real Imgur gallery responses return "ups": null with the actual vote
    # count under "score" instead — a post with score=None must be treated
    # as 0, not crash the comparison against min_score.
    posts = [_post("a", score=None), _post("b", score=1000)]
    result = imgur_source.pick_post(posts, media_kind="image", min_score=500, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_filters_by_media_kind_video():
    posts = [_post("a", animated=False), _post("b", animated=True)]
    result = imgur_source.pick_post(posts, media_kind="video", min_score=0, seen_ids=set())
    assert result["id"] == "b"


def test_pick_post_returns_none_when_no_match():
    posts = [_post("a", score=0)]
    result = imgur_source.pick_post(posts, media_kind="image", min_score=500, seen_ids=set())
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


def test_download_media_wraps_network_error_as_imgur_source_error(tmp_path):
    session = RaisingSession(requests.exceptions.Timeout("timed out"))

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
