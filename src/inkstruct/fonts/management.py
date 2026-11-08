"""Read-only font summaries and real-ink previews, suitable for background jobs."""

import unicodedata
from collections import Counter

from .core import FontPackage
from .library import entry, fingerprint

GROUPS = ('全部', '汉字', '英文正体', '英文斜体', '英文未分类', '数字', '希腊字母', '其他符号')


def group(record):
    char = record['character']
    if '\u3400' <= char <= '\u9fff' or '\U00020000' <= char <= '\U000323af':
        return '汉字'
    if char.isascii() and char.isalpha():
        return {'italic': '英文斜体', 'upright': '英文正体'}.get(record['letter_style'], '英文未分类')
    if char in '0123456789':
        return '数字'
    if 'GREEK' in unicodedata.name(char, ''):
        return '希腊字母'
    return '其他符号'


def summarize(path):
    font = FontPackage(path, verify_all=False)
    title, detail = entry(font)
    counts = {key: len({r['character'] for r in font.records if group(r) == key and r['enabled']})
              for key in GROUPS[1:]}
    origins = Counter('合成/复用' if any(key in s for key in ('symbol_construction', 'confirmed_reuse', 'mapped_reuse', 'shared_punctuation'))
                      else '独立录制' if s.get('source_kind') == 'recorded' else '生成'
                      for s in font.provenance.values())
    return {'stamp': list(fingerprint(path)), 'manifest': {k: font.manifest.get(k) for k in
            ('font_id', 'release_id', 'package_id', 'font_version', 'name', 'writer_alias', 'package_kind', 'derived_from_package')},
            'title': title, 'detail': detail, 'groups': counts, 'origins': dict(origins)}


def inspect_font(path, text, char='', sample=0, category='全部', offset=0, *, preset='custom'):
    font = FontPackage(path, verify_all=False)
    records = [r for r in font.records if r['enabled'] and (category == '全部' or group(r) == category)]
    chars = sorted({r['character'] for r in records}, key=ord)
    if char.startswith('U+'):
        try:
            char = chr(int(char[2:], 16))  # noqa: FURB166 -- U+ is a Unicode notation, not a Python integer prefix.
        except (ValueError, OverflowError):
            chars = []
    if char:
        chars = [c for c in chars if c in char]
    preview_text = text[:120]
    if preset == 'mixed':
        available = {r['character'] for r in font.records if r['enabled']}
        preferred = '中国书法文字自然山水天地春风明月孔正果我'
        han = ''.join(c for c in preferred if c in available)
        han += ''.join(c for c in sorted(available, key=ord)
                       if group({'character': c, 'letter_style': ''}) == '汉字' and c not in han)
        preview_text = (han[:8] + '\n' if han else '') + 'Abc 0123456789\n，。！？ ∶ ∘ ℃ ～'
    selected_char = chars[0] if char and chars else ''
    if preset == 'formula' and not selected_char:
        return {**formula_preview(font), 'characters': chars[offset:offset+200],
                'total': len(chars), 'source': '', 'samples': 0, 'stamp': fingerprint(path)}
    if selected_char:
        preview_text = selected_char
    glyphs = {c: tuple(font.glyphs(c)) for c in set(preview_text) if not c.isspace()}
    if selected_char and category != '全部':
        glyphs[selected_char] = tuple(g for g in glyphs[selected_char] if group(g.font_core['record']) == category)
    dimensions = '90 90' if selected_char else '720 240'
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dimensions}"><rect width="100%" height="100%" fill="white"/>']
    x, y, missing = 15., 12., []
    chosen = None
    for char in preview_text:
        if char == '\n' or x > 650:
            x, y = 15., y+76
        if y > 180:
            break
        if char.isspace():
            x += 24
            continue
        pool = glyphs.get(char, ())
        if pool:
            glyph = pool[sample % len(pool)] if selected_char else next((g for g in pool if g.font_core['record']['letter_style'] == 'upright'), pool[0])
            chosen = glyph if selected_char else chosen
            a, _, c, _ = glyph.bounds
            for stroke in glyph.strokes:
                pts = ' '.join(f'{x+(px-a)*60:.5f},{y+py*60:.5f}' for px, py in stroke)
                svg.append(f'<polyline points="{pts}" stroke="#24354b" stroke-width="1.5" fill="none" stroke-linecap="round"/>')
            x += max(16., (c-a+.12)*60)
        else:
            missing.append(char)
            svg.append(f'<rect x="{x}" y="{y+12}" width="32" height="42" fill="none" stroke="#c44848"/><text x="{x+2}" y="{y+70}" font-size="9" fill="#c44848">U+{ord(char):04X}</text>')
            x += 40
    svg.append('</svg>')
    source = ''
    sample_count = 0
    if chosen:
        summary = chosen.font_core['summary']
        origin = ('由录制笔迹合成/复用' if any(key in summary for key in ('symbol_construction', 'confirmed_reuse', 'mapped_reuse', 'shared_punctuation'))
                  else '独立录制' if summary['source_kind'] == 'recorded' else '生成字形')
        sample_count = len(glyphs[selected_char])
        source = f'{selected_char} · U+{ord(selected_char):04X} · 样本 {sample % sample_count + 1}/{sample_count}\n{group(chosen.font_core["record"])} · {origin}\n候选 {chosen.sample_id}\n来源状态：{summary["author_source_status"]} · 评价：{summary["review_status"]}'
        if summary.get('warnings'):
            source += '\n' + '\n'.join(summary['warnings'])
    return {'svg': ''.join(svg).encode(), 'missing': ''.join(dict.fromkeys(missing)), 'source': source,
            'characters': chars[offset:offset+200], 'total': len(chars), 'samples': sample_count,
            'stamp': fingerprint(path), 'preview_text': preview_text,
            'preview_note': '汉字从本字体可用字中选取。' if preset == 'mixed' and not selected_char else ''}


def formula_preview(font):
    """Reuse the math/layout renderer in a private, bounded preview document."""
    from ..assets.resolver import AssetResolver
    from ..document.markdown import parse_markdown
    from ..document.schema import PageProfile, StyleProfile
    from ..document.styles import FlowStyle
    from ..layout.blocks import layout_markdown
    from ..math.style import MathStyle
    from ..renderers.pages import page_svg

    text = '$$\na^2+b^2=c^2\n$$\n\n$$\n\\frac{1}{2}+\\frac{1}{2}=1\n$$'
    document = parse_markdown(text)
    required = {o.text for o in document.occurrences} | {'−'}
    resolver = AssetResolver(embedded=font.glyphs(required), builtin_numbers=False)
    snapshot = layout_markdown(document, resolver, page=PageProfile(90, 60, 6),
                               style=StyleProfile(10, 15, .22),
                               flow=FlowStyle(math=MathStyle.handwriting(em_mm=10)))
    counts = Counter(d.code for d in snapshot.diagnostics)
    return {'svg': page_svg(snapshot, 0, debug=not snapshot.exportable).encode(), 'preview_text': text,
            'missing': ''.join(dict.fromkeys(o.text for o in document.occurrences
                                             if o.text not in resolver.pools and not o.text.isspace())),
            'preview_note': '公式使用本字体与现有排版规则；这是独立诊断预览，非成品导出。',
            'diagnostics': [f'{code} · {count} 项（详见提示）' for code, count in counts.items()],
            'diagnostic_details': '\n'.join(d.code + '：' + d.message for d in snapshot.diagnostics)}
