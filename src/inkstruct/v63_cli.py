"""Explicit entry points for the isolated v6.3 experiment."""

from pathlib import Path


def add_v63_commands(groups):
    parser = groups.add_parser("v63", help="experimental connected handwriting workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--workspace", type=Path, required=True)
    archive = commands.add_parser("archive")
    archive.add_argument("--source", type=Path, required=True)
    archive.add_argument("--writer", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--archive", type=Path, required=True)
    generate.add_argument("--text", required=True)
    generate.add_argument("--reference-root", type=Path)
    generate.add_argument("--same-character", action="store_true")
    for command in (capture, archive, generate):
        command.add_argument("--database", type=Path, required=True)
    for command in (archive, generate):
        command.add_argument("--output", type=Path, required=True)
    package = commands.add_parser("package")
    package.add_argument("--run", type=Path, required=True)
    package.add_argument("--writer", required=True)
    package.add_argument("--name", required=True)
    package.add_argument("--library", type=Path, required=True)
    package.add_argument("--symbols", type=Path)
    package.add_argument("--accept-partial", action="store_true")


def run_v63_command(args):
    if args.command == "capture":
        from .collector import main
        return main(["inkstruct-v63"], workspace=args.workspace, database=args.database,
                    connected_capture=True)
    if args.command == "package":
        from .fonts.library import publish_font
        from .fonts.publication import GROUPS, publication_stamp, review_selection
        groups = {"han", *GROUPS} if args.symbols else {"han"}
        stamp = publication_stamp(args.writer, args.run, args.symbols)
        review = review_selection(args.writer, args.run, args.symbols, args.name, groups)
        if review["batch"]["failed"] and not args.accept_partial:
            raise ValueError("批次有未完成字符。接受部分批次后请使用 --accept-partial")
        report = publish_font(args.library, writer=args.writer, run=args.run, symbols=args.symbols,
                              name=args.name, package_kind="user", groups=groups, stamp=stamp,
                              expected=review["coverage"], progress=lambda _: None)
        return {k: report[k] for k in ("path", "verification", "timings", "log")}
    from .generation_workflow import corrections
    from .structures import StructureRepository
    from .v63 import generate, make_archive
    repo = StructureRepository(args.database.resolve())
    if args.command == "archive":
        return make_archive(args.source.resolve(), args.writer, repo, args.output.resolve())
    references = corrections(args.reference_root.resolve()) if args.reference_root else corrections()
    return generate(args.archive.resolve(), repo, args.text, args.output.resolve(), references,
                    same_character=args.same_character)
