# latex-automation — DeepSeek Harness 技能

用一句话在本机 LaTeX 上干活：编译、诊断、渲染、检查、脚手架。全部离线。

## 这是什么

一个 DSH 技能（`~/.dsh/skills/latex-automation/`）。它不是一个 LaTeX 插件，也不是一个
GUI —— 它是一组能被 `Bash` 工具直接调用的命令行，加上一份教会模型怎么用这些命令、
怎么读诊断、什么时候该停手的说明书。

- **入口**：`bin/latex-{build,doctor,logs,clean,render,check,init,templates}`
- **实现**：`latex_automation/` 纯标准库 Python 包（无第三方依赖）
- **产物**：落在调用者项目的 `latex-out/`，**不写 `~/.dsh`，不留全局状态**

## 为什么不是插件

调研阶段（`docs/01-research-report.md`）扫过 DSH 生态：LaTeX 相关的十来个项目
**清一色是「插件 + 网页 GUI + 预览窗口」**，没有一个走纯技能形态。插件路线要求
DSH 侧长期维护一套 UI 和常驻服务；技能路线只要子进程能把活干完，模型看得懂输出就够了。
LaTeX 编译天然是「输入文件 → 子进程 → 文本诊断」的形态，用技能更轻也更稳。

## 快装

```bash
SKILL_DIR="$HOME/.dsh/skills/latex-automation"
bash "$SKILL_DIR/bin/latex-doctor"       # 先看环境
bash "$SKILL_DIR/bin/latex-build" 你的项目/
```

要求（缺了会 `doctor` 里报 `warn`/`fail`，不会静默）：

| 级别 | 工具 |
| --- | --- |
| 必需 | `latexmk` `pdflatex` `xelatex` |
| 推荐 | `biber` `bibtex` `kpsewhich` `pdftoppm` `pdfinfo` `chktex` `latexindent` |
| 可选 | `lualatex` `dvisvgm` `pdftotext` `latexdiff` `lacheck` |

Python ≥ 3.8（实测 3.14.7）。包装脚本会自动挑一个能真正执行起来的解释器，
可用 `LATEX_SKILL_PYTHON` 覆盖。

## 与调研结论的对应关系

技能是自研的，但四类设计明确借自 MIT 许可的公开项目，逐条对应：

| 来源 | 借了什么 | 没借什么 |
| --- | --- | --- |
| `Calix-L/awesome-latex-skills`（MIT） | `build-report.json` 的 schema 形状、`%PDF-` 魔数校验、源码 sha256 未变校验、`-recorder` 指纹 | 绝对 `-output-directory`（本机会 putenv 崩）、`-halt-on-error`（会截断错误） |
| `Yaohua-Leo/dsh-latex`（MIT） | 日志正则集（含 `Missing character`）、`docs/env-audit.md` 里的 Windows 事实、`-outdir` 单 argv、latexmk 退出码表 | 插件形态、网页编辑器、PDF 预览 |
| `Qingzhu093/dsh-latex-studio`（MIT） | 引用/浮动体/重跑警告的正则、失败台账与门禁思路 | 环境探测层（硬编码 MiKTeX）、不解析 latexmk 的策略 |
| `OpenRaiser/PaperFit`（MIT） | overfull 归因与 `compile_diagnostics` 的字段形状 | 常驻 monitor 服务、tectonic 依赖 |

`ndpvt-web/latex-document-skill`（无 LICENSE）只读了引擎自动探测规则就停手，
它的「检测不到就自动下载 TeX Live」分支明确不采用。

## 自研补上的四个空缺

1. **CJK+空格的 putenv 规避** —— 生态里没有任何项目处理这个 Windows TeX Live 缺陷；
   本技能把「绝对 outdir 会崩、相对 outdir 安全」做成硬约束。
2. **完全离线的缺包解析** —— `tlmgr` 离线必失败（且退出码撒谎），改用
   `kpsewhich` + `texlive.tlpdb` 本地索引，0.1 秒建 1.4 万条并缓存。
3. **全量收集 + 因果归并** —— 不靠 `-halt-on-error`；`Emergency stop`/`Fatal error`/
   `No pages of output` 全部折进 `suppressed_cascade`，`root_cause` 按类别优先级取第一条。
4. **DSH 技能契约** —— frontmatter、`allowed-tools`、bash 包装、产物落调用者工作区。

## 目录

```
latex-automation/
├── SKILL.md                    # 技能说明书（模型读这个）
├── README.md               # 本文件
├── CHANGELOG.md                # 版本记录
├── LICENSE                     # MIT
├── bin/                        # 8 个 bash 包装 + _bootstrap.sh
├── latex_automation/           # Python 包
│   ├── proc.py                 # 子进程、解码链、runscript 噪音过滤、进程树杀掉
│   ├── paths.py                # 相对 outdir 计算、CJK 检测、项目文件遍历
│   ├── logparse.py             # 日志 → LogReport（本包最大件）
│   ├── packages.py             # tlpdb 离线索引 + 缺包 → 安装命令
│   ├── engine.py               # 引擎/后端探测、latexmk 与直调引擎、报告
│   ├── doctor.py               # 环境与项目体检
│   ├── render.py               # PDF → PNG/JPEG
│   ├── lint.py                 # chktex + latexindent
│   ├── scaffold.py             # 5 个模板
│   └── cli.py                  # argparse 子命令
├── tests/
│   ├── test_logparse.py        # 10 个日志解析单测（fixtures 是真实日志裁剪）
│   └── smoke.sh                # 21 个端到端用例
├── fixtures/                   # broken.tex / misspkg.tex
├── research/                   # 调研脚本与 L4 实测夹具（非运行依赖）
└── docs/
    ├── 00-research-plan.md     # 调研计划
    └── 01-research-report.md   # 调研报告与评分表
```

## 装到 DSH

```bash
git clone https://github.com/ccyk-hash/latex-automation.git \
  "$HOME/.dsh/skills/latex-automation"
bash "$HOME/.dsh/skills/latex-automation/bin/latex-doctor"
```

DSH 启动时扫描 `~/.dsh/skills/*/SKILL.md`，读 frontmatter 的 `name` 与
`description` 决定何时加载。本技能声明 `disable-model-invocation: false`，
所以描述里带触发词即可自动命中；也可在会话里直接说「用 latex-automation 编译这个项目」。

## 验证状态

在 TeX Live 2026 + Python 3.14.7 + Windows 上实测：

- `python -m unittest discover -s tests` → **10/10 通过**
- `bash tests/smoke.sh` → **21/21 通过**，含 5 个模板真编译、2 个 putenv 回归、
  2 个失败文档的因果归并、渲染/检查/清理、报告 schema 契约
- `doctor` → `environment ready: 13 ok, 0 warn, 0 fail`

改任何东西之后这两个套件都必须仍然全绿。`tests/smoke.sh` 必须保持 **LF 行尾** ——
用 CRLF 存会让 Bash 把 `$?` 读成 `"0\r"`，判定全错（这个坑踩过一次）。

## 已知边界

- 不解析 `.dtx`、不做 `\write18` 沙箱、不做 SyncTeX 双向跳转（`--synctex` 只负责生成）。
- 版面检查是「渲染出来给模型看」，没有自动的视觉回归基线。
- 只认 TeX Live 的 `texlive.tlpdb`；MiKTeX 的包库结构不同，缺包提示会退化成
  「不属于任何已装包」。
- 模板是 5 个最小可用骨架，不是期刊投稿模板库。

## 许可

MIT。
