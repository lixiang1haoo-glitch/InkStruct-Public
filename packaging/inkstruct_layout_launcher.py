"""Portable layout preview with settings isolated from the regular application."""
import os
import sys
from pathlib import Path


def configure_preview():
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(root / "src"))
        sys.path.insert(0, str(root / "artifacts/external/data_collection"))
    private = Path(os.environ.get("INKSTRUCT_LAYOUT_PREVIEW_HOME", str(root / "preview-data"))).resolve()
    os.environ["INKSTRUCT_LAYOUT_PREVIEW_HOME"] = str(private)
    os.environ["INKSTRUCT_LAYOUT_PREVIEW"] = "1"
    from PySide6 import QtCore

    original = QtCore.QSettings
    original.setDefaultFormat(original.IniFormat)
    original.setPath(original.IniFormat, original.UserScope, str(private / "settings"))
    original.setPath(original.IniFormat, original.SystemScope, str(private / "settings-system"))

    class PreviewSettings(original):
        def __init__(self, *args, **kwargs):
            if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str):
                args = (original.IniFormat, original.UserScope, *args)
            super().__init__(*args, **kwargs)

    QtCore.QSettings = PreviewSettings
    from handwriting_collector import config
    store = config.UiSettingsStore

    class PreviewUiSettingsStore(store):
        def __init__(self, path=None):
            super().__init__(path if path is not None else private / "settings/collector-ui.json")

    config.UiSettingsStore = PreviewUiSettingsStore
    return private


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    private = configure_preview()
    if len(sys.argv) > 1 and sys.argv[1] == "--inkstruct-layout-check":
        import runpy
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.reconfigure(encoding="utf-8")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
        script = root / "inkstruct_layout_smoke.py"
        sys.argv = [str(script), *sys.argv[2:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    # Companion service switches must retain their original argv. Only the GUI
    # receives the private default workspace; an explicit user override is kept.
    service = len(sys.argv) > 1 and sys.argv[1].startswith("--inkstruct-")
    if not service and not any(a == "--workspace" or a.startswith("--workspace=") for a in sys.argv[1:]):
        sys.argv.extend(["--workspace", str(private / "workspace")])
    from inkstruct_launcher import main as launch
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
