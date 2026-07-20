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
