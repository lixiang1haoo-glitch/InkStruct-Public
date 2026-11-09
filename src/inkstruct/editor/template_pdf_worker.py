"""Private newline-JSON PDF service; PDF parsing never runs in the GUI process."""

import json
import sys
from dataclasses import asdict

from PySide6 import QtWidgets

from ..document.template_authoring import parse_template, template_json
from .template_pdf import PdfReference

MAX_MESSAGE_BYTES = 3 * 1024 * 1024


def main():
    # Windows PDF uses a multithreaded COM apartment. QApplication would
    # initialize an incompatible single-threaded apartment on this worker.
    app = QtWidgets.QApplication([]) if sys.platform != "win32" else None
    pdf = None
    try:
        while raw := sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1):
            try:
                if len(raw) > MAX_MESSAGE_BYTES:
                    raise ValueError("PDF 导入请求超过限制")
                request = json.loads(raw)
                action = request["action"]
                if action in {"open", "import"}:
                    if pdf is not None:
                        pdf.close()
                        pdf = None
                    pdf = PdfReference(request["path"])
                    result = {
                        "action": action,
                        "page_count": pdf.page_count,
                        "source_sha256": pdf.source_sha256,
                    }
                    if action == "import":
                        index = request["index"]
                        template = pdf.apply(
                            parse_template(request["template"]),
                            request["face"],
                            index,
                            mode=request["mode"],
                        )
                        result.update(
                            template=template_json(template), size_mm=pdf.page_size_mm(index)
                        )
                elif action == "render" and pdf is not None:
                    index = request["index"]
                    result = {
                        "action": action,
                        "index": index,
                        "size_mm": pdf.page_size_mm(index),
                        "background": asdict(pdf.background(index)),
                    }
                else:
                    raise ValueError("PDF 请求无效或文件未打开")
                response = {"ok": True, "result": result}
            except Exception as error:  # noqa: BLE001 - isolated worker boundary
                response = {"ok": False, "error": str(error)}
            line = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
            sys.stdout.buffer.write(line.encode("utf-8"))
            sys.stdout.buffer.flush()
    finally:
        if pdf is not None:
            pdf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
