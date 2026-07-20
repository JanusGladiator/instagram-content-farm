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
