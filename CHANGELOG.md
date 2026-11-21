# Changelog

版本号遵循 `MAJOR.MINOR.PATCH`：`MAJOR` 破坏 `build-report.json` 契约，
`MINOR` 新增子命令或新增可选字段，`PATCH` 只修 bug。

## v0.2.0 — 2026-11-21

补上调研计划里的 P4（诊断闭环）与 P5（版面视觉量化）。`build-report.json` 契约不变。

### 新增子命令

- **`repair [dir]`** —— 有界修复闭环。每轮编译一次、只出一条建议、只改一处，
  最多 `--max-rounds`（默认 3）轮，每轮写 `latex-out/round-N.diag.json`。
  建议类型：`switch-engine`（换引擎，不需授权）、`edit`（单行源码改名/补 `$`）、
  `move-to-preamble`（把误放的 `\usepackage` 搬回导言区）、`install`（给
  `tlmgr install` 命令但不执行）、`manual`（需要人或需要联网，立即停手）。
  六种 `status`：`already-ok` / `repaired` / `needs-apply` / `needs-human` /
  `failed` / `exhausted`。
- **`layout [dir]`** —— 版面量化。走 `pdftotext -bbox-layout` 取每行坐标，报
  `overflow-edge`（越过纸边，`error`）、`overflow-margin`（越过版心，`layout`）、
  `hole`（行距 > 4× 正常，`layout`）、`widow-orphan`（孤行/寡行，`warning`）。
  默认并读同名 `.log`，把 `Overfull \hbox` 并进 `log_overfull` 以覆盖几何看不见的
  盒子。退出码按严重度而非置信度。

### 关键设计（每条都有实测依据）

- **修复只改 UTF-8 文件** —— 把 CP936 文件按 UTF-8 写回会静默毁掉它，比不修更糟；
  这类文件直接判 `needs-human`。
- **`--apply` 先备份再改**，备份在 `latex-out/repair/round-N/`。备份目录用绝对路径：
  `--outdir` 相对项目根，`mkdir` 却相对进程 cwd，早期版本会把备份写到错误位置。
- **行距取 20% 分位数而非中位数** —— 短页上一个 430pt 的浮动体空洞会把中位数拽走，
  检测失效（实测 3.9× 漏报）；改分位数后 18.1× 正确报出。
- **版心右边界取「至少两行印证的最右聚类」** —— 单行不能自证；取最频繁聚类会被表格
  列边（成员更多）骗到，取中位数会被越界行自己拽走。同一份 zh 示例早期误报 3 条
  `overflow-margin`，改后 0 条。
- **孤行按缩进判，不按短行判** —— 段落末行本来就是短的。早期版本给 9 页文档报 16 条
  假孤行，改后 4 条；而真实「段首孤悬页底」的 8 页文档报 7 条，全部命中。
- **空洞阈值 4×** —— 标题前 2.5–3× 的间距是正常排版，2.5× 阈值会报 15 条假空洞。
- **`summary()` 不会把「测不了」藏起来** —— 版心无法确定时明说
  `right margin not measurable: too few full lines`，并退回只看日志 overfull。

### 验证

- 单测 **28/28**（`test_logparse.py` 10 + 新增 `test_layout.py` 18，后者用手造 box 数据
  绕开真实 `pdftotext`，一个用例只考一个判据）。
- 冒烟 **31/31**，新增 8 例：修复闭环 5（干净文档 `already-ok`、`\usepackage` 错位
  自动搬回并保持行序、备份落盘、`round-1.diag.json` 存在、需人工时非零退出）、
  版面量化 4（合规文档 rc=0、overfull rc=1、`--report` JSON 契约）。

### 修正

- `repair` 的备份目录改为绝对路径解析（相对 `--outdir` 会落到调用者 cwd）。
- `_split_furniture` 不再把「只剩一行正文」的页面吸成页眉：那更可能是真实空洞。

## v0.1.0 — 2026-11-21

首个可交付版本。DeepSeek Harness 技能形态，本机 TeX Live 实测通过。

### 新增

- 子命令 `doctor` / `build` / `logs` / `clean` / `render` / `check` / `init` / `templates`，
  全部支持 `--json`。
- 引擎自动选择：扫描主文档判断是否需要 `xelatex`（`ctex`/`xeCJK`/`fontspec`/CJK 字符）
  或 `lualatex`（`luacode`/`luatexja`），默认经 `latexmk` 驱动。
- 后端自动选择：`biblatex` 读 `backend=` 选项，否则看 `\bibliography` 决定
  `biber` / `bibtex`。
- 两阶段诊断：先全量收集（不加 `-halt-on-error`），再按因果优先级排序
  （缺包 → 缺文件 → 未定义宏 → 数学/括号 → 编码 → 其它），级联后果折叠进
  `counts.suppressed_cascade`。
- `TeX` 文件栈跟踪，错误归属到作者源码而不是 `size10.clo` / `.aux` 之类的中间文件。
- 完全离线的缺包解析：`kpsewhich` 判定 + `texlive.tlpdb` 本地索引（0.1 s / 1.4 万条，
  按 mtime 缓存），给出 `tlmgr install <pkg>` 建议；`tlmgr` 本身离线不可用且退出码
  会撒谎，因此从不调用它。
- CJK+空格 putenv 规避：所有 outdir 一律以**相对路径**传给引擎，绝对路径仅在
  内部用于校验，命中风险特征时在报告里给出显式 warning。
- 5 个脚手架模板：`article` / `zh`（ctexart + xelatex）/ `biblatex`（biber）/
  `beamer` / `tikz`（lualatex）。
- 版面视觉检查：`render` 走 `pdftoppm` 出 PNG，附带页数与页面尺寸；
  `pdfinfo` 只解析 `Pages` / `Page size` / `PDF version` / `Encrypted`（时间字段在
  CP936 控制台下是乱码）。
- `check` 走 `chktex -f "%f:%l:%c:%k:%m"`（不用 `-o`，本机 `-o` 会报
  `Could not rename 'nul' to 'nul.bak'`），`latexindent` 做格式化。
- `build-report.json`（`schema: 4`）：`steps[]` 含每条命令的 argv、cwd、退出码、
  耗时、日志路径；顶层含 `status` / `engine` / `engine_reason` / `backend` /
  `pdf_sha256` / `source_sha256` / `failure` / `failed_step` / `warnings`。
- bash 包装 `bin/latex-*`：逐个候选真跑 `python -c` 验证解释器可用
  （本机 `python3` 是 Microsoft Store 存根，`command -v` 能找到但不执行），
  支持 `LATEX_SKILL_PYTHON` 覆盖。

### 验证

- `python -m unittest discover -s tests` → 10/10。
- `bash tests/smoke.sh` → 21 passed, 0 failed，含 5 个模板真编译、2 个 putenv 回归
  （`带 空格 目录`、`中 文`）、2 个预期失败的破坏性用例、1 个报告契约校验。
- 环境：TeX Live 2026 / Python 3.14.7 / Windows / MSYS bash。

### 已知边界

- 只处理本机已安装的 TeX 发行版，不联网下载 bundle。
- `bin/*.sh` 与 `tests/*.sh` 必须保持 LF 行尾（`.gitattributes` 已固定），
  CRLF 会让 bash 的 `$?` 捕获静默失效。
- outdir 必须在项目目录内；跨盘或上级目录会被拒绝并说明原因。
