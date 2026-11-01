"""Regression for the actual unsupported shared QI and zero-dispatch continuation."""
from copy import deepcopy
from pathlib import Path
import hashlib,importlib.util,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_finish_cnc_zero as m
from scripts import sw_cam_guide_finish_compensation as c
from scripts.sw_cam_comtypes import _INTERFACES
from scripts.sw_cam_face_interfaces import FACE_IIDS


def failure():
    path=os.environ.get('SW_CAM_CANDIDATE_FAILURE_RECEIPT')
    if not path:pytest.skip('Actual pre-dispatch evidence not provided')
    return json.loads(Path(path).read_text())


def actual_args():
    r=failure();p=deepcopy(r['request']);p['module_sha256']=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
    loaded=dict(ownership=r['ownership'],generated_checkpoint_pin=r['generated_checkpoint_pin'],
        guide_parameters={'expected_parameters':r['before']},generated={'saved_cl':r['before_cl']})
    return r,p,loaded


def test_actual_metadata_resolves_every_candidate_adapter_and_member():
    r=failure();pin=next(v for v in r['live_pins']if Path(v['path']).name.startswith('_FE488'))
    tlb=next(v['path']for v in r['live_pins']if v['path'].endswith('.tlb'))
    assert 'ICWNCParam2'not in _INTERFACES and 'ICWNCParam2'in FACE_IIDS
    result=c.audit(tlb,pin)
    assert len(result['members'])==11 and result['native_called']is False
    routes={v['name']:v['resolution']for v in result['interface_resolution']['interfaces']}
    assert routes['ICWNCParam2']=='face_extension'and len(routes)==7


def test_actual_failed_writer_was_rejected_before_all_mutations():
    r,p,l=actual_args();m.zero_attempt_contract(r,p,l)
    assert r['issue']['locations'][-1]['function']=='_interface_class'
    assert r['cleanup_session_active']is False


@pytest.mark.parametrize('key',['mutation_attempted','native_call_attempted','native_call_returned','native_dispatch_pending',
    'setter_attempted','GTP_attempted','save_attempted','model_saved','SetTool_attempted','operation_creation_attempted',
    'readback_verified','continuation_ready','cleanup_session_active'])
def test_any_possible_mutation_or_missing_cleanup_rejects_continuation(key):
    r,p,l=actual_args();r[key]=True
    with pytest.raises(ValueError):m.zero_attempt_contract(r,p,l)


@pytest.mark.parametrize('case',['wrong_action','attempted','source','owner','checkpoint','parameters','saved_cl','same_code','error_kind','cleanup_error','events'])
def test_changed_failure_lineage_rejects_continuation(case):
    r,p,l=actual_args()
    if case=='wrong_action':r['actions']['SaveActiveDocument']={}
    elif case=='attempted':r['actions']['SetCNCComp:324']['attempted']=True
    elif case=='source':r['source_sha256']='a'*64
    elif case=='owner':r['ownership']=dict(r['ownership'],create_time=0)
    elif case=='checkpoint':r['generated_checkpoint_pin']=dict(r['generated_checkpoint_pin'],sha256='a'*64)
    elif case=='parameters':r['before']=dict(r['before'],extra=True)
    elif case=='saved_cl':r['before_cl']=dict(r['before_cl'],extra=True)
    elif case=='same_code':p['module_sha256']=r['module_pin']['sha256']
    elif case=='error_kind':r['issue']['type']='TimeoutError'
    elif case=='cleanup_error':r['cleanup_issue']={}
    elif case=='events':r['messages']['active']=True
    with pytest.raises(ValueError):m.zero_attempt_contract(r,p,l)


def test_previous_generic_adapter_route_is_rejected_by_actual_catalogue():
    # This is the exact previous resolver boundary, not a permissive fake QI.
    from scripts.sw_cam_comtypes import _interface_class
    r=failure();tlb=next(v['path']for v in r['live_pins']if v['path'].endswith('.tlb'))
    with pytest.raises(ValueError):_interface_class('ICWNCParam2',tlb)


@pytest.mark.parametrize('marker_exists',[False,True])
def test_original_no_dispatch_marker_must_remain_absent(tmp_path,monkeypatch,marker_exists):
    from types import SimpleNamespace
    marker=tmp_path/'original_once.json'
    if marker_exists:marker.write_text('pending')
    context=SimpleNamespace(loaded={'checkpoint_pins':[{}],'zero_attempt_original_marker':str(marker)})
    monkeypatch.setattr(m.generation.reopen.CheckpointContext,'files',lambda self:None)
    if marker_exists:
        with pytest.raises(ValueError):m.CorrectionContext.files(context)
        assert marker.read_text()=='pending'
    else:m.CorrectionContext.files(context)
