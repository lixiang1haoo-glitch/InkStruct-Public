"""Persistent application defaults, separate from each saved document's state."""

import json
from dataclasses import asdict, dataclass, field, replace

from PySide6 import QtCore

from .document.schema import PageProfile, StyleProfile
from .document.styles import FlowStyle
from .math.style import MathStyle, math_style_record


@dataclass(frozen=True)
class LayoutDefaults:
    page: PageProfile = field(default_factory=PageProfile)
    style: StyleProfile = field(default_factory=StyleProfile)
    flow: FlowStyle = field(default_factory=lambda: FlowStyle(latin_spacing="handwriting", punctuation_spacing="handwriting", math=MathStyle.handwriting()))
    mode: str = "markdown"
    run: str = ""
    symbols: str = ""

    def __post_init__(self):
        if (
            self.mode not in {"markdown", "plain-text"}
            or not isinstance(self.run, str)
            or not isinstance(self.symbols, str)
        ):
            raise ValueError("全局默认包含无效的内容模式或字体路径")
        if (
            self.flow.table_overrides
            or self.flow.image_overrides
            or self.flow.images
            or self.flow.template_bindings
            or self.flow.glyph_corrections
        ):
            raise ValueError("全局默认不能包含文档元素、图片资源或模板填写绑定")


class GlobalDefaultsStore:
    KEY = "layout_defaults_v1"
    FRACTION_DEFAULT_KEY = "fraction_sample_default_v1"
    PUNCTUATION_DEFAULT_KEY = "punctuation_handwriting_default_v1"
    MATH_DEFAULT_KEY = "compact_math_default_v1"

    @staticmethod
    def make_settings():
        # The (organization, application) overload always uses NativeFormat on
        # Windows. Honor the selected format so test/portable scopes stay isolated.
        return QtCore.QSettings(
            QtCore.QSettings.defaultFormat(),
            QtCore.QSettings.Scope.UserScope,
            "InkStruct",
            "UnifiedSettings",
        )

    def __init__(self):
        self.settings = self.make_settings()
        self.expected = self.settings.value(self.KEY, None)

    def load(self):
        if self.expected is None:
            return LayoutDefaults(), None
        try:
            if not isinstance(self.expected, str) or len(self.expected) > 16_000_000:
                raise ValueError("默认配置超过容量限制")
            data = json.loads(self.expected)
            if (
                set(data) != {"version", "page", "style", "flow", "mode", "run", "symbols"}
                or type(data["version"]) is not int
                or data["version"] not in {1,2}
            ):
                raise ValueError("未知默认配置版本")
            result=LayoutDefaults(
                PageProfile(**data["page"]),
                StyleProfile(**data["style"]),
                FlowStyle(**data["flow"]),
                data["mode"],
                data["run"],
                data["symbols"],
            )
            if (data['version']==2) != result.flow.named_fields or (data['version']==1 and len(self.expected)>4_000_000):
                raise ValueError('默认配置协议与模板版本不一致')
            # Upgrade application defaults in memory only. Saved documents keep
            # their own v1 image style and the original preference record stays
            # untouched until an explicit Save/Apply.
            if result.flow.image.schema_version == "inkstruct_image_style_v1":
                image = replace(result.flow.image, height_mm=60, max_height_mm=None)
                result = replace(result, flow=replace(result.flow, image=image))
            # One-time application-default upgrade, never a saved-document edit.
            # Persist the marker only with explicit Apply/Save, so a subsequent
            # deliberate choice of geometric bars remains effective on restart.
            if (not self.settings.value(self.FRACTION_DEFAULT_KEY, False, type=bool)
                    and result.flow.math.fraction_source == "geometric"):
                result = replace(result, flow=replace(result.flow, math=replace(result.flow.math, fraction_source="sample")))
            if (not self.settings.value(self.PUNCTUATION_DEFAULT_KEY, False, type=bool)
                    and result.flow.punctuation_spacing == "capture"):
                result = replace(result, flow=replace(result.flow, punctuation_spacing="handwriting"))
            if (not self.settings.value(self.MATH_DEFAULT_KEY, False, type=bool)
                    and result.flow.math.schema_version == "inkstruct_math_style_v1"):
                old_math = result.flow.math
                new_math = MathStyle.handwriting()
                keys = ("spacing_policy", "schema_version", "binary_gap_em", "relation_gap_em",
                        "operator_gap_em", "fraction_clearance_em", "radical_clearance_em",
                        "delimiter_clearance_em", "delimiter_width_em", "radical_source", "delimiter_source")
                result = replace(result, flow=replace(result.flow, math=replace(
                    old_math, **{key: getattr(new_math, key) for key in keys})))
            return result,None
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            # Preserve the original record. Only an explicit Apply can replace it.
            return LayoutDefaults(), f"全局默认未载入，暂用初始值；原配置保留：{error}"

    def save(self, defaults):
        record = asdict(defaults)
        record["flow"]["math"] = math_style_record(defaults.flow.math)
        if record["flow"]["image"]["schema_version"] == "inkstruct_image_style_v1":
            record["flow"]["image"].pop("height_mm")
        if defaults.flow.schema_version not in {"inkstruct_flow_style_v3", "inkstruct_flow_style_v4"}:
            record["flow"].pop("latin_spacing")
        if defaults.flow.schema_version != "inkstruct_flow_style_v4":
            record["flow"].pop("punctuation_spacing")
        raw = json.dumps({"version": 2 if defaults.flow.named_fields else 1, **record}, ensure_ascii=False, allow_nan=False)
        if len(raw) > (16_000_000 if defaults.flow.named_fields else 4_000_000):
            raise ValueError("全局默认超过容量限制")
        current = self.make_settings()
        current.sync()
        if current.value(self.KEY, None) != self.expected:
            raise ValueError("其他窗口已修改全局默认，请重新打开设置后再试")
        current.setValue(self.KEY, raw)
        current.setValue(self.FRACTION_DEFAULT_KEY, True)
        current.setValue(self.PUNCTUATION_DEFAULT_KEY, True)
        current.setValue(self.MATH_DEFAULT_KEY, True)
        current.sync()
        if current.status() != QtCore.QSettings.Status.NoError:
            raise OSError("全局默认保存失败，请检查配置目录的写入权限")
        self.expected = raw


def document_flow(defaults, current):
    return replace(
        defaults.flow,
        table_overrides=current.table_overrides,
        image_overrides=current.image_overrides,
        images=current.images,
        glyph_corrections=current.glyph_corrections,
        template_bindings=current.template_bindings
        if defaults.flow.template == current.template
        else (),
    )


def apply_to_document(editor, defaults, *, resources=None):
    """Explicitly copy default parameters, retaining per-element state and assets."""
    flow = document_flow(defaults, editor.flow)
    changed = (flow, defaults.style, defaults.page, defaults.mode) != (
        editor.flow,
        editor.style,
        editor.page,
        editor.mode,
    )
    if not changed and resources is None:
        return False
    if resources is not None:
        editor.run_path, editor.symbol_path, editor.resolver = resources
    if defaults.mode != editor.mode:
        editor.session_path = editor.session_hash = None
    editor.flow, editor.loaded_style, editor.page, editor.mode = (
        flow,
        defaults.style,
        defaults.page,
        defaults.mode,
    )
    for control, value in [
        (editor.em, defaults.style.em_mm),
        (editor.line_height, defaults.style.line_height_mm),
        (editor.stroke, defaults.style.stroke_width_mm),
    ]:
        with QtCore.QSignalBlocker(control):
            control.setDecimals(6)
            control.setRange(min(control.minimum(), value), max(control.maximum(), value))
            control.setValue(value)
    for key, control in editor.flow_controls.items():
        with QtCore.QSignalBlocker(control):
            value = getattr(flow, key)
            control.setRange(min(control.minimum(), value), max(control.maximum(), value))
            control.setValue(value)
    with QtCore.QSignalBlocker(editor.mode_picker), QtCore.QSignalBlocker(editor.dialect_picker):
        editor.mode_picker.setCurrentIndex(editor.mode_picker.findData(defaults.mode))
        editor.dialect_picker.setCurrentIndex(editor.dialect_picker.findData(flow.markdown_dialect))
    editor.mark_dirty()
    editor.schedule_layout()
    return True
