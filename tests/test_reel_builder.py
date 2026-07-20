from pathlib import Path
import pytest
from pipeline import reel_builder


def test_build_ffmpeg_command_includes_all_image_inputs_and_output():
    command = reel_builder.build_ffmpeg_command(
        [Path("setup.jpg"), Path("punchline.jpg")], Path("audio.mp3"),
        "hello world", Path("out.mp4"),
    )
    assert command[0] == "ffmpeg"
    assert "setup.jpg" in command
    assert "punchline.jpg" in command
    assert "audio.mp3" in command
    assert command[-1] == "out.mp4"


def test_build_ffmpeg_command_escapes_special_chars_in_text():
    command = reel_builder.build_ffmpeg_command(
        [Path("img.jpg")], Path("audio.mp3"), "it's 5:00", Path("out.mp4"),
    )
    filter_arg = command[command.index("-filter_complex") + 1]
    assert r"\:" in filter_arg
    assert r"\'" in filter_arg


def test_build_ffmpeg_command_restricts_text_to_hook_window():
    command = reel_builder.build_ffmpeg_command(
        [Path("img.jpg")], Path("audio.mp3"), "hook", Path("out.mp4"),
        hook_seconds=3,
    )
    filter_arg = command[command.index("-filter_complex") + 1]
    assert "enable='between(t,0,3)'" in filter_arg


def test_build_ffmpeg_command_raises_on_empty_image_list():
    with pytest.raises(ValueError):
        reel_builder.build_ffmpeg_command(
            [], Path("audio.mp3"), "hook", Path("out.mp4"),
        )


class FakeCompletedProcess:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_build_reel_returns_out_path_on_success(tmp_path):
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append(command)
        return FakeCompletedProcess(returncode=0)

    out_path = tmp_path / "out.mp4"
    result = reel_builder.build_reel(
        [tmp_path / "setup.jpg", tmp_path / "punchline.jpg"],
        tmp_path / "audio.mp3", "caption", out_path,
        runner=fake_runner,
    )

    assert result == out_path
    assert len(calls) == 1
    assert calls[0][0] == "ffmpeg"


def test_build_reel_raises_on_nonzero_returncode(tmp_path):
    def fake_runner(command, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="boom")

    with pytest.raises(reel_builder.ReelBuildError, match="boom"):
        reel_builder.build_reel(
            [tmp_path / "img.jpg"], tmp_path / "audio.mp3", "caption",
            tmp_path / "out.mp4", runner=fake_runner,
        )
