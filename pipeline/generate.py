from datetime import date, timedelta
from pathlib import Path

from pipeline import (
    apileague_source,
    asset_host,
    image_gen,
    queue_store,
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

# repost sourcing: `reddit_source.py` and `imgur_source.py` are dormant
# (both platforms closed API registration for this use case — see the
# design spec's "Repost Sourcing" section for the full history). Active
# repost source is `apileague_source.py` (Random Meme API, a third-party
# proxy over Reddit content) — accepted per explicit user decision despite
# unclear content provenance and no server-side NSFW filter; content
# safety for repost items relies on the weekly human review step, not
# automated filtering. That API returns one random item per call with no
# way to request image vs video, so repost is restricted to post slots
# only — reel slots never use it (see SOURCE_PLAN below).

# 14 slots = 7 days x (post, reel). Posts: 3 repost / 2 original / 2
# template. Reels: 4 original / 3 template (repost never lands on a reel).
SOURCE_PLAN = [
    "repost", "original", "original", "template",
    "template", "original", "repost", "template",
    "original", "original", "template", "template",
    "repost", "original",
]


def pick_theme(day_index: int) -> str:
    return THEMES[day_index % len(THEMES)]


def source_for_slot(day_index: int, slot_type: str) -> str:
    slot_index = day_index * 2 + (0 if slot_type == "post" else 1)
    return SOURCE_PLAN[slot_index % len(SOURCE_PLAN)]


def _produce_original(*, slot_type: str, theme: str, work_dir: Path,
                       day_label: str, audio_path: Path,
                       caption: str, hashtags: list[str]) -> tuple[Path, dict]:
    caption_dict = {"caption": caption, "hashtags": hashtags}

    if slot_type == "post":
        image_path = work_dir / f"{day_label}-post-original.jpg"
        image_gen.generate_image(theme, image_path)
        return image_path, caption_dict

    reel_image_paths = []
    for shot_index, variant in enumerate(REEL_SHOT_VARIANTS):
        reel_image = work_dir / f"{day_label}-reel-original-{shot_index}.jpg"
        image_gen.generate_image(f"{theme}, {variant}", reel_image)
        reel_image_paths.append(reel_image)

    reel_video = work_dir / f"{day_label}-reel-original.mp4"
    reel_builder.build_reel(reel_image_paths, audio_path, caption, reel_video)
    return reel_video, caption_dict


def _produce_template(*, slot_type: str, work_dir: Path, day_label: str,
                       audio_path: Path, templates: list[dict], day_index: int,
                       caption: str, hashtags: list[str], top: str, bottom: str) -> tuple[Path, dict]:
    caption_dict = {"caption": caption, "hashtags": hashtags}
    chosen_template = template_source.pick_template(templates, day_index)

    blank_path = work_dir / f"{day_label}-{slot_type}-template-blank.jpg"
    template_source.download_template_image(chosen_template, blank_path)

    rendered_path = work_dir / f"{day_label}-{slot_type}-template.jpg"
    template_source.render_caption_on_template(blank_path, top, bottom, rendered_path)

    if slot_type == "post":
        return rendered_path, caption_dict

    reel_video = work_dir / f"{day_label}-reel-template.mp4"
    reel_builder.build_reel([rendered_path, rendered_path], audio_path,
                             caption, reel_video)
    return reel_video, caption_dict


# Allowlist, not a denylist derived from the untrusted `type` field directly
# -- an unmapped/unexpected subtype is rejected rather than trusted as a
# filename extension (an attacker-controlled `type` string must never reach
# a filesystem path unfiltered).
_REPOST_IMAGE_EXTENSIONS = {
    "jpeg": "jpg",
    "jpg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
}


def _produce_repost(*, work_dir: Path, day_label: str, apileague_api_key: str,
                     seen_path: Path) -> tuple[Path, dict] | None:
    seen_ids = apileague_source.load_seen_ids(seen_path)
    meme = apileague_source.pick_unique_meme(apileague_api_key, seen_ids=seen_ids)
    if meme is None:
        return None

    # Mark seen regardless of what happens next so a rejected (wrong-type)
    # meme is never redrawn in a future slot.
    apileague_source.mark_seen(seen_path, apileague_source.meme_id(meme))

    media_type = meme.get("type", "")
    if not media_type.startswith("image/"):
        return None

    subtype = media_type.split("/", 1)[1].split(";", 1)[0].strip().lower()
    extension = _REPOST_IMAGE_EXTENSIONS.get(subtype)
    if extension is None:
        return None

    # No LLM rewrite here -- the meme's own description becomes the
    # caption directly. This isn't known until the meme is fetched at
    # runtime, so it can't be part of a pre-written content_plan the way
    # original/template captions are; using it as-is (rather than looping
    # back to the calling agent mid-script) avoids both the extra round
    # trip and the prompt-injection surface that a rewrite step would
    # reintroduce. No hashtags are generated for repost items for the same
    # reason.
    caption_dict = {"caption": meme["description"], "hashtags": []}

    asset_path = work_dir / f"{day_label}-post-repost.{extension}"
    apileague_source.download_media(meme, asset_path)

    return asset_path, caption_dict


def generate_week(*, start_date: date, queue_path: Path, work_dir: Path,
                   repo_root: Path, repo_owner: str, repo_name: str,
                   audio_path: Path, apileague_api_key: str, seen_path: Path,
                   content_plan: dict[int, dict]) -> list[dict]:
    """content_plan maps slot_index (0-13, day_index*2 + 0-for-post/1-for-reel,
    matching SOURCE_PLAN's own indexing) to a dict with "caption" and
    "hashtags" (used directly for `original`, and as the fallback if a
    `repost`-planned slot's fetch fails) plus, for every index where
    SOURCE_PLAN[index] == "template", "top" and "bottom" meme text.
    Written by the calling agent per pipeline.captions's guidelines, not
    generated inside this function -- see that module for why.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    created = []
    templates = template_source.list_templates()

    for offset in range(7):
        day = start_date + timedelta(days=offset)
        day_label = day.isoformat()
        theme = pick_theme(offset)

        for slot_type in ("post", "reel"):
            slot_index = offset * 2 + (0 if slot_type == "post" else 1)
            source = SOURCE_PLAN[slot_index]

            if source == "template":
                content = content_plan[slot_index]
                result = _produce_template(
                    slot_type=slot_type, work_dir=work_dir, day_label=day_label,
                    audio_path=audio_path, templates=templates, day_index=offset,
                    caption=content["caption"], hashtags=content["hashtags"],
                    top=content["top"], bottom=content["bottom"],
                )
            elif source == "repost":
                try:
                    result = _produce_repost(
                        work_dir=work_dir, day_label=day_label,
                        apileague_api_key=apileague_api_key, seen_path=seen_path,
                    )
                except apileague_source.ApileagueSourceError:
                    result = None
                if result is None:
                    source = "original"

            if source == "original":
                content = content_plan[slot_index]
                result = _produce_original(
                    slot_type=slot_type, theme=theme, work_dir=work_dir,
                    day_label=day_label, audio_path=audio_path,
                    caption=content["caption"], hashtags=content["hashtags"],
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
