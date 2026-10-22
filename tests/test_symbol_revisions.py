"""Rerecord transactions preserve originals and recover interrupted commits."""
import json

import pytest
from test_symbol_capture import CollectionTask, TaskRepository, specimen_args

from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font
from inkstruct.symbol_capture import SymbolStorage
from inkstruct.symbol_revisions import requeue_completed


def captured(root):
    repo, storage = TaskRepository(root), SymbolStorage(root)
    task = CollectionTask.create('test','legacy:upright','user_001',[('A',5,0),('B',5,1)])
    repo.save(task)
    originals = {}
    for _ in range(8):
        args = specimen_args()
        args.update(task=task,item=task.current_item(),writer_id='user_001')
        sid,path = storage.save_single(**args)
        originals[path] = path.read_bytes()
        task.complete_current(sid)
        repo.save(task)
    return task,repo,storage,originals


def test_rerecord_three_B_keeps_A_and_excludes_retired_samples_from_font(tmp_path):
    task,repo,storage,originals = captured(tmp_path/'collection')
    b = [i.item_id for i in task.items[5:8]]
    revision = requeue_completed(storage.root,task,repo,b)
    assert task.completed_count==5 and task.cursor==5
    assert all(i.status=='pending' and i.sample_id is None for i in task.items[5:8])
    assert storage.reconcile_task(repo.load(repo.path_for(task.task_id)))==0
    assert len(list((storage.root/'samples').rglob('*.json')))==5
    for path,raw in originals.items():
        if path.parent.name=='U+0041':
            assert path.read_bytes()==raw
        else:
            assert not path.exists()
            assert (revision/(path.name+'.bak')).read_bytes()==raw
    font = tmp_path/'only-good.inkfont'
    build_font(font,writer='user_001',name='test',symbols=storage.root)
    assert set(FontPackage(font).pools)=={'A'}
    old_ids = {p.stem for p in originals}
    args=specimen_args('B'); args.update(task=task,item=task.current_item(),writer_id='user_001')
    sid,_=storage.save_single(**args)
    assert sid not in old_ids
    task.complete_current(sid); repo.save(task)
    reopened = repo.load(repo.path_for(task.task_id))
    assert storage.reconcile_task(reopened)==0 and reopened.completed_count==6
    assert reopened.current_item().character=='B' and reopened.current_item().repeat_index==2


def test_failed_task_save_restores_all_active_bytes(tmp_path,monkeypatch):
    task,repo,storage,originals = captured(tmp_path)
    before=task.to_dict()
    def failed(_):
        raise OSError('disk full')
    monkeypatch.setattr(repo,'save',failed)
    with pytest.raises(OSError,match='disk full'):
        requeue_completed(storage.root,task,repo,[task.items[5].item_id])
    assert task.to_dict()==before and repo.load(repo.path_for(task.task_id)).to_dict()==before
    assert all(p.read_bytes()==raw for p,raw in originals.items())
    journal=next((tmp_path/'revisions').rglob('revision.json'))
    assert json.loads(journal.read_bytes())['status']=='rolled_back'


def test_crash_before_task_commit_recovers_on_resume(tmp_path,monkeypatch):
    task,repo,storage,originals=captured(tmp_path)
    def crash(_):
        raise SystemExit('simulated power loss')
    monkeypatch.setattr(repo,'save',crash)
    with pytest.raises(SystemExit):
        requeue_completed(storage.root,task,repo,[i.item_id for i in task.items[5:8]])
    assert len(list((tmp_path/'samples').rglob('*.json')))==5
    restored=repo.load(repo.path_for(task.task_id))
    storage.reconcile_task(restored)
    assert restored.completed_count==8
    assert all(p.read_bytes()==raw for p,raw in originals.items())


def test_crash_after_commit_does_not_resurrect_retired_record(tmp_path,monkeypatch):
    from inkstruct import symbol_revisions as revisions
    task,repo,storage,_=captured(tmp_path)
    real=revisions._write
    def fail_marker(path,value):
        if value['status']=='committed':
            raise OSError('marker interrupted')
        real(path,value)
    monkeypatch.setattr(revisions,'_write',fail_marker)
    requeue_completed(storage.root,task,repo,[task.items[5].item_id])
    monkeypatch.setattr(revisions,'_write',real)
    reopened=repo.load(repo.path_for(task.task_id))
    assert storage.reconcile_task(reopened)==0 and reopened.completed_count==7
    assert reopened.current_item().repeat_index==1


def test_stale_task_is_rejected_without_changing_samples(tmp_path):
    task,repo,storage,originals=captured(tmp_path)
    changed=type(task).from_dict(task.to_dict()); changed.name='another writer updated the task'
    repo.save(changed)
    with pytest.raises(ValueError,match='进度已变化'):
        requeue_completed(storage.root,task,repo,[task.items[5].item_id])
    assert all(p.read_bytes()==raw for p,raw in originals.items())


def test_display_cursor_movement_does_not_block_rerecord(tmp_path):
    task,repo,storage,originals=captured(tmp_path)
    # Requeue an earlier specimen while displaying a cursor normalized over
    # completed entries. All durable specimen/status records are unchanged.
    task.cursor=0
    assert task.current_item().character=='B' and task.cursor==8
    requeue_completed(storage.root,task,repo,[task.items[0].item_id])
    assert task.completed_count==7 and task.items[0].status=='pending'
    assert all(p.read_bytes()==raw for p,raw in originals.items() if p.parent.name=='U+0042')
