# 本机 LaTeX 自动化技能 —— 调研计划（DSH 版 / 阶段 1）

- 文档版本：v0.1（2026-11-21）
- 适用范围：仅 DeepSeek Harness 版技能；Work Buddy 版本阶段不启动
- 本阶段性质：**只做调研与决策材料，不写实现代码**

---

## 0. 已核实的环境基线（调研的可行性前提）

以下为本次实测结果，作为筛选候选项目时的硬约束，不是猜测：

| 项 | 实测结果 | 对调研的含义 |
|---|---|---|
| TeX 发行版 | TeX Live **2026**，`D:/Latex/texlive/2026`，约 9.7 GB（近似 full scheme） | 主流宏包基本本地就有，**不需要**依赖「按需联网下载宏包」的方案（tectonic 的核心卖点在此失效） |
| 引擎 | `pdflatex` / `xelatex` / `lualatex` / `latexmk` / `biber` / `bibtex` / `kpsewhich` / `tlmgr` / `texliveonfly` 全部在 PATH（`.../bin/windows`） | 编排层首选 `latexmk`；MiKTeX 专属方案不可直接用 |
| 中文 | `ctex.sty` / `ctexart.cls` / `xeCJK.sty` 均存在 | 中文文档是必须覆盖的一等场景，评估维度里单列 |
| 常用宏包 | `article.cls` `geometry` `amsmath` `booktabs` `listings` `tikz` 均存在 | 冒烟测试用例可全部离线跑通 |
| PDF 工具 | `pdftoppm` `pdfinfo` `pdftotext` 有；**`qpdf` / `ghostscript(gs)` / `magick` / `mutool` / `pandoc` 均无** | PDF 逐页渲染只能走 poppler 系；不要设计依赖 gs/magick/pandoc 的流程 |
| Python / Node | `C:/Python314/python.exe`、`py`、`node`、`npm` 可用；**无 `pnpm`** | 若复用 Python 项目，需确认 3.14 兼容性（不少老项目卡 3.9–3.11） |
| 编辑器 | TeXstudio 在 `D:/Latex/texstudio` | 只能作为人工核对手段，不能作为技能依赖 |
| DSH 宿主 | dsh 0.2.2-rc.5；bash 为 MSYS2（路径 `/d/Latex/...`） | 技能入口必须是 bash 可调用；Windows 路径/编码（控制台 CP936）是真实风险点 |
| 技能落点 | `~/.dsh/skills/<name>/`（如 `chemdraw-automation` 已是同款形态：`SKILL.md` + 包装 `.sh` + Python 包 + `tests/` + `README-DSH.md`） | 交付形态有现成模板可对齐，无需另起结构 |
| WorkBuddy 侧 | `~/.workbuddy/skills/`（后续版本），已有 `academic-paper-writing` 等技能 | 本期不碰，仅预留可迁移边界 |

---

## 1. 调研目标与范围

### 1.1 目标（可判定的产出）

1. 判定 GitHub（及 npm / PyPI / DSH 插件市场）上**是否已有**能覆盖「本机 LaTeX 自动化」的开源实现。
2. 对每个候选给出：能直接复用什么（命令 / 库 / 错误映射表 / 设计思路）、不能复用的原因。
3. 输出**一个明确决策**：以复用为主、以参考为主、还是自研薄层；并给出依据分数。
4. 输出后续实现的阶段拆分（只到「做什么、验收标准」，不含代码）。

### 1.2 任务范围（技能要覆盖的 LaTeX 自动化能力清单）

这份清单同时是评估候选项目的**打分基准**（每项 0–3 分）：

| # | 能力 | 说明 | 优先级 |
|---|---|---|---|
| C1 | 环境自检 | 定位 TeX 发行版/引擎/latexmk/poppler，缺什么报什么，给出可执行修复建议 | P0 |
| C2 | 一键编译 | 自动选引擎（含中文→xelatex/lualatex），latexmk 多趟 + bib/biber，超时与并发隔离 | P0 |
| C3 | 日志结构化 | 把上千行 `.log` 压成「文件:行号:错误类型:原文:建议」的紧凑 JSON/Markdown | P0 |
| C4 | 错误修复闭环 | 只修第一处错误 → 复编译，有界迭代（≤N 次），每轮留证据 | P0 |
| C5 | 缺包/缺字体处置 | 判定缺宏包是本地可装（tlmgr）还是代码问题；给出不联网也能降级的写法 | P1 |
| C6 | 中文排版 | ctex/xeCJK、字号字体、断行、中文标点、混排 | P1 |
| C7 | 版面视觉检查 | `pdftoppm` 渲染指定页 → 看图判断溢出/孤行/浮动体错位/表格断裂 | P1 |
| C8 | 引用与参考文献 | bibtex/biber、缺失 key、重复 key、排序样式 | P1 |
| C9 | 清理与增量 | 清理 aux 家族、只重建变更、产物目录规范 | P2 |
| C10 | 模板脚手架 | 论文/报告/幻灯片/中文文档骨架，可直接编译通过 | P2 |
| C11 | 批量构建 | 多 `.tex` 目录批量编译 + 汇总报告 | P2 |
| C12 | 静态检查 | 语法/排版风格检查（chktex 类）与格式化（latexindent 类） | P3 |

### 1.3 明确不在本期范围

- DSH **UI 插件**形态（右侧栏编辑器、PDF 预览面板、插件配置页）——与本阶段「技能」交付形态不同，只在评估时作为设计参考。
- Overleaf / 云端编译 / Docker 编译服务。
- Work Buddy 版技能。
- 学术写作方法论（已有 `academic-paper-writing` 覆盖）。

---

## 2. GitHub 检索方案

### 2.1 检索维度（三轴组合，避免只搜一个词）

- **形态轴**：`skill` / `mcp` / `plugin` / `cli` / `agent` / `dsh` / `claude-code` / `openai`（工具协议）
- **任务轴**：`compile` / `latexmk` / `tectonic` / `log parse` / `error fix` / `pdf render` / `preview` / `linter` / `formatter` / `bibtex` / `tikz`
- **语种轴**：`ctex` / `xecjk` / `chinese` / 中文 / `thesis`

### 2.2 精确查询式（GitHub Search API，`curl` 已验证可用，core 限额 60/h）

优先跑「高信噪比」的 6 组，每组结果缓存成 JSON 落盘再精读，不做重复请求：

```
1) q=latex+mcp+server             sort=stars   per_page=30
2) q=latex+skill+in:name,description,readme   sort=stars
3) q="latex"+"claude" +skill       sort=updated
4) q=latex+compile+agent+tool      sort=stars   stars:>10
5) q=latexmk+pushed:>2025-01-01    sort=stars
6) q=ctex+OR+xecjk+latex           sort=stars
```

补充渠道（低成本、覆盖不一样）：

- topic 页：`topic:latex`、`topic:latexmk`、`topic:agent-skills`、`topic:mcp-server`
- code search（限额 60/h，按需）：`"latexmk" path:SKILL.md`、`"pdftoppm" path:SKILL.md`
- npm / PyPI：`latex` `latexmk` `latex-process` `tectonic`
- DSH 生态：已用插件检索确认存在 **dsh-latex-studio / dsh-latex / dsh-molingTex / dsh-Mimir / kasaki002 dsh-latex-studio** 等（见 §5）

### 2.3 筛选漏斗（四级收敛）

| 级 | 动作 | 淘汰标准 |
|---|---|---|
| L1 元数据 | 星数、最后 push、archived、语言、license | archived；>12 个月无提交且星 <50；纯 demo/课程作业 |
| L2 README | 是否真有「编译 + 日志/错误 + 渲染」链路 | 只是公式渲染、语法高亮、Overleaf 客户端 |
| L3 源码抽样 | 入口文件、错误解析代码、依赖清单 | 硬绑定 MiKTeX / Docker / 云服务；GPL 且需内联 |
| L4 试跑 | 本机装一份最小复现跑通 | 在 TeX Live 2026 + Windows + 无 gs 环境下跑不起来 |

**注意**：L4 只在隔离目录里试跑，不改动 `~/.dsh/profiles`，不安装到当前 profile。

### 2.4 候选项目的评估维度（打分表，满分 100）

| 维度 | 权重 | 判据 |
|---|---|---|
| 任务覆盖度 | 30 | 对照 C1–C12，按 P0=3/P1=2/P2=1 加权求和归一 |
| 可复用形态 | 20 | 20=可直接当 CLI 后端调用；15=可作库引用；8=只能抄设计；0=只能看 README |
| 本机兼容性 | 20 | 是否硬绑 MiKTeX/Docker/联网 bundle；Windows 路径与 CP936 编码表现；Python 3.14 兼容 |
| 维护状态 | 10 | 近 90 天提交、release、issue 响应、CI |
| 许可与依赖 | 10 | MIT/Apache 满分；GPL 且需内联代码扣分；新增依赖数量 |
| 技能契约契合 | 10 | 无 GUI 依赖、非交互、可 JSON 输出、单命令超时可控 |

**决策阈值**：

- ≥ 75：**复用为主**（把它当后端，技能只做编排与提示词层）
- 55–74：**参考实现**（借错误映射表/流程设计，代码自己写）
- < 55：**不纳入**，进入自研

---

## 3. 复用与自研的判断依据

用决策树而不是拍脑袋：

```
候选是否有「非交互、可 bash 调用、输出可解析」的成熟 CLI？
├─ 有 ──> 直接复用为后端（例：latexmk、chktex、latexindent、latexdiff、pdftoppm、pdfinfo）
│         技能层职责 = 选参 + 解析 + 有界闭环 + 给人看的结论
├─ 无，但有可嵌入的库/映射表（log 解析器、错误→修法知识库）
│         └─> vendored 引用或注明依赖；GPL 代码不内联，只外部调用
├─ 只有 DSH 插件形态（UI 插件 / MiKTeX 绑定 / 需装 profile）
│         └─> 不依赖，仅沉淀「设计可借鉴点」与「缺陷清单」
└─ 完全没有 ──> 自研薄层：bash 包装 + 单文件 Python（标准库优先），零新增重依赖
```

**三条红线（写进最终决策里）**：

1. 不引入必须联网下载 bundle 的引擎作为唯一路径（本机是 full TeX Live）。
2. 不引入必须 Docker / 常驻服务 / GUI 的依赖。
3. 不因为「已有插件」就改变交付形态：本期交付是**技能**（`SKILL.md` + 脚本），不是插件。

---

## 4. 已完成的初筛（待 L2–L4 核实，不等于结论）

| 候选 | 形态 | 与本任务的匹配点 | 疑点 / 初判 |
|---|---|---|---|
| `Qingzhu093/dsh-latex-studio` | DSH 插件（10 工具 / 3 技能 / 缺陷台账 / VTO 循环） | 编译门禁 + 结构化诊断 + 逐页看图 + 有界修复 + 回滚，几乎就是目标能力集 | **MiKTeX 原生**，本机是 TeX Live；插件形态非技能形态。→ **参考为主，重点抄它的缺陷分类与台账设计** |
| `Yaohua-Leo/dsh-latex` | DSH 插件 | latexmk 编译 + 保存即刷新 PDF 预览 | 偏编辑器体验，无错误闭环。→ 参考预览与产物组织 |
| `kasaki002/dsh-latex-studio` / `dichi123456/dsh-molingTex` | DSH 插件 | 便携 MiKTeX、21 套模板 | 模板库可借鉴；引擎绑定同样不合 |
| `1692775560/dsh-Mimir-Academic-research` | DSH 插件（大而全） | 边写边编译 + 文献管理 | 体量过大、版本线落后。→ 只看编译子流程 |
| `elias-ramzi/WebLatexMCP` | MCP server（Node） | 本地 latexmk/tectonic 编译、错误回传、git 审阅流 | 强绑 Overleaf/git 流程，超出「本机自动化」。→ 参考「编译→看页→改」的闭环哲学 |
| `SepineTam/latex-mcp` | MCP server | 容器内编译 TeX | Docker 依赖，直接排除 |
| `igorilic/latex-agentic`（`fix-errors` / `compile` 技能） | Agent Skill | 「只修第一处错误、≤5 轮复编译」的边界策略 | 与 C4 高度一致。→ **流程策略直接借鉴** |
| `saintgo7/agents-skills`（latex 家族 7 个技能） | Agent Skill 集 | latex / latex-autofix / latex-thesis-zh / latex-posters | 覆盖面广但偏写作；`latex-autofix` 值得读 |
| `tectonic-typesetting/tectonic` | 引擎（Rust） | 自动多趟、可复现、无中间文件 | 需联网取 bundle，且本机已 full TeX Live。→ **不作主路径**，可作可选后端 |
| `chktex` / `latexindent` / `latexdiff` / `lacheck` | 经典 CLI | C12 静态检查与格式化 | 大概率直接复用（需确认本机 TeX Live 是否带 `chktex`/`latexindent`，待 L4） |
| `latex-process`（PyPI） | Python 库 | 多引擎 + bib + 导出 | 老项目、Py3.14 风险。→ 只参考 API 设计 |
| `benbrastmckie/.config` latex 子代理 | Agent 定义 | 编译序列与阶段化流程 | 只作流程参考 |

> 初筛结论（暂定，待核实后定稿）：**没有找到「Windows + TeX Live + 技能形态」三者同时命中的现成项目**；最接近的两个都各自缺一角（dsh-latex-studio 缺 TeX Live 与技能形态，latex-agentic 缺工程化脚本层）。因此预计落点是 **「复用经典 CLI + 借鉴两个项目的闭环设计 + 自研编排薄层」**。

---

## 5. 验证实验设计（阶段 2 执行，此处先定义标准）

固定 6 个冒烟用例，全部离线可跑：

| 用例 | 覆盖 | 验收标准 |
|---|---|---|
| `hello.tex`（article + amsmath） | C2 基础链路 | 一次调用产出 PDF，耗时记录 |
| `zh.tex`（ctexart + xeCJK） | C6 中文 | 编译通过且无缺字体告警 |
| `bib.tex`（biblatex+biber） | C8 | 参考文献条目正确出现 |
| `tikz.tex`（tikz 图） | C2/C7 | 图完整，无溢出到页边 |
| `broken.tex`（3 处递进错误：缺包→未定义命令→括号不配对） | C3/C4 | 能定位到**第一处**错误并给出最小修法，≤3 轮收敛 |
| `big.tex`（~30 页，含表格/浮动体） | C7 版面 | 能指出 overfull 与明显空洞的页码 |

度量指标（用于对比候选工具与自研基线）：编译耗时、log 原始行数 vs 结构化后行数、错误定位准确率（人判）、修复轮数、JSON 输出可解析率。

---

## 6. 后续实现步骤的初步拆分（阶段 3 起，本阶段不执行）

| 阶段 | 内容 | 验收 |
|---|---|---|
| P3 骨架 | `SKILL.md`（frontmatter 对齐 `chemdraw-automation` 体例）+ `bin/latexctl` 子命令 `doctor / compile / logs / clean / render / check / init` | `doctor` 能准确报出本机引擎与 poppler 状态；`compile` 跑通 hello |
| P4 诊断闭环 | log 解析器 → 结构化诊断 → 最小修复建议 → 有界复编译；错误模式表（缺包/未定义/括号/编码/字体/重复 label） | broken.tex ≤3 轮收敛；每轮留下 `.diag.json` |
| P5 版面与视觉 | `render`（pdftoppm）+ 版面指标（overfull 坐标、空洞、孤行）→ 看图决策 | big.tex 能给出页码级结论 |
| P6 打包验证 | 6 用例回归、Windows 路径/中文文件名/CP936 编码专项、`README-DSH.md` 差异说明 | 全部用例通过；技能可被模型按 description 正确触发 |
| P7（预留） | Work Buddy 版适配（只做入口与落点差异，不改算法） | 不在本期 |

**结构性决策（提前定，避免后期返工）**：编排层用 bash 包装 + 单文件 Python（标准库为主），不引入 pywin32/rdkit 类重依赖；所有产物落调用者工作区（如 `./latex-out/`），不写 `~/.dsh`。

---

## 7. 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| 控制台 CP936 与 UTF-8 日志混排导致中文乱码/解析失败 | C3 准确率 | 解析器统一按字节读、显式多编码尝试；用例里加中文文件名 |
| 路径含空格 / MSYS 路径与 Windows 路径互转 | 全线 | 统一绝对 Windows 路径 + `cygpath` 规范化；用例覆盖 `C:\a b\x.tex` |
| TeX Live 2026 与老项目行为差异（biblatex/ctex 版本） | 复用失败 | L4 必须先跑通再判定复用 |
| GitHub API 限额 60/h | 调研中断 | 结果落盘缓存，分组批量请求，避免重复查询 |
| 视觉检查过度依赖模型看图 | 成本/稳定性 | 先出可量化指标（overfull 坐标/页数/字号），看图只作二次确认 |

---

## 8. 本阶段交付物与下一步

- 交付物：本文件。
- 下一步（待你确认后执行）：按 §2 跑完检索与 L2–L4 筛选 → 填实 §4 的分数表 → 给出「复用 / 参考 / 自研」最终决策与理由 → 再进入 P3。
- 未确认前不写任何实现代码，不改动 `~/.dsh/profiles`，不安装插件。
