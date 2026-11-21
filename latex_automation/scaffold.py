"""Project scaffolding: small, dependency-light starting points.

Every template must build on a stock TeX Live with no network access, so they
only use packages that ship in the distribution's common schemes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TEMPLATES: dict[str, dict] = {
    "article": {
        "description": "English article, pdfLaTeX, no external packages beyond amsmath/booktabs",
        "engine": "pdflatex",
        "files": {
            "main.tex": r"""\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{hyperref}

\title{TITLE}
\author{AUTHOR}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
ABSTRACT
\end{abstract}

\section{Introduction}
\label{sec:intro}

Start writing here.

\section{Results}

\begin{table}[htbp]
  \centering
  \begin{tabular}{lrr}
    \toprule
    Item & Value & Unit \\
    \midrule
    Alpha & 1.0 & m \\
    Beta  & 2.5 & s \\
    \bottomrule
  \end{tabular}
  \caption{A first table.}
  \label{tab:first}
\end{table}

\section{Conclusion}

See Section~\ref{sec:intro} and Table~\ref{tab:first}.

\end{document}
""",
        },
    },
    "zh": {
        "description": "中文文档，ctexart + XeLaTeX，含中文字体设置说明",
        "engine": "xelatex",
        "files": {
            "main.tex": r"""\documentclass[UTF8,11pt,a4paper]{ctexart}
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{hyperref}

\title{TITLE}
\author{AUTHOR}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
ABSTRACT
\end{abstract}

\section{引言}
\label{sec:intro}

这是一个中文排版的最小可编译示例。ctexart 会自动配置中文断行、标点挤压
与章节标题格式，正文直接写中文即可。

公式示例：
\begin{equation}
  E = mc^2
  \label{eq:emc}
\end{equation}

表格示例见表~\ref{tab:first}。

\begin{table}[htbp]
  \centering
  \begin{tabular}{lrr}
    \toprule
    项目 & 数值 & 单位 \\
    \midrule
    甲 & 1.0 & 米 \\
    乙 & 2.5 & 秒 \\
    \bottomrule
  \end{tabular}
  \caption{第一个表格。}
  \label{tab:first}
\end{table}

\section{结论}

参见第~\ref{sec:intro}~节与式~\eqref{eq:emc}。

\end{document}
""",
        },
    },
    "biblatex": {
        "description": "biblatex + biber bibliography skeleton",
        "engine": "pdflatex",
        "backend": "biber",
        "files": {
            "main.tex": r"""\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[margin=2.5cm]{geometry}
\usepackage[backend=biber,style=numeric]{biblatex}
\addbibresource{refs.bib}
\usepackage{hyperref}

\title{TITLE}
\author{AUTHOR}
\date{\today}

\begin{document}
\maketitle

\section{Introduction}

A citation with no surprises~\cite{example2024}.

\printbibliography

\end{document}
""",
            "refs.bib": r"""@article{example2024,
  author  = {Doe, Jane and Roe, Richard},
  title   = {An Example Article for the Skeleton},
  journal = {Journal of Placeholders},
  year    = {2024},
  volume  = {1},
  number  = {1},
  pages   = {1--10},
  doi     = {10.0000/example.2024.1}
}
""",
        },
    },
    "beamer": {
        "description": "Beamer presentation skeleton",
        "engine": "pdflatex",
        "files": {
            "main.tex": r"""\documentclass[aspectratio=169,11pt]{beamer}
\usetheme{default}
\usecolortheme{seahorse}

\title{TITLE}
\author{AUTHOR}
\date{\today}

\begin{document}

\begin{frame}
  \titlepage
\end{frame}

\begin{frame}{Outline}
  \tableofcontents
\end{frame}

\section{Motivation}

\begin{frame}{Why}
  \begin{itemize}
    \item First point
    \item Second point
  \end{itemize}
\end{frame}

\section{Results}

\begin{frame}{Numbers}
  \begin{block}{Headline}
    The result goes here.
  \end{block}
\end{frame}

\end{document}
""",
        },
    },
    "tikz": {
        "description": "Standalone TikZ figure plus a wrapper document",
        "engine": "lualatex",
        "files": {
            "main.tex": r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.5cm]{geometry}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning}
\usepackage{hyperref}

\title{TITLE}
\author{AUTHOR}
\date{\today}

\begin{document}
\maketitle

\begin{figure}[htbp]
  \centering
  \input{figure}
  \caption{A TikZ diagram.}
  \label{fig:diagram}
\end{figure}

See Figure~\ref{fig:diagram}.

\end{document}
""",
            "figure.tex": r"""\begin{tikzpicture}[
    node distance=18mm,
    box/.style={draw, rounded corners, minimum width=26mm, minimum height=9mm},
    arrow/.style={-{Stealth}}
  ]
  \node[box] (a) {Input};
  \node[box, right=of a] (b) {Process};
  \node[box, right=of b] (c) {Output};
  \draw[arrow] (a) -- (b);
  \draw[arrow] (b) -- (c);
\end{tikzpicture}
""",
        },
    },
}


def list_templates() -> list[dict]:
    return [
        {"name": name, "description": meta["description"], "engine": meta["engine"],
         "backend": meta.get("backend"), "files": sorted(meta["files"])}
        for name, meta in sorted(TEMPLATES.items())
    ]


def create_project(
    target: Path,
    template: str = "article",
    title: str = "Document Title",
    author: str = "Author Name",
    abstract: str = "Replace this abstract with your own summary.",
    force: bool = False,
) -> dict:
    """Write a template into ``target`` and return a manifest of what happened."""
    if template not in TEMPLATES:
        raise KeyError(f"unknown template '{template}'; available: {', '.join(sorted(TEMPLATES))}")
    meta = TEMPLATES[template]
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    skipped: list[str] = []
    for name, body in meta["files"].items():
        destination = target / name
        if destination.exists() and not force:
            skipped.append(name)
            continue
        text = (
            body.replace("TITLE", title)
            .replace("AUTHOR", author)
            .replace("ABSTRACT", abstract)
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        written.append(name)

    manifest = {
        "template": template,
        "engine": meta["engine"],
        "backend": meta.get("backend"),
        "target": str(target),
        "written": written,
        "skipped": skipped,
        "main": "main.tex",
    }
    (target / "latex-project.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
