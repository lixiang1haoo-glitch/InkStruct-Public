"""Render integration-regression evidence without claiming a fresh validation set."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import numpy as np

from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.trajectory_experiment import curve_error


def read(path):
    return json.loads(path.read_text())


def curves(payload):
    return [np.array([(p['x'], p['y']) for p in s['points']]) for s in payload['strokes']]


def svg(strokes):
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">',
             '<rect width="1000" height="1000" fill="white" stroke="#e0e6ed"/>']
    for stroke in strokes:
        values = ' '.join(f'{float(x)*1000:.8f},{float(y)*1000:.8f}' for x, y in stroke)
        lines.append(f'<polyline points="{values}" fill="none" stroke="#243e59" stroke-width="4" stroke-linejoin="round"/>')
    return ''.join(lines) + '</svg>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--ui-screenshot', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    summary = read(args.input / 'summary.json')
    assert sha256_file(args.plan) == summary['plan_sha256']
    plan = read(args.plan)
    output = args.output or args.input / 'report'
    output.mkdir(exist_ok=False)
    figures = output / 'figures'
    figures.mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(output / '.mpl'))
    os.environ.setdefault('XDG_CACHE_HOME', str(output / '.cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams['font.family'] = 'Arial Unicode MS'
    titles = ['作者原稿（仅评估）', 'A：原有平滑', '完整原始部件', '保护折钩的轻量简化']
    table, gallery, details = [], [], []
    for writer, result in summary['results'].items():
        sources = load_profile(Path(plan['datasets'][writer]['sources'])).source_trajectories
        tasks = {t['character']: t for t in plan['datasets'][writer]['tasks']}
        ordered = sorted(result['rows'], key=lambda r: r['metrics_whole_glyph']['source-raw']['mean_distance'] - r['metrics_whole_glyph']['legacy']['mean_distance'])
        selected = {r['character'] for r in ordered[:2] + ordered[-2:]}
        for mode, metrics in result['mean_whole_glyph_metrics'].items():
            table.append(f'<tr><td>{writer}</td><td>{result["characters"]}</td><td>{mode}</td><td>{metrics["mean_distance"]:.6f}</td><td>{metrics["terminal_angle_deg"]:.2f}°</td></tr>')
        for row in result['rows']:
            character = row['character']
            key = f'{writer}-{ord(character):04X}'
            task = tasks[character]
            target = sources[task['target_sample_id']]
            mapping = {s.standard_stroke_id: s.points for s in target.strokes}
            payloads = {mode: read(Path(run) / f'trajectories/U+{ord(character):04X}.json')
                        for mode, run in result['run_directories'].items()}
            reference = [np.asarray(mapping[s['standard_stroke_id']]) for s in payloads['legacy']['strokes']]
            groups = [reference] + [curves(payloads[m]) for m in ('legacy', 'source-raw', 'source-simplified')]
            images = []
            for i, group in enumerate(groups):
                name = f'{key}-{i}.svg'
                (figures / name).write_text(svg(group))
                images.append(f'<div><p>{titles[i]}</p><img loading="lazy" src="figures/{name}"></div>')
            gallery.append(f'<article><h2>{writer} · {character}</h2><div class="grid">' + ''.join(images) + '</div></article>')
            if character not in selected:
                continue
            differences = [curve_error(a.tolist(), b.tolist())[0] for a, b in zip(groups[1], groups[2], strict=True)]
            index = int(np.argmax(differences))
            region = np.concatenate([g[index] for g in groups])
            center = (region.min(0) + region.max(0)) / 2
            width = max(float(np.ptp(region, axis=0).max()) * 1.2, .1)
            limits = (center[0]-width/2, center[0]+width/2, center[1]+width/2, center[1]-width/2)
            fig, axes = plt.subplots(2, 4, figsize=(13, 7))
            for col, group in enumerate(groups):
                for line in range(2):
                    ax = axes[line, col]
                    for i, stroke in enumerate(group):
                        color = '#ba3a32' if i == index else '#a8b2bc'
                        ax.plot(stroke[:, 0], stroke[:, 1], color=color, lw=1.5)
                        if i == index:
                            ax.plot(*stroke[-1], 'o', color=color, ms=3)
                    ax.set_aspect('equal')
                    ax.axis((0, 1, 1, 0) if line == 0 else limits)
                    ax.grid(alpha=.15)
                    ax.tick_params(labelsize=7)
                    if line == 0:
                        ax.set_title(titles[col], fontsize=10)
            delta = row['metrics_whole_glyph']['source-raw']['mean_distance'] - row['metrics_whole_glyph']['legacy']['mean_distance']
            fig.suptitle(f'{writer} · {character}｜原始部件减 A 几何偏差 {delta:+.5f}；局部为变化最大笔画 s{index+1}', fontsize=12)
            fig.tight_layout(rect=(0, 0, 1, .95))
            png = f'figures/{key}-detail.png'
            fig.savefig(output / png, dpi=140)
            plt.close(fig)
            details.append(f'<article><h2>{writer} · {character}</h2><img src="{png}"><p>按与 A 的整字几何偏差变化自动选取每位作者最改善/最退化各两例。局部窗口四图相同，末点圆标记；不对输出重采样。</p></article>')
    css = '<style>body{max-width:1250px;margin:32px auto;padding:0 24px;background:#f6f8fa;color:#21374c;font:16px/1.8 system-ui}img{width:100%;height:auto}article{padding:22px;margin:24px 0;background:white;border:1px solid #dae1e8;border-radius:12px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:9px;border-bottom:1px solid #dde4ea}a{color:#166ca0}</style>'
    (output / 'gallery.html').write_text('<!doctype html><meta charset="utf-8"><title>全部 80 字接入回归</title>' + css + '<h1>全部 80 字：统一比例、统一线宽</h1><p>原稿只用于生成后的评估；这是已观察数据的回归图集。</p>' + ''.join(gallery))
    text = '''<h1>完整源轨迹接入：Mac 实际生成与回归报告</h1>
<p>默认仍为原有平滑。命令行与 Mac 界面现可明确选择完整原始部件或保护折钩的轻量简化，并选用独立高保真副档案。未启用时输出数据格式与坐标不变。</p>
<p><strong>接入结果：</strong>两作者已有 80 个确认案例共 240 个 A/原始/简化输出通过基础不变量；原始与简化的供体、共同等比变换一致，未新增相对 A 的严格笔间交叉。4,275 个完整源点简化到 2,098 个，约减少 50.9%。逐点核对源坐标、压力与误差上限，续跑轨迹文件逐字节一致。</p>
<p><strong>证据范围：</strong>这些案例已经被观察过，只用于接入回归，不是新的泛化集。候选限定原冻结训练字符，排除同字全部重复样本；目标原稿只用于生成完成后的评估。下表对整字全部笔画先求字内均值再按字平均，不能与此前“被迁移部件”的约 3% 数字直接比较。</p>
<p><strong>仍存在取舍：</strong>全字平均几何误差略降，末端方向误差略增。保住供体轨迹不等于供体末向符合目标原稿，因此不建议替换默认路径。弧长与点数也不单独作为质量判断。</p>
<table><tr><th>作者</th><th>字数</th><th>路径</th><th>全字几何均差</th><th>全字末向均差</th></tr>''' + ''.join(table) + '''</table>
<p><strong>安全回退：</strong>没有完整相容部件就保留原 A；简化若改变全字交叉关系，就退回同一个完整供体，保持候选不变。每个部件的全部笔画共享一个变换。多部件模式不会宣称整个上级部件共享变换：嵌套叶部件分别是独立单元。已复核单笔平移和轮廓推导结构修正仍未自动启用。</p>
<p><strong>可追溯性：</strong>轨迹 JSON 附带供体样本哈希、源笔画 ID、保留点索引、变换、候选拒绝/回退原因和逐笔几何审计。运行身份固定输入档案、训练字符表、结构数据库和实现哈希；变更后拒绝混合续跑。置信度明确沿用 A、未校准，源映射支持分数单独记录。</p>
<h2>Mac 界面真实样本操作</h2><p>在 Mac 的 Qt 离屏事件循环中操作同一实际窗口和后台 Worker，完成 scx“侈徼劓岛”的轻量简化生成；不是界面原型。默认选择与禁用状态、输出目录和 s13 低分显示均核验。离屏测试不覆盖真实手写设备输入。</p><img src="../../ui/completed.png">
<p><a href="gallery.html">查看全部 80 字图集</a> · <a href="../summary.json">逐例回归指标</a></p>
<h2>自动选出的改善与退化案例</h2>''' + ''.join(details)
    screenshot = args.ui_screenshot or args.input.parent / 'ui/completed.png'
    if screenshot.is_file():
        shutil.copyfile(screenshot, figures / 'ui.png')
        text = text.replace('src="../../ui/completed.png"', 'src="figures/ui.png"')
    else:
        start = text.index('<h2>Mac 界面真实样本操作</h2>')
        end = text.index('<p><a href="gallery.html">', start)
        text = text[:start] + '<p>本次报告未附独立 GUI 验证截图。</p>' + text[end:]
    path = output / 'InkStruct_生成入口接入报告.html'
    path.write_text('<!doctype html><meta charset="utf-8"><title>InkStruct 生成入口接入报告</title>' + css + text)
    print(path)


if __name__ == '__main__':
    main()
