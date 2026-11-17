"""Presentation exports of frozen pages, without editor overlays."""
from base64 import b64decode
from io import BytesIO
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

from .pages import _draw_svg, _export_gate, page_draw, page_png


def _save_pdf(snapshot, output, indices, check, progress):
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle
    from PIL import Image

    with PdfPages(output, metadata={'Title': 'InkStruct', 'Creator': 'InkStruct'}) as pdf:
        for number, index in enumerate(indices, 1):
            check()
            page = page_draw(snapshot, index, False)
            width, height = page.width_mm, page.height_mm
            fig = Figure(figsize=(width / 25.4, height / 25.4), facecolor='white')
            fig.suppressComposite = True
            axes = fig.add_axes([0, 0, 1, 1], xlim=(0, width), ylim=(height, 0), aspect='auto')
            axes.set_axis_off()
            layers = (((0, 0, width, height), page.background), *page.images)
            for (left, top, right, bottom), encoded in layers:
                check()
                if encoded:
                    with Image.open(BytesIO(b64decode(encoded))) as image:
                        axes.imshow(image.convert('RGBA'), extent=(left, right, bottom, top),
                                    interpolation='none', aspect='auto', zorder=0)
            # Equal z-order keeps successive strokes and dots in scene order.
            for dot, group in groupby(page.strokes, key=lambda op: len(op.points) == 1):
                check()
                if dot:
                    for op in group:
                        axes.add_patch(Circle(op.points[0], op.width_mm / 2, color=op.color,
                                              linewidth=0, zorder=1))
                else:
                    ops = list(group)
                    ink = LineCollection([op.points for op in ops], colors=[op.color for op in ops],
                                         linewidths=[op.width_mm * 72 / 25.4 for op in ops],
                                         capstyle='round', joinstyle='round', zorder=1)
                    for path in ink.get_paths():
                        path.should_simplify = False
                    axes.add_collection(ink, autolim=False)
            # imshow's autoscale must never change the frozen paper coordinates.
            axes.set(xlim=(0, width), ylim=(height, 0))
            pdf.savefig(fig, bbox_inches=fig.bbox_inches)
            fig.clear()
            progress(number, len(indices))


def export_visual(snapshot, output, indices, format, *, control, progress, replace_file=False):
    _export_gate(snapshot, False, cancelled=control.cancelled)
    if not indices or any(not 0 <= i < len(snapshot.pages) for i in indices):
        raise ValueError('导出页码无效')
    if format not in {'pdf', 'png', 'svg'}:
        raise ValueError('未知的排版图格式')
    if format == 'pdf' and tuple(indices) != tuple(range(len(snapshot.pages))):
        raise ValueError('整篇 PDF 必须按顺序包含全部页面')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    single_file = format == 'pdf' or len(indices) == 1
    with TemporaryDirectory(prefix='.inkstruct-visual-', dir=output.parent) as temp:
        stage = Path(temp) / 'output'
        if format == 'pdf':
            _save_pdf(snapshot, stage, indices, control.check, progress)
        else:
            if not single_file:
                stage.mkdir()
            for number, index in enumerate(indices, 1):
                control.check()
                path = stage if single_file else stage / f'page-{index + 1:03d}.{format}'
                if format == 'png':
                    with page_png(snapshot, index, reference_notice=False) as image:
                        image.save(path, format='PNG', dpi=(144, 144))
                else:
                    path.write_text(_draw_svg(page_draw(snapshot, index, False), reference_notice=False,
                                              cancelled=control.cancelled), encoding='utf-8')
                progress(number, len(indices))
        control.publish(stage, output, replace_file=single_file and replace_file)
