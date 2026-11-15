import os
import subprocess
import sys
import textwrap


def test_speed_label_and_graph_adapt_to_live_theme_changes():
    program = r"""
        from PySide6 import QtTest, QtWidgets
        from inkstruct.generation_progress_ui import GenerationProgress
        from inkstruct.theme import use_platform_theme

        app = QtWidgets.QApplication([])
        progress = GenerationProgress()
        graph = progress.graph
        graph.resize(480, 86)
        progress.resize(480, 170)
        progress.show()
        graph.set_progress(.9, 115)
        graph.set_progress(.96, 60.1)
        history = tuple(graph.history)
        for mode in ('light', 'dark', 'light'):
            use_platform_theme(app, mode=mode)
            app.processEvents()
            assert graph.speed_label.text() == '速度：60.1 字/秒'
            assert tuple(graph.history) == history
            image = graph.grab().toImage()
            base = graph.palette().base().color()
            assert (base.lightness() < 128) == (mode == 'dark')
            assert image.pixelColor(image.width() - 9, 10) == base
            label = graph.speed_label.geometry()
            assert image.pixelColor(label.left() + 1, label.top() + 1) == base
            glyph_lightness = [
                image.pixelColor(x, y).lightness()
                for y in range(label.top() + 1, label.bottom())
                for x in range(label.left() + 5, label.right() - 4)
            ]
            if mode == 'dark':
                assert max(glyph_lightness) >= 155
            else:
                assert min(glyph_lightness) <= 105
        graph.set_progress(0, None)
        assert graph.speed_label.text() == '测速中' and graph.speed_label.isEnabled()
        graph.set_progress(.96, 60.1)
        larger = graph.speed_label.font()
        larger.setPixelSize(24)
        graph.speed_label.setFont(larger)
        QtTest.QTest.qWait(20)
        assert graph.speed_label.size() == graph.speed_label.sizeHint()
        assert graph.speed_label.geometry().right() < graph.width() - 4
    """
    result = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(program)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1"},
        capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
