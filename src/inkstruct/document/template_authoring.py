"""Shared, non-executable template authoring contract for people and agents."""

import base64
import io
import json
import math
from dataclasses import asdict
from hashlib import sha256
from html import escape
from pathlib import Path

from .template import PageTemplate, Region, TemplateBackground, TemplateFace, template_from_record
from .template_revision import SCHEMA as REVISION_SCHEMA
from .template_revision import template_record
from .template_validation import TemplateValidationError

MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
MAX_FLOW_TEMPLATE_BYTES = 16 * 1024 * 1024


def import_reference_image(path):
    """Normalize a local reference image without altering the source file."""
    from PIL import Image, ImageOps

    with Path(path).open("rb") as stream:
        raw = stream.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("底图文件不能超过 20 MiB")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG"} or source.width * source.height > 20_000_000:
                raise ValueError("底图须为 PNG/JPEG，且不超过 2000 万像素")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except Image.DecompressionBombError as error:
        raise ValueError("底图像素数超出限制") from error
    return pack_reference_image(image)


def pack_reference_image(image):
    """Encode a normalized reference under the shared two-face PNG budget."""
    image.info.clear()
    image.thumbnail((1600, 1600))
    while True:
        out = io.BytesIO()
        image.save(out, format="PNG")
        data = out.getvalue()
        encoded = base64.b64encode(data).decode("ascii")
        if len(encoded) <= 900_000:
            # Leave room for two faces plus geometry under the existing file budget.
            return TemplateBackground(encoded, sha256(data).hexdigest())
        image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)))


def new_template():
    """A neutral A4 starting point, unrelated to any supplied form."""
    face = TemplateFace(Region("body", 20, 30, 170, 247))
    return PageTemplate("未命名模板", 210, 297, face, face)


def template_json(template):
    return json.dumps(template_record(template), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def parse_template(text):
    size=len(text.encode("utf-8"))
    if size > MAX_FLOW_TEMPLATE_BYTES:
        raise ValueError("模板文件超过 16 MiB")
    try:
        def unique_pairs(items):
            result={}
            for key,value in items:
                if key in result:
                    raise TemplateValidationError('template-json-duplicate',f'Duplicate template JSON key: {key}')
                result[key]=value
            return result
        data = json.loads(text,object_pairs_hook=unique_pairs)
    except json.JSONDecodeError as error:
        raise TemplateValidationError(
            "template-json-syntax", str(error), source_offset=error.pos
        ) from error
    except RecursionError as error:
        raise TemplateValidationError("template-json-depth", "模板 JSON 嵌套过深") from error
    if not isinstance(data, dict):
        raise TypeError("模板必须是 JSON 对象")
    inner = data.get('template') if data.get('schema_version') == REVISION_SCHEMA else data
    if isinstance(inner, dict) and inner.get('schema_version') != 'inkstruct_page_template_v3' and size>MAX_TEMPLATE_BYTES:
        raise ValueError("旧模板文件超过 2 MiB")
    return template_from_record(data)


def read_template(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FLOW_TEMPLATE_BYTES + 1)
    if len(raw) > MAX_FLOW_TEMPLATE_BYTES:
        raise ValueError("模板文件超过 16 MiB")
    return parse_template(raw.decode("utf-8"))


def geometry_preview(template, face_name, *, background_opacity=0.4):
    """Reference drawing, explicitly NOT a plotter SVG or rendered document."""
    if template.schema_version=='inkstruct_page_template_v3':
        from .flow_template_preview import geometry_preview as flow_preview
        return flow_preview(template,face_name)
    if (
        not isinstance(background_opacity, (int, float))
        or not math.isfinite(background_opacity)
        or not 0 <= background_opacity <= 1
    ):
        raise ValueError("Background opacity must be between zero and one")
    if face_name not in {"first", "continuation"}:
        raise ValueError("Unknown template face")
    face = getattr(template, face_name)
    w, h = template.width_mm, template.height_mm
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" '
            f'viewBox="0 0 {w} {h}">'
        ),
        "<title>Template geometry reference — not a machine export</title>",
        f'<rect width="{w}" height="{h}" fill="white" stroke="#94a3b8" stroke-width="0.2"/>',
    ]
    if face.background:
        parts.append(
            f'<image width="{w}" height="{h}" preserveAspectRatio="none" opacity="{background_opacity}" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'xlink:href="data:image/png;base64,{face.background.png_base64}"/>'
        )
    parts.append(f'<g transform="translate({template.offset_x_mm} {template.offset_y_mm})">')
    for rule in face.rules:
        points = " ".join(f"{x},{y}" for x, y in rule.points)
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="#64748b" '
            f'stroke-width="{rule.width_mm}"/>'
        )
    for region in (face.body, *face.reserved):
        color = "#2563eb" if region is face.body else "#c2410c"
        parts.extend(
            [
                (
                    f'<rect x="{region.x_mm}" y="{region.y_mm}" width="{region.width_mm}" '
                    f'height="{region.height_mm}" fill="{color}" fill-opacity="0.08" '
                    f'stroke="{color}" stroke-width="0.3"/>'
                ),
                (
                    f'<text x="{region.x_mm + 1}" y="{region.y_mm + 3}" font-size="2.6" '
                    f'fill="{color}">{escape(region.name)}</text>'
                ),
            ]
        )
    for anchor in face.anchors:
        x, y = anchor.x_mm, anchor.y_mm
        parts.append(
            f'<path d="M {x - 1} {y} L {x + 1} {y} M {x} {y - 1} L {x} {y + 1}" '
            'fill="none" stroke="#059669" stroke-width="0.3"/>'
        )
        parts.append(
            f'<text x="{x + 1}" y="{y - 1}" font-size="2.2" '
            f'fill="#047857">{escape(anchor.name)}</text>'
        )
    parts.append("</g></svg>")
    return "\n".join(parts)


def add_template_parser(commands):
    parser = commands.add_parser("template", help="create, validate and preview reusable templates")
    actions = parser.add_subparsers(dest="template_action", required=True)
    create = actions.add_parser("new", help="write a neutral A4 template")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument('--format',choices=('v1','v3'),default='v1')
    create.add_argument('--kind',choices=('simple','custom'),default='simple')
    check = actions.add_parser(
        "validate", help="validate geometry; does not certify content fitting"
    )
    check.add_argument("source", type=Path)
    slots = actions.add_parser("inspect-slots", help="inspect reusable template fields")
    slots.add_argument("source", type=Path)
    upgrade = actions.add_parser("upgrade", help="explicitly copy v1 geometry into template v2")
    upgrade.add_argument("source", type=Path)
    upgrade.add_argument("--output", type=Path, required=True)
    upgrade.add_argument('--version',choices=('2','3'),default='2')
    rename = actions.add_parser(
        "rename", help="rename a region/anchor and its references in a template or native project"
    )
    rename.add_argument("source", type=Path)
    rename.add_argument("--kind", choices=("region", "anchor"), required=True)
    rename.add_argument("--from-name", required=True)
    rename.add_argument("--to-name", required=True)
    rename.add_argument("--expect-sha256", help="optional hash of the inspected input file")
    rename.add_argument("--output", type=Path, required=True)
    preview = actions.add_parser("preview", help="draw geometry only, not machine output")
    preview.add_argument("source", type=Path)
    preview.add_argument("--output", type=Path, required=True, help="new directory")
    pdf = actions.add_parser("from-pdf", help="import a PDF page reference; requires desktop extra")
    pdf.add_argument("source", type=Path)
    pdf.add_argument("--page", type=int, default=1, help="one-based PDF page number")
    pdf.add_argument("--face", choices=("first", "continuation"), default="first")
    pdf.add_argument("--template", type=Path, help="existing template; defaults to a new layout")
    pdf.add_argument(
        "--layout",
        choices=("background", "new"),
        help="default: preserve supplied template, otherwise new",
    )
    pdf.add_argument("--output", type=Path, required=True, help="new template JSON file")
    for action in ("inspect-content", "validate-document", "bind"):
        command = actions.add_parser(action, help="inspect or bind a native .inkdoc project")
        command.add_argument("source", type=Path)
        command.add_argument("--template", type=Path, help="explicit replacement template")
        if action == "bind":
            command.add_argument(
                "--bindings", type=Path, required=True, help="complete binding request JSON"
            )
            command.add_argument("--output", type=Path, required=True, help="new .inkdoc file")


def run_template_command(args):
    if args.template_action == "rename":
        from .template_rename import run_rename_command

        return run_rename_command(args)
    if args.template_action in {"inspect-content", "validate-document", "bind"}:
        from .template_binding_cli import run_binding_command

        return run_binding_command(args)
    imported = None
    if args.template_action == "from-pdf":
        from ..editor.template_pdf_process import import_pdf

        if args.output.exists() or args.output.is_symlink():
            raise ValueError("输出已存在，请另存为新文件")
        base = read_template(args.template) if args.template else new_template()
        mode = args.layout or ("background" if args.template else "new")
        result = import_pdf(
            {
                "action": "import",
                "path": str(args.source.resolve()),
                "index": args.page - 1,
                "face": args.face,
                "mode": mode,
                "template": template_json(base),
            }
        )
        template = parse_template(result["template"])
        imported = {
            "page": args.page,
            "page_count": result["page_count"],
            "face": args.face,
            "layout": mode,
            "source_sha256": result["source_sha256"],
            "page_size_mm": result["size_mm"],
        }
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(template_json(template))
    elif args.template_action == "new":
        if args.format=='v3':
            from .flow_template import FlowTemplate, PageLayout
            template=FlowTemplate() if args.kind=='simple' else FlowTemplate(kind='custom',layouts=(PageLayout('layout-1','布局 1'),),loop_pages=('layout-1',))
        else:
            template = new_template()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(template_json(template))
    else:
        template = read_template(args.source)
    if args.template_action == "upgrade":
        from .template_slots import upgrade_template

        if args.version=='3':
            from .flow_template import migrate_layout
            template=migrate_layout(template)
        else:
            template = upgrade_template(template)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(template_json(template))
    report = {
        "kind": "template-geometry-validation",
        "schema_version": template.schema_version,
        "name": template.name,
        "valid": True,
        "machine_export_ready": False,
        "calibration": template.calibration,
        "content_fit_checked": False,
        "slots": [asdict(s) for s in getattr(template, "slots", ())],
        "faces": {} if template.schema_version=='inkstruct_page_template_v3' else {
            name: {
                "body": asdict(getattr(template, name).body),
                "regions": [r.name for r in getattr(template, name).reserved],
                "anchors": [a.name for a in getattr(template, name).anchors],
                "rules": [r.name for r in getattr(template, name).rules],
            }
            for name in ("first", "continuation")
        },
    }
    if template.schema_version=='inkstruct_page_template_v3':
        report.update(layouts=[asdict(p) for p in template.effective_layouts],fields=[asdict(f) for f in template.fields],
                      start_pages=template.start_pages,loop_pages=template.effective_loop,markdown_skeleton=template.skeleton())
    if imported is not None:
        report["pdf_import"] = imported
    if args.template_action == "preview":
        args.output.mkdir(parents=True, exist_ok=False)
        for name in ([p.layout_id for p in template.effective_layouts] if template.schema_version=='inkstruct_page_template_v3' else ("first", "continuation")):
            (args.output / f"{name}.svg").write_text(geometry_preview(template, name), "utf-8")
        (args.output / "validation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
        )
    return 0, report
