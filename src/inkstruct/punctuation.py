"""Explicit punctuation sharing: one recording, distinct Unicode identities."""

# Only width variants with the same handwritten shape share a recording.
# Ideographic stops/commas, quotes, book-title marks and mathematical symbols
# deliberately remain distinct. Do not apply broad Unicode normalization.
SHARED_PUNCTUATION = {
    '，': ',', '．': '.', '；': ';', '：': ':', '！': '!', '？': '?',
    '（': '(', '）': ')', '［': '[', '］': ']', '｛': '{', '｝': '}', '％': '%',
}
CHINESE_PUNCTUATION = '。、【】《》〈〉「」『』“”‘’—…'
POLICY = 'shared-handwriting-punctuation-v1'


def capture_character(character):
    return SHARED_PUNCTUATION.get(character, character)


def shared_characters(character):
    canonical = capture_character(character)
    return (canonical, *(c for c, source in SHARED_PUNCTUATION.items() if source == canonical))


def capture_label(character):
    characters = shared_characters(character)
    return ' / '.join(characters) + '（共用笔迹）' if len(characters) > 1 else character
