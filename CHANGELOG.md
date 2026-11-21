# Changelog

版本号遵循 `MAJOR.MINOR.PATCH`：`MAJOR` 破坏 `build-report.json` 契约，
`MINOR` 新增子命令或新增可选字段，`PATCH` 只修 bug。

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
