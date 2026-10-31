"""Bounded read journaling, failure durability and independent mutation writes."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest
STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE));sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('read_progress_under_test',STAGE/'scripts/sw_cam_read_progress_journal.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def setup(tmp_path):
    source=tmp_path/'model.SLDPRT';source.write_bytes(b'saved')
    receipt=tmp_path/'owner.json';progress=tmp_path/'batch.read-progress.json'
    report={'raw':[],'actions':{}};snapshots=[];last={}
    def persist():
        snapshots.append(deepcopy(report));receipt.write_text(json.dumps(report),encoding='utf-8')
    def scope(**changes):
        params=dict(full_persist=persist,progress_path=progress,describe=lambda:deepcopy(last),
                    max_updates=128,protected_paths=[source,receipt]);params.update(changes)
        return m.ReadProgressJournal(**params)
    return dict(source=source,receipt=receipt,progress=progress,report=report,snapshots=snapshots,
                last=last,persist=persist,scope=scope)

def test_119_read_updates_flush_full_report_only_at_boundaries(setup):
    f=setup
    with f['scope']() as p:
        for i in range(119):
            f['last'].update(member='Field'+str(i),read_index=i,returned=True,validated=True)
            f['report']['raw'].append({'index':i,'value':float(i)})
            p.read()
        assert len(f['snapshots'])==1
        p.complete()
    assert len(f['snapshots'])==2 and f['snapshots'][-1]==f['report']
    assert len(json.loads(f['receipt'].read_text())['raw'])==119
    last=json.loads(f['progress'].read_text())
    assert last['status']=='completed' and last['read_updates']==119
    assert last['last_read']['read_index']==118 and last['mutation_authority'] is False
    assert f['progress'].stat().st_size<m.MAX_PROGRESS_BYTES

def test_mutation_pending_and_returned_use_unmodified_immediate_persist(setup):
    f=setup
    def mutation(phase):
        f['report']['actions']['SaveActiveDocument']={'phase':phase};f['persist']()
    with f['scope']() as p:
        f['last'].update(member='read',returned=True);p.read()
        mutation('pending')
        assert f['snapshots'][-1]['actions']['SaveActiveDocument']['phase']=='pending'
        mutation('returned')
        assert f['snapshots'][-1]['actions']['SaveActiveDocument']['phase']=='returned'
        p.complete()
    assert len(f['snapshots'])==4
    assert [v['actions'].get('SaveActiveDocument',{}).get('phase') for v in f['snapshots']]==[None,'pending','returned','returned']

def test_native_reader_failure_flushes_raw_partial_and_last_read(setup):
    f=setup
    with pytest.raises(RuntimeError,match='getter failed'):
        with f['scope']() as p:
            f['last'].update(member='Field42',attempted=True,returned=False)
            f['report']['raw'].append({'partial':42});p.read()
            raise RuntimeError('getter failed')
    assert len(f['snapshots'])==2 and f['snapshots'][-1]['raw']==[{'partial':42}]
    row=json.loads(f['progress'].read_text())
    assert row['status']=='failed' and row['last_read']['member']=='Field42' and row['error_type']=='RuntimeError'

def test_missing_completion_is_failure_and_flushes(setup):
    with pytest.raises(ValueError,match='explicitly complete'):
        with setup['scope']() as p:p.read()
    assert len(setup['snapshots'])==2 and json.loads(setup['progress'].read_text())['status']=='failed'

@pytest.mark.parametrize('bad',[{'x':float('nan')},{'x':object()},{'x':'a'*513},{'x':list(range(9))},{'x':{'y':{}}}])
def test_unbounded_descriptions_stop_and_flush(setup,bad):
    with pytest.raises(ValueError):
        with setup['scope'](describe=lambda:bad) as p:p.read()
    assert len(setup['snapshots'])==2
    assert json.loads(setup['progress'].read_text())['status']=='failed'

def test_update_budget_failure_keeps_last_accepted_read(setup):
    with pytest.raises(ValueError,match='budget'):
        with setup['scope'](max_updates=1) as p:
            setup['last'].update(read_index=1);p.read()
            setup['last'].update(read_index=2);p.read()
    assert len(setup['snapshots'])==2
    assert json.loads(setup['progress'].read_text())['last_read']['read_index']==1

def test_compact_write_failure_still_flushes_full_evidence(setup,monkeypatch):
    original=m._write_receipt;calls=[]
    def writer(path,row,**kw):
        calls.append(row['status'])
        if len(calls)==2:raise OSError('progress write failed')
        original(path,row,**kw)
    monkeypatch.setattr(m,'_write_receipt',writer)
    with pytest.raises(OSError,match='progress write failed'):
        with setup['scope']() as p:
            setup['report']['raw'].append(12);p.read()
    assert len(setup['snapshots'])==2 and setup['snapshots'][-1]['raw']==[12]
    assert calls==['reading','reading','failed']

def test_full_flush_failure_is_never_reported_as_success(setup):
    count=[]
    def persist():
        count.append(1)
        if len(count)==2:raise OSError('full receipt failed')
    with pytest.raises(OSError,match='full receipt failed'):
        with setup['scope'](full_persist=persist) as p:p.complete()
    assert len(count)==2
    assert json.loads(setup['progress'].read_text())['status']=='failed'

@pytest.mark.parametrize('kind',['existing','alias','relative','bad_extension'])
def test_invalid_progress_output_never_calls_owner_persist(setup,kind):
    if kind=='existing':setup['progress'].write_text('{}');path=setup['progress']
    elif kind=='alias':path=setup['receipt']
    elif kind=='relative':path=Path('relative.json')
    else:path=setup['progress'].with_suffix('.txt')
    with pytest.raises(ValueError):setup['scope'](progress_path=path)
    assert setup['snapshots']==[]

def test_completed_scope_cannot_be_reused(setup):
    p=setup['scope']()
    with p:p.read();p.complete()
    with pytest.raises(ValueError):p.read()
    with pytest.raises(ValueError):p.__enter__()

def test_failure_during_final_progress_write_keeps_full_flush(setup,monkeypatch):
    original=m._write_receipt
    def writer(path,row,**kw):
        if row['status']=='completed':raise OSError('final progress failed')
        original(path,row,**kw)
    monkeypatch.setattr(m,'_write_receipt',writer)
    with pytest.raises(OSError,match='final progress failed'):
        with setup['scope']() as p:setup['report']['raw'].append(33);p.complete()
    assert len(setup['snapshots'])==2 and setup['snapshots'][-1]['raw']==[33]


def test_total_description_bytes_are_bounded_before_publication(setup):
    bad={str(i):'x'*512 for i in range(16)}
    with pytest.raises(ValueError,match='byte budget'):
        with setup['scope'](describe=lambda:bad) as p:p.read()
    assert len(setup['snapshots'])==2
    assert json.loads(setup['progress'].read_text())['last_read']=={}
