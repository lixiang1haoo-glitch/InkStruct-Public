"""Lossless, opt-in receipt of collection batches; never writes a production index."""
from __future__ import annotations

import stat
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def extract_new_batch(zip_path: Path, destination: Path) -> list[Path]:
    """Preflight the entire archive before extracting into a new private directory."""
    with ZipFile(zip_path) as archive:
        names = set()
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if (name.is_absolute() or '..' in name.parts or '\\' in info.filename
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError(f'unsafe archive member: {info.filename}')
            if name in names:
                raise ValueError(f'duplicate archive member: {info.filename}')
            names.add(name)
        destination.mkdir(parents=True, exist_ok=False)
        archive.extractall(destination)
    return sorted(destination.rglob('*.json'))


def partition_samples(samples, training_characters, excluded_characters):
    """Every repeat follows its character group, regardless of embedded task labels."""
    training_characters, excluded_characters = set(training_characters), set(excluded_characters)
    if training_characters & excluded_characters:
        raise ValueError('training and evaluation character groups overlap')
    groups = {'training': [], 'evaluation': [], 'unplanned': []}
    seen_ids, seen_payloads = set(), set()
    for sample in samples:
        if sample.sample_id in seen_ids or sample.source_sha256 in seen_payloads:
            raise ValueError('duplicate capture ID or payload in received batch')
        seen_ids.add(sample.sample_id)
        seen_payloads.add(sample.source_sha256)
        group = ('evaluation' if sample.character in excluded_characters else
                 'training' if sample.character in training_characters else 'unplanned')
        groups[group].append(sample)
    return groups
