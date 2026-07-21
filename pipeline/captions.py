"""Caption and meme-text writing guidance.

No API calls happen in this module. The weekly Generate routine is itself
a scheduled Claude Code agent -- caption/hashtag/meme-text writing happens
as part of that agent's own turn (covered by the existing Claude Code
subscription) rather than via a separate, separately-billed Anthropic API
call. These constants are the single source of truth for what the
routine's prompt asks the agent to follow when it writes the week's
`content_plan` passed into `pipeline.generate.generate_week`.
"""

CAPTION_GUIDELINES = """Write an Instagram caption and 5-10 hashtags for the given concept.

Optimize for one thing: would a specific person send this to a specific
friend in a DM? That's the top distribution signal on Instagram right now —
write like you're describing a moment a reader will recognize and want to
tag someone in, not a generic joke. Keep it broadly relatable (daily life,
work, phone habits, group chats) — not tied to any specialist subject.

Caption should be short (1-2 sentences), punchy, no hashtags inside it.
Hashtags should be relevant, given without the # symbol."""

MEME_TEXT_GUIDELINES = """Write top and bottom text for a meme image about the given concept.

Keep each line short (under 8 words), classic meme format (setup on top,
punchline on bottom)."""
