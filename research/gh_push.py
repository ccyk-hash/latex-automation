"""Push the working tree to a GitHub repo using the Git Data REST API.

`git push` cannot reach github.com from this host (proxy CONNECT returns 502),
while api.github.com works, so the commit is assembled server-side instead:
blobs -> tree -> commit -> ref update.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

TOKEN = os.environ["GH_TOKEN"]
OWNER = os.environ.get("GH_OWNER", "ccyk-hash")
REPO = os.environ.get("GH_REPO", "latex-automation")
BRANCH = os.environ.get("GH_BRANCH", "main")
ROOT = pathlib.Path(".").resolve()
MSG_FILE = os.environ.get("GH_MSG_FILE", "commit-msg.txt")
API = "https://api.github.com"


def call(method: str, path: str, payload=None):
    url = path if path.startswith("http") else f"{API}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, {"raw": body}


def tracked_files() -> list[tuple[str, str]]:
    """Return (path, git_mode) pairs read from the index.

    The filesystem mode cannot be trusted on Windows: `os.stat` reports no
    executable bits there, so every wrapper would be pushed as 100644 and a
    fresh clone could not run `bin/latex-*`. The index already carries the
    intended mode after `git update-index --chmod=+x`.
    """
    out = subprocess.run(
        ["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, rel = line.split("\t", 1)
        mode = meta.split()[0]
        files.append((rel, mode))
    return files


def bootstrap_empty_repo() -> bool:
    """A brand-new repo rejects blob creation with 409 until it has one commit."""
    status, body = call("PUT", f"/repos/{OWNER}/{REPO}/contents/.bootstrap",
                        {"message": "chore: bootstrap empty repository",
                         "content": base64.b64encode(b"bootstrap\n").decode("ascii")})
    if status in (200, 201):
        print("bootstrapped empty repository with initial commit")
        return True
    print(f"bootstrap FAILED: {status} {body}", file=sys.stderr)
    return False


def main() -> int:
    files = tracked_files()
    if not files:
        print("no tracked files", file=sys.stderr)
        return 1
    print(f"tracked files: {len(files)}")

    entries = []
    for rel, mode in files:
        path = ROOT / rel
        raw = path.read_bytes()
        status, blob = call(
            "POST",
            f"/repos/{OWNER}/{REPO}/git/blobs",
            {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"},
        )
        if status == 409:
            print("repository is empty, bootstrapping")
            if not bootstrap_empty_repo():
                return 1
            status, blob = call(
                "POST",
                f"/repos/{OWNER}/{REPO}/git/blobs",
                {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"},
            )
        if status not in (200, 201):
            print(f"blob FAILED {rel}: {status} {blob}", file=sys.stderr)
            return 1
        entries.append({"path": rel, "mode": mode, "type": "blob", "sha": blob["sha"]})
        print(f"  blob {blob['sha'][:10]}  {mode}  {rel}")

    status, tree = call(
        "POST", f"/repos/{OWNER}/{REPO}/git/trees", {"tree": entries}
    )
    if status not in (200, 201):
        print(f"tree FAILED: {status} {tree}", file=sys.stderr)
        return 1
    print(f"tree: {tree['sha']}")

    # GH_PARENT pins the parent explicitly, which is how a messy branch gets
    # replaced by a single squashed commit; GH_FORCE then allows the ref update.
    pinned = os.environ.get("GH_PARENT", "").strip()
    force = os.environ.get("GH_FORCE", "").strip() in ("1", "true", "yes")
    status, ref = call("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")
    parents = []
    if pinned:
        parents = [pinned]
        print(f"parent: {pinned} (pinned by GH_PARENT)")
    elif status == 200:
        parents = [ref["object"]["sha"]]
        print(f"parent: {parents[0]}")
    else:
        print(f"no existing ref ({status}), creating root commit")

    message = pathlib.Path(MSG_FILE).read_text(encoding="utf-8")
    payload = {"message": message, "tree": tree["sha"]}
    if parents:
        payload["parents"] = parents
    status, commit = call("POST", f"/repos/{OWNER}/{REPO}/git/commits", payload)
    if status not in (200, 201):
        print(f"commit FAILED: {status} {commit}", file=sys.stderr)
        return 1
    print(f"commit: {commit['sha']}")

    if parents:
        status, updated = call(
            "PATCH",
            f"/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}",
            {"sha": commit["sha"], "force": force},
        )
    else:
        status, updated = call(
            "POST",
            f"/repos/{OWNER}/{REPO}/git/refs",
            {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]},
        )
    if status not in (200, 201):
        print(f"ref update FAILED: {status} {updated}", file=sys.stderr)
        return 1
    print(f"ref {BRANCH} -> {updated.get('object', {}).get('sha')}")
    print(f"https://github.com/{OWNER}/{REPO}/commit/{commit['sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
