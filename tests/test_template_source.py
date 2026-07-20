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
