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
