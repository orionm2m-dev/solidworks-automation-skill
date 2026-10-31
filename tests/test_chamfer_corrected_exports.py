"""Current flat authority exports use the existing exact CL/WIP contracts."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import os
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_chamfer_corrected_exports as m
spec=importlib.util.spec_from_file_location('corrected_cl_fixture',ROOT/'tests/test_chamfer_exports.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
case=fixture.case


@pytest.fixture
def current(case,monkeypatch):
    old=case.source.read_bytes();old_hash=m._file_hash(case.source)
    archive=case.root/'R114.SLDPRT';archive.write_bytes(old)
    case.source.write_bytes(b'corrected current saved R115')
    loaded=case.loaded
    loaded['source_sha256']=loaded['state']['saved_file_sha256']=case.args['expected_source_sha256']=m._file_hash(case.source)
    loaded['configured_contour']['record_counts']=[47]
    loaded['state']['operations'][-1]['toolpath_record_counts']=[47]
    loaded.update(authority_kind=m.AUTHORITY,approach_settings={'nc':{'clearance':1.}})
    loaded['current_context_sha256']=m._digest(m.group.current_projection(loaded))
    correction_file=case.root/'sw_cam_chamfer_approach_correction.py';correction_file.write_text('# fixed writer proof')
    loaded['pins'].append(m.common._pin(correction_file))
    loaded['offline_export_proof_pins'].append(m.common._pin(archive))
    calls=[]
    def load_completed(path,digest,**identity):
        calls.append((path,digest,identity))
        assert identity['expected_source_sha256']!=old_hash
        return deepcopy(loaded)
    def writer_loader(*args,**kwargs):raise AssertionError('Generic writer receipt loader must not execute')
    correction=SimpleNamespace(__file__=str(correction_file),load_completed=writer_loader)
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_chamfer_approach_correction',correction)
    reader_file=case.root/'sw_cam_chamfer_receipt.py';reader_file.write_text('# scoped receipt reader proof')
    reader=SimpleNamespace(__file__=str(reader_file),load_completed=load_completed)
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_chamfer_receipt',reader)
    def old_loader(*a,**k):raise AssertionError('Old T5 current-source loader must not execute')
    monkeypatch.setattr(m.cl,'load_checkpoint',old_loader)
    monkeypatch.setattr(m.wip,'load_checkpoint',old_loader)
    return SimpleNamespace(case=case,loaded=loaded,calls=calls,archive=archive,old_hash=old_hash)


def load(f,action='export_cl'):
    c=f.case
    return m.load_checkpoint(c.loaded['parent_pin']['path'],c.loaded['parent_pin']['sha256'],action=action,
        **{k:c.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})


@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_changed_source_loads_only_flat_current_authority(current,action):
    loaded=load(current,action)
    assert len(current.calls)==1
    assert loaded['configured_contour']['record_counts']==[47]
    assert m.cl.operation_contract(loaded)[-1]['toolpath_record_counts']==[47]
    names={Path(p['path']).name for p in loaded['pins']}
    assert 'sw_cam_chamfer_corrected_exports.py' in names
    assert 'sw_cam_chamfer_receipt.py' in names
    assert 'sw_cam_chamfer_approach_correction.py' not in names
    assert current.archive.read_bytes()!=current.case.source.read_bytes()
    if action=='export_wip':assert 'sw_cam_completed_gtp_wip.py' in names
    else:assert 'sw_cam_mill_generic_cl.py' in names
    assert any(Path(p['path']).name=='sw_cam_chamfer_approach_correction.py'
               for p in loaded['offline_export_proof_pins'])


@pytest.mark.parametrize('change',['authority','dirty','source','count','old_count','catalogue','context','empty_approach'])
def test_inconsistent_flat_context_rejected(current,change):
    l=current.loaded
    if change=='authority':l['authority_kind']='saved_generated_contour_geometry_review_pending'
    elif change=='dirty':l['state']['document']['needs_save']=True
    elif change=='source':l['source_sha256']=current.old_hash
    elif change=='count':l['configured_contour']['record_counts']=[48]
    elif change=='old_count':l['state']['operations'][4]['toolpath_record_counts']=[761]
    elif change=='catalogue':l['operation_checkpoint']['final_observation']['tools'][-1]['CutDiameter']=2.
    elif change=='context':l['current_context_sha256']='f'*64
    else:l['approach_settings']={}
    if change not in ('context','source'):l['current_context_sha256']=m._digest(m.group.current_projection(l))
    with pytest.raises(ValueError):load(current)
    assert current.case.control.calls==0


def test_changed_history_proof_blocks_without_reopening_current_as_old(current):
    current.archive.write_bytes(b'tampered archive')
    with pytest.raises(ValueError):load(current)
    assert current.case.control.calls==0


def test_existing_cl_core_exports_new_actual_count_and_source_once(current):
    loaded=load(current)
    result=m.cl.export_cl(object(),'fixture','fixture.tlb',loaded=loaded,args=current.case.args,
                          output_path=str(current.case.root/'out'/'route.cl'))
    assert result['readback_verified'] and result['checkpoint_export_readback_verified']
    assert current.case.control.calls==1 and len(current.case.control.labels)==3
    assert result['before']['expected_generated_operations'][-1]['toolpath_record_counts']==[47]
    assert result['saved_checkpoint_pin']==loaded['parent_pin']
    assert all(result[k] is False for k in ('GTP_attempted','GOP_attempted','model_saved','setter_attempted'))


def test_earlier_source_once_marker_does_not_rearm_current_source(current):
    loaded=load(current);c=current.case
    old_marker=m.cl.marker_path(c.source,current.old_hash,271)
    old_marker.parent.mkdir(parents=True,exist_ok=True);old_marker.write_text('{}')
    current_marker,_=m.cl.fresh_paths(loaded,c.args)
    assert current_marker!=old_marker
    current_marker.write_text('{}')
    with pytest.raises(ValueError):m.cl.fresh_paths(loaded,c.args)


def test_invalid_actions_never_call_parent(current):
    with pytest.raises(ValueError):load(current,'generate')
    assert not current.calls


def test_parent_receipt_must_remain_live(current):
    current.loaded['pins']=[p for p in current.loaded['pins'] if p!=current.loaded['parent_pin']]
    with pytest.raises(ValueError):load(current)


def test_live_dependency_tampering_stops_before_export(current):
    extra=current.case.root/'retained.py';extra.write_text('first')
    current.loaded['pins'].append(m.common._pin(extra));extra.write_text('different')
    with pytest.raises(ValueError):load(current)
    assert current.case.control.calls==0
