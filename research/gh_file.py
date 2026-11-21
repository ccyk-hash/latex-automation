"""Fetch a single file from a repo via GitHub API contents endpoint."""
import base64, json, os, sys, urllib.request, urllib.error

OUT = os.path.dirname(os.path.abspath(__file__))


def get(repo, path, ref=None):
    q = f"?ref={ref}" if ref else ""
    url = f"https://api.github.com/repos/{repo}/contents/{path}{q}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "dsh-latex-research"})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if isinstance(d, list):
        return None, d
    return base64.b64decode(d["content"]).decode("utf-8", "replace"), d


if __name__ == "__main__":
    repo = sys.argv[1]
    for path in sys.argv[2:]:
        safe = repo.replace("/", "_") + "__" + path.replace("/", "_")
        dest = os.path.join(OUT, "files", safe)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            txt, meta = get(repo, path)
        except urllib.error.HTTPError as e:
            print(f"{repo}:{path} HTTP {e.code}")
            continue
        if txt is None:
            print(f"{repo}:{path} is a dir ({len(meta)} entries)")
            continue
        open(dest, "w", encoding="utf-8").write(txt)
        print(f"{repo}:{path} -> files/{safe} ({len(txt)} chars, {meta.get('size')} B)")
