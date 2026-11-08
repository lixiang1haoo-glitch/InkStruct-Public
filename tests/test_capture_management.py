import json
import sys

import pytest

from inkstruct.collector import _collector_source

sys.path.insert(0, str(_collector_source()))
from handwriting_collector.models import Trajectory, TrajectoryPoint
from handwriting_collector.storage import SampleStorage
from handwriting_collector.tasks import CollectionTask, TaskRepository

from inkstruct.capture_management import CaptureCatalog, check_capture_paths, preview_han_file
from inkstruct.symbol_revisions import read_sample, recover_revisions, requeue_completed


def legacy(root):
    task = CollectionTask.create('推荐字表', 'recommended.csv', 'user_001', [('一', 2, 0)])
    repo = TaskRepository(root)
    repo.save(task)
    return task, repo


def test_writer_registry_unique_names_rename_and_legacy_unchanged(tmp_path):
    task, repo = legacy(tmp_path)
    before = repo.path_for(task.task_id).read_bytes()
    catalog = CaptureCatalog(tmp_path)
    assert catalog.writers() == {'user_001': {'name': 'user_001'}}
    assert not catalog.index.exists()
    a, b = catalog.create_writer('张三'), catalog.create_writer('张三')
    assert a != b and a.startswith('w_')
    catalog.rename_writer('user_001', '原作者')
    assert catalog.writers()['user_001']['name'] == '原作者'
    assert repo.path_for(task.task_id).read_bytes() == before


def test_cancel_restore_archive_only_changes_management(tmp_path):
    task, repo = legacy(tmp_path)
    before = repo.path_for(task.task_id).read_bytes()
    catalog = CaptureCatalog(tmp_path)
    for state in ('active', 'paused', 'cancelled', 'paused', 'archived'):
        catalog.set_state('han', task.task_id, state)
        assert catalog.tasks()[0]['state'] == state
        assert repo.path_for(task.task_id).read_bytes() == before


def test_damaged_task_and_unknown_management_remain_visible(tmp_path):
    task, repo = legacy(tmp_path)
    repo.path_for(task.task_id).write_text('{bad', 'utf-8')
    catalog = CaptureCatalog(tmp_path)
    assert catalog.tasks()[0]['state'] == 'damaged'
    catalog.index.write_text('{"schema_version":"future"}', 'utf-8')
    before = catalog.index.read_bytes()
    with pytest.raises(ValueError):
        catalog.create_writer('test')
    assert catalog.index.read_bytes() == before


@pytest.mark.parametrize('rows,match', [('一,101', '1–100'), ('一,5\n一,4', '冲突'), ('一,x', '不是整数')])
def test_csv_preflight_rejects_bad_or_conflicting_counts(tmp_path, rows, match):
    path = tmp_path/'推荐.csv'
    path.write_text('character,repeats\n'+rows, 'utf-8-sig')
    with pytest.raises(ValueError, match=match):
        preview_han_file(path, 5)


def test_csv_preview_explicit_default_and_duplicates(tmp_path):
    path = tmp_path/'推荐.csv'
    path.write_text('character,repeats\n一,\n二,3\n一,5', 'utf-8-sig')
    entries, lines = preview_han_file(path, 5)
    assert [(c, n) for c,n,_ in entries] == [('一', 5), ('二', 3)]
    assert lines == [4]


def test_deep_windows_capture_root_is_rejected_before_writing(tmp_path, monkeypatch):
    import inkstruct.capture_management as management
    monkeypatch.setattr(management.os, 'name', 'nt')
    root = tmp_path / ('x'*100)
    with pytest.raises(ValueError, match='目录过深'):
        check_capture_paths(root, 'w_'+'1'*32)
    assert not root.exists()


def recorded_han(root):
    task, repo = legacy(root)
    trajectory = Trajectory()
    trajectory.start_stroke(TrajectoryPoint(100,100,.4,0))
    trajectory.append_point(TrajectoryPoint(200,100,.7,10))
    storage = SampleStorage(root)
    sid, path = storage.save_single(writer_id=task.writer_id, task=task, item=task.current_item(),
        trajectory=trajectory, canvas_width=560, canvas_height=320, device_pixel_ratio=1)
    task.complete_current(sid)
    repo.save(task)
    files = {p:p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name != 'state.json'}
    return task, repo, storage, path, files


def test_han_rerecord_retires_json_and_legacy_with_exact_backup(tmp_path):
    task, repo, storage, path, files = recorded_han(tmp_path)
    item = task.items[0]
    assert read_sample(tmp_path, task, item)[2]['schema_version'] == 'handwriting_single_v1'
    revision = requeue_completed(tmp_path, task, repo, [item.item_id])
    assert not path.exists() and task.completed_count == 0
    journal = json.loads((revision/'revision.json').read_text('utf-8'))
    assert journal['schema_version'] == 'inkstruct_capture_revision_v1'
    for entry in journal['samples'][0]['files']:
        original = tmp_path/entry['path']
        assert not original.exists()
        assert (revision/entry['backup']).read_bytes() == files[original]
    assert storage.reconcile_task(task) == 0


def test_han_failed_requeue_restores_every_export_copy(tmp_path, monkeypatch):
    task, repo, _, _, files = recorded_han(tmp_path)
    before = task.to_dict()
    monkeypatch.setattr(repo, 'save', lambda _: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        requeue_completed(tmp_path, task, repo, [task.items[0].item_id])
    assert task.to_dict() == before
    assert all(p.read_bytes() == data for p,data in files.items())
    recover_revisions(tmp_path, task)
