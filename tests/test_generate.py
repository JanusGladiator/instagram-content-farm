from datetime import date

from pipeline import generate, queue_store


def test_pick_theme_cycles_through_themes():
    assert generate.pick_theme(0) == generate.THEMES[0]
    assert generate.pick_theme(len(generate.THEMES)) == generate.THEMES[0]


def test_source_for_slot_matches_source_plan():
    assert generate.source_for_slot(0, "post") == "original"
    assert generate.source_for_slot(0, "reel") == "template"
    assert generate.source_for_slot(1, "post") == "original"
    assert generate.source_for_slot(1, "reel") == "template"


def _patch_all_producers(monkeypatch):
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
    )


def test_generate_week_creates_14_items_with_correct_sources_and_dates(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "audio.mp3").write_bytes(b"a")
    _patch_all_producers(monkeypatch)

    created = _run_generate_week(tmp_path)

    assert len(created) == 14
    loaded = queue_store.load_queue(tmp_path / "queue.json")
    assert len(loaded) == 14

    ordered = sorted(loaded, key=lambda i: (i["scheduled_date"], i["type"] == "reel"))
    assert [i["source"] for i in ordered] == generate.SOURCE_PLAN
    assert set(i["source"] for i in loaded) == {"original", "template"}

    post_dates = sorted(i["scheduled_date"] for i in loaded if i["type"] == "post")
    assert post_dates == [
        "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23",
        "2026-07-24", "2026-07-25", "2026-07-26",
    ]
    assert all(i["status"] == "pending" for i in loaded)
