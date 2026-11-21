"""Command line surface for the LaTeX automation skill.

Subcommands are intentionally small and composable so a shell wrapper per
command can call ``python -m latex_automation <sub> ...`` without translation.
Every command can emit ``--json`` for machine consumption and prints a compact
human summary otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .doctor import check_environment, print_doctor
from .engine import (
    BACKENDS,
    DEFAULT_REPORT_NAME,
    ENGINES,
    BuildOptions,
    clean_artifacts,
    compile_project,
    detect_backend,
    detect_engine,
    find_master,
    write_report,
)
from .lint import format_file, lint_file
from .logparse import (
    attribute_missing_locations,
    compress_log,
    parse_engine_log,
    parse_log_text,
)
from .layout import attach_log_overfull, measure_layout, page_verdicts
from .packages import resolve_many
from .paths import read_text, relative_outdir
from .render import read_pdfinfo, render_pdf
from .repair import repair_project, render_rounds
from .scaffold import create_project, list_templates


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for key, value in payload.items():
            if isinstance(value, (list, dict)):
                continue
            print(f"{key}: {value}")


def _resolve_master(root: Path, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.is_file():
            raise SystemExit(f"master file not found: {candidate}")
        return candidate.resolve()
    master = find_master(root.resolve())
    if master is None:
        raise SystemExit(f"no .tex file found under {root}")
    return master


# --------------------------------------------------------------------------- #


def cmd_doctor(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve() if args.project else None
    report = check_environment(project)
    return print_doctor(report, as_json=args.json)


def cmd_build(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    source = _resolve_master(root, args.file)

    engine = args.engine
    engine_reason = "explicit --engine"
    if engine == "auto":
        engine, engine_reason = detect_engine(source)

    backend = args.backend
    if backend == "auto":
        backend = detect_backend(source)
    elif backend == "none":
        backend = None

    outdir = Path(args.outdir)
    options = BuildOptions(
        source=source,
        outdir=outdir,
        engine=engine,
        backend=backend,
        use_latexmk=not args.no_latexmk,
        jobname=args.jobname,
        timeout=args.timeout,
        stop_on_first_error=args.stop_on_first_error,
        shell_escape=args.shell_escape,
        synctex=args.synctex,
    )
    report = compile_project(options)
    report.engine_reason = engine_reason

    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = root / report_path
    else:
        # Default next to the artefacts, which live relative to the master file.
        report_path = Path(report.outdir) / DEFAULT_REPORT_NAME if report.outdir else (
            root / args.outdir / DEFAULT_REPORT_NAME
        )
    write_report(report, report_path)

    if args.json:
        payload = report.as_dict()
        payload["report_path"] = str(report_path)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(report.summary())
        print(f"engine: {report.engine} ({report.engine_reason}); backend: {report.backend or 'none'}")
        if report.pdf:
            print(f"pdf: {report.pdf}")
        if report.status != "success":
            if report.failure:
                print(f"failure: {report.failure}")
            for diag in report.log.errors[:5]:
                location = f"{diag.file}:{diag.line}" if diag.file else "?"
                print(f"  error [{diag.category}] {location}: {diag.message}")
        for hint in report.warnings:
            print(f"  hint: {hint}")
        print(f"report: {report_path}")
    return 0 if report.status == "success" else 1


def cmd_repair(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    source = _resolve_master(root, args.file)

    engine = args.engine
    engine_reason = "explicit --engine"
    if engine == "auto":
        engine, engine_reason = detect_engine(source)

    backend = args.backend
    if backend == "auto":
        backend = detect_backend(source)
    elif backend == "none":
        backend = None

    outdir = Path(args.outdir)
    options = BuildOptions(
        source=source,
        outdir=outdir,
        engine=engine,
        backend=backend,
        use_latexmk=not args.no_latexmk,
        jobname=args.jobname,
        timeout=args.timeout,
        stop_on_first_error=False,
        shell_escape=args.shell_escape,
        synctex=args.synctex,
        project_root=root,
    )

    verdict = repair_project(
        options,
        max_rounds=args.max_rounds,
        apply_edits=args.apply,
        # Absolute: the repair module writes backups before the build has had a
        # chance to resolve the outdir, so a relative path would land under the
        # caller's cwd instead of next to the build artifacts.
        backup_dir=(root / outdir / "repair") if args.apply else None,
    )

    # Every round leaves its own diagnostics file so a caller can diff rounds.
    diag_paths: list[str] = []
    base = Path(verdict.final.outdir) if verdict.final and verdict.final.outdir else (root / args.outdir)
    for entry in verdict.rounds:
        path = base / f"round-{entry.index}.diag.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(entry.as_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            diag_paths.append(str(path))
        except OSError:
            pass

    if args.report and verdict.final is not None:
        write_report(verdict.final, Path(args.report))

    if args.json:
        payload = verdict.as_dict()
        payload["diagnostic_files"] = diag_paths
        payload["engine_reason"] = engine_reason
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_rounds(verdict))
        for path in diag_paths:
            print(f"diag: {path}")
    return 0 if verdict.status in ("already-ok", "repaired") else 1


def cmd_logs(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    log_path = Path(args.log) if args.log else None
    if log_path is None:
        outdir, _ = relative_outdir(root, Path(args.outdir))
        stem = args.jobname or _resolve_master(root, args.file).stem
        log_path = outdir / f"{stem}.log"
    elif not log_path.is_absolute():
        log_path = root / log_path
    if not log_path.is_file():
        raise SystemExit(f"log not found: {log_path}")

    text = read_text(log_path, limit=8_000_000)
    report = parse_log_text(text, root, "engine")
    attribute_missing_locations(report, log_path.stem + ".tex")
    if args.json:
        payload = report.as_dict()
        payload["log_path"] = str(log_path)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(report.summary_line())
        print(
            f"errors={len(report.errors)} warnings={len(report.warnings)} "
            f"layout={len(report.layout)} missing_glyphs={len(report.missing_chars)} "
            f"suppressed_cascade={report.suppressed}"
        )
        if report.root_cause:
            cause = report.root_cause
            location = f"{cause.file}:{cause.line}" if cause.file else "?"
            print(f"root cause [{cause.category}] {location}: {cause.message}")
            if cause.detail:
                print(f"  context: {cause.detail}")
        for diag in report.errors[1:6]:
            location = f"{diag.file}:{diag.line}" if diag.file else "?"
            print(f"  also [{diag.category}] {location}: {diag.message}")
        if report.missing_packages:
            print("missing packages:")
            for hit in resolve_many(report.missing_packages):
                if hit.suggestion:
                    print(f"  {hit.filename} -> {hit.package}: {hit.suggestion}")
                else:
                    print(f"  {hit.filename} -> not provided by any installed TeX Live package")
        if report.undefined_refs:
            print("undefined refs: " + ", ".join(report.undefined_refs[:10]))
        if report.undefined_cites:
            print("undefined cites: " + ", ".join(report.undefined_cites[:10]))
        if report.missing_chars:
            fonts = sorted({d.detail for d in report.missing_chars if d.detail})
            print("missing glyphs: " + f"{len(report.missing_chars)} distinct, fonts: {', '.join(fonts[:5])}")
        if args.excerpt:
            print("\n--- excerpt ---")
            print(compress_log(text, max_lines=args.excerpt))
    return 0 if report.ok else 1


def cmd_clean(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    outdir, _ = relative_outdir(root, Path(args.outdir))
    removed = clean_artifacts(outdir, keep_pdf=not args.drop_pdf)
    if args.json:
        print(json.dumps({"outdir": str(outdir), "removed": removed}, indent=2, ensure_ascii=False))
    else:
        print(f"cleaned {len(removed)} file(s) in {outdir}")
        for name in removed[:20]:
            print(f"  - {name}")
    return 0


def cmd_layout(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    if args.pdf:
        pdf = Path(args.pdf)
        if not pdf.is_absolute():
            pdf = root / pdf
        log_path = None
    else:
        outdir, _ = relative_outdir(root, Path(args.outdir))
        stem = args.jobname or _resolve_master(root, args.file).stem
        pdf = outdir / f"{stem}.pdf"
        log_path = outdir / f"{stem}.log"

    layout = measure_layout(pdf)

    # The log's overfull boxes catch what geometry cannot: a short page has no
    # measure to compare against, so a box wider than the text block but still
    # on the paper would otherwise pass unnoticed.
    if not layout.error and not args.no_log and log_path and log_path.is_file():
        try:
            text = read_text(log_path)
            report = parse_engine_log(text, root, "engine")
            attach_log_overfull(layout, report)
        except OSError:
            pass

    if not layout.error and args.only:
        wanted = {int(value) for value in args.only if value.isdigit()}
        layout.pages = [page for page in layout.pages if page.index in wanted]
        layout.issues = [issue for issue in layout.issues if issue.page in wanted]

    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = root / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(layout.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    if args.json:
        print(json.dumps(layout.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(layout.summary())
        if layout.error:
            return 1
        for line in page_verdicts(layout):
            print(line)
        for entry in layout.log_overfull[:5]:
            where = f"{entry['file']}:{entry['line']}" if entry["line"] else entry["file"]
            print(f"  ! [log] {where}: {entry['detail']}")
        if args.report:
            print(f"report: {report_path}")
    # Severity, not confidence, decides the exit code: a hole is a real layout
    # defect even though the heuristic that found it is only 80% sure, while a
    # suspected widow is a style hint a caller may legitimately ignore.
    hard = any(issue.severity in ("error", "layout") for issue in layout.issues)
    return 1 if layout.error or hard or layout.log_overfull else 0


def cmd_render(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    if args.pdf:
        pdf = Path(args.pdf)
        if not pdf.is_absolute():
            pdf = root / pdf
    else:
        outdir, _ = relative_outdir(root, Path(args.outdir))
        pdf = outdir / f"{(args.jobname or _resolve_master(root, args.file).stem)}.pdf"
    info = read_pdfinfo(pdf)
    render_dir = Path(args.render_dir)
    if not render_dir.is_absolute():
        render_dir = root / render_dir
    rendered = render_pdf(
        pdf,
        render_dir,
        dpi=args.dpi,
        fmt="jpeg" if args.jpeg else "png",
        first=args.first,
        last=args.last,
    )
    payload = {"pdf": info.as_dict(), "render": rendered.as_dict()}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"pdf: {pdf}")
        if info.pages:
            size = ""
            if info.page_width_pt:
                size = f", {info.page_width_pt:.1f}x{info.page_height_pt:.1f}pt"
            print(f"pages: {info.pages}{size}")
        if rendered.error:
            print(f"render error: {rendered.error}")
        else:
            print(f"rendered {len(rendered.pages)} page(s) at {args.dpi} dpi in {rendered.duration_ms} ms")
            for page in rendered.pages[:5]:
                print(f"  {page}")
    return 0 if not rendered.error else 1


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.project).resolve()
    source = _resolve_master(root, args.file)
    report = lint_file(source, root=root)
    payload = report.as_dict()
    if args.format:
        output = format_file(source, in_place=args.in_place)
        payload["format"] = {"ok": output[0], "detail": output[1] if output[0] else output[1]}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"{source.name}: {report.summary()}")
        for finding in report.findings[:args.limit]:
            print(f"  {finding.file}:{finding.line}:{finding.column} [{finding.kind}] {finding.message}")
        if args.format:
            ok, detail = payload["format"]["ok"], payload["format"]["detail"]
            print(f"format: {'done' if ok else 'skipped'} {detail if not ok else ''}".rstrip())
    return 0 if not report.error else 1


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    # `latex-init zh` reads like "scaffold the zh template", but the positional
    # argument is the destination and the template defaults to article. Say so
    # instead of quietly building the wrong project in a directory called "zh".
    known = {item["name"] for item in list_templates()}
    if args.template == "article" and target.name in known and not target.exists():
        print(
            f"note: '{target.name}' is also a template name; "
            f"this creates an article project in ./{target.name}. "
            f"Use `--template {target.name}` for that template.",
            file=sys.stderr,
        )
    manifest = create_project(
        target,
        template=args.template,
        title=args.title,
        author=args.author,
        abstract=args.abstract,
        force=args.force,
    )
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"created '{manifest['template']}' project at {manifest['target']}")
        print(f"engine: {manifest['engine']}, backend: {manifest['backend'] or 'none'}")
        for name in manifest["written"]:
            print(f"  + {name}")
        for name in manifest["skipped"]:
            print(f"  = {name} (exists, use --force to overwrite)")
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    templates = list_templates()
    if args.json:
        print(json.dumps(templates, indent=2, ensure_ascii=False))
    else:
        for template in templates:
            backend = f", {template['backend']}" if template["backend"] else ""
            print(f"{template['name']:<10} {template['engine']}{backend:<8} {template['description']}")
    return 0


# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="latex-automation",
        description="Local LaTeX automation: build, diagnose, render, lint, scaffold.",
    )
    parser.add_argument("--version", action="version", version=f"latex-automation {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # doctor
    p = sub.add_parser("doctor", help="check the local LaTeX toolchain")
    p.add_argument("project", nargs="?", default=".", help="project directory to inspect")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    # build
    p = sub.add_parser("build", help="compile a project")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--file", help="master .tex (default: auto-detect)")
    p.add_argument("--engine", default="auto", choices=("auto",) + ENGINES)
    p.add_argument("--backend", default="auto", choices=("auto", "none") + BACKENDS)
    p.add_argument("--outdir", default="latex-out")
    p.add_argument("--jobname")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--no-latexmk", action="store_true")
    p.add_argument("--stop-on-first-error", action="store_true")
    p.add_argument("--shell-escape", action="store_true")
    p.add_argument("--synctex", action="store_true")
    p.add_argument("--report")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_build)

    # repair
    p = sub.add_parser(
        "repair",
        help="compile, diagnose, propose a minimal fix, and recompile (bounded)",
    )
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--file", help="master .tex (default: auto-detect)")
    p.add_argument("--engine", default="auto", choices=("auto",) + ENGINES)
    p.add_argument("--backend", default="auto", choices=("auto", "none") + BACKENDS)
    p.add_argument("--outdir", default="latex-out")
    p.add_argument("--jobname")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--no-latexmk", action="store_true")
    p.add_argument("--shell-escape", action="store_true")
    p.add_argument("--synctex", action="store_true")
    p.add_argument(
        "--max-rounds", type=int, default=3, help="upper bound on compile rounds (default 3)"
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="write the proposed source edit (a backup is kept under <outdir>/repair/)",
    )
    p.add_argument("--report")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_repair)

    # logs
    p = sub.add_parser("logs", help="parse a LaTeX log into structured diagnostics")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--log", help="explicit .log path")
    p.add_argument("--outdir", default="latex-out")
    p.add_argument("--file")
    p.add_argument("--jobname")
    p.add_argument("--excerpt", type=int, default=0, help="also print N compressed log lines")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_logs)

    # clean
    p = sub.add_parser("clean", help="remove intermediate build artefacts")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--outdir", default="latex-out")
    p.add_argument("--drop-pdf", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_clean)

    # render
    p = sub.add_parser("render", help="render PDF pages to images")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--pdf")
    p.add_argument("--outdir", default="latex-out")
    p.add_argument("--render-dir", default="latex-out/pages")
    p.add_argument("--file")
    p.add_argument("--jobname")
    p.add_argument("--dpi", type=int, default=120)
    p.add_argument("--first", type=int)
    p.add_argument("--last", type=int)
    p.add_argument("--jpeg", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_render)

    # layout
    p = sub.add_parser(
        "layout",
        help="measure page geometry: overflow past the margin or paper, holes, widows",
    )
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--pdf", help="explicit PDF path")
    p.add_argument("--outdir", default="latex-out")
    p.add_argument("--file")
    p.add_argument("--jobname")
    p.add_argument("--only", nargs="*", help="restrict to these page numbers")
    p.add_argument(
        "--no-log",
        action="store_true",
        help="skip the .log, so only geometry is reported",
    )
    p.add_argument("--report", help="write the measurements to this JSON file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_layout)

    # check
    p = sub.add_parser("check", help="static style check with chktex")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--file")
    p.add_argument("--format", action="store_true", help="also run latexindent")
    p.add_argument("--in-place", action="store_true", help="let latexindent rewrite the file")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    # init
    p = sub.add_parser("init", help="scaffold a new project from a template")
    p.add_argument("target", nargs="?", default=".")
    p.add_argument("--template", default="article")
    p.add_argument("--title", default="Document Title")
    p.add_argument("--author", default="Author Name")
    p.add_argument("--abstract", default="Replace this abstract with your own summary.")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_init)

    # templates
    p = sub.add_parser("templates", help="list available templates")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_templates)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
