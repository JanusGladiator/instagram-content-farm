from datetime import date

from pipeline import generate, queue_store


def test_pick_theme_cycles_through_themes():
    assert generate.pick_theme(0) == generate.THEMES[0]
    assert generate.pick_theme(len(generate.THEMES)) == generate.THEMES[0]


def test_source_for_slot_matches_source_plan():
    assert generate.source_for_slot(0, "post") == "repost"
    assert generate.source_for_slot(0, "reel") == "original"
    assert generate.source_for_slot(1, "post") == "original"


def test_source_for_slot_never_returns_repost_for_a_reel():
    for day_index in range(7):
        assert generate.source_for_slot(day_index, "reel") != "repost"


def _build_content_plan():
    """Every slot gets a caption/hashtags (used directly for `original`,
    and as the fallback if a `repost`-planned slot's fetch fails); slots
    planned as `template` additionally get top/bottom meme text. Mirrors
    what the calling agent is expected to write per pipeline.captions's
    guidelines."""
    plan = {}
    for slot_index in range(14):
        entry = {"caption": f"cap-{slot_index}", "hashtags": ["h"]}
        if generate.SOURCE_PLAN[slot_index] == "template":
            entry["top"] = "T"
            entry["bottom"] = "B"
        plan[slot_index] = entry
    return plan


def _patch_all_producers(monkeypatch, *, repost_meme):
    monkeypatch.setattr(generate.image_gen, "generate_image",
                         lambda prompt, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reel_builder, "build_reel",
                         lambda image_paths, audio_path, text, out_path, **kw: out_path)
    monkeypatch.setattr(generate.template_source, "list_templates",
                         lambda **kw: [{"id": "1", "url": "http://x/blank.jpg"}])
    monkeypatch.setattr(generate.template_source, "pick_template",
                         lambda templates, day_index: templates[0])
    monkeypatch.setattr(generate.template_source, "download_template_image",
                         lambda template, out_path, **kw: out_path)
    monkeypatch.setattr(generate.template_source, "render_caption_on_template",
                         lambda blank_path, top, bottom, out_path, **kw: out_path)
    monkeypatch.setattr(
        generate.apileague_source, "pick_unique_meme",
        lambda api_key, *, seen_ids, **kw:
            ({"description": "funny thing", "url": "http://x/img.jpg", "type": "image/jpeg"}
             if repost_meme else None),
    )
    monkeypatch.setattr(generate.apileague_source, "download_media",
                         lambda meme, out_path, **kw: out_path)
    monkeypatch.setattr(generate.apileague_source, "meme_id", lambda meme: "meme-id")
    monkeypatch.setattr(generate.apileague_source, "load_seen_ids", lambda path: set())
    monkeypatch.setattr(generate.apileague_source, "mark_seen", lambda path, meme_id_value: None)
    monkeypatch.setattr(
        generate.asset_host, "publish_asset",
        lambda local_path, repo_root, relative_dest, **kw:
            f"https://raw.githubusercontent.com/me/repo/master/{relative_dest}",
    )


def _run_generate_week(tmp_path, *, content_plan=None):
    return generate.generate_week(
        start_date=date(2026, 7, 20),
        queue_path=tmp_path / "queue.json",
        work_dir=tmp_path / "work",
        repo_root=tmp_path / "repo",
        repo_owner="me", repo_name="repo",
        audio_path=tmp_path / "audio.mp3",
        apileague_api_key="key123",
        seen_path=tmp_path / "apileague_seen.json",
        content_plan=content_plan if content_plan is not None else _build_content_plan(),
    )


def test_generate_week_creates_14_items_with_correct_sources_and_dates(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=True)

    created = _run_generate_week(tmp_path)

    assert len(created) == 14
    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert len(loaded) == 14

    ordered = sorted(loaded, key=lambda i: (i["scheduled_date"], i["type"] == "reel"))
    assert [i["source"] for i in ordered] == generate.SOURCE_PLAN
    assert all(i["source"] != "repost" or i["type"] == "post" for i in loaded)

    post_dates = sorted(i["scheduled_date"] for i in loaded if i["type"] == "post")
    assert post_dates == [
        "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26",
    ]
    assert all(i["status"] == "pending" for i in loaded)

    repost_items = [i for i in loaded if i["source"] == "repost"]
    assert repost_items, "expected at least one repost item"
    for item in repost_items:
        assert item["caption"] == "funny thing"
        assert item["hashtags"] == []

    non_repost_items = [i for i in loaded if i["source"] != "repost"]
    for item in non_repost_items:
        assert item["caption"].startswith("cap-")
        assert item["hashtags"] == ["h"]


def test_generate_week_falls_back_to_original_when_repost_unavailable(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=False)

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)
    expected_original_count = (
        generate.SOURCE_PLAN.count("original") + generate.SOURCE_PLAN.count("repost")
    )
    assert sum(1 for i in loaded if i["source"] == "original") == expected_original_count
    # Fallback items use the pre-written content_plan entry for their slot,
    # not the meme description (there is no meme).
    assert all(i["caption"].startswith("cap-") for i in loaded)


def test_generate_week_falls_back_to_original_when_apileague_raises(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=True)

    def _raise(*a, **k):
        raise generate.apileague_source.ApileagueSourceError("quota exceeded")

    monkeypatch.setattr(generate.apileague_source, "pick_unique_meme", _raise)

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)


def test_generate_week_falls_back_to_original_when_meme_is_not_an_image(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=True)

    marked_seen = []
    monkeypatch.setattr(
        generate.apileague_source, "pick_unique_meme",
        lambda api_key, *, seen_ids, **kw:
            {"description": "a video meme", "url": "http://x/clip.mp4", "type": "video/mp4"},
    )
    monkeypatch.setattr(generate.apileague_source, "mark_seen",
                         lambda path, meme_id_value: marked_seen.append(meme_id_value))

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)
    # Rejected (wrong-type) memes must still be marked seen so they aren't
    # redrawn in a later slot.
    assert marked_seen == ["meme-id", "meme-id", "meme-id"]


def test_generate_week_falls_back_to_original_when_image_subtype_not_allowlisted(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=True)

    # A real image MIME type, but not one this pipeline maps to a safe
    # filename extension -- must be rejected, not trusted as a path segment.
    monkeypatch.setattr(
        generate.apileague_source, "pick_unique_meme",
        lambda api_key, *, seen_ids, **kw:
            {"description": "a tiff meme", "url": "http://x/img.tiff", "type": "image/tiff"},
    )

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)


def test_repost_asset_extension_matches_real_meme_content_type(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=True)

    monkeypatch.setattr(
        generate.apileague_source, "pick_unique_meme",
        lambda api_key, *, seen_ids, **kw:
            {"description": "a png meme", "url": "http://x/img.png", "type": "image/png"},
    )

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    repost_items = [i for i in loaded if i["source"] == "repost"]
    assert repost_items, "expected at least one repost item"
    assert all(i["asset_url"].endswith(".png") for i in repost_items)


def test_generate_week_raises_key_error_if_content_plan_missing_a_directly_planned_slot(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_meme=False)

    incomplete_plan = _build_content_plan()
    del incomplete_plan[1]  # slot 1 (day 0 reel) is "original" per SOURCE_PLAN

    try:
        _run_generate_week(tmp_path, content_plan=incomplete_plan)
        assert False, "expected KeyError for a content_plan missing a required slot"
    except KeyError:
        pass


def test_generate_week_raises_key_error_if_content_plan_missing_a_repost_fallback_slot(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    # Force the repost slot to fail so it needs its content_plan entry as
    # an `original` fallback -- this is the actual scenario the "every
    # slot including repost-planned ones" requirement exists to cover.
    _patch_all_producers(monkeypatch, repost_meme=False)

    incomplete_plan = _build_content_plan()
    del incomplete_plan[0]  # slot 0 (day 0 post) is "repost" per SOURCE_PLAN

    try:
        _run_generate_week(tmp_path, content_plan=incomplete_plan)
        assert False, "expected KeyError when the repost-planned slot's fallback entry is missing"
    except KeyError:
        pass
