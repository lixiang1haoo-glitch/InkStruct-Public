"""Integrated application and explicitly selected headless companion services."""

import os
import runpy
import sys
from pathlib import Path


def main():
    # PyInstaller dispatches spawn/resource-tracker children before Qt startup.
    # Without this, a font verification child would open another application.
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv) > 2 and sys.argv[1] == '--inkstruct-preview-worker':
        os.environ['QT_QPA_PLATFORM'] = ('windows' if sys.platform == 'win32' and
                                       os.environ.get('INKSTRUCT_PREVIEW_BACKEND') == 'gpu' else 'offscreen')
        from inkstruct.editor.preview_raster_worker import main as worker

        return worker(sys.argv[2])
    if len(sys.argv) > 1 and sys.argv[1] == "--inkstruct-pdf-worker":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from inkstruct.editor.template_pdf_worker import main as worker

        return worker()
    if len(sys.argv) > 1 and sys.argv[1] == "--inkstruct-check":
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.reconfigure(encoding='utf-8')
        os.environ["QT_QPA_PLATFORM"] = "windows" if (
            sys.platform == "win32" and "--windows-style-check" in sys.argv[2:]
        ) else "offscreen"
        script = Path(sys._MEIPASS) / "inkstruct-smoke.py"
        sys.argv = [str(script), *sys.argv[2:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    from inkstruct.application import main as app

    return app(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
