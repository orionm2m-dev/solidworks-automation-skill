
"""Portable request, once-marker, and exact phase-closure contract tests."""
from copy import deepcopy
from pathlib import Path
import importlib
import os
import sys
import pytest

ROOT=Path(os.environ['SOLIDWORKS_SKILL_ROOT']).resolve()
sys.path.insert(0,str(ROOT))
import scripts
STAGE=Path(__file__).resolve().parents[1]
scripts.__path__.insert(0,str(STAGE/'scripts'))
m=importlib.import_module('scripts.sw_cam_taper_tool_candidate')


def request(tmp_path):
    p={k:str(tmp_path/(k+'.json')) for k in m.PARAMS if k.endswith('path')}
    p.update({k:'a'*64 for k in m.PARAMS if k.endswith('sha256')})
    p.update(process_id=123,module_sha256=m._file_hash(m.__file__),
        qualification_only=True,acknowledge_disposable_copy=True,
        acknowledge_machine_scope=True,message_policy='vendor_default',
        addin_clsid='{11111111-2222-3333-4444-555555555555}')
    return dict(action='create_taper_candidate',params=p)


def test_request_accepts_only_bounded_action_and_fields(tmp_path):
    q=request(tmp_path)
    assert m.validate_request(q)==q['params']
    for key in ['tool_native_id','operation_id','target_value']:
        copy=deepcopy(q);copy['params'][key]=1
        with pytest.raises(ValueError):m.validate_request(copy)
    q['action']='generate'
    with pytest.raises(ValueError):m.validate_request(q)


@pytest.mark.parametrize('key,value',[
    ('process_id',True),('process_id',0),('qualification_only',1),
    ('acknowledge_machine_scope',False),('module_sha256','b'*64),
    ('message_policy','suppress'),('addin_clsid','any'),('recipe_sha256','bad'),
    ('recipe_path','relative.json')])
def test_request_rejects_unsafe_or_stale_parameters(tmp_path,key,value):
    q=request(tmp_path);q['params'][key]=value
    with pytest.raises(ValueError):m.validate_request(q)


@pytest.mark.parametrize('a,b,expected',[
    (True,1,False),(False,0.,False),(1,1,True),(1.,1,False),
    (1,1.,True),(1.0000000001,1.,True),(float('nan'),1.,False)])
def test_scalar_readback_keeps_bool_and_integer_semantics(a,b,expected):
    assert m.scalar_equal(a,b) is expected


def test_once_key_ignores_receipt_name_and_requested_value(tmp_path,monkeypatch):
    monkeypatch.setattr(m.exports,'local_evidence_root',lambda:tmp_path)
    a=m.marker_path(str(tmp_path/'source.sldprt'),'a'*64)
    assert a==m.marker_path(str(tmp_path/'source.sldprt'),'a'*64)
    assert a!=m.marker_path(str(tmp_path/'source.sldprt'),'b'*64)
    r=dict(source_path=str(tmp_path/'source.sldprt'),initial_source_sha256='a'*64,
           phase='prepared',actions={})
    j=m.Journal(r,tmp_path/'first.json',a);j.pending('AddNewTool3')
    assert a.exists()
    other=m.Journal(deepcopy(r),tmp_path/'renamed.json',a)
    with pytest.raises(ValueError):other.pending('DifferentRequestedValue')
    assert not (tmp_path/'renamed.json').exists()


def test_journal_intent_and_return_persist_before_validation(tmp_path):
    r=dict(source_path=str(tmp_path/'model.sldprt'),initial_source_sha256='a'*64,
           phase='prepared',actions={})
    j=m.Journal(r,tmp_path/'result.json',tmp_path/'once.json')
    j.pending('SaveActiveDocument')
    import json
    raw=json.loads(j.receipt.read_text())
    assert raw['actions']['SaveActiveDocument']['pending'] is True
    j.returned('SaveActiveDocument',False)
    raw=json.loads(j.receipt.read_text())
    assert raw['actions']['SaveActiveDocument']['native_return_type']=='bool'
    assert raw['actions']['SaveActiveDocument']['native_return_value'] is False
    with pytest.raises(ValueError):j.pending('SaveActiveDocument')


def test_catalogue_exact_addition_and_old_fields():
    before=[dict(native_id=10,tool_type_raw=1,CutDiameter=8.,Protrusion=25.,StnNo=1)]
    new=dict(native_id=20,tool_type_raw=8,CutDiameter=.6,Protrusion=20.,StnNo=2)
    m.verify_new_catalogue(before,before+[new],20)
    for after in ([new],before+[new,new],before+[dict(new,tool_type_raw=11)],
                  [dict(before[0],Protrusion=20.)]+[new]):
        with pytest.raises(ValueError):m.verify_new_catalogue(before,after,20)


def test_phase_closure_keeps_identity_call_live(tmp_path,monkeypatch):
    names=sorted(m.OFFLINE_PHASE_NAMES)+['sw_cam_feature_sketch.py','other.py']
    parent=dict(pins=[dict(path=str(tmp_path/n),sha256='a'*64) for n in names],
        offline_export_proof_pins=[],historical_source_pin=dict(path=str(tmp_path/'old.sldprt'),sha256='b'*64))
    pin=lambda p:dict(path=str(Path(p).resolve()),sha256='c'*64)
    monkeypatch.setattr(m.exports,'_pin',pin)
    recipe=pin(tmp_path/'recipe.json');catalogue=pin(tmp_path/'catalogue.json')
    live,offline,retired=m.derive_closure(parent,recipe,catalogue)
    assert {Path(v['path']).name for v in retired}==m.OFFLINE_PHASE_NAMES
    assert 'sw_cam_feature_sketch.py' in {Path(v['path']).name for v in live}
    assert all(v in offline for v in retired)
    assert recipe in offline and catalogue in offline and parent['historical_source_pin'] in offline
    assert {'sw_cam_taper_tool_candidate.py','sw_cam_taper_profile.py','sw_cam_ud14_qualification.py'} <= {Path(v['path']).name for v in live}
    parent['pins']=parent['pins'][1:]
    with pytest.raises(ValueError):m.derive_closure(parent,recipe,catalogue)


from test_taper_tool_writer import case as writer_case, run as writer_run


def test_changed_configuration_with_unchanged_saved_sha_is_uncertain(writer_case):
    c=writer_case
    c.b.saved_hash=lambda stage:c.r['initial_source_sha256']
    result=writer_run(c)
    assert result['readback_verified'] is False and result['status']=='uncertain'
    assert c.b.calls.count('save')==1
    assert 'candidate:save_after' not in c.b.calls


def test_save_zero_float_is_rejected(writer_case):
    c=writer_case;c.b.save_return=0.0
    result=writer_run(c)
    assert result['status']=='uncertain' and not result['readback_verified']
    assert c.b.calls.count('save')==1 and 'saved_hash' not in c.b.calls
