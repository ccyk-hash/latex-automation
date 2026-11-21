# 调研实证材料

本目录是 `docs/00-research-plan.md` 与 `docs/01-research-report.md` 的原始取证材料，
不是技能运行所需的一部分。

| 内容 | 说明 |
| --- | --- |
| `gh_search.py` / `gh_repo.py` / `gh_file.py` | 走 GitHub REST API 的检索脚本（本机 `git clone` 与 `raw.githubusercontent.com` 均不通，只能走 `api.github.com`） |
| `q01.json` … `q10.json`、`aggregate.json` | 10 条检索查询的原始命中（已 gitignore，可用脚本重跑） |
| `tree_*.txt` | 候选仓库的完整文件树 |
| `readme/`、`files/` | 候选仓库的 README 与抽样源码（已 gitignore） |
| `l4/` | L4 本机试跑用的最小 `.tex` 夹具：`hello`/`zh`/`bib`/`bib2`/`tikz`/`big`/`cascade`/`broken`/`miss`/`lint`/`ind` |

`l4/*.tex` 里每一个都对应报告里的一条实测结论：

- `hello.tex` — pdflatex 基线，1.36 s / 1 页
- `zh.tex` — ctexart + xelatex，中文链路
- `bib.tex` — biblatex + biber，4 steps
- `bib2.tex` — 传统 bibtex，4 steps
- `tikz.tex` — xelatex + TikZ + 中文标注
- `big.tex` — 30 页压力样本，latexmk 1.58 s 出 9 页
- `cascade.tex` — `-halt-on-error` 截断证据：不加 halt 有 5 个 `!`，加了只剩 2 个
- `broken.tex` — 三个独立错误，用于因果排序与级联折叠
- `miss.tex` — 缺包诊断，验证错误归属不被错标到 `size10.clo`
- `lint.tex` — chktex 输出格式验证
- `ind.tex` — latexindent 可用性验证

目录名里的空格与中文（`带 空格 目录`、`中 文` 等）是 putenv 缺陷的复现矩阵，
实测完成后已清理，结论见 `docs/01-research-report.md` 第 3.1 节。
