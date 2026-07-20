from datetime import date, timedelta
from pathlib import Path

from pipeline import (
    asset_host,
    captions,
    image_gen,
    queue_store,
    reddit_source,
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

SUBREDDITS = ["memes", "funny", "wholesomememes", "AdviceAnimals", "mildlyinteresting"]
MIN_UPVOTES = 500

# 14 slots = 7 days x (post, reel). 5 original / 5 template / 4 repost.
SOURCE_PLAN = [
    "original", "template", "repost", "original", "template",
    "repost", "original", "template", "repost", "original",
    "template", "repost", "original", "template",
]


def pick_theme(day_index: int) -> str:
    return THEMES[day_index % len(THEMES)]


def source_for_slot(day_index: int, slot_type: str) -> str:
    slot_index = day_index * 2 + (0 if slot_type == "post" else 1)
    return SOURCE_PLAN[slot_index % len(SOURCE_PLAN)]


def _produce_original(*, slot_type: str, theme: str, work_dir: Path,
                       day_label: str, audio_path: Path) -> tuple[Path, dict]:
    caption = captions.generate_caption(theme)

    if slot_type == "post":
        image_path = work_dir / f"{day_label}-post-original.jpg"
        image_gen.generate_image(theme, image_path)
        return image_path, caption

    reel_image_paths = []
    for shot_index, variant in enumerate(REEL_SHOT_VARIANTS):
        reel_image = work_dir / f"{day_label}-reel-original-{shot_index}.jpg"
        image_gen.generate_image(f"{theme}, {variant}", reel_image)
        reel_image_paths.append(reel_image)

    reel_video = work_dir / f"{day_label}-reel-original.mp4"
    reel_builder.build_reel(reel_image_paths, audio_path, caption["caption"], reel_video)
    return reel_video, caption


def _produce_template(*, slot_type: str, theme: str, work_dir: Path, day_label: str,
                       audio_path: Path, templates: list[dict], day_index: int) -> tuple[Path, dict]:
    caption = captions.generate_caption(theme)
    meme_text = captions.generate_meme_text(theme)
    chosen_template = template_source.pick_template(templates, day_index)

    blank_path = work_dir / f"{day_label}-{slot_type}-template-blank.jpg"
    template_source.download_template_image(chosen_template, blank_path)

    rendered_path = work_dir / f"{day_label}-{slot_type}-template.jpg"
    template_source.render_caption_on_template(
        blank_path, meme_text["top"], meme_text["bottom"], rendered_path,
    )

    if slot_type == "post":
        return rendered_path, caption

    reel_video = work_dir / f"{day_label}-reel-template.mp4"
    reel_builder.build_reel([rendered_path, rendered_path], audio_path,
                             caption["caption"], reel_video)
    return reel_video, caption


def _produce_repost(*, slot_type: str, work_dir: Path, day_label: str, subreddit: str,
                     access_token: str, user_agent: str, seen_path: Path) -> tuple[Path, dict] | None:
    posts = reddit_source.fetch_top_posts(subreddit, access_token, user_agent)
    seen_ids = reddit_source.load_seen_ids(seen_path)
    media_kind = "image" if slot_type == "post" else "video"
    post = reddit_source.pick_post(posts, media_kind=media_kind,
                                    min_upvotes=MIN_UPVOTES, seen_ids=seen_ids)
    if post is None:
        return None

    caption = captions.generate_caption(
        "polish this into a punchy shareable caption without changing its "
        f"meaning: {post['title']}"
    )

    if slot_type == "post":
        asset_path = work_dir / f"{day_label}-post-repost.jpg"
        reddit_source.download_image_post(post, asset_path)
    else:
        asset_path = work_dir / f"{day_label}-reel-repost.mp4"
        reddit_source.download_video_post(post, asset_path)

    reddit_source.mark_seen(seen_path, post["id"])
    return asset_path, caption


def generate_week(*, start_date: date, queue_path: Path, work_dir: Path,
                   repo_root: Path, repo_owner: str, repo_name: str,
                   audio_path: Path, reddit_client_id: str, reddit_client_secret: str,
                   reddit_user_agent: str, seen_path: Path) -> list[dict]:
    work_dir.mkdir(parents=True, exist_ok=True)
    created = []
    templates = template_source.list_templates()

    try:
        reddit_access_token = reddit_source.get_access_token(
            reddit_client_id, reddit_client_secret, reddit_user_agent,
        )
    except reddit_source.RedditSourceError:
        reddit_access_token = None

    for offset in range(7):
        day = start_date + timedelta(days=offset)
        day_label = day.isoformat()
        theme = pick_theme(offset)
        subreddit = SUBREDDITS[offset % len(SUBREDDITS)]

        for slot_type in ("post", "reel"):
            source = source_for_slot(offset, slot_type)
            result = None

            if source == "template":
                result = _produce_template(
                    slot_type=slot_type, theme=theme, work_dir=work_dir,
                    day_label=day_label, audio_path=audio_path,
                    templates=templates, day_index=offset,
                )
            elif source == "repost":
                if reddit_access_token is None:
                    result = None
                else:
                    try:
                        result = _produce_repost(
                            slot_type=slot_type, work_dir=work_dir, day_label=day_label,
                            subreddit=subreddit, access_token=reddit_access_token,
                            user_agent=reddit_user_agent, seen_path=seen_path,
                        )
                    except reddit_source.RedditSourceError:
                        result = None
                if result is None:
                    source = "original"

            if source == "original":
                result = _produce_original(
                    slot_type=slot_type, theme=theme, work_dir=work_dir,
                    day_label=day_label, audio_path=audio_path,
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
