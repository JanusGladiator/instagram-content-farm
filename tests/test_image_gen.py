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
