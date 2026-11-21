"""Fetch repo README + file tree via GitHub API (core limit 60/h)."""
import base64, json, os, sys, time, urllib.request, urllib.error

OUT = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


def api(path, tries=3):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "dsh-latex-research",
        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {}),
    })
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and k < tries - 1:
                time.sleep(20 * (k + 1))
                continue
            return {"_error": e.code, "_msg": e.read()[:200].decode("utf-8", "replace")}


def one(repo):
    safe = repo.replace("/", "_")
    rd = os.path.join(OUT, "readme")
    os.makedirs(rd, exist_ok=True)
    meta = api(f"/repos/{repo}")
    if "_error" in meta:
        print(f"{repo}: META ERR {meta['_error']} {meta['_msg']}")
        return
    info = {
        "full_name": meta["full_name"], "stars": meta["stargazers_count"],
        "pushed": meta["pushed_at"][:10], "created": meta["created_at"][:10],
        "lang": meta.get("language"), "license": (meta.get("license") or {}).get("spdx_id"),
        "archived": meta["archived"], "size_kb": meta["size"],
        "desc": meta.get("description"), "topics": meta.get("topics", []),
        "default_branch": meta["default_branch"], "open_issues": meta["open_issues_count"],
    }
    print(json.dumps(info, ensure_ascii=False))
    time.sleep(0.6)
    r = api(f"/repos/{repo}/readme")
    if "_error" not in r:
        txt = base64.b64decode(r["content"]).decode("utf-8", "replace")
        open(os.path.join(rd, safe + ".md"), "w", encoding="utf-8").write(txt)
        print(f"  readme {len(txt)} chars -> readme/{safe}.md")
    else:
        print(f"  README ERR {r['_error']}")
    time.sleep(0.6)
    t = api(f"/repos/{repo}/git/trees/{info['default_branch']}?recursive=1")
    if "_error" not in t:
        paths = [e["path"] for e in t.get("tree", []) if e["type"] == "blob"]
        open(os.path.join(OUT, "tree_" + safe + ".txt"), "w", encoding="utf-8").write("\n".join(paths))
        print(f"  tree {len(paths)} files -> tree_{safe}.txt")
        print("  sample:", ", ".join(paths[:18]))
    else:
        print(f"  TREE ERR {t['_error']}")


if __name__ == "__main__":
    for repo in sys.argv[1:]:
        one(repo)
        print("-" * 60)
