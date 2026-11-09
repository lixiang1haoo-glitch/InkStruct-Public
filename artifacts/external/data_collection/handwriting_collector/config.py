from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QStandardPaths


@dataclass(frozen=True)
class UiSettings:
    """Persistent rendering preferences, independent from task data."""

    stroke_width_scale: float = 2.0
    grid_scale: float = 0.72
    schema_version: str = "ui_settings_v1"
    symbol_stroke_width_scale: float | None = None

    @property
    def symbol_stroke_scale(self) -> float:
        return self.stroke_width_scale if self.symbol_stroke_width_scale is None else self.symbol_stroke_width_scale

    def validated(self) -> "UiSettings":
        if self.schema_version != "ui_settings_v1":
            raise ValueError("不支持的界面配置版本")
        if not 0.75 <= float(self.stroke_width_scale) <= 4.0:
            raise ValueError("笔画粗细比例必须位于 0.75–4.0")
        if not 0.75 <= float(self.symbol_stroke_scale) <= 4.0:
            raise ValueError("符号笔迹粗细比例必须位于 0.75–4.0")
        if not 0.45 <= float(self.grid_scale) <= 0.95:
            raise ValueError("田字格尺寸比例必须位于 0.45–0.95")
        return self


class UiSettingsStore:
    def __init__(self, path: Path | None = None):
        if path is None:
            config_dir = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppConfigLocation
            )
            path = Path(config_dir) / "ui_settings.json"
        self.path = Path(path)

    def load(self) -> tuple[UiSettings, str | None]:
        if not self.path.exists():
            return UiSettings(), None
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            settings = UiSettings(
                stroke_width_scale=float(payload["stroke_width_scale"]),
                grid_scale=float(payload["grid_scale"]),
                schema_version=str(payload["schema_version"]),
                symbol_stroke_width_scale=(
                    float(payload["symbol_stroke_width_scale"])
                    if payload.get("symbol_stroke_width_scale") is not None else None
                ),
            ).validated()
            return settings, None
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return UiSettings(), f"界面配置无效，已恢复默认值：{error}"

    def save(self, settings: UiSettings) -> None:
        settings.validated()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=".ui_settings.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
