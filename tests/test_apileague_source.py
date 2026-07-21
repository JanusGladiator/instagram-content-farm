from pathlib import Path
import pytest
import requests
from pipeline import apileague_source


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


def _meme(url="https://i.redd.it/abc.jpeg", type_="image/jpeg"):
    return {
        "description": "a meme",
        "url": url,
        "type": type_,
        "width": 500,
        "height": 500,
        "ratio": 1.0,
    }


def test_fetch_random_meme_returns_body_on_success():
    session = FakeSession([FakeResponse(200, body=_meme())])

    meme = apileague_source.fetch_random_meme("key123", session=session)

    assert meme["url"] == "https://i.redd.it/abc.jpeg"
    url, kwargs = session.calls[0]
    assert url == "https://api.apileague.com/retrieve-random-meme"
    assert kwargs["headers"]["X-API-Key"] == "key123"


def test_fetch_random_meme_raises_on_error_status():
    session = FakeSession([FakeResponse(403, body={"error": "quota exceeded"})])

    with pytest.raises(apileague_source.ApileagueSourceError):
        apileague_source.fetch_random_meme("key123", session=session)


def test_fetch_random_meme_wraps_network_error():
    session = RaisingSession(requests.exceptions.ConnectionError("down"))

    with pytest.raises(apileague_source.ApileagueSourceError):
        apileague_source.fetch_random_meme("key123", session=session)


def test_meme_id_is_stable_for_same_url():
    meme_a = _meme(url="https://i.redd.it/same.jpeg")
    meme_b = _meme(url="https://i.redd.it/same.jpeg")
    assert apileague_source.meme_id(meme_a) == apileague_source.meme_id(meme_b)


def test_meme_id_differs_for_different_url():
    meme_a = _meme(url="https://i.redd.it/one.jpeg")
    meme_b = _meme(url="https://i.redd.it/two.jpeg")
    assert apileague_source.meme_id(meme_a) != apileague_source.meme_id(meme_b)


def test_pick_unique_meme_returns_first_unseen():
    session = FakeSession([FakeResponse(200, body=_meme(url="https://i.redd.it/x.jpeg"))])

    meme = apileague_source.pick_unique_meme("key123", seen_ids=set(), session=session)

    assert meme["url"] == "https://i.redd.it/x.jpeg"
    assert len(session.calls) == 1


def test_pick_unique_meme_retries_past_seen_ids():
    seen_url = "https://i.redd.it/seen.jpeg"
    new_url = "https://i.redd.it/new.jpeg"
    seen_id = apileague_source.meme_id(_meme(url=seen_url))
    session = FakeSession([
        FakeResponse(200, body=_meme(url=seen_url)),
        FakeResponse(200, body=_meme(url=new_url)),
    ])

    meme = apileague_source.pick_unique_meme(
        "key123", seen_ids={seen_id}, max_attempts=5, session=session,
    )

    assert meme["url"] == new_url
    assert len(session.calls) == 2


def test_pick_unique_meme_returns_none_after_max_attempts_all_seen():
    seen_url = "https://i.redd.it/seen.jpeg"
    seen_id = apileague_source.meme_id(_meme(url=seen_url))
    session = FakeSession([FakeResponse(200, body=_meme(url=seen_url))] * 3)

    meme = apileague_source.pick_unique_meme(
        "key123", seen_ids={seen_id}, max_attempts=3, session=session,
    )

    assert meme is None
    assert len(session.calls) == 3


def test_download_media_writes_file(tmp_path):
    session = FakeSession([FakeResponse(200, content=b"meme-bytes")])
    out_path = tmp_path / "meme.jpg"

    result = apileague_source.download_media(_meme(), out_path, session=session)

    assert result == out_path
    assert out_path.read_bytes() == b"meme-bytes"


def test_download_media_raises_on_failure(tmp_path):
    session = FakeSession([FakeResponse(404)])

    with pytest.raises(apileague_source.ApileagueSourceError):
        apileague_source.download_media(_meme(), tmp_path / "meme.jpg", session=session)


def test_download_media_wraps_network_error(tmp_path):
    session = RaisingSession(requests.exceptions.Timeout("timed out"))

    with pytest.raises(apileague_source.ApileagueSourceError):
        apileague_source.download_media(_meme(), tmp_path / "meme.jpg", session=session)


def test_load_seen_ids_empty_when_missing(tmp_path):
    assert apileague_source.load_seen_ids(tmp_path / "seen.json") == set()


def test_mark_seen_persists_and_dedupes(tmp_path):
    path = tmp_path / "seen.json"
    apileague_source.mark_seen(path, "a")
    apileague_source.mark_seen(path, "b")
    apileague_source.mark_seen(path, "a")
    assert apileague_source.load_seen_ids(path) == {"a", "b"}
