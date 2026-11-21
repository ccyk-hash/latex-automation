# P6 验收执行记录（v0.3.0）

`docs/02-p6-verification.md` 写的是**为什么这样验收、抓到了什么缺陷**。本文是**这一次
执行的原始账**：每项检查的名字、判定、现场取值，以及手测覆盖了哪些 02 没提到的角。

- 命令：`python tests/verify_p6.py --keep`（对 `git archive HEAD` 出来的包，不是工作区）
- 结果：**31/31 通过**，耗时 **54.0 s**
- 产物：`tests/.p6/report.json`（逐项 JSON）、`tests/.p6/包 目录/relocated/`（被测包）

## 1. 打包完整性（7 项）

| 检查 | 判定 | 现场 |
|---|---|---|
| tarball 非空 | ok | 389,120 B |
| 33 个必需路径齐 | ok | 14 个模块 + 11 个包装 + `tests/smoke.sh` 与两个单测 + 4 份文档 |
| 包装脚本是 `100755` | ok | 11/11（另 `tests/smoke.sh`、`research/gh_push.py` 也是） |
| 包内无 CRLF | ok | LF only |
| 无 token / 绝对用户路径 | ok | clean |
| `doctor` 能从解包目录跑 | ok | `13 ok, 0 warn, 0 fail` |
| 包装脚本能从无关 cwd 跑 | ok | 在 `relocated/` 的上级目录执行成功 |

第一次跑这一组时挂了两项，都是真问题：

- **CRLF**：`.gitignore` 不在 `.gitattributes` 的 `*.md`/`*.py` 规则里，被写成 CRLF 也没人管。
  补三条规则并把它本身转 LF。
- **自检举报自己**：泄漏扫描写死了 GitHub token 的字面前缀，脚本扫到自己。改成运行时拼接。

## 2. 六用例回归（10 项）

| 用例 | 判定 | 引擎 / 后端 | 页数 | 耗时 | log 压缩 |
|---|---|---|---|---|---|
| `hello` | ok | pdflatex | 1 | 1118 ms | 5231 → 512 B（10.2×） |
| `zh` | ok | xelatex | 1 | 4184 ms | 26418 → 183 B（144.4×） |
| `bib` | ok | pdflatex + biber | 1 | 6704 ms | 12829 → 515 B（24.9×） |
| `tikz` | ok | **xelatex** | 1 | 2397 ms | 15039 → 676 B（22.2×） |
| `big` | ok | pdflatex | 9 | 1676 ms | 5891 → 514 B（11.5×） |
| `broken` | ok（应失败） | pdflatex | — | 1120 ms | 3888 → 911 B（4.3×） |

- 错误定位：`main.tex:3` 命中，同时报 `main.tex:6` 的次生错误 → 1/1。
- 修复收敛：typo 用例 **2 轮**（预算 3）。
- 不可修：`\undefinedmacro` **1 轮**停 `needs-human`，无空转。
- JSON：9/9 可解析。

`tikz` 与 `big` 是这一轮的检查点：前者原来是 pdflatex 且报 3 条 Unicode 错（裸 CJK 探测
不认），后者原来断言 10 页、实际稳定 9 页（断言写错，改成 9）。

## 3. 路径与文件名（10 项）

目录 7 个：`plain`、`with space`、`中文`、`中 文`、`带 空格 目录`、`a b c`、
`deep/one two/中文 目录/level4/five`。
文件名 3 个：`my paper.tex`、`我的 论文.tex`、`résumé.tex`。
全部 ok，没有额外参数——技能自己把 outdir 转成相对路径。

## 4. CP936（4 项）

| 检查 | 现场 |
|---|---|
| 报错而非静默产乱码 | `status=failed`, `categories=['encoding']` |
| `repair` 不改非 UTF-8 文件 | `status=needs-human`，字节不变 |
| 建议里点名编码而不是换引擎 | `main.tex is not UTF-8 encoded` |
| 换引擎也不动字节 | unchanged |

第三条是这轮修出来的：旧逻辑见 `encoding` 就建议换 xelatex，而文件本身不是 UTF-8 时，
换引擎只是把一种错误换成另一种。

## 5. 脚本之外的手测

P6 的六用例偏编译，以下几项是人工补的，结论记在这里：

- **`layout` 对真实文档**：9 页填充文档 `no geometry issues`（rc=0）；手造 300.8pt
  overfull 报 `overflow-edge 2.4pt`（rc=1）；`10cm×14cm` 浮动体报空洞 `18.1x`（rc=1）。
- **`repair --apply` 真改文件**：`\usepackage{amsmath}` 错位 → 第 1 轮搬移、第 2 轮成功，
  备份在 `latex-out/repair/round-1/main.tex`。
- **`check`**：`chktex -f` 管道拿到 2 条警告，退出码 0（警告不算失败）。
- **`init` 的位置参数陷阱**：`latex-init zh` 里的 `zh` 是**目标目录**，模板仍是默认
  `article`——它会在 `./zh` 建一个英文项目。正确写法是 `latex-init . --template zh`。
  这是手测时真踩到的（连着踩两次），所以 `cmd_init` 现在会在「目标名恰好是模板名且未
  指定 `--template`」时打一行提示。
- **`render` + 看图**：120 dpi PNG 能肉眼确认文字冲出右边界——量化与看图互相印证。

## 6. 漏测与未覆盖

- **`latexmk` 后端只在默认路径上被测过**；`--no-latexmk` 直调引擎的多次 pass 只在
  `bib` 用例里跑到（4 steps），没有独立的 pass 稳定性断言。
- **PDF/A、`--shell-escape`、`-synctex`** 三个开关只有代码路径，没有端到端用例。
- **Linux/macOS** 完全没有实测，只有代码里的分支（`os.killpg`、`PATH` 分隔符）。
- **`layout` 的像素级比对**没做（本机无 Ghostscript），只有文本层几何。
- **并发**：两个 `build` 同时写同一个 outdir 没有锁，行为未定义。

这些写进 `README.md` 的「已知边界」，不假装测过。
