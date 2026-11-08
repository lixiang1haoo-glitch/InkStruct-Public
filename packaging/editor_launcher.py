"""Frozen desktop entry and its explicitly selected console services."""

import os
import runpy
import sys
from pathlib import Path


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--inkstruct-pdf-worker":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from inkstruct.editor.template_pdf_worker import main as worker_main

        return worker_main()
    if len(sys.argv) > 1 and sys.argv[1] == "--inkstruct-cli":
        from inkstruct.cli import main as cli_main

        arguments = sys.argv[2:]
        if not arguments or arguments[0] != "document":
            raise ValueError("此编辑器工具仅提供 document 命令")
        return cli_main(arguments)
    if len(sys.argv) > 1 and sys.argv[1] == "--inkstruct-check":
        script = Path(sys._MEIPASS) / "editor-smoke.py"
        sys.argv = [str(script), *sys.argv[2:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    from inkstruct.editor.app import main as editor_main

    return editor_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
