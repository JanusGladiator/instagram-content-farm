import subprocess
from pathlib import Path


class AssetPublishError(RuntimeError):
    pass


def raw_url(repo_owner: str, repo_name: str, branch: str, relative_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{relative_path}"


def publish_asset(local_path: Path, repo_root: Path, relative_dest: str, *,
                   repo_owner: str, repo_name: str, branch: str = "master",
                   runner=subprocess.run) -> str:
    dest_path = repo_root / relative_dest
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(local_path.read_bytes())

    add = runner(["git", "add", relative_dest], cwd=repo_root,
                 capture_output=True, text=True)
    if add.returncode != 0:
        raise AssetPublishError(f"git add failed: {add.stderr}")

    commit = runner(["git", "commit", "-m", f"content: add {relative_dest}"],
                     cwd=repo_root, capture_output=True, text=True)
    if commit.returncode != 0:
        raise AssetPublishError(f"git commit failed: {commit.stderr}")

    push = runner(["git", "push"], cwd=repo_root, capture_output=True, text=True)
    if push.returncode != 0:
        raise AssetPublishError(f"git push failed: {push.stderr}")

    return raw_url(repo_owner, repo_name, branch, relative_dest)
