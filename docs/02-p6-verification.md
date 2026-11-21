# P6 打包验收记录

P6 在 `docs/00-research-plan.md` 里的定义是三件事：六用例回归、Windows 路径/中文文件名/
CP936 专项、以及证明"发出去的东西就是测过的东西"。本文记录执行方式、实测数字，以及
这一轮**跑出来的真问题**——它们不是设计时想到的，是验收逼出来的。

验收脚本是 `tests/verify_p6.py`（标准库，无外部依赖）。

## 1. 为什么宁可麻烦也要测 tarball

工作区能跑不代表发出去的包能跑。两种失败方式只有打包后才看得见：

- **文件漏了**：`tests/test_engine.py` 这种新文件忘了 `git add`，工作区照跑，包里没有。
- **可执行位丢了**：Windows 的 `os.stat` 不报可执行位，一旦按文件系统推，`bin/latex-*`
  在 clone 下来就不可执行。

所以脚本的做法是：`git archive HEAD` → 解到 `包 目录/relocated`（**中文 + 空格**，
顺便就是 putenv 的触发形状）→ **只从那里跑**以下全部检查。`--workspace` 用工作区代替
tarball，只用于改代码时迭代；发布前必须**不带参数**跑一遍。

## 2. 31 项检查与结果

| 组 | 项数 | 内容 |
|---|---|---|
| 打包完整性 | 7 | tarball 存在、33 个必需路径齐、11 个包装脚本在 index 里是 `100755`、包内无 CRLF、无 token 与绝对用户路径泄漏、`doctor` 能从解包目录跑、包装脚本能从无关 cwd 跑 |
| 六用例回归 | 10 | 6 个用例 + 错误定位 + 修复收敛 + 不可修停手 + JSON 可解析率 |
| Windows 路径 | 10 | 7 种目录 + 3 种文件名 |
| CP936 | 4 | 报错而非产乱码、字节不变（repair）、建议正确、换引擎仍不改字节 |

**最终：31/31 通过**（打包 7 项 + 六用例 10 项 + 路径 10 项 + CP936 4 项）。
`--workspace` 模式少 6 项打包检查（没有 tarball 可比），所以那边是 25 项——**25 不是一个
可以发布的数字**，只有 tarball 模式的 31 才算门槛。

## 3. 六用例实测指标

跑在 `git archive` 出来的包上，TeX Live 2026 + Python 3.14.7 + Windows。

| 用例 | 结果 | 引擎 | 页数 | 耗时 | log 原始→压缩 | 压缩比 |
|---|---|---|---|---|---|---|
| `hello` | success | pdflatex | 1 | 1118 ms | 5231 → 512 B | 10.2× |
| `zh` | success | xelatex | 1 | 4184 ms | 26418 → 183 B | 144.4× |
| `bib` | success | pdflatex + biber | 1 | 6704 ms | 12829 → 515 B | 24.9× |
| `tikz` | success | **xelatex** | 1 | 2397 ms | 15039 → 676 B | 22.2× |
| `big` | success | pdflatex | 9 | 1676 ms | 5891 → 514 B | 11.5× |
| `broken` | failed（应然） | pdflatex | — | 1120 ms | 3888 → 911 B | 4.3× |

- **错误定位准确率**：`broken.tex` 唯一定位到 `main.tex:3`（`\undefinedmacro`），
  同时报告 `main.tex:6` 的次生错误。1/1。
- **修复收敛**：`\myemhp` → `\myemph` 的 typo 用例 **2 轮**收敛（第 1 轮修 typo，
  第 2 轮暴露并修掉 `\usepackage` 位置问题），预算是 3。
- **不可修缺陷**：`\undefinedmacro` 无近似匹配，**1 轮**停在 `needs-human`，没有空转。
- **JSON 可解析率**：9/9（`build-report.json`、`round-N.diag.json`、`layout` 报告）。

耗时比 v0.2.0 略高（hello 1046→1118 ms），因为 `compile_project` 多了一次全项目
UTF-8 预检扫描；这点成本换掉了"静默产出乱码 PDF"，值得。

## 4. Windows 路径与文件名

全部通过：

- 目录：`plain`、`with space`、`中文`、`中 文`、`带 空格 目录`、`a b c`、
  `deep/one two/中文 目录/level4/five`（六级嵌套）
- 文件名：`my paper.tex`、`我的 论文.tex`、`résumé.tex`

其中 `中 文` 与 `带 空格 目录` 是 putenv 缺陷的触发形状（CJK 段紧跟空格），
技能靠"只传相对 outdir"绕过，验收时另行打印提示行。

## 5. CP936 专项：两个真缺陷

### 5.1 GBK 文件交给 xelatex 会"成功"产出一份错字 PDF

这是本轮最严重的发现。旧行为链条：

1. `detect_engine` 读源码（`read_text` 的编码链是 utf-8 → cp936），GBK 文件被 cp936
   解码成功，看到中文；
2. 正文有 CJK 且没装 `CJKutf8` → 新规则选 xelatex（这条是对的）；
3. xelatex 拿 GBK 字节按 UTF-8 读 → **有的情况下不报错**，直接排出一堆错字。

一份看起来正常、内容全错的 PDF，比一次失败危险得多。**修法**：`compile_project` 在
启动任何 Unicode 引擎（xelatex/lualatex）之前，扫项目内所有 `.tex`，发现非 UTF-8 就
直接失败并给 `encoding` 诊断。pdfTeX 不做这个检查——`\usepackage[latin1]{inputenc}`
在 pdflatex 下是合法配置。

### 5.2 `repair` 的编码建议原本会把人带错方向

旧逻辑：`encoding` 一律建议换 xelatex。但文件本身不是 UTF-8 时，换引擎只是把一种错误
换成另一种。现在分两支：

- 文件非 UTF-8 → `manual`，给 `iconv -f gb18030 -t utf-8` 命令并停手。
  **不自动转码**：原始编码只能猜，猜错就是毁文件。
- 文件是 UTF-8 只是缺字形 → 才建议换引擎。

配套修了 `_classify`：GBK 源在 pdfTeX 下报的是 `Invalid UTF-8 byte sequence (ÖÐ)`，
报的是**字节**不是字符，文案与 Unicode 分支不同，以前落到 `generic`。

## 6. 引擎探测的第三个规则与两个反例

裸 CJK 判定加进来时，两个反例决定了它的形状：

| 症状 | 想要的行为 | 理由 |
|---|---|---|
| 只有注释里有中文 | 仍是 pdflatex | pdfTeX 不读注释；为注释换引擎会让输出莫名变样 |
| `\usepackage{CJKutf8}` + 中文 | 仍是 pdflatex | 这是刻意的 pdfLaTeX 方案，换引擎反而破坏它 |

所以规则是"**去掉注释后**正文含 CJK，且**没有**加载 `CJK`/`CJKutf8`/`CJKfnt`/`CJKec`
→ xelatex"。去注释用的是转义感知的扫描（`\\%` 不是注释，`a\\%` 后面的 `%` 才是），
单测里四条 `strip_comments` 用例锁住这个边界。

## 7. 这一轮的教训

- **"编译成功"不是证据**。第 5.1 条说明：没有 PDF 魔数之外的判断，成功也可能是有毒的。
  本技能因此坚持"rc + log + `%PDF-` 魔数 + 源文件 sha256 未变"四条同时成立。
- **自检脚本会扫到自己**。泄漏扫描原先写死了 GitHub token 的字面前缀，于是脚本举报自己；
  改成运行时拼接前缀。这条也适用于文档——本文件第一版因为引用了那个字面量被自己的扫描
  判成泄漏。
- **`.gitignore` 也要进 `.gitattributes`**。CRLF 检查在 tarball 模式才暴露：`.gitignore`
  不在 `*.md`/`*.py` 的规则里，被写成 CRLF 也不会有人管，直到 P6 报错。
- **迭代用工作区，门槛用包**。`--workspace` 让改代码快，但它的绿灯不算数——第 1 节那两种
  失败只有 tarball 模式能抓。

## 8. 复现

```bash
cd latex-skill
python tests/verify_p6.py            # 发布门槛：跑 git archive 出来的包，约 55 秒
python tests/verify_p6.py --keep     # 保留 tests/.p6/（含 report.json 与各用例现场）
python tests/verify_p6.py --workspace  # 改代码时迭代，结论不作为发布依据
```

`tests/.p6/report.json` 是机器可读的逐项结果与指标，已在 `.gitignore` 里。
