from pathlib import Path
import pytest
from pipeline import asset_host


def test_raw_url_builds_expected_url():
    url = asset_host.raw_url("me", "instagram-farm", "master", "content/assets/a.jpg")
    assert url == "https://raw.githubusercontent.com/me/instagram-farm/master/content/assets/a.jpg"


class FakeCompletedProcess:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_publish_asset_copies_file_runs_git_and_returns_url(tmp_path):
    local_path = tmp_path / "source" / "img.jpg"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"image-bytes")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    calls = []

    def fake_runner(command, cwd, capture_output, text):
        calls.append((command, cwd))
        return FakeCompletedProcess(returncode=0)

    url = asset_host.publish_asset(
        local_path, repo_root, "content/assets/img.jpg",
        repo_owner="me", repo_name="instagram-farm", runner=fake_runner,
    )

    assert url == "https://raw.githubusercontent.com/me/instagram-farm/master/content/assets/img.jpg"
    assert (repo_root / "content/assets/img.jpg").read_bytes() == b"image-bytes"
    assert [c[0][:2] for c in calls] == [["git", "add"], ["git", "commit"], ["git", "push"]]


def test_publish_asset_raises_on_git_failure(tmp_path):
    local_path = tmp_path / "img.jpg"
    local_path.write_bytes(b"x")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_runner(command, cwd, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="add failed")

    with pytest.raises(asset_host.AssetPublishError, match="add failed"):
        asset_host.publish_asset(
            local_path, repo_root, "content/assets/img.jpg",
            repo_owner="me", repo_name="instagram-farm", runner=fake_runner,
        )
