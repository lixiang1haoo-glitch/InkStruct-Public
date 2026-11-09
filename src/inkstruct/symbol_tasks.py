"""Configurable symbol tasks using the existing task and specimen schemas."""
import json
import string

from .punctuation import CHINESE_PUNCTUATION, capture_character
from .symbol_capture import CATALOG
from .symbol_catalog import capture_groups

PREFIX = 'inkstruct:symbol_catalog_v2:'
LEGACY_CUSTOM_PREFIX = 'inkstruct:symbol_selection_v1:'
CUSTOM_PREFIX = 'inkstruct:symbol_selection_v2:'
CUSTOM_PREFIXES = (CUSTOM_PREFIX, LEGACY_CUSTOM_PREFIX)
BRACKETS = '()[]{}|'
PUNCTUATION = '.,:;?!%‰°′″\"\''
LEGACY_GROUPS = {
    'latin_upright': ('英文正体', string.ascii_uppercase + string.ascii_lowercase, 'upright'),
    'latin_italic': ('英文斜体', string.ascii_uppercase + string.ascii_lowercase, 'italic'),
    'digits': ('数字', CATALOG['数字'], 'unspecified'),
    'operators': ('运算符与数学符号', ''.join(c for c in CATALOG['数学与标点'] if c not in BRACKETS + PUNCTUATION), 'unspecified'),
    'greek': ('希腊字母', CATALOG['希腊字母'], 'unspecified'),
    'greek_variants': ('希腊变体', CATALOG['希腊变体'], 'unspecified'),
    'brackets': ('括号与定界符（中英共用）', BRACKETS, 'unspecified'),
    'punctuation': ('标点与单位符号（中英共用）', PUNCTUATION, 'unspecified'),
    'chinese_punctuation': ('中文专用标点', CHINESE_PUNCTUATION, 'unspecified'),
}
TASK_GROUPS = capture_groups()


def imported_entries(groups, imported):
    """Preserve explicit counts, deduplicating shared punctuation per style."""
    entries, seen = [], {}
    for group_index, group in enumerate(groups):
        for char, count, _ in imported:
            char = capture_character(char)
            if char not in TASK_GROUPS[group][1]:
                continue
            key = (char, TASK_GROUPS[group][2])
            if key in seen:
                if seen[key] != count:
                    raise ValueError(f'共用采集字符 {char!r} 的份数不一致')
                continue
            entries.append((char, count, group_index))
            seen[key] = count
    return entries


def task_plan(groups, repeats=5):
    if not isinstance(repeats, int) or not 1 <= repeats <= 100:
        raise ValueError('每个字符采集份数需在 1–100 之间')
    groups = tuple(groups)
    if not groups or len(set(groups)) != len(groups) or any(g not in TASK_GROUPS for g in groups):
        raise ValueError('请至少选择一类有效字符')
    source = CUSTOM_PREFIX + json.dumps({'groups': groups, 'reuse': []}, separators=(',', ':'))
    entries = [(character, repeats, index) for index, group in enumerate(groups)
               for character in TASK_GROUPS[group][1]]
    return source, entries


def item_letter_style(task, item):
    if task.source.startswith((PREFIX, *CUSTOM_PREFIXES)):
        try:
            groups = source_configuration(task.source)['groups']
            if not isinstance(groups, list) or not 0 <= item.source_index < len(groups):
                raise ValueError('invalid group index')
            catalog = TASK_GROUPS if task.source.startswith(CUSTOM_PREFIX) else LEGACY_GROUPS
            _, characters, style = catalog[groups[item.source_index]]
            if item.character not in characters:
                raise ValueError('character does not match task group')
            return style
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise ValueError('采集任务的字符分类记录无效') from error
    style = task.source.rsplit(':', 1)[-1]
    return style if style in ('upright', 'italic') and item.character in string.ascii_letters else 'unspecified'


def source_configuration(source):
    if source.startswith(PREFIX):
        return {'groups': json.loads(source[len(PREFIX):]), 'reuse': []}
    if source.startswith(CUSTOM_PREFIXES):
        prefix = source.split(':', 2)
        value = json.loads(prefix[2])
        catalog = TASK_GROUPS if source.startswith(CUSTOM_PREFIX) else LEGACY_GROUPS
        if not isinstance(value, dict) or set(value) != {'groups', 'reuse'}:
            raise ValueError('字符选择配置无效')
        groups = value['groups']
        if (not isinstance(groups, list) or any(not isinstance(g, str) or g not in catalog for g in groups)
                or len(set(groups)) != len(groups) or not isinstance(value['reuse'], list)):
            raise ValueError('字符选择类别或复用配置无效')
        return value
    return {'groups': [], 'reuse': []}
