from pathlib import Path
from copy import deepcopy
import ast,os,sys,importlib.util
import pytest
if os.environ.get('SOLIDWORKS_SKILL_ROOT'):sys.path.insert(0,os.environ['SOLIDWORKS_SKILL_ROOT'])
spec=importlib.util.spec_from_file_location('save_observer',Path(__file__).parents[1]/'scripts/sw_cam_save_error_observation.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def known():return dict(handle=123,title='Сообщение SOLIDWORKS CAM',**{'class':'#32770'},texts=[{'class':'Button','text':'ОК'},{'class':'Static','text':'Проблемы сохранения данных SOLIDWORKS CAM.\nВ файле сохранены последние успешно сохраненные данные SOLIDWORKS CAM.'}])
def identity(pid):return dict(process_id=pid,create_time=100.5,executable=r'C:\CAD\SLDWORKS.exe',alive=True)
def run(snapshot=(None,[],None),previous=None,reader=identity):
    calls=[]
    def windows(pid):calls.append(pid);return deepcopy(snapshot)
    r=m.observe(process_id=7,expected_creation_time=100.5,save_attempt_key='save-attempt',enumerate_windows=windows,read_identity=reader,previous_observation=previous)
    return r,calls


def test_exact_error_is_captured_with_raw_text_and_no_commands():
    r,calls=run((None,[known()],None));assert calls==[7] and r['status']=='save_error_observed' and r['save_error_observed'] and r['save_completion_must_be_rejected']
    assert r['save_error_evidence'][0]['texts'][1]['text']==known()['texts'][1]['text']
    for k in ('COM_called','window_commands_sent','focus_changed','dialog_dismissed','process_mutated','native_save_called','persistence_verified'):assert r[k] is False
@pytest.mark.parametrize('native_return',[0,False,None,1])
def test_save_error_remains_rejected_even_hresult_zero(native_return):
    r,_=run((None,[known()],None));a=m.assess_save_return(r,native_return);assert a['save_completion_must_be_rejected'] and not a['persistence_verified']
def test_error_latches_after_dialog_disappears():
    a,_=run((None,[known()],None));b,_=run(previous=a);assert b['save_error_observed'] and b['status']=='save_error_observed' and b['observation_count']==2 and b['save_error_evidence']==a['save_error_evidence']
def test_no_dialog_is_not_persistence_proof():
    r,_=run();assert r['status']=='no_save_error_observed' and r['persistence_unverified'] and not r['persistence_verified']
    a=m.assess_save_return(r,0);assert not a['save_completion_must_be_rejected'] and not a['persistence_verified'] and a['independent_disk_persistence_check_required']
def test_unknown_cam_message_requires_review_not_known_error_claim():
    d=known();d['texts'][1]['text']='Different CAM message';r,_=run((None,[d],None));assert r['status']=='unclassified_cam_dialog_observed' and not r['save_error_observed'] and r['save_completion_must_be_rejected']
def test_other_dialog_not_misattributed_as_cam_save_error():
    d=known();d['title']='SOLIDWORKS';r,_=run((None,[d],None));assert r['status']=='no_save_error_observed' and not r['save_error_observed']
def test_window_probe_error_cannot_report_clear():
    r,_=run((None,[],'enumeration failed'));assert r['status']=='inconclusive' and r['save_completion_must_be_rejected']
def test_child_text_error_cannot_report_clear():
    d=known();d['title']='SOLIDWORKS';d['text_error']='Timeout';r,_=run((None,[d],None));assert r['status']=='inconclusive'
@pytest.mark.parametrize('change',['pid','creation','executable','alive'])
def test_wrong_process_is_rejected_without_window_enumeration(change):
    def wrong(pid):
        p=identity(pid)
        if change=='pid':p['process_id']=8
        if change=='creation':p['create_time']=101.0
        if change=='executable':p['executable']='another.exe'
        if change=='alive':p['alive']=False
        return p
    r,calls=run(reader=wrong);assert r['status']=='inconclusive' and calls==[] and r['save_completion_must_be_rejected']
def test_pid_reuse_during_observation_requires_review():
    n=[0]
    def changed(pid):
        n[0]+=1;p=identity(pid)
        if n[0]==2:p['create_time']=200.5
        return p
    r,calls=run((None,[known()],None),reader=changed);assert r['status']=='inconclusive' and r['save_completion_must_be_rejected']
@pytest.mark.parametrize('field,value',[('process_id',8),('process_creation_time',200.5),('save_attempt_key','other')])
def test_previous_observation_must_be_same_attempt(field,value):
    r,_=run();r[field]=value
    with pytest.raises(ValueError):run(previous=r)
def test_bounded_dialog_text():
    d=known();d['texts'][0]['text']='x'*2001;r,_=run((None,[d],None));assert r['status']=='inconclusive'
def test_excessive_dialog_count_rejected():
    r,_=run((None,[known() for _ in range(33)],None));assert r['status']=='inconclusive'
def test_partial_known_message_not_assumed_complete_error():
    d=known();d['texts'][1]['text']=m.KNOWN_SAVE_ERROR[0];r,_=run((None,[d],None));assert not r['save_error_observed'] and r['status']=='unclassified_cam_dialog_observed'
def test_module_and_wrapper_do_not_call_UI_or_COM_control():
    root=Path(__file__).parents[1]
    trees=[ast.parse(Path(m.__file__).read_text(encoding='utf-8'))]
    staged=root/'SERVER_ADDITION.py'
    if staged.exists():
        trees.append(ast.parse(staged.read_text(encoding='utf-8')))
    else:
        server=ast.parse((root/'mcp-server/server.py').read_text(encoding='utf-8'))
        expected={'SolidWorksCamSaveErrorObservationInput','solidworks_cam_observe_save_errors'}
        selected=[node for node in server.body if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in expected]
        assert {node.name for node in selected}==expected
        trees.append(ast.Module(body=selected,type_ignores=[]))
    banned={'SendMessage','PostMessage','SetForegroundWindow','SetFocus','ShowWindow','connect_solidworks','solidworks_recover','_run_locked','_member','GetActiveObject','Dispatch','CreateObject'}
    for t in trees:
        names={x.func.id if isinstance(x.func,ast.Name) else x.func.attr for x in ast.walk(t) if isinstance(x,ast.Call) and isinstance(x.func,(ast.Name,ast.Attribute))}
        assert not names&banned

def test_after_identity_failure_retains_window_evidence_without_owned_error_claim():
    count=[0]
    def read_identity(pid):
        count[0]+=1
        if count[0]==2:raise OSError('process identity unavailable')
        return identity(pid)
    r,calls=run((None,[known()],None),reader=read_identity)
    assert calls==[7] and r['status']=='inconclusive' and r['save_completion_must_be_rejected']
    assert r['process_identity_before']==identity(7) and r['snapshot_owner_verified'] is False
    assert r['process_identity_unchanged'] is False and r['save_error_observed'] is False
    assert r['known_save_error_dialogs'][0]['handle']==123
    assert r['known_save_error_dialogs'][0]['texts'][1]['text']==known()['texts'][1]['text']
    assert 'process_identity_after' not in r and r['persistence_verified'] is False
