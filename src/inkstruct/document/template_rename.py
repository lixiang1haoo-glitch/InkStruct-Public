"""Explicit atomic reference renames shared by people and agents."""

from dataclasses import asdict, replace
from hashlib import sha256

from .styles import FlowStyle
from .template_authoring import MAX_TEMPLATE_BYTES, parse_template, template_json


def rename_reference(template, bindings, kind, old_name, new_name):
    if template.schema_version=='inkstruct_page_template_v3':
        raise ValueError('Template v3 frame labels and stable field IDs are separate; edit the source layout in the v3 designer')
    if template is None or kind not in {"region", "anchor"}:
        raise ValueError("请选择模板中的填写区或锚点")
    if not isinstance(old_name, str) or not isinstance(new_name, str) or not new_name.strip():
        raise ValueError("名称不能为空")
    collection, reference = ("reserved", "region") if kind == "region" else ("anchors", "anchor")
    faces = tuple(
        name
        for name in ("first", "continuation")
        if any(v.name == old_name for v in getattr(getattr(template, name), collection))
    )
    if not faces:
        raise ValueError("原对象已不存在，不能猜测要迁移的引用")
    bindings = tuple(bindings)
    if old_name == new_name:
        return template, bindings
    if len(new_name) > 256:
        raise ValueError("新名称最多 256 个字符")
    # Treat the name as one cross-face identifier. Never adopt a dangling binding.
    if any(
        v.name == new_name
        for name in ("first", "continuation")
        for v in getattr(getattr(template, name), collection)
    ):
        raise ValueError("新名称已被其他同类对象使用")
    if kind == "region" and any(
        getattr(template, name).body.name == new_name for name in ("first", "continuation")
    ):
        raise ValueError("新名称与正文区标识冲突")
    if any(getattr(b, reference) == new_name for b in bindings):
        raise ValueError("新名称已被现有绑定引用，不能接管失效绑定")
    changes = {}
    for name in faces:
        face = getattr(template, name)
        changes[name] = replace(
            face,
            **{
                collection: tuple(
                    replace(v, name=new_name) if v.name == old_name else v
                    for v in getattr(face, collection)
                )
            },
        )
    if hasattr(template, "slots"):
        changes["slots"] = tuple(
            replace(s, **{reference: new_name}) if getattr(s, reference) == old_name else s
            for s in template.slots
        )
    updated = replace(template, **changes)
    if len(template_json(updated).encode("utf-8")) > MAX_TEMPLATE_BYTES:
        raise ValueError("改名后的模板超过 2 MiB，请使用更短的名称")
    updated_bindings = tuple(
        replace(b, **{reference: new_name}) if getattr(b, reference) == old_name else b
        for b in bindings
    )
    FlowStyle(template=updated, template_bindings=updated_bindings)
    return updated, updated_bindings


def run_rename_command(args):
    from ..layout.blocks import layout_markdown
    from .markdown import parse_markdown
    from .package import load_package, save_package

    if args.output.exists() or args.output.is_symlink():
        raise ValueError("输出已存在，请另存为新文件")
    native = args.source.suffix.lower() == ".inkdoc"
    if args.output.suffix.lower() != (".inkdoc" if native else ".json"):
        raise ValueError("原生项目另存为 .inkdoc，独立模板另存为 .json")
    loaded = load_package(args.source) if native else None
    if loaded:
        template, bindings, stamp = (
            loaded.flow.template,
            loaded.flow.template_bindings,
            loaded.file_hash,
        )
    else:
        with args.source.open("rb") as stream:
            raw = stream.read(MAX_TEMPLATE_BYTES + 1)
        if len(raw) > MAX_TEMPLATE_BYTES:
            raise ValueError("模板文件超过 2 MiB")
        template, bindings, stamp = parse_template(raw.decode("utf-8")), (), sha256(raw).hexdigest()
    if args.expect_sha256 is not None and args.expect_sha256 != stamp:
        raise ValueError("输入已在检查后发生变化，请重新检查")
    updated, updated_bindings = rename_reference(
        template, bindings, args.kind, args.from_name, args.to_name
    )
    report = {
        "kind": "template-reference-rename",
        "source_sha256": stamp,
        "reference_kind": args.kind,
        "from_name": args.from_name,
        "to_name": args.to_name,
        "changed": updated != template,
        "geometry_valid": True,
        "content_fit_checked": native,
        "machine_export_ready": False,
        "bindings_changed": sum(a != b for a, b in zip(bindings, updated_bindings)),
        "saved": False,
    }
    if loaded:
        flow = replace(loaded.flow, template=updated, template_bindings=updated_bindings)
        snapshot = layout_markdown(
            parse_markdown(loaded.session, dialect=flow.markdown_dialect),
            loaded.resolver,
            page=updated.page,
            style=loaded.style,
            flow=flow,
        )
        report.update(
            exportable=snapshot.exportable,
            plotter_exportable=snapshot.plotter_exportable,
            pages=len(snapshot.pages),
            diagnostics=[asdict(d) for d in snapshot.diagnostics],
        )
        if not snapshot.exportable:
            return 2, report
        output_hash = save_package(
            args.output,
            loaded.session,
            loaded.resolver,
            updated.page,
            loaded.style,
            flow=flow,
            optimize=loaded.optimize,
            reviews=loaded.reviews,
        )
    else:
        text = template_json(updated)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
        output_hash = sha256(text.encode("utf-8")).hexdigest()
    report.update(saved=True, output=str(args.output.resolve()), output_sha256=output_hash)
    return 0, report
