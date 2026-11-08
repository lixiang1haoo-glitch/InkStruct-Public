from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from ..assets.glyph_provider import GlyphMetrics, GlyphProvider
from ..layout.plain import layout_document
from ..renderers.pages import export_pages
from .schema import PageProfile, StyleProfile
from .source import parse_plain_text


def add_document_parser(groups) -> None:
    parser = groups.add_parser("document", help="Markdown and plain-text page layout")
    commands = parser.add_subparsers(dest="command", required=True)
    from .template_authoring import add_template_parser

    add_template_parser(commands)
    editor = commands.add_parser("edit", help="launch the source editor and paginated preview")
    editor.add_argument("--source", type=Path)
    editor.add_argument("--run", type=Path)
    editor.add_argument("--symbols", type=Path)
    editor.add_argument("--project", type=Path)
    editor.add_argument("--mode", choices=("plain-text", "markdown"), default="markdown")
    inspector = commands.add_parser("inspect", help="inspect Markdown structure and source ranges")
    inspector.add_argument("source", type=Path, help="UTF-8 Markdown; no layout or machine export")
    resources = commands.add_parser(
        "resources", help="inspect Markdown glyph gaps and capture needs"
    )
    resources.add_argument("source", type=Path, help="UTF-8 Markdown or portable .inkdoc/.inktable")
    for command in (inspector, resources):
        command.add_argument(
            "--dialect",
            choices=("markdown", "obsidian"),
            default="markdown" if command is inspector else None,
        )
    resources.add_argument("--run", type=Path)
    resources.add_argument("--symbols", type=Path, help="one writer's collected symbol ZIP")
    resources.add_argument("--capture-csv", type=Path, help="new CSV file, five repeats per symbol")
    for name in ("fraction", "radical", "delimiter"):
        resources.add_argument(
            "--" + name + "-source",
            choices=("geometric", "sample"),
            help="construction source; inherit portable project setting, otherwise geometric",
        )
    for command in ("render", "preview"):
        p = commands.add_parser(command)
        p.add_argument("source", type=Path, help="UTF-8 text, .inkdoc, or legacy .inktable project")
        p.add_argument("--mode", choices=("plain-text", "markdown"), default="plain-text")
        p.add_argument(
            "--dialect",
            choices=("markdown", "obsidian"),
            help="Markdown dialect; inherit portable project setting",
        )
        p.add_argument("--run", type=Path, help="existing generated run directory")
        p.add_argument("--symbols", type=Path, help="collected symbol ZIP for Markdown")
        p.add_argument(
            "--image-root", type=Path, help="local image root; defaults to source directory"
        )
        p.add_argument("--metrics", type=Path, help="explicit calibrated non-Han em metrics JSON")
        p.add_argument("--page-width", type=float)
        p.add_argument("--page-height", type=float)
        p.add_argument("--margin", type=float)
        p.add_argument("--template", type=Path, help="explicit page template JSON (Markdown only)")
        p.add_argument("--em", type=float)
        p.add_argument("--line-height", type=float)
        p.add_argument("--stroke-width", type=float)
        if command == "render":
            p.add_argument("--output", type=Path, required=True, help="new output directory")
            p.add_argument("--save-project", type=Path, help="save a new portable .inkdoc project")
            p.add_argument("--no-png", action="store_true")
            p.add_argument("--dpi", type=float, default=144.0)
            p.add_argument("--debug", action="store_true", help="watermarked problem preview only")
            p.add_argument("--plotter", action="store_true", help="strict path-only M/L SVG export")
            p.add_argument("--omit-reference-images", action="store_true",
                           help="with --plotter, explicitly omit loaded or missing local PNG/JPEG references; preserve layout and captions")
            p.add_argument(
                "--optimize-paths",
                action="store_true",
                default=None,
                help="plotter routing with reversal; inherit saved setting when omitted",
            )
            p.add_argument("--no-optimize-paths", action="store_false", dest="optimize_paths")


def run_document_command(args) -> tuple[int, dict]:
    try:
        if args.command == "template":
            from .template_authoring import run_template_command

            return run_template_command(args)
        if args.command == "edit":
            from ..editor.app import main

            argv = ["--mode", args.mode]
            for name in ("source", "run", "symbols", "project"):
                value = getattr(args, name)
                if value:
                    argv += ["--" + name, str(value)]
            return main(argv), {"status": "editor-closed"}
        if args.command == "render":
            if args.omit_reference_images and not args.plotter:
                raise ValueError("--omit-reference-images requires --plotter")
            if args.optimize_paths and not args.plotter:
                raise ValueError("--optimize-paths requires --plotter")
            if args.plotter and args.debug:
                raise ValueError("Debug previews cannot be exported to the plotter")
        if (
            args.command in {"render", "preview"}
            and args.dialect
            and args.mode != "markdown"
            and args.source.suffix.lower() not in {".inkdoc", ".inktable"}
        ):
            raise ValueError("--dialect requires --mode markdown")
        loaded = None
        if args.command in {"render", "preview", "resources"} and args.source.suffix.lower() in {
            ".inkdoc",
            ".inktable",
        }:
            from .package import load_package
            from .table_import import import_table_project

            if any(getattr(args, key, None) for key in ("run", "symbols", "metrics", "image_root")):
                raise ValueError("Portable project uses its embedded resources")
            loaded = (
                import_table_project(args.source)
                if args.source.suffix.lower() == ".inktable"
                else load_package(args.source)
            )
            args.mode = "markdown"
        if not loaded and args.source.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Source exceeds the 2 MiB prototype budget")
        source = loaded.session.source if loaded else args.source.read_bytes().decode("utf-8")
        optimize = bool(
            args.optimize_paths
            if args.command == "render" and args.optimize_paths is not None
            else loaded.optimize
            if loaded
            else False
        )
        if len(source) > 100_000:
            raise ValueError("Source exceeds the 100,000 scalar prototype budget")
        if args.command in {"inspect", "resources"}:
            from .editing import SourceSession
            from .markdown import parse_markdown

            session = loaded.session if loaded else SourceSession(source)
            dialect = args.dialect or (loaded.flow.markdown_dialect if loaded else "markdown")
            document = parse_markdown(session, dialect=dialect,field_blocks=bool(loaded and loaded.flow.named_fields))
            if args.command == "resources":
                from ..assets.resolver import AssetResolver, gap_capture_csv
                from ..assets.symbol_provider import SymbolProvider
                from .resources import inspect_resources
                from .styles import FlowStyle

                if any(
                    d.severity == "error" and d.code != "math-layout-pending"
                    for d in document.diagnostics
                ):
                    raise ValueError("Resource inspection requires resolved syntax diagnostics")
                visible = "".join(o.text for o in document.occurrences)
                generated = GlyphProvider.from_run(args.run, visible) if args.run else None
                symbols = SymbolProvider.from_zip(args.symbols) if args.symbols else None
                resolver = loaded.resolver if loaded else AssetResolver(generated, symbols)
                flow = loaded.flow if loaded else FlowStyle()
                overrides = {
                    key: getattr(args, key)
                    for key in ("fraction_source", "radical_source", "delimiter_source")
                    if getattr(args, key) is not None
                }
                flow = replace(flow, markdown_dialect=dialect, math=replace(flow.math, **overrides))
                report = inspect_resources(document, resolver, flow=flow)
                if args.capture_csv:
                    with args.capture_csv.open("x", encoding="utf-8-sig", newline="") as stream:
                        stream.write(gap_capture_csv(report["gaps"]))
                return 0, report
            return 0, {
                "kind": "markdown-structure",
                "layout_ready": False,
                "machine_export_ready": False,
                "document": asdict(document),
                "identity": session.identity_record(),
            }
        calibrations = {}
        if args.metrics:
            value = json.loads(args.metrics.read_bytes())
            if value["schema_version"] != "inkstruct_glyph_metrics_v1":
                raise ValueError("Unsupported metrics schema")
            calibrations = {c: GlyphMetrics(**m) for c, m in value["characters"].items()}
        page_base = loaded.page if loaded else PageProfile()
        style_base = loaded.style if loaded else StyleProfile()
        page = PageProfile(
            *[
                v if v is not None else default
                for v, default in (
                    (args.page_width, page_base.width_mm),
                    (args.page_height, page_base.height_mm),
                    (args.margin, page_base.margin_mm),
                )
            ]
        )
        style = StyleProfile(
            *[
                v if v is not None else default
                for v, default in (
                    (args.em, style_base.em_mm),
                    (args.line_height, style_base.line_height_mm),
                    (args.stroke_width, style_base.stroke_width_mm),
                )
            ]
        )
        if args.mode == "markdown":
            from ..assets.resolver import AssetResolver
            from ..assets.symbol_provider import SymbolProvider
            from ..layout.blocks import layout_markdown
            from .editing import SourceSession
            from .markdown import parse_markdown
            from .styles import FlowStyle
            from .table_style import calibrate_tables

            session = loaded.session if loaded else SourceSession(source)
            samples = SymbolProvider.from_zip(args.symbols) if args.symbols else None
            flow = (
                loaded.flow
                if loaded
                else calibrate_tables(FlowStyle(), samples)
                if samples
                else FlowStyle()
            )
            if args.dialect:
                flow = replace(flow, markdown_dialect=args.dialect)
            if args.template:
                from .template_authoring import read_template

                flow = replace(flow, template=read_template(args.template))
            document = parse_markdown(session, dialect=flow.markdown_dialect,field_blocks=flow.named_fields)
            visible = "".join(o.text for o in document.occurrences)
            if flow.template:
                if any(v is not None for v in (args.page_width, args.page_height, args.margin)):
                    raise ValueError(
                        "Template owns page dimensions and regions; edit the template instead"
                    )
                page = flow.template.page
            if not loaded:
                from .images import import_local_images

                flow, image_issues = import_local_images(
                    document, flow, args.image_root or args.source.parent
                )
                document = replace(document, diagnostics=(*document.diagnostics, *image_issues))
            resolver = (
                loaded.resolver
                if loaded
                else AssetResolver(
                    GlyphProvider.from_run(args.run, visible, calibrations) if args.run else None,
                    samples,
                    builtin_numbers=True,
                )
            )
            snapshot = layout_markdown(document, resolver, page=page, style=style, flow=flow)
            if args.command == "render" and args.save_project:
                from .package import save_package

                save_package(
                    args.save_project,
                    session,
                    resolver,
                    page,
                    style,
                    optimize=optimize,
                    flow=flow,
                    reviews=loaded.reviews if loaded else (),
                )
        else:
            if args.image_root:
                raise ValueError("Image references require Markdown mode")
            if args.template:
                raise ValueError("Page templates require Markdown mode")
            if not args.run:
                raise ValueError("Plain-text mode requires --run")
            if args.symbols or (args.command == "render" and args.save_project):
                raise ValueError("Symbol samples and .inkdoc saving require Markdown mode")
            document = parse_plain_text(source, page=page, style=style)
            provider = GlyphProvider.from_run(args.run, source, calibrations)
            snapshot = layout_document(document, provider)
        report = {
            "exportable": snapshot.exportable,
            "plotter_exportable": snapshot.plotter_exportable,
            "pages": len(snapshot.pages),
            "occurrences": len(snapshot.fragments),
            "job_key": snapshot.job_key,
            "diagnostics": [asdict(d) for d in snapshot.diagnostics],
        }
        from ..plotter.adapters import can_export_with_image_omission

        omission_export = (args.command == 'render' and args.plotter and args.omit_reference_images
                           and can_export_with_image_omission(snapshot))
        if args.command == "preview":
            from ..renderers.qt import show_preview

            show_preview(snapshot)
        elif snapshot.exportable or args.debug or omission_export:
            if args.plotter:
                from ..plotter.adapters import plan_from_snapshot, reference_image_export_scope
                from ..plotter.export import export_plan

                scope = reference_image_export_scope(snapshot) if args.omit_reference_images else None
                export_plan(plan_from_snapshot(snapshot, omit_reference_images=args.omit_reference_images),
                            args.output, optimize=optimize, export_scope=scope)
                if scope:
                    report['export_scope'] = scope
            else:
                export_pages(
                    snapshot, args.output, png=not args.no_png, dpi=args.dpi, debug=args.debug
                )
            report["output"] = str(args.output.resolve())
            report["kind"] = (
                "plotter-pages"
                if args.plotter
                else "debug-preview"
                if args.debug
                else "reference-pages"
                if not snapshot.plotter_exportable
                else "finished-pages"
            )
        return (0 if snapshot.exportable or omission_export else 2), report
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, ImportError) as error:
        from .template_validation import TemplateValidationError

        if isinstance(error, TemplateValidationError):
            return 2, {
                "exportable": False,
                "valid": False,
                "error": str(error),
                "diagnostics": [error.report()],
            }
        return 2, {"exportable": False, "error": str(error)}
