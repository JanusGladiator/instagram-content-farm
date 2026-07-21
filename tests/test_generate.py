from datetime import date
from pathlib import Path

from pipeline import generate, queue_store


def test_pick_theme_cycles_through_themes():
    assert generate.pick_theme(0) == generate.THEMES[0]
    assert generate.pick_theme(len(generate.THEMES)) == generate.THEMES[0]


def test_source_for_slot_matches_source_plan():
    assert generate.source_for_slot(0, "post") == "original"
    assert generate.source_for_slot(0, "reel") == "template"
    assert generate.source_for_slot(1, "post") == "repost"


def _patch_all_producers(monkeypatch, *, repost_post):
    monkeypatch.setattr(generate.image_gen, "generate_image",
                         lambda prompt, out_path, **kw: out_path)
    monkeypatch.setattr(generate.reel_builder, "build_reel",
                         lambda image_paths, audio_path, text, out_path, **kw: out_path)
    monkeypatch.setattr(generate.captions, "generate_caption",
                         lambda concept, **kw: {"caption": "cap", "hashtags": ["h"]})
    monkeypatch.setattr(generate.captions, "generate_meme_text",
                         lambda concept, **kw: {"top": "T", "bottom": "B"})
    monkeypatch.setattr(generate.template_source, "list_templates",
                         lambda **kw: [{"id": "1", "url": "http://x/blank.jpg"}])
    monkeypatch.setattr(generate.template_source, "pick_template",
                         lambda templates, day_index: templates[0])
    monkeypatch.setattr(generate.template_source, "download_template_image",
                         lambda template, out_path, **kw: out_path)
    monkeypatch.setattr(generate.template_source, "render_caption_on_template",
                         lambda blank_path, top, bottom, out_path, **kw: out_path)
    monkeypatch.setattr(
        generate.imgur_source, "fetch_tag_gallery",
        lambda tag, client_id, **kw: [{"id": "abc", "title": "funny thing", "link": "http://x/img.jpg"}],
    )
    monkeypatch.setattr(generate.imgur_source, "load_seen_ids", lambda path: set())
    monkeypatch.setattr(
        generate.imgur_source, "pick_post",
        lambda posts, *, media_kind, min_score, seen_ids: (posts[0] if repost_post else None),
    )
    monkeypatch.setattr(generate.imgur_source, "download_media",
                         lambda post, out_path, **kw: out_path)
    monkeypatch.setattr(generate.imgur_source, "mark_seen", lambda path, post_id: None)
    monkeypatch.setattr(
        generate.asset_host, "publish_asset",
        lambda local_path, repo_root, relative_dest, **kw:
            f"https://raw.githubusercontent.com/me/repo/master/{relative_dest}",
    )


def _run_generate_week(tmp_path):
    return generate.generate_week(
        start_date=date(2026, 7, 20),
        queue_path=tmp_path / "queue.json",
        work_dir=tmp_path / "work",
        repo_root=tmp_path / "repo",
        repo_owner="me", repo_name="repo",
        audio_path=tmp_path / "audio.mp3",
        imgur_client_id="client123",
        seen_path=tmp_path / "imgur_seen.json",
    )


def test_generate_week_creates_14_items_with_correct_sources_and_dates(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_post=True)

    created = _run_generate_week(tmp_path)

    assert len(created) == 14
    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert len(loaded) == 14

    ordered = sorted(loaded, key=lambda i: (i["scheduled_date"], i["type"] == "reel"))
    assert [i["source"] for i in ordered] == generate.SOURCE_PLAN

    post_dates = sorted(i["scheduled_date"] for i in loaded if i["type"] == "post")
    assert post_dates == [
        "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26",
    ]
    assert all(i["status"] == "pending" for i in loaded)


def test_generate_week_falls_back_to_original_when_repost_unavailable(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_post=False)

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)
    expected_original_count = (
        generate.SOURCE_PLAN.count("original") + generate.SOURCE_PLAN.count("repost")
    )
    assert sum(1 for i in loaded if i["source"] == "original") == expected_original_count


def test_generate_week_falls_back_to_original_when_imgur_fetch_raises(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_post=True)

    def _raise_fetch_error(*a, **k):
        raise generate.imgur_source.ImgurSourceError("403 forbidden")

    monkeypatch.setattr(generate.imgur_source, "fetch_tag_gallery", _raise_fetch_error)

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)


def test_generate_week_falls_back_to_original_when_imgur_download_raises(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch, repost_post=True)

    def _raise_download_error(*a, **k):
        raise generate.imgur_source.ImgurSourceError("download failed")

    monkeypatch.setattr(generate.imgur_source, "download_media", _raise_download_error)

    _run_generate_week(tmp_path)

    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert all(item["source"] != "repost" for item in loaded)
