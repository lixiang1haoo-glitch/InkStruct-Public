"""The packaged preview companion uses bounded, request-specific screen data."""
import json
import os
import subprocess
import sys


def test_preview_worker_pixels_and_rejected_oversize_request(tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'
    (tmp_path/'1.svg').write_bytes(svg)
    (tmp_path/'2.svg').write_bytes(svg)
    requests = [{'token': 1, 'spec': [10, 10, 2], 'tiles': [[-1, -1]]},
                {'token': 2, 'spec': [10000, 10000, 2], 'tiles': [[-1, -1]]}]
    result = subprocess.run([sys.executable, '-m', 'inkstruct.editor.preview_raster_worker', str(tmp_path)],
                            input=b''.join(json.dumps(r).encode()+b'\n' for r in requests),
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                            capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    first, failed = responses
    assert first['token'] == 1 and first['images'][0]['bytes'] == 20*20*4
    assert len((tmp_path/'1--1--1.argb').read_bytes()) == 20*20*4
    assert failed['token'] == 2 and 'budget' in failed['error']
    assert not (tmp_path/'2--1--1.argb').exists()
