"""Private newline-JSON PDF service; PDF parsing never runs in the GUI process."""

import json
import sys
from dataclasses import asdict

from PySide6 import QtWidgets

from ..document.template_authoring import parse_template, template_json
from .template_pdf import PdfReference

MAX_MESSAGE_BYTES = 3 * 1024 * 1024


def main():
    app = QtWidgets.QApplication([])
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
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    finally:
        if pdf is not None:
            pdf.close()
    return 0 if app else 1


if __name__ == "__main__":
    raise SystemExit(main())
