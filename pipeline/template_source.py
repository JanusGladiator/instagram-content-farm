import subprocess
from pathlib import Path

import requests

IMGFLIP_TEMPLATES_URL = "https://api.imgflip.com/get_memes"


class TemplateSourceError(RuntimeError):
    pass


def list_templates(*, session=None) -> list[dict]:
    session = session or requests.Session()
    response = session.get(IMGFLIP_TEMPLATES_URL, timeout=30)
    body = response.json()
    if response.status_code != 200 or not body.get("success"):
        raise TemplateSourceError(f"imgflip template list failed: {body}")
    return body["data"]["memes"]


def pick_template(templates: list[dict], day_index: int) -> dict:
    if not templates:
        raise TemplateSourceError("no templates available")
    return templates[day_index % len(templates)]


def download_template_image(template: dict, out_path: Path, *, session=None) -> Path:
    session = session or requests.Session()
    response = session.get(template["url"], timeout=60)
    if response.status_code != 200:
        raise TemplateSourceError(
            f"failed to download template {template['id']}: status {response.status_code}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(response.content)
    return out_path


def render_caption_on_template(template_image: Path, top_text: str, bottom_text: str,
                                out_path: Path, *, runner=subprocess.run) -> Path:
    def _escape(text: str) -> str:
        # See reel_builder.build_ffmpeg_command for why this isn't `\'`.
        return text.replace(":", r"\:").replace("'", r"'\''").upper()

    top_draw = (
        f"drawtext=text='{_escape(top_text)}':fontcolor=white:fontsize=48:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=20"
    )
    bottom_draw = (
        f"drawtext=text='{_escape(bottom_text)}':fontcolor=white:fontsize=48:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-th-20"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-i", str(template_image),
        "-vf", f"{top_draw},{bottom_draw}",
        "-frames:v", "1",
        str(out_path),
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise TemplateSourceError(f"template render failed: {result.stderr}")
    return out_path
