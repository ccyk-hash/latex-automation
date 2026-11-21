# 阶段 2 调研报告：本机 LaTeX 自动化技能的复用性评估

- 调研依据：`docs/00-research-plan.md`（四级漏斗 L1→L4、百分制评分、三条红线）
- 调研时间：2026-11-21
- 本机基线：TeX Live 2026（`D:/Latex/texlive/2026`）、Python 3.14.7、MSYS bash、控制台 CP936
- 证据目录：`research/`（检索缓存 `q01–q10.json`、`readme/`、`tree_*.txt`、`files/`）、`research/l4/`（本机实跑产物）
- 结论摘要：**没有任何仓库达到"复用为主"阈值（≥75）。最优候选 70 分。最终决策＝自研骨架 + 局部 MIT 代码级复用 + 四类设计参考。**

---

## 1. 检索执行情况

### 1.1 规模

| 项 | 值 |
| --- | --- |
| 检索式 | 10 条（q01–q10） |
| 命中总量（各查询 total_count 之和） | 105,328 |
| 去重后进入 L1 的候选 | 41 |
| 进入 L2（读 README） | 12 |
| 进入 L3（抽源码） | 4 |
| 进入 L4（本机试跑） | 2（`check_build.py`、`latexmk` 调用矩阵） |

q09 `latex autofix OR "latex fix"` 的 102,940 命中属于宽泛噪声（大量无关仓库），已在 L1 按 `description` 与 `topics` 过滤掉 99% 以上。

### 1.2 生态图景（关键判断）

GitHub 上的 LaTeX 相关仓库分成四族，**没有一族对应当前任务**：

| 族 | 代表 | 与本任务的关系 |
| --- | --- | --- |
| agent-skill 型（SKILL.md + scripts） | Calix、ndpvt-web、PaperFit | 形态最近，但是 Claude Code / Codex 语境，非 DSH 契约 |
| DSH 插件型（cordis.patch.yml + Web UI） | Yaohua-Leo、Qingzhu093、kasaki002、dichi123456、Mimir | 全部带 GUI/编辑器/侧栏，是**插件**不是**技能** |
| MCP server 型 | arxiv-mcp、OverleafMCP、olcli | 面向远程 Overleaf / arXiv 取源，不做本机编译 |
| 宏包/模板型 | ctex-kit、TongjiThesis、nasa-latex-docs | 是排版内容，不是自动化工具 |

**即：DSH 生态内 LaTeX 能力全部走"插件 + GUI"路线，纯技能 + bash 工具链形态是空缺。** 这与 `00-research-plan.md` 红线三（不因已有插件改变交付形态）一致，也说明本期交付形态有独立价值，而非重复造轮子。

---

## 2. 候选评估（百分制，权重见计划）

权重：任务覆盖 30 / 可复用形态 20 / 本机兼容 20 / 维护状态 10 / 许可依赖 10 / 技能契约 10。
阈值：≥75 复用为主；55–74 参考实现；<55 不纳入。

| # | 候选 | 任务覆盖 | 复用形态 | 本机兼容 | 维护 | 许可 | 技能契约 | **总分** | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `Calix-L/awesome-latex-skills` | 18 | 15 | 12 | 8 | 10 | 7 | **70** | 参考实现（局部可复用） |
| 2 | `ndpvt-web/latex-document-skill` | 26 | 16 | 8 | 9 | 2 | 7 | **68** | 参考实现（代码不可搬） |
| 3 | `OpenRaiser/PaperFit` | 25 | 10 | 10 | 8 | 7 | 6 | **66** | 参考实现 |
| 4 | `Yaohua-Leo/dsh-latex` | 24 | 7 | 14 | 5 | 9 | 4 | **63** | 参考实现 |
| 5 | `Qingzhu093/dsh-latex-studio` | 22 | 8 | 4 | 5 | 7 | 6 | **52** | 不纳入（仅正则参考） |
| 6 | `1692775560/dsh-Mimir` | 20 | 5 | 5 | 9 | 8 | 3 | **50** | 不纳入 |
| 7 | `aloth/olcli` | 10 | 6 | 6 | 8 | 9 | 2 | **41** | 不纳入（Overleaf 远程） |
| 8 | `CTeX-org/ctex-kit` | 6 | 4 | 14 | 9 | 2 | 1 | **36** | 不纳入（宏包非工具） |
| 9 | `MartinCornelius/ltxlog-c` | 8 | 6 | 8 | 2 | 6 | 1 | **31** | 不纳入 |

### 2.1 逐项判据

**#1 Calix-L/awesome-latex-skills（70）**
- 覆盖：`check_build.py` 覆盖 C2 编译（三引擎 + bibtex/biber）、C3 日志定级、C4 部分闭环、C8 部分；缺 C1 独立自检、C5 缺包处置、C7 视觉、C9–C12。
- 形态：`SKILL.md + references/*.md + scripts/*.py` 正是目标形态；但 `doctor.py` 有 `from install import SKILLS`、`check_packages.py` 依赖 `check_distribution`/`project_support`，包内耦合，**只有 `check_build.py` 是真正单文件可拿的**。
- 本机兼容：**实测能跑**（hello/zh/bib/bib2/tikz 全成功），但**默认行为在本机有硬缺陷**——它把 `-output-directory` 传成绝对路径，在"CJK 段 + 空格"路径下触发 TeX Live 2026 的 `putenv(TEXMF_OUTPUT_DIRECTORY=...)` 致命失败。见第 3 节。
- 许可：MIT、纯标准库、无网络调用 → 可代码级复用。
- 契约：frontmatter 仅 `name`/`description`/`metadata.version`，缺 `allowed-tools`/`compatibility`，需补齐。

**#2 ndpvt-web/latex-document-skill（68）**
- 覆盖最高：27 模板 + 27 脚本，`compile_latex.sh` 支持引擎自动探测（`fontspec`/`xeCJK` → xelatex）、latexmk 后端、`texfot`、PDF/A、`--preview`，另有 `pdf_*` 脚本族。
- 但：`compile_latex.sh` 内含 **TeX Live 自动下载安装逻辑**（失败分支直接下载安装），触碰红线一；且**仓库无 LICENSE 文件**（L1 元数据 `license: null`），代码不可直接搬用，只能读设计。

**#3 OpenRaiser/PaperFit（66）**
- 能力最完整：编译 + `parse_log.py` 结构化 + `overfull_attribution.py` 版面归因 + `defect_report_builder.py` + VTO 视觉闭环。
- 但：依赖 Node 18+ / Poppler / tectonic，含 `monitor_server.py` + `monitor_ui/` 常驻服务倾向，触碰红线二；258 个脚本 + 插件式目录结构，抽取成本高。

**#4 Yaohua-Leo/dsh-latex（63）**
- 工程最扎实：`src/build.js` 用 `ctx.subprocess.spawn` 数组传参、无 shell、默认 `-no-shell-escape`、`max_print_line` 拉宽防折行、`PDF_FRESH_SLACK_MS` 防陈旧 PDF 误判；`src/logparse.js` 的正则集**含 `MISSING_CHAR_RE`（缺字形检测）**，是中文排版排障的关键信号。
- `docs/env-audit.md` 是本机 Windows + TeX Live 的**一手事实来源**（退出码 0/12/22、runscript 包装器、`-outdir` 单 argv、CP936 噪音）。
- 但：它是插件（`cordis.patch.yml` + `client.js` + 内嵌 pdf.js），0★、单人维护，不能作为技能直接采用。

**#5 Qingzhu093/dsh-latex-studio（52，不纳入复用）**
- `lib/core/env.js` 硬编码 `D:\MiKTeX\miktex\bin\x64` 与 MiKTeX 注册表，且注释明写「latexmk is deliberately NOT resolved as a compile driver」——与本机 TeX Live 2026 + latexmk 路线直接冲突，兼容项仅 4/20。
- 但其 `lib/core/logparse.js` 的正则集（15 条）与"门禁/台账/回滚"设计仍有参考价值，**仅作离线阅读，不复制代码**。

---

## 3. 本机 L4 实测：决定架构的硬事实

### 3.1 `putenv` 缺陷（最高优先级，所有候选都没处理）

Windows TeX Live 2026 的 `pdflatex` / `xelatex` 在 **`-output-directory` 传绝对路径**且路径含"CJK 段 + 空格"时直接失败：

```
pdflatex.exe: fatal: putenv(TEXMF_OUTPUT_DIRECTORY=D:\...\0_字 字\o6).
```

确定性复现矩阵（两轮独立目录一致）：

| 目录名 | 绝对 outdir | 相对 outdir |
| --- | --- | --- |
| `中 文` | ✗ putenv | ✓ |
| `文 中` | ✗ putenv | ✓ |
| `a中 b` | ✗ putenv | ✓ |
| `中文字 符` | ✗ putenv | ✓ |
| `带 空格 目录` | ✗ putenv | ✓ |
| `中a b` | ✓ | ✓ |
| `字符 中文` | ✓ | ✓ |
| `abc def` | ✓ | ✓ |
| `中文` / `带空格` | ✓ | ✓ |

- `lualatex` 三种情况全部通过（不走同一条 `putenv` 路径）。
- `latexmk -outdir=`（相对或绝对）**全部通过**。→ latexmk 自身不受影响，因为它对子进程的处理不同。
- 结论：**技能必须（a）默认把 outdir 建成相对名交给 latexmk，或（b）直调引擎时只传相对路径。** 这条规则必须写进 SKILL.md，因为 `check_build.py` 的默认行为在本机不可用——实测 `带 空格 目录` 下 `check_build.py` 直接 `status=failed`。

### 3.2 缺包处置必须离线

- `kpsewhich nonexistentpkgxyz.sty` → rc=1；`kpsewhich ctex.sty` → 真实路径。**缺包可判定。**
- `tlmgr search/info` **强制联网**：`TLPDB::from_file could not get texlive.tlpdb from: https://mirror.ctan.org/...`，且 **rc=0**（不能用退出码判断失败）。
- 离线替代：`D:\Latex\texlive\2026\tlpkg\texlive.tlpdb`（20,058,852 B，CRLF）逐行扫 `name ` 起块 + 缩进行文件名，建 `.sty/.cls/.def/.fd` 索引 **0.09 s / 13,966 键**：
  `ctex.sty→ctex`、`geometry.sty→geometry`、`ctexart.cls→ctex`、`tikz.sty→pgf`、`nonexistentpkgxyz.sty→None`。
  → **C5 走 kpsewhich + tlpdb 索引，绝不调 tlmgr。**

### 3.3 全量收集 vs `-halt-on-error`

`cascade.tex`（两处未定义命令 + 一个未闭合 `\frac`）：

| 调用 | `!` 错误数 | 内容 |
| --- | --- | --- |
| 不加 halt | **5** | l.4 `\badcmdA`、l.5 `\badcmdB`、`File ended while scanning use of \frac`、`Emergency stop`、`Fatal error` |
| 加 halt | **2** | 只有第一个 |

→ 诊断顺序必须是**先全量跑（不加 halt）收集 → 再按因果排序**，与 `latex-rescue/SKILL.md` 的 "Read the first causal error" 一致，但实现上不能靠 halt。

### 3.4 实测性能基线（用于设定技能默认超时与阈值）

| 用例 | 引擎/后端 | 耗时 | 产物 |
| --- | --- | --- | --- |
| `hello.tex` | pdflatex ×2 | 1.36 s | 1 页，31,692 B |
| `zh.tex`（ctexart） | xelatex | ~2 s | 1 页 |
| `bib.tex`（biblatex+biber） | xelatex + biber | 4 steps | 1 页 |
| `bib2.tex`（bibtex） | xelatex + bibtex | 4 steps | 1 页 |
| `big.tex`（30 页） | latexmk -pdf | 1.58 s | 9 页，log 5,827 B |
| `tikz.tex`（含中文标注） | latexmk -xelatex | ~1.5 s | 1 页 |
| 渲染 9 页 PNG @100dpi | pdftoppm | 0.74 s | 单页 ~104 KB |
| hello 单页 @110dpi | pdftoppm | — | 10 KB |

→ 默认超时 120 s 足够；视觉检查按页数分批（每批 ≤8 页）控制上下文成本。

### 3.5 其他本机约束（写进实现注意事项）

- `chktex`：只能用 `-q -f "%f:%l:%c:%k:%m\n"` 走 stdout；**`-o` 会报 `Could not rename 'nul' to 'nul.bak'`**。
- `texfot`：outdir 已存在时误报 `! I can't write on file 'hello.log'.`，且失败时 rc 仍为 0 → **不可作为唯一证据源**。
- `latexindent`：可用，纯格式化。
- `pdfinfo`：页数/尺寸可读，但 `CreationDate`/`ModDate` 在 CP936 控制台下乱码（`�й���׼ʱ��`）→ **按行前缀解析，忽略时间字段**。
- 每次经 `runscript` 启动都会打印 2 行 `Initial Win CP ... CP936` 噪音 → 解析前过滤。
- Python 输出含非 GBK 字符会 `UnicodeEncodeError` → 所有脚本入口设 `PYTHONIOENCODING=utf-8`，并统一 `errors="replace"` 读日志。

---

## 4. 复用 / 自研决策

### 4.1 决策

**自研骨架，局部复用 MIT 代码，四类设计参考。** 理由：

1. 最高分 70 < 75，且该 70 分候选在本机默认行为下有致命缺陷（3.1），"直接复用"会在用户的第一个中文路径目录上失败。
2. 唯一覆盖完整的候选（ndpvt-web，68）**无 LICENSE**，代码不可搬。
3. 形态最完整的两个（PaperFit、dsh-latex）都是插件 + GUI + 常驻服务，与"技能 + bash 工具链 + 红线二"冲突。
4. 交付形态（DSH 技能）在整个生态里空缺，没有可复用的整件。

### 4.2 具体处置表

| 来源 | 处置 | 内容 |
| --- | --- | --- |
| Calix `latex-rescue/scripts/check_build.py`（MIT） | **代码级复用 + 修复** | 沿用 `build()` 契约、`build-report.json` schema（`steps[]`/`diagnostics`/`failure`/`failed_step`/`pdf_sha256`）、`%PDF-` 魔数校验、源码 sha256 未变校验、`-recorder` 输入指纹；**改掉**：绝对 outdir → 相对名/交给 latexmk；去掉 `-halt-on-error` 改为两阶段；补 C5 离线缺包解析 |
| Calix `latex-rescue/SKILL.md` 规则 | 设计参考 | "main.tex 是候选不是证据"、"陈旧 PDF 不是构建证据"、"缺工具则编译未验证"、"不得为消错开 shell-escape"、"读第一个因果错误" |
| Yaohua-Leo `src/logparse.js`（MIT） | 正则级参考（重写为 Python） | `MISSING_CHAR_RE`、`ERROR_RE`、`WARNING_RE`、`OVERFULL_RE`、`OUTPUT_RE`、`FATAL_RE`；`parseLatexLog` 的去重与 `seen` 集合策略 |
| Yaohua-Leo `docs/env-audit.md`（MIT） | 事实取证来源 | 退出码 0/12/22、runlatexmk 包装器、`-outdir` 单 argv、`max_print_line`、CP936 噪音、bibtex 的 `BIBINPUTS`/`BSTINPUTS` 行为 |
| dsh-latex-studio `lib/core/logparse.js`（MIT） | 正则级参考 | `UNDEF_REF_RE`/`UNDEF_CITE_RE`/`FLOAT_TOO_LARGE_RE`/`PACKAGE_WARNING_RE`/`RERUN_RE`/`AT_LINES_RE`；`auxFingerprint` 增量判据 |
| dsh-latex-studio 的台账/门禁/回滚设计 | 设计参考 | 缺陷台账、规则门禁、可回滚修改——用于 P4 修复闭环 |
| PaperFit `overfull_attribution.py` 思路 | 设计参考 | 把 overfull 归因到具体段落/表格，而非只报一个 pt 数值 |
| PaperFit `parse_log.py` 的 `compile_diagnostics` 字段 | 设计参考 | `primary_category`/`missing_packages`/`missing_files`/`undefined_macros`/`bibliography_signals`/`suggested_action` 的 JSON 形状 |
| ndpvt-web `compile_latex.sh` | 仅读设计 | 引擎自动探测规则（`fontspec`/`xeCJK`→xelatex）；**自动安装 TeX Live 的分支一律不采用**（红线一） |
| Qingzhu093 `env.js` | 不采用 | MiKTeX 硬编码 + 拒绝 latexmk，与本机冲突 |

### 4.3 生态空缺 → 自研必须补齐的四项

| 编号 | 空缺 | 依据 |
| --- | --- | --- |
| G1 | CJK + 空格路径下的 `putenv` 规避策略 | 所有候选均未处理；`check_build.py` 实测在本机失败（3.1） |
| G2 | 完全离线的缺包 → 包名 → 安装命令解析 | 候选都走 `tlmgr` 联网或干脆不做；本机 `tlmgr` 离线不可用（3.2） |
| G3 | 全量错误收集 + 因果归并（不靠 halt） | `check_build.py` 用 halt 截断成 2 条；候选均无因果排序（3.3） |
| G4 | DSH 技能契约（frontmatter / `allowed-tools` / bash 包装 / 产物落调用者工作区） | 生态内全是插件，无技能形态可参照（1.2） |

---

## 5. 后续实现步骤（P3 起，细化版）

结构不变（bash 包装 + 单文件 Python 标准库优先，产物落调用者工作区 `./latex-out/`），但吸收本次调研结论后细化如下。

### P3 骨架（可交付最小闭环）

| 步骤 | 产物 | 关键要求（来自调研） |
| --- | --- | --- |
| P3.1 | `scripts/latex_doctor.py`（C1） | 探测 `latexmk`/三引擎/`biber`/`bibtex`/`pdftoppm`/`pdfinfo`/`kpsewhich`/`chktex`/`latexindent`；输出 JSON；**不用** 插件式探测顺序，PATH + 显式目录（`D:/Latex/texlive/2026/bin/windows`）；带 `TEXLIVE_WINDOWS_TRY_EXTERNAL_PERL` 说明 |
| P3.2 | `scripts/latex_build.py`（C2/C3） | 默认后端 latexmk + `-outdir=build`（**相对名**）；直调引擎时 outdir 也只传相对路径；`-no-shell-escape`（除非项目要求）；`max_print_line=10000`；两阶段：先全量收集，再判定；`build-report.json` 沿用 Calix schema |
| P3.3 | `scripts/latex_logs.py`（C3） | 移植第 4.2 节正则集（Python 重写）；`\r\n` 归一；过滤 CP936 噪音两行；`errors/warnings/overfull/underfull/undefined_refs/citation_issues/missing_chars/rerun_needed` 分类；`missing_chars` 单独成类 |
| P3.4 | `scripts/latex_clean.py`（C9） | 按后缀白名单清理（`.aux/.log/.fls/.fdb_latexmk/.synctex.gz/.xdv/.bbl/.blg/.bcf/.run.xml/.toc/.out/.lof/.lot/.nav/.snm/.vrb`）；默认 dry-run |
| P3.5 | `scripts/latex_render.py`（C7） | `pdftoppm -r 110 -png -f N -l M`；`pdfinfo` 取页数（忽略时间字段）；输出 PNG 到 `./latex-out/render/` |
| P3.6 | `scripts/latex_check.py`（C12） | `chktex -q -f "%f:%l:%c:%k:%m\n"`；`latexindent --check` 视为可选 |
| P3.7 | `scripts/latex_init.py`（C10） | 3 个内置模板：`article` / `ctexart`（中文）/ `beamer`；生成时即含 `latexmkrc` 或等价配置 |
| P3.8 | `SKILL.md` + `*.sh` 包装 | frontmatter 含 `name/description/license/compatibility/allowed-tools/metadata(version,last-reviewed,skill-author,upstream,verified-on)`；上游标注 `Calix-L/awesome-latex-skills`（MIT）与 `Yaohua-Leo/dsh-latex`（MIT） |

### P4 诊断闭环

- 因果归并：把 `! LaTeX Error: File X not found` 后的 `Emergency stop`/`Fatal error` 折叠掉，只保留根因。
- 缺包 → 包名（`kpsewhich` + tlpdb 离线索引）→ 给出 `tlmgr install <pkg>`（**只给命令文本，不执行**）。
- 缺字形（`Missing character`）→ 提示字体缺失，给出 `fontspec`/`xeCJK` 修复方向。
- 修复循环上限：默认 3 轮，每轮记录 diff（回滚副本），超限即停并如实报告。

### P5 版面视觉

- 只对"用户点名页"或"overfull 命中的页"渲染，避免全量 30 页成本。
- 输入给模型的不是 PNG 本身而是：页号 + overfull 的 pt/位置 + 上下文行。

### P6 打包验证

- 6 个冒烟用例（hello/zh/bib/tikz/broken/big）+ **新增 2 个回归用例**：`带 空格 目录`、`中 文`（守护 G1）。
- 度量：编译耗时、log 压缩比、错误定位准确率、修复轮数、JSON 可解析率。

### P7（预留）WorkBuddy 适配

- 待 DSH 版通过 P6 后启动；预期差异仅在 frontmatter 与包装层，Python 核心复用。

---

## 6. 风险与对策（更新）

| 风险 | 现状 | 对策 |
| --- | --- | --- |
| CJK+空格路径 `putenv` | **已实测确认** | 一律相对 outdir；P6 加回归用例 |
| `tlmgr` 离线不可用 | 已实测确认 | 走 tlpdb 离线索引；只输出安装命令不执行 |
| `-halt-on-error` 截断错误 | 已实测确认 | 两阶段：全量收集 → 因果排序 |
| CP936 乱码 | 已实测确认 | `PYTHONIOENCODING=utf-8` + `errors="replace"` + 前缀解析 |
| `texfot`/`chktex -o` 陷阱 | 已实测确认 | 不用 texfot 作证据源；chktex 只用 `-f` |
| GitHub API 限额 | 调研期多次打满 | 调研已结束；后续仅在需要时低频调用 |
| 视觉检查成本 | pdftoppm 0.74 s/9 页 | 按需渲染单页，不批量 |
| TeX Live 2026 与老项目差异 | 未穷尽 | doctor 输出引擎/包版本，报告里标明实测环境 |

---

## 7. 结论

1. **无可直接复用的整件**：最高 70 分，且在本机默认行为下有硬缺陷；覆盖最全的候选无 LICENSE；形态最完整的都是插件。
2. **可复用的具体资产**：Calix `check_build.py`（MIT，需修 outdir 与 halt 两处）、Yaohua-Leo 与 Qingzhu093 的正则集（MIT，Python 重写）、Yaohua-Leo 的 `env-audit.md`（一手事实）。
3. **自研必须补齐**：G1 putenv 规避、G2 离线缺包解析、G3 因果归并、G4 DSH 技能契约。
4. **交付形态成立**：DSH 生态内 LaTeX 能力全为插件 + GUI，纯技能 + bash 工具链是空缺，不与既有插件重复。

**下一步**：按 P3.1–P3.8 进入实现。等待确认。
