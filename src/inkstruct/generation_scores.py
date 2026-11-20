"""Score validated generation candidates using the font packer's default priorities."""

import multiprocessing as mp
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from itertools import batched, groupby
from pathlib import Path
from statistics import fmean

from .fonts.importer import _read, font_candidate_priority, generated_records, make_generated, protocol_records
from .generation_parallel import worker_count
from .generation_variants import geometry_key


def diversity_points(count):
    return 100 * (1 - 2 ** (-max(count - 1, 0) / 3))


def stroke_source_points(kind):
    return 80 if kind in {"author_complete_component", "author_group"} else 0 if kind in {"explicit_gap", "reference"} else 60


def source_points(glyph, payload):
    if glyph.get("method") == "same_character":
        return 100.0
    if "segments" in glyph:
        segments = glyph["segments"]
        return fmean((stroke_source_points(segment.get("source_kind", segment["kind"])) for segment in segments),
                     weights=(len(segment["standard_slots"]) for segment in segments))
    return fmean(stroke_source_points(row["kind"]) for row in payload["stroke_sources"])


def _character_scores(records, targets, source, diversity, cancelled):
    for character, candidates in groupby(records, key=lambda record: record[0]["character"]):
        if cancelled():
            raise InterruptedError("评分已取消")
        if character not in targets:
            continue
        choices = []
        for glyph, row, payload, protocol in candidates:
            trajectory, _, summary = make_generated(glyph, row, payload, protocol)
            choices.append((font_candidate_priority(summary), trajectory, glyph, payload))
        priority = min(choice[0] for choice in choices)
        active = [(t, g, p) for rank, t, g, p in choices if rank == priority]
        quality = fmean(source_points(g, p) for _, g, p in active) if source else 0
        replay = source and any(g.get("method") == "same_character" for _, g, _ in active)
        count = len({geometry_key(t) for t, _, _ in active}) if diversity else 0
        yield quality, replay, diversity_points(count), count >= 2


def _initialize_worker(root, writer, protocol, source, diversity, stop):
    global _worker_config
    _worker_config = root, writer, protocol, source, diversity, stop


def _score_block(characters):
    root, writer, protocol, source, diversity, stop = _worker_config
    if protocol is None:
        records = (record for ch in characters for record in generated_records(root, writer, character=ch))
    else:
        records = protocol_records(root, writer, protocol, characters)
    return list(_character_scores(records, set(characters), source, diversity, stop.is_set))


def _parallel_blocks(root, writer, targets, source, diversity, workers, cancelled):
    protocol_path = root / 'protocol.json'
    if (root / 'v63-run.json').is_file():
        protocol = None
        ordered = _read(root / 'v63-run.json')['files']
    elif (root / 'trajectories').is_dir():
        protocol = None
        ordered = (chr(int(p.stem[2:], 16)) for p in sorted((root / 'trajectories').glob('U+*.json')))
    else:
        protocol = _read(protocol_path)
        ordered = protocol['characters']
    chars = [ch for ch in ordered if ch in targets]
    if not chars:
        return
    size = min(32, max(1, (len(chars) + workers - 1) // workers))
    blocks = iter(batched(chars, size))
    context = mp.get_context("spawn")
    stop = context.Event()
    with ProcessPoolExecutor(max_workers=workers, mp_context=context, initializer=_initialize_worker,
                             initargs=(root, writer, protocol, source, diversity, stop)) as pool:
        pending = deque()
        try:
            while True:
                if cancelled():
                    raise InterruptedError("评分已取消")
                while len(pending) < workers * 2 and (block := next(blocks, None)):
                    pending.append(pool.submit(_score_block, block))
                if not pending:
                    break
                # Resolve in manifest order to preserve floating point accumulation.
                try:
                    scored = pending[0].result(timeout=.1)
                except TimeoutError:
                    if pending[0].done():
                        scored = pending[0].result()
                    else:
                        continue
                pending.popleft()
                yield scored
        finally:
            stop.set()
            for job in pending:
                job.cancel()


def evaluate(run, writer, targets, *, source, diversity, completed, workers=1,
             progress=None, cancelled=lambda: False):
    targets = set(targets)
    total = len(targets)
    count = worker_count(completed, 8 if workers == 'auto' and completed >= 128 else
                         1 if workers == 'auto' else workers)
    if progress:
        progress(0, completed)
    if cancelled():
        raise InterruptedError("评分已取消")
    if count > 1:
        blocks = _parallel_blocks(Path(run), writer, targets, source, diversity, count, cancelled)
    else:
        records = generated_records(run, writer) if completed else ()
        blocks = batched(_character_scores(records, targets, source, diversity, cancelled), 32)
    source_total = diversity_total = replayed = rotatable = covered = 0
    for block in blocks:
        for quality, replay, variety, rotates in block:
            source_total += quality
            replayed += replay
            diversity_total += variety
            rotatable += rotates
            covered += 1
        if progress:
            progress(covered, completed)
    if cancelled():
        raise InterruptedError("评分已取消")
    result = {"target_count": total, "covered_count": covered}
    if source:
        result.update(source_score=source_total / total, replayed_count=replayed)
    if diversity:
        result.update(diversity_score=diversity_total / total, rotatable_count=rotatable)
    return result
