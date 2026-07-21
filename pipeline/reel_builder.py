import subprocess
from pathlib import Path


class ReelBuildError(RuntimeError):
    pass


def build_ffmpeg_command(image_paths: list[Path], audio_path: Path, text: str,
                          out_path: Path, *, duration_seconds: int = 8,
                          hook_seconds: int = 3) -> list[str]:
    if not image_paths:
        raise ValueError("image_paths must contain at least one image")

    per_image_seconds = duration_seconds / len(image_paths)
    # A backslash cannot escape a quote *inside* a single-quoted ffmpeg filter
    # value -- the parser doesn't treat it specially there. The correct way to
    # get a literal quote is to close the quoted string, insert an escaped
    # quote outside of it, then reopen: 'it'\''s' -> it's.
    escaped_text = text.replace(":", r"\:").replace("'", r"'\''")

    command = ["ffmpeg", "-y"]
    for image_path in image_paths:
        command += ["-loop", "1", "-t", str(per_image_seconds), "-i", str(image_path)]
    command += ["-i", str(audio_path)]

    video_labels = "".join(f"[{i}:v]" for i in range(len(image_paths)))
    drawtext = (
        f"drawtext=text='{escaped_text}':fontcolor=white:fontsize=48:"
        f"x=(w-text_w)/2:y=h-th-60:box=1:boxcolor=black@0.5:boxborderw=10:"
        f"enable='between(t,0,{hook_seconds})'"
    )
    filter_complex = (
        f"{video_labels}concat=n={len(image_paths)}:v=1:a=0[vcat];"
        f"[vcat]{drawtext}[vout]"
    )
    audio_index = len(image_paths)

    command += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", f"{audio_index}:a",
        "-t", str(duration_seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    return command


def build_reel(image_paths: list[Path], audio_path: Path, text: str, out_path: Path,
                *, duration_seconds: int = 8, hook_seconds: int = 3,
                runner=subprocess.run) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(image_paths, audio_path, text, out_path,
                                    duration_seconds=duration_seconds,
                                    hook_seconds=hook_seconds)
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ReelBuildError(f"ffmpeg failed: {result.stderr}")
    return out_path
