"""Render persisted same-character reconstruction separately from cross-character results."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from validate_observed_reconstruction import curves, read

from inkstruct.samples import sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    out = args.input/'report'
    out.mkdir(exist_ok=False)
    (out/'figures').mkdir()
    os.environ['MPLCONFIGDIR'] = str(out/'.mpl')
    os.environ['XDG_CACHE_HOME'] = str(out/'.cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams['font.family'] = 'Arial Unicode MS'
    plt.rcParams['axes.unicode_minus'] = False
    plan = read(args.input/'frozen_plan.json')
    for section in ('code_sha256', 'input_sha256'):
        for path, expected in plan[section].items():
            assert sha256_file(Path(path)) == expected, path
    summary = read(args.input/'summary.json')
    rows = [read(p) for p in sorted((args.input/'cases').glob('*.json'))]
    gallery, featured = [], []
    for n, row in enumerate(rows):
        labels = ['reference', 'A', 'B', 'C']
        lines = {'reference': row['reference'], **{k: curves(v) for k, v in row['variants'].items()}}
        chosen = {'岛': 3, '尴': 2}.get(row['character'])
        if chosen is None:
            chosen = max(range(len(row['metrics']['A'])), key=lambda i: row['metrics']['A'][i]['max_distance'])
        cloud = np.asarray([p for k in labels for p in lines[k][chosen]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.25, .1)
        fig, axes = plt.subplots(2, 4, figsize=(12, 8))
        for col, label in enumerate(labels):
            color = ['#303944', '#277bb5', '#1a8265', '#ae5779'][col]
            for r in range(2):
                ax = axes[r, col]
                for i, stroke in enumerate(lines[label]):
                    a = np.asarray(stroke)
                    ax.plot(a[:, 0], a[:, 1], color=color if i == chosen else '#abb6c1', lw=1.8 if i == chosen else 1.1)
                    if i == chosen:
                        ax.scatter(*a[-1], color=color, s=14)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title(['已采集原稿', 'A · 原有平滑', 'B · 完整原稿优先', 'C · 保护折钩简化'][col], fontsize=11)
            if label != 'reference':
                m = row['metrics'][label][chosen]
                axes[1, col].set_xlabel(f"局部最大偏差 {m['max_distance']:.5f}\n弧长比 {m['length_ratio']:.3f} · 末向差 {m['terminal_angle_deg'] or 0:.2f}°", fontsize=9)
        status = '同字整稿重建' if row['reconstructed'] else '映射不合格，沿用跨字推断'
        fig.suptitle(f"{row['writer']} · {row['character']} · {status}\n全图同尺度，下排共享局部范围 s{chosen+1}；直接绘制全部输出顶点", fontsize=12)
        fig.tight_layout(rect=(0, .025, 1, .91))
        fig.subplots_adjust(hspace=.22)
        filename = f"figures/{row['writer']}-U+{ord(row['character']):04X}.png"
        fig.savefig(out/filename, dpi=125)
        plt.close(fig)
        gallery.append(f'<details><summary>{row["writer"]} · {row["character"]} · {status}</summary><img loading="lazy" src="{filename}"><a href="../cases/{row["writer"]}-U+{ord(row["character"]):04X}.json">坐标、来源与全部逐笔指标</a></details>')
        if row['character'] in '岛尴':
            featured.append((row['writer'], row['character'], filename))
        if (n+1)%32 == 0:
            print('figures', n+1, flush=True)
    style = '<style>body{max-width:1250px;margin:32px auto;padding:0 24px;font:16px/1.8 system-ui;color:#263b50;background:#f5f7fa}img{width:100%}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}details{padding:14px;background:white;margin:12px 0}.finding{background:#e6f3ec;padding:20px}a{color:#13688f}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><title>InkStruct 已采集原稿优先重建</title>'+style
    text = '<h1>让“岛、尴”的原始折钩进入实际输出</h1><p>2026-10-07 · 显式原稿优先开关 · 同字重建与跨字推断分别标注</p><p class="finding"><strong>结果：</strong>完整原稿重建已接入 CLI 与 Mac 界面；默认关闭。合格已采集字复用一个完整原稿的全部标准笔画，保留其原始位置、尺度和相互关系。轻量简化只删掉误差预算内且不受保护的顶点，不再经过 16/8 点压缩、平均原型与 B-Spline。</p>'
    text += '<h2>这次解决的实际缺口</h2><p>此前源部件入口始终排除同字供体，即使“岛、尴”有完整原稿，也可能因缺少跨字供体继续使用平滑结果。新开关 source-observed 优先恢复已采集整字；其余字符走原有跨字逻辑。整字使用高保真建档时保留的共同归一坐标，不逐笔拉伸，不拟合 A 的部件布局，也不混合不同原稿。原始设备尺寸已经在建档时等比归一，本报告比较的是该保留坐标系。</p>'
    text += '<p>同字重用接近原稿是预期结果，本次用于检验实际入口是否无损保留已有证据，不能作为跨字泛化结果。需要对未见字评估时关闭此开关，或用训练字符白名单排除目标字的全部采样；代码对重建和跨字两条路径都遵循白名单。</p>'
    text += '<h2>两位作者的固定重建与保护集</h2><p>每位作者固定“岛、尴”，再按样本 ID 哈希排序补到 64 个已采集字；另加无原稿的丢、侈、徼、黧验证回退。0.35 采用现有映射低分复核边界，0.004 沿用已冻结的简化误差预算，本轮不调参数。低分边界不是质量概率，也不保证高分原稿美观。</p><table><tr><th>作者</th><th>已采集目标</th><th>整稿重建</th><th>映射拒绝</th><th>完整点数</th><th>简化点数</th></tr>'
    for writer, s in summary.items():
        text += f'<tr><td>{writer}</td><td>{s["cases"]}</td><td>{s["observed"]}</td><td>{s["fallback"]}</td><td>{s["verified_raw_points"]}</td><td>{s["simplified_points"]}</td></tr>'
    text += '</table><p>下表仅汇总实际整稿重建的目标；按笔画求字内均值，再按字平均。映射拒绝字保留在全部图集中，另列覆盖率，不混入“无损重建”的分母。</p><table><tr><th>作者</th><th>路径</th><th>几何均差</th><th>局部最大偏差的均值</th><th>末向差</th><th>弧长绝对相对差</th></tr>'
    for writer, s in summary.items():
        for label, m in s['metrics_observed_only'].items():
            text += f'<tr><td>{writer}</td><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["max_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.3f}°</td><td>{m["absolute_length_error"]:.2%}</td></tr>'
    text += '</table><p>原稿可能有噪声。完整复用证明没有额外压缩损失；不能把原稿的抖动或弧长都当作理想质量。C 的误差界是源顶点到简化折线不超过 0.004；折点、端点和短钩邻域受保护，整字严格笔间交叉改变则整稿退回 B。</p>'
    for writer, char, filename in featured:
        text += f'<h2>{writer} · {char}</h2><img src="{filename}">'
    text += '<h2>不变量、续跑与 Mac 使用</h2><p>重建保持笔数、标准 ID、笔顺、有限坐标和压力范围，按输出笔顺重新计时；整数毫秒的笔内相对时间与保留源点一致。B 的全部坐标、压力逐项相等；C 每个顶点都有原索引、受保护点保留、误差预算及交叉检查。与 A 不同但原稿已有的交叉被明确记录，不算新生成异常；系统不会为迎合 A 删除作者原有交叉。</p><p>136 个 A/B/C 目标分别写出，共 408 个轨迹；B/C 续跑文件哈希不变。两个作者各 4 个无原稿字，在开关开启和关闭时的全部生成字段一致。改变原稿优先开关后复用旧 run-id 会被拒绝。档案、输入、代码和运行身份都有哈希记录，旧档案与输出未覆盖。</p><p>Mac 界面操作实际后台 Worker，生成“岛尴侈劓”：默认仍为 legacy 且新选项禁用；显式源模式下启用“优先保留已采集原稿”。岛、尴日志标为同字重建；侈走原有跨字路径；劓的低分 s13 仍显示。Qt 使用离屏模式，未验证真实手写设备。</p>'
    text += '<h2>仍不适用的情况</h2><p>没有原稿、歧义或不完整映射、低分笔画、无效压力/时间、退化笔画均不能强行重建。手写原稿自身的错字、采集裁断或异常形态也不会自动修复。这个开关适合已有真实样本的个性化字库；未采集字仍依赖跨字推断，前两轮末向和随机变化负结果仍然有效。暂不改变默认。</p><p><a href="gallery.html">全部 128 个已采集目标的图集</a> · <a href="../summary.json">汇总</a> · <a href="../frozen_plan.json">冻结输入与代码哈希</a></p>'
    (out/'InkStruct_已采集原稿重建报告.html').write_text(prefix+text)
    (out/'gallery.html').write_text(prefix+'<h1>同字重建及拒绝样本完整图集</h1>'+''.join(gallery))
    print(out/'InkStruct_已采集原稿重建报告.html', flush=True)


if __name__ == '__main__':
    main()
