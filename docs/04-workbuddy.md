# WorkBuddy 版：同一份代码，换一个头部

第一个交付物（DeepSeek Harness 版）在 v0.3.0 做完。这一版是把同一套能力装到
WorkBuddy 里。做法不是复制一份代码，而是**只换 SKILL.md 的头部**，正文与 Python 包
逐字节共用。

## 1. 为什么可以共用

实测两台宿主在真正相关的地方没有差异：

| 维度 | DeepSeek Harness | WorkBuddy | 结论 |
|---|---|---|---|
| 技能目录 | `~/.dsh/skills/<name>/` | `~/.workbuddy/skills/<name>/` | 只有前缀不同 |
| 发现方式 | 扫 `*/SKILL.md`，读 `name` + `description` | 同上 | 相同 |
| 执行工具 | `Bash`（MSYS bash） | `Bash`（自带 PortableGit bash） | 相同 |
| frontmatter | `license`/`compatibility`/`allowed-tools`/`metadata` | 主要读 `name`/`description`，`allowed-tools` 用逗号列表 | **头部不同** |
| Python | 系统 `python` 3.14.7 | 托管 `python.exe` 3.13.14（`~/.workbuddy/binaries/python/envs/default/Scripts/`） | 都满足 3.8+ |

所以差异只有两处：**SKILL.md 头部**、**解释器可能不同**。前者靠生成，后者靠
`bin/_bootstrap.sh` 里加一个候选。

## 2. 一份正文，两个头部

仓库里只有一份正文（`SKILL.md` 的 body）。WorkBuddy 版由
`tools/install_workbuddy.py` 在安装时拼出来：

```
workbuddy/frontmatter.yaml   (WorkBuddy 头部：name / description / version / allowed-tools / metadata)
        +
SKILL.md 的 body             (与 DSH 版逐字节相同)
        =
<安装目标>/SKILL.md
```

这样不存在「改了一边忘了另一边」的可能。`tests/test_workbuddy.py` 把这条契约钉住：
`test_body_is_reused_verbatim` 断言合成结果**以原始 body 结尾**，
`test_body_starts_after_the_first_closed_block` 断言切分只认第一个闭合的 `---`
（正文后面还有 `---` 分隔线，不能误当第二段头部）。

另一个防漂移的断言是 `test_every_subcommand_is_documented`：它从 `cli.build_parser()`
取出真实子命令集合，再要求每个名字都出现在正文里。加子命令忘了写文档，这条会红。

## 3. 解释器候选

`bin/_bootstrap.sh` 的候选顺序变成：

```
LATEX_SKILL_PYTHON（显式指定，逐字使用）
  -> python
  -> $HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  -> python3
  -> py
```

每个候选都要**真跑一次** `import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)`。
这不是洁癖：本机 `python3` 解析到 Microsoft Store 的存根，`command -v` 找得到但执行
无输出，早期版本因此静默失败过。

WorkBuddy 那条放在 `python3` 之前、`python` 之后：PATH 上真有 python 时优先用调用者
的环境，没有时才回落到宿主自带的解释器。已实测：把 PATH 缩到只剩 TeX Live 与
PortableGit（`command -v python` 为空）时，`latex-doctor` 仍能跑起来。

## 4. 安装

```bash
cd latex-skill
python tools/install_workbuddy.py --dry-run     # 先看会写哪些文件（42 个）
python tools/install_workbuddy.py               # 装到 ~/.workbuddy/skills/latex-automation
python tools/install_workbuddy.py --check       # 比对已装副本与仓库（逐文件 sha256）
python tools/install_workbuddy.py --force       # 覆盖已存在的安装
```

- 默认排除 `research/`（3 MB 调研夹具，运行时不读）、`workbuddy/`（已被合成进 SKILL.md）、
  以及 `__pycache__` 等构建残留。
- 文件清单来自 `git ls-files`，所以 `.gitignore` 里的东西天然不会进包；非 git 副本
  退回遍历目录。
- 安装后 `SKILL.md` 的头部来自 `workbuddy/frontmatter.yaml`，正文来自 `SKILL.md`。

## 5. 验收

`tools/verify_workbuddy.py` 验的是**装出来的副本**，不是仓库：它先 `install(force=True)`
到临时目录，再用 **WorkBuddy 自己的 PortableGit bash** 驱动一个真实项目。

```
install --check -> doctor -> init(zh) -> build -> layout -> repair(不可修) -> render -> check
```

15 项全通过（17.9 s），关键几项：

| 检查 | 现场 |
|---|---|
| 装出来的 SKILL.md 头部正确 | `name: latex-automation` + `allowed-tools` 在 |
| 正文与仓库逐字节相同 | body byte-identical |
| `doctor` 从安装目录跑 | 12 ok / 1 warn / 0 fail |
| 中文+空格目录建工程并编译 | xelatex / 1 页 / 6.2 s |
| putenv 提示行 | `output directory contains CJK text followed by a space; ...` |
| `layout` 读得到的 PDF | 896 ms |
| `repair` 遇不可验证缺陷 | 退出码非 0、`needs-human`、源文件未改 |
| `render` / `check` | 1 张 PNG / chktex 跑通 |

## 6. 两个宿主上仍需分别注意的差异

- **`SKILL_DIR` 默认值**：正文里两种路径都列出来了，靠 `LATEX_SKILL_DIR` 覆盖或直接
  写死其一。包装脚本本身不依赖它——`_bootstrap.sh` 用 `BASH_SOURCE` 自解析。
- **bash 版本**：WorkBuddy 的 PortableGit bash 与 DSH 的 MSYS bash 都支持
  `cygpath`/`pwd -W`，但**都不支持** `pwd -W` 的那台机器上要回落到 POSIX 路径并把
  分隔符切成 `:`——这段逻辑已有，两个宿主都走到了 `cygpath` 分支。
- **中文控制台**：WorkBuddy 的 bash 在某些终端仍是 CP936，包装脚本统一
  `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`，与 DSH 侧一致。

## 7. 复现

```bash
cd latex-skill
python -m unittest discover -s tests     # 含 test_workbuddy.py 的 16 项
python tools/verify_workbuddy.py         # 15 项，约 18 秒
python tools/install_workbuddy.py --force
```
