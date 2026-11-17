"""The three issued research recording stages and their writer-specific queues."""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

SOURCE_PREFIX = 'builtin:research-v1:'
STAGES = {
    'starter32': ('起步 · 32 字', 32),
    'add68': ('推荐 · 补至 100 字', 68),
    'add300': ('进阶 · 补至 400 字', 300),
}
ISSUED_LISTS = {
    'starter32/characters.csv': '7edac1a867d52e76a39215e32f711b1eca7ade0bec9f17af3f7bfc895542736f',
    'add68/characters.csv': '9495d09f96a3f045629f4ab20a85626316ba787e550a2a3ead000995d9aa5eaa',
    'historical400.csv': 'a0055fae4d848706cf3aa2769f0b66ffc8466112014ca336e225b7079c528d16',
}


@dataclass(frozen=True)
class RecordingStage:
    key: str
    entries: tuple[tuple[str, int, int], ...]

    @property
    def title(self):
        return STAGES[self.key][0]

    @property
    def source(self):
        return SOURCE_PREFIX + self.key


def stage_key(source):
    key = source.removeprefix(SOURCE_PREFIX)
    return key if source.startswith(SOURCE_PREFIX) and key in STAGES else None


@lru_cache(maxsize=1)
def recording_stages():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    root = root / 'configs' / 'collection' / 'research_v1'

    def read(filename):
        raw = (root / filename).read_bytes()
        if sha256(raw).hexdigest() != ISSUED_LISTS[filename]:
            raise ValueError(f'内置录制字表校验失败：{filename}')
        return tuple(row['character'] for row in csv.DictReader(raw.decode('utf-8-sig').splitlines()))

    starter = read('starter32/characters.csv')
    addition = read('add68/characters.csv')
    historical = read('historical400.csv')
    if (len(starter), len(addition), len(historical)) != (32, 68, 400) or (
        historical[:100] != starter + addition or len(set(historical)) != 400
    ):
        raise ValueError('内置录制字表顺序或字数不一致')
    return {
        key: RecordingStage(key, tuple((char, 1, index) for index, char in enumerate(characters)))
        for key, characters in zip(STAGES, (starter, addition, historical[100:]), strict=True)
    }


def qualifies(sample, graph):
    from .alignment import align_sample
    from .source_trajectory import source_trajectory

    if len(sample.strokes) == len(graph.strokes):
        for stroke in sample.strokes:
            first = stroke.points[0]
            if all((p.x, p.y) == (first.x, first.y) for p in stroke.points[1:]):
                return False
        return source_trajectory(sample, align_sample(sample, graph), graph)[0] is not None
    if len(sample.strokes) < len(graph.strokes):
        from .v631.connected import sample_units

        return any(part == 'whole' for part, _, _ in sample_units(sample, graph))
    return False


def remaining_entries(catalog, writer, stage, structures, cancelled=lambda: False):
    """Check current local Han samples, including attributed imports and legacy tasks."""
    from .capture_management import valid_writer
    from .sample_library import read_file
    from .samples import parse_raw_sample

    if not valid_writer(writer):
        raise ValueError('请选择书写者')
    root = catalog.task_root('han') / 'samples' / writer
    missing = {char for char, _, _ in stage.entries}
    codepoints = {f'U+{ord(char):04X}': char for char in missing}
    graphs = {}
    for folder in root.iterdir() if root.is_dir() else ():
        if cancelled() or not missing:
            break
        codepoint = folder.name.upper()
        folder_char = codepoints.get(codepoint)
        if codepoint.startswith('U+') and folder_char not in missing:
            continue
        for path in folder.glob('*.json'):
            if cancelled() or not missing or (folder_char and folder_char not in missing):
                break
            try:
                sample = parse_raw_sample(read_file(path), path, expected_writer=writer)
                char = sample.character
                if char not in missing or (folder_char and folder_char != char):
                    continue
                if char not in graphs:
                    graphs[char] = structures.get(char)
                if qualifies(sample, graphs[char]):
                    missing.remove(char)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
                continue
    return tuple(entry for entry in stage.entries if entry[0] in missing)
