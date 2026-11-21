---
name: latex-automation
description: 在本机 TeX Live 上自动化 LaTeX 任务：编译出 PDF、把 .log 变成带因果排序的结构化诊断、缺包缺字体给出离线安装命令、有界修复闭环自动试改、版面量化（溢出/空洞/孤行）与渲染页面做视觉检查、chktex 静态检查与 latexindent 格式化、从模板新建工程。触发词：LaTeX、latex、TeX、XeLaTeX、pdflatex、lualatex、编译 PDF、论文编译、排版、ctex、中文 LaTeX、latexmk、biber、bibtex、参考文献、.tex、.log、编译报错、overfull、underfull、缺包、缺字体、修复编译错误、自动修 LaTeX、版面检查、孤行、寡行、空洞、模板、latexindent、chktex、渲染页面、LaTeX 自动化。
license: MIT
compatibility: Windows（MSYS bash 调用），已在 TeX Live 2026 + Python 3.14 实测；Linux/macOS 上同样可用，只是路径与引擎探测分支不同。需要本机已装 TeX Live（含 latexmk、pdflatex、xelatex），可选 biber/bibtex/kpsewhich/pdftoppm/pdfinfo/chktex/latexindent。不联网、不自动安装任何 TeX 包。
allowed-tools: Read Write Edit Bash Glob Grep
metadata:
  version: "0.4.0"
  last-reviewed: "2026-11-21"
  skill-author: built for DeepSeek Harness from the research in docs/01-research-report.md
  upstream: https://github.com/ccyk-hash/latex-automation
  verified-on: "DSH bash + WorkBuddy PortableGit bash + TeX Live 2026 (D:/Latex/texlive/2026) + Python 3.14.7 / 3.13.14 on Windows"
disable-model-invocation: false
---

# latex-automation：在本机 TeX Live 上做 LaTeX 自动化

把 `.tex` 变成 PDF，把看不懂的 `.log` 变成「哪一行、什么类别、怎么修」，把缺的包变成
一条可执行的安装命令，把 PDF 渲成图给模型自己看版面。全部走本机已装的 TeX Live，**不联网**。

## 唯一入口

约定 `SKILL_DIR` = 本 skill 根目录。三条等价入口，任选其一：

```bash
# 本 skill 的根目录，选你实际装的那一处
SKILL_DIR="${LATEX_SKILL_DIR:-$HOME/.dsh/skills/latex-automation}"   # DeepSeek Harness
# SKILL_DIR="$HOME/.workbuddy/skills/latex-automation"               # WorkBuddy

# 1) 包装脚本（推荐，自带 PYTHONPATH / UTF-8 / max_print_line 环境）
bash "$SKILL_DIR/bin/latex-build" <项目目录>

# 2) 直接跑模块
PYTHONPATH="$SKILL_DIR" python -m latex_automation build <项目目录>

# 3) 已把 bin/ 加进 PATH 时
latex-build <项目目录>
```

包装脚本会自动挑一个**真能跑**的 Python（`python` → WorkBuddy 托管解释器 → `python3`
→ `py`，逐个实跑验证，跳过 Microsoft Store 的 python3 存根）。需要指定解释器就设
`LATEX_SKILL_PYTHON`。Windows 上 `bin/*.sh` 用 Git Bash / MSYS bash 执行即可
（WorkBuddy 自带 PortableGit，DSH 自带 bash）。

## 子命令一览

| 命令 | 作用 | 典型场景 |
| --- | --- | --- |
| `doctor [dir]` | 探测引擎/工具/字体/tlpdb，给项目体检 | 接手新机器、编译前先确认环境 |
| `build [dir]` | 编译出 PDF，写 `build-report.json` | 主入口，99% 的活都从这开始 |
| `logs [dir]` | 解析已有 `.log`（不重编） | 编译产物还在、只想看诊断 |
| `clean [dir]` | 删中间产物，保留 PDF | 交付前瘦身、强制全量重编 |
| `render [dir]` | PDF 页 → PNG/JPEG | 版面视觉检查、给模型看效果 |
| `repair [dir]` | 有界修复闭环，每轮落 `round-N.diag.json` | 编不过、想让它自己试一轮 |
| `layout [dir]` | 版面量化：溢出/空洞/孤行，页码级结论 | 想知道版面哪里不对，而不只是"看着怪" |
| `check [dir]` | chktex 静态检查 + latexindent | 语法风格、缩进规范 |
| `init <target>` | 从模板新建工程 | 起新文档，别从空白开始 |
| `templates` | 列出模板 | 不确定有哪些模板时 |

所有子命令都支持 `--json`，输出可直接被程序消费。

## build：默认就该这么用

```bash
bash "$SKILL_DIR/bin/latex-build" path/to/project
```

它会自动做完这些判断，**你不需要先告诉它用哪个引擎**：

- **主文档**：在项目里评分挑主 `.tex`（`main.tex`/`paper.tex`/`thesis.tex` 优先，其次浅层、
  其次 `\documentclass` 所在）。挑错了就显式传 `--file other.tex`。
- **引擎**：扫源码里的 `fontspec`/`ctex`/`xeCJK`/`unicode-math` → XeLaTeX；`luacode`/
  `luatexja` → LuaLaTeX；正文里有裸 CJK 字符（且没装 `CJK`/`CJKutf8` 这类 pdfLaTeX 方案）
  → XeLaTeX；否则 pdflatex。`--engine auto` 是默认值。
  注释里的中文不算——pdfTeX 根本不读注释，为它换引擎只会让输出莫名变样。
- **后端**：`biblatex` + `backend=biber` → biber；`\bibliography{}` → bibtex。
- **驱动**：默认走 `latexmk`（自动跑够轮数、自动处理 bib）。`--no-latexmk` 才直调引擎
  并按 `.aux` 指纹跑到稳定。

产物落在项目下的 `latex-out/`，报告是 `latex-out/build-report.json`（`schema: 4`）。

```bash
# 常用开关
--engine {auto,pdflatex,xelatex,lualatex}
--backend {auto,none,bibtex,biber}
--outdir latex-out          # 必须是项目内的相对子目录
--jobname NAME
--timeout 300
--no-latexmk                # 直调引擎
--stop-on-first-error       # 默认关：先全量收集错误再排序
--shell-escape              # 默认永远不加，确有需要才显式开
--synctex                   # 需要正向/反向搜索时
--json
```

### 退出码与判据

`build` 返回 0 才算成功。判定不只看退出码：还要有 `%PDF-` 魔数、PDF 真的落在磁盘上、
源码 sha256 在编译期间没被改动过。**退出码 0 但没出 PDF 的情况一律算失败**。

## 读诊断：先读 root_cause

`build` 失败时的输出形如：

```
build failed: File `nonexistentpkgxyz.sty' not found at misspkg.tex:3
engine: pdflatex (...); backend: none
failure: ...
  error [missing_package] misspkg.tex:3: File `nonexistentpkgxyz.sty' not found.
```

规则只有一条：**看 `root_cause`，不要看 `errors` 里的最后一条**。TeX 的错误会级联，
`Emergency stop` / `Fatal error occurred` / `No pages of output` 是后果不是原因，
它们在 `counts.suppressed_cascade` 里计数，不进 `errors`。

因果优先级（`root_cause` 就是按这个排序取第一条）：

```
missing_package < missing_file < undefined_macro / undefined_environment / unbalanced_argument
< math_or_brace < encoding < package_error < generic
```

同优先级下 `.tex` 文件优先于宏包文件，再按行号升序。**位置永远指向作者源码**，
不会指到 `size10.clo`、`main.aux` 或 `inserted text` 这类伪帧上去。

想拿完整结构：

```bash
bash "$SKILL_DIR/bin/latex-build" proj --json | python -c "import json,sys; d=json.load(sys.stdin); print(d['log']['root_cause'])"
```

## 缺包 / 缺字体：离线解析，别去 tlmgr 联网

`build` 失败时会把缺失的 `.sty`/`.cls` 拿去查本机 TeX Live 的文件清单
（`tlpkg/texlive.tlpdb`，索引 1.4 万+ 文件名，0.1 秒建完并缓存），直接告诉你包名：

```
missing packages:
  nonexistentpkgxyz.sty -> not provided by any installed TeX Live package
  algorithm2e.sty -> algorithm2e: tlmgr install algorithm2e
```

`tlmgr search` / `tlmgr info` **必须联网**，离线必失败（而且失败时退出码还是 0，别被骗）。
所以判断「装没装、属于哪个包」一律走 `kpsewhich` + 本地 tlpdb 索引。

**缺字形**（中文最常见的坑）表现为 `Missing character: There is no 中 in font ...`，
这类信息进 `log.missing_chars`，`detail` 是字体名。根因通常是：

- 用 pdflatex 编了含中文的文档 → 换 `--engine xelatex` + `ctex`/`xeCJK`；
- 字体真有缺口 → 换字体或加 `\setCJKmainfont`。

## 静态检查与格式化

```bash
bash "$SKILL_DIR/bin/latex-check" proj               # chktex 报告
bash "$SKILL_DIR/bin/latex-check" proj --format      # 顺带打印 latexindent 结果
bash "$SKILL_DIR/bin/latex-check" proj --format --in-place   # 直接改写
```

`chktex` 在本机（v1.7.9）**不能用 `-o` 输出到文件**，会报 `Could not rename 'nul'`，
所以这里固定用 `-f "%f:%l:%c:%k:%m"` 走 stdout。`--in-place` 会改文件，改前想清楚。

## 新建工程

```bash
bash "$SKILL_DIR/bin/latex-templates"
bash "$SKILL_DIR/bin/latex-init" my-paper --template zh --title "论文标题" --author "作者"
```

模板：`article`(pdflatex) / `zh`(xelatex + ctexart) / `biblatex`(pdflatex + biber) /
`beamer`(pdflatex) / `tikz`(lualatex)。生成后目录里有 `latex-project.json` 记着清单。

## 有界修复闭环

文档编不过时，**不要盲改源码**。`repair` 把这件事变成一个有上限的循环：

```bash
bash "$SKILL_DIR/bin/latex-repair" proj                  # 先看它想怎么修
bash "$SKILL_DIR/bin/latex-repair" proj --apply          # 允许它改源码
bash "$SKILL_DIR/bin/latex-repair" proj --apply --max-rounds 3 --json
```

语义要点：

- **每轮只出一条建议、只改一处**。构建开关类建议（换引擎）不需要 `--apply`，
  下一轮编译本身就能证明对错。
- 不加 `--apply` 时只报告，`status` 为 `needs-apply`，源码一个字节都不动。
- `--apply` 会**先备份再改**，备份在 `latex-out/repair/round-N/`。只改 UTF-8 文件——
  把 CP936 文件按 UTF-8 写回会静默毁掉它，所以这类文件直接判 `needs-human`。
- 每轮都会写 `latex-out/round-N.diag.json`，几轮之间可以 diff。

`status` 的六种结果，各自该做什么：

| status | 含义 | 下一步 |
| --- | --- | --- |
| `already-ok` | 一编就过 | 没你的事了 |
| `repaired` | 改完过了 | 看一眼备份目录，确认改得对 |
| `needs-apply` | 有建议但没授权改 | 加上 `--apply` 重跑 |
| `needs-human` | 建议需要人做（装包、换字体、逻辑错） | 读 `stopped_reason`，照做 |
| `failed` | 同一根因修了还在 | 停手，人工看源码 |
| `exhausted` | 轮数用完还不过 | 提高 `--max-rounds` 或人工介入 |

哪些情况它**不会**硬试（这是设计，不是缺陷）：缺包要联网装、需要加字体、缺图缺
`.bib` 条目、源码逻辑错。这些停下来给结论比乱改更有用。

不想用闭环、只想手动走一遍时：`latex-build proj` → 读 `root_cause`（file / line /
category / message）→ 只改那一处 → 重跑。`--shell-escape` 永远不是消错手段。

## 版面视觉检查

两件事，用途不同：

**看图**（人/模型的眼睛）：

```bash
bash "$SKILL_DIR/bin/latex-render" proj --dpi 120             # 全部页
bash "$SKILL_DIR/bin/latex-render" proj --first 1 --last 3     # 只看前 3 页
bash "$SKILL_DIR/bin/latex-render" proj --jpeg                 # JPEG 更小
```

产物在 `latex-out/render/`，用 Read 工具打开 PNG 自己看。文字溢出页边、浮动体错位、
图表压字、目录页空白这些 `overfull` 说不清的问题，只能看图判断。

**量化**（不必逐页看就能定位）：

```bash
bash "$SKILL_DIR/bin/latex-layout" proj
bash "$SKILL_DIR/bin/latex-layout" proj --json --report latex-out/layout.json
bash "$SKILL_DIR/bin/latex-layout" proj --only 2 3      # 只看第 2、3 页
```

它用 `pdftotext -bbox-layout` 拿每行坐标，报四类问题：

| kind | 判据 | severity |
| --- | --- | --- |
| `overflow-edge` | 行尾超过**纸张**右边界 | `error`（确定） |
| `overflow-margin` | 行尾超过**版心**右边界但仍在纸内 | `layout`（确定） |
| `hole` | 相邻行间距 > 4× 正常行距 | `layout`（启发式，0.8） |
| `widow-orphan` | 页首短行不缩进（寡行）/ 页末行缩进（孤行） | `warning`（启发式，0.7） |

几个判据是**校准过的**，改之前先读代码注释：行距取 20% 分位数而非中位数（否则短
页上的空洞会把"正常行距"拽过去）；版心右边界取"至少两行互相印证的最右聚类"（单行
不能自证，越界行不能定义正常）；孤行按**缩进**判而非按短行判（段落末行本来就是短
的，按短行判会给每个正常段落都报一次）；空洞阈值 4× 而非 2.5×（标题前的 2.5–3× 间距
是正常排版）。

**几何看不到的，日志补**：比版心宽、但还没冲出纸面的盒子，`pdftotext` 的坐标看不出
异常，只有 `.log` 的 `Overfull \hbox` 知道。所以 `layout` 默认读同名 `.log` 并把它
并进 `log_overfull`；测不出右边距时（短页、beamer 这类行数太少的文档）会在
`measure_source` 标 `log`，并在摘要里明说"right margin not measurable"——这是诚实的
测不了，不是漏报。

退出码按**严重度**而非置信度：`error`/`layout` 类问题 rc=1，纯 `warning` 类 rc=0
（可疑寡行只是样式提示，调用者可以合法忽略）。

## 必须知道的平台约束

### 1. `--outdir` 只能是项目内的相对子目录

Windows TeX Live 有一个确定性缺陷：**绝对路径** `-output-directory` 且路径里「CJK 段紧跟
空格」时，`pdflatex`/`xelatex` 直接 `fatal: putenv(TEXMF_OUTPUT_DIRECTORY=...)` 死掉（rc=1，
无 PDF）。`lualatex` 不受影响，`latexmk -outdir=` 也不受影响。

所以本技能**永远给引擎传相对 outdir**，并在检测到风险路径时打印提示。想放到项目外
（比如 `--outdir ../build`）会直接报错让你改回来 —— 这是故意的，不是 bug。

### 2. `-halt-on-error` 默认关

它会在第一个错误处停下，把后面的错误全吞掉。本技能的策略是**先全量收集再按因果排序**，
这比「第一行 `!` 就是根因」可靠得多（第一行 `!` 经常只是前一个错误的余波）。

### 3. 不要用 `texfot` 当证据源

本机实测：outdir 已存在时它报 `! I can't write on file '...log'` 却仍然 **exit 0**，
退出码不可信。判断成败只看本技能的 `build-report.json`。

### 4. 日志里的乱码是正常的

`latexmk` 经 runscript 启动会打印两行 `Initial Win CP ...`，技能已过滤。
`pdfinfo` 的时间字段在 CP936 控制台下必然是乱码，技能只解析 `Pages`/`Page size`，
**不要拿 `pdfinfo` 的 CreationDate 去做任何判断**。

### 5. 绝不自动联网装 TeX 包

`build` 不会执行 `tlmgr install`，只打印命令。装不装、装什么是用户决定。

### 6. 非 UTF-8 的 `.tex` 会被拒绝，而不是硬编

GBK/GB18030 源交给 xelatex 会"编译成功"，产出一份全是错字的 PDF —— 这比报错更糟，因为
没人看得出坏了。所以选 Unicode 引擎（xelatex/lualatex）时，`compile_project` **在启动前**
扫项目里的 `.tex`，发现非 UTF-8 直接失败并给 `encoding` 诊断，`repair` 也不会去改那个文件，
只告诉你先转码：

```bash
iconv -f gb18030 -t utf-8 'main.tex' > 'main.tex.utf8' && mv 'main.tex.utf8' 'main.tex'
```

pdfTeX 不做这个检查：`\usepackage[latin1]{inputenc}` 在 pdflatex 下是合法配置。

## 报告结构（`latex-out/build-report.json`）

```jsonc
{
  "schema": 4,
  "status": "success" | "failed",
  "engine": "xelatex",
  "engine_reason": "document loads ctex/xeCJK/fontspec",
  "backend": "biber" | "bibtex" | null,
  "source": "...", "pdf": "...", "outdir": "...",
  "duration_ms": 1830,
  "steps": [{ "tool": "latexmk", "command": [...], "returncode": 0, "duration_ms": 1790 }],
  "log": { /* LogReport：success/pages/errors/warnings/layout/missing_chars/
              undefined_refs/undefined_cites/missing_files/missing_packages/
              root_cause/counts{errors,warnings,layout,missing_chars,suppressed_cascade} */ },
  "failure": null,
  "pdf_sha256": "...", "source_sha256": "...",
  "warnings": ["..."]   // 技能自己给的提示，例如 putenv 规避
}
```

`repair` 与 `layout` 另有两类产物：

- `latex-out/round-N.diag.json` —— 修复闭环每一轮的诊断快照（`status`/`root_cause`/
  `suggestion`/`applied`/`note`），几轮之间可直接 diff；
- `latex-out/repair/round-N/<file>` —— `--apply` 改动前的原文件备份；
- `--report` 指定的 `layout.json` —— 版面量化的完整结果（`counts`/`issues`/`log_overfull`/
  逐页 `lines`/`measure_pt`）。

## 出错时怎么办

| 现象 | 处理 |
| --- | --- |
| `no .tex file found` | 显式 `--file`，或确认目录里真有 `.tex` |
| `output directory ... is outside the project` | `--outdir` 改回项目内 |
| `log not found` | 先 `build` 一次；或 `--log` 指到具体 `.log` |
| `python3` 存在但包装脚本没输出 | 那是 Store 存根；设 `LATEX_SKILL_PYTHON=python` |
| `layout` 说 `right margin not measurable` | 行数太少无法定版心（beamer、单行页）；这是诚实结论，此时看 `log_overfull` |
| 编译成功但 PDF 是旧的 | 看 `report` 里的 `pdf_sha256`；不确定就 `clean --drop-pdf` 后重编 |
| 中文全是空白/方框 | 引擎选错，`--engine xelatex`；看 `log.missing_chars` 确认字体 |

## 自检

```bash
bash "$SKILL_DIR/tests/smoke.sh"          # 31 个端到端用例，约 60 秒
python -m unittest discover -s "$SKILL_DIR/tests"   # 44 个单测（日志解析 + 引擎探测 + 版面量化）
python "$SKILL_DIR/tests/verify_p6.py"    # 25 项打包验收，约 60 秒；发布前必跑
```

冒烟套件里有两个**故意难看的目录名**（`带 空格 目录`、`中 文`）——它们就是 putenv 回归，
任何改动后都必须仍然全绿。

`verify_p6.py` 不跑工作区，它跑 `git archive HEAD` 出来的包，解到 `包 目录/relocated`
（中文 + 空格）再验证。工作区能跑而包里跑不了，就是打包漏了文件或丢了可执行位。
改代码时用 `--workspace` 迭代，发布前**不带参数**跑一遍。
