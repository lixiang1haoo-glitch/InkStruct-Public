"""The packaged preview companion uses bounded, request-specific screen data."""
import json
import os
import subprocess
import sys

import pytest

from inkstruct.editor.preview_wire import HEADER, POINT, STROKE, VERSION, read_page, write_page

from test_preview_path_simplification import sample_snapshot


def test_preview_worker_pixels_and_rejected_oversize_request(tmp_path):
    write_page(tmp_path/'page-1.bin', sample_snapshot(), 0, None)
    (tmp_path/'4.cancel').touch()
    base = {'version': VERSION, 'page': 1, 'accelerate': True, 'spec': [10, 10, 2], 'tiles': [[-1, -1]]}
    requests = [dict(base, token=1),
                dict(base, token=2, accelerate=False, spec=[10000, 10000, 2], tiles=[[1, 2]]),
                dict(base, token=3, spec=[10000, 10000, 2]),
                dict(base, token=4),
                dict(base, token=5, version=VERSION + 1),
                dict(base, token=6, accelerate=1)]
    result = subprocess.run([sys.executable, '-m', 'inkstruct.editor.preview_raster_worker', str(tmp_path)],
                            input=b''.join(json.dumps(r).encode()+b'\n' for r in requests),
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    first, zoomed, failed, cancelled, bad_version, bad_flag = responses
    assert first['token'] == 1 and not first['page_reused'] and first['images'][0]['bytes'] == 20*20*4
    assert len((tmp_path/'1--1--1.argb').read_bytes()) == 20*20*4
    assert zoomed['page_reused'] and zoomed['images'][0]['bytes'] == 512*512*4
    assert failed['token'] == 3 and 'budget' in failed['error']
    assert cancelled == {'token': 4, 'cancelled': True}
    assert 'error' in bad_version and 'error' in bad_flag
    assert not list(tmp_path.glob('[3-6]-*.argb'))


@pytest.mark.parametrize('mutation', ['wrong_version', 'length', 'truncated', 'invalid_counts', 'nan'])
def test_page_payload_rejects_bad_header_and_coordinates(tmp_path, mutation):
    path = tmp_path/'page.bin'
    write_page(path, sample_snapshot(), 0, None)
    raw = bytearray(path.read_bytes())
    header = list(HEADER.unpack_from(raw))
    if mutation == 'wrong_version':
        header[1] += 1
    elif mutation == 'length':
        header[3] += 1
    elif mutation == 'truncated':
        del raw[-1]
        header[3] -= 1
    elif mutation == 'invalid_counts':
        header[-1] = 2**32 - 1
    else:
        _, id_bytes, color_bytes, _ = STROKE.unpack_from(raw, HEADER.size)
        POINT.pack_into(raw, HEADER.size + STROKE.size + id_bytes + color_bytes, float('nan'), 0.0)
    HEADER.pack_into(raw, 0, *header)
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        read_page(path)
