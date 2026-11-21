"""GitHub repo search -> compact CSV/markdown, cached per query."""
import json, sys, time, urllib.parse, urllib.request, os

OUT = os.path.dirname(os.path.abspath(__file__))
QUERIES = [
    ("q01", 'latex mcp server', 'stars'),
    ("q02", 'latex skill in:name,description', 'stars'),
    ("q03", 'latex compile agent', 'stars'),
    ("q04", 'latexmk', 'stars'),
    ("q05", 'ctex OR xecjk OR "chinese latex"', 'stars'),
    ("q06", 'latex cli pdf compile', 'stars'),
    ("q07", 'texlive automation', 'stars'),
    ("q08", 'latex log parse error', 'stars'),
    ("q09", 'latex autofix OR "latex fix"', 'updated'),
    ("q10", '"agent skill" latex', 'stars'),
]


def fetch(q, sort, n=30, tries=4):
    url = ("https://api.github.com/search/repositories?q="
           + urllib.parse.quote(q) + f"&sort={sort}&order=desc&per_page={n}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "dsh-latex-research"})
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and k < tries - 1:
                wait = 25 * (k + 1)
                print(f"  [403] wait {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def brief(it):
    return {
        "full_name": it["full_name"],
        "stars": it["stargazers_count"],
        "pushed": it["pushed_at"][:10],
        "lang": it.get("language"),
        "license": (it.get("license") or {}).get("spdx_id"),
        "archived": it["archived"],
        "size_kb": it["size"],
        "desc": (it.get("description") or "").replace("\n", " ")[:160],
    }


def main():
    only = sys.argv[1:] or None
    agg = {}
    for name, q, sort in QUERIES:
        if only and name not in only:
            continue
        path = os.path.join(OUT, name + ".json")
        legacy = {"q02": "s2", "q05": "s5", "q07": "s7"}.get(name)
        for cand in ([path] + ([os.path.join(OUT, legacy + ".json")] if legacy else [])):
            if os.path.exists(cand) and os.path.getsize(cand) > 500:
                path = cand
                break
        else:
            path = os.path.join(OUT, name + ".json")
        if os.path.exists(path) and os.path.getsize(path) > 500:
            data = json.load(open(path, encoding="utf-8"))
        else:
            data = fetch(q, sort)
            json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(7)  # search API: 10 req/min
        items = [brief(i) for i in data.get("items", [])]
        agg[name] = {"query": q, "total": data.get("total_count"), "items": items}
        print(f"\n### {name}  q={q}  total={data.get('total_count')}")
        for i in items:
            flag = "A" if i["archived"] else " "
            print(f'{flag} {i["stars"]:>6} {i["pushed"]} {str(i["lang"]):<10} {str(i["license"]):<12} {i["full_name"]} — {i["desc"][:110]}')
    json.dump(agg, open(os.path.join(OUT, "aggregate.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
