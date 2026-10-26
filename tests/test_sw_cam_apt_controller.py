"""APT-only assignment regressions, with no live CAD or runtime source edits."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_apt_controller as cam
from scripts import sw_cam_events as events


@pytest.fixture
def case(tmp_path,monkeypatch):
    part=tmp_path/'disposable.sldprt';part.write_bytes(b'isolated native copy')
    apt=tmp_path/'Posts'/'turn.aptctl';apt.parent.mkdir();apt.write_bytes(b'installed APT fixture')
    receipt=tmp_path/'receipt.json'
    document=dict(path=str(part),title=part.name,type=1,needs_save=False)
    state=dict(document=document,controller=(False,'',False),names=('turn','other'),
        inventory={'operations':[{'setup_index':0,'operation_index':0,'turn_operation_type':12,'toolpath_generated':True,'toolpath_record_counts':[34]}]},
        callbacks={},writes=[],op_id=47,params=(['program'],['9999'],True))
    status=dict(active=False,subscribed=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
    class Session:
        def __enter__(self):status.update(active=True,subscribed=True);return self
        def __exit__(self,*_):
            status.update(active=False,disconnected=True)
            if state['callbacks'].get('exit'):state['callbacks']['exit']()
        def summary(self):return deepcopy(status)
    op=object();setup=N(IGetEnumOperations=lambda:[op])
    doc=N(GetCWObjectID=lambda obj:(state['op_id'],True))
    def get(name,value):
        assert status['active'],'CAM read after Unadvise/before Advise'
        if state['callbacks'].get(name):state['callbacks'][name]()
        return value() if callable(value) else value
    def put(*args):
        durable=json.loads(receipt.read_text())
        assert durable['mutation_attempted'] and not durable['native_call_returned']
        assert status['active'] and args==(True,'turn',str(apt.parent)+os.sep)
        state['writes'].append(args);state['controller']=(True,'turn',True);state['document']['needs_save']=True
        if state['callbacks'].get('write'):state['callbacks']['write']()
        return state.get('setter_return',True)
    machine=N(MachType=3,IGetEnumOpSetups=lambda:[setup],
        GetPostProcessorList=Mock(side_effect=lambda isapt:get('list',lambda:state['names']) if isapt is True else pytest.fail('No NC catalogue')),
        GetController2=Mock(side_effect=lambda:get('controller',lambda:state['controller'])),
        GetControllerParameters=Mock(side_effect=lambda isapt,name:get('parameters',lambda:state['params']) if isapt is True and name=='turn' else pytest.fail('Exact APT name required')),
        SetController2=Mock(side_effect=put))
    sw=N(GetProcessID=lambda:731,GetAddInObject=lambda clsid:N(GetCWApp=lambda:object()))
    monkeypatch.setattr(cam,'document_snapshot',lambda sw:deepcopy(state['document']))
    monkeypatch.setattr(cam,'_typed',lambda obj,*args:obj)
    def context(sw,clsid,tlb,read):
        read(machine,'GetController2')
        return object(),doc,object(),machine,None
    monkeypatch.setattr(cam,'_context',context)
    monkeypatch.setattr(cam,'_inventory',lambda machine,tlb,read:deepcopy(state['inventory']))
    monkeypatch.setattr(cam,'_items',lambda value,tlb,read,limit=512:list(value) if len(value)<=limit else pytest.fail('collection bound'))
    monkeypatch.setattr(events,'CamMessageSession',lambda *args:Session())
    base=dict(process_id=731,expected_document_path=str(part),expected_source_sha256=cam._file_hash(part),qualification_only=True,
        acknowledge_disposable_copy=True,message_policy='vendor_default')
    assignment=dict(controller_name='turn',controller_file_path=str(apt),controller_file_sha256=cam._file_hash(apt),
        acknowledge_path_argument_qualification=True)
    def run(action='apply',**changes):
        args=base|{'action':action}
        if action!='inspect':args.update(assignment)
        if action=='apply':
            prep=cam.configure_apt_controller(sw,'clsid','tlb',**(base|assignment|{'action':'prepare'}))
            args.update(expected_state_sha256=prep.get('state_sha256','0'*64),receipt_path=str(receipt))
        return cam.configure_apt_controller(sw,'clsid','tlb',**(args|changes))
    return N(**locals())


def test_inspect_reads_only_actual_APT_catalogue_no_setter(case):
    out=case.run('inspect')
    assert out['status']=='ok' and out['before']['apt_names']==['turn','other']
    case.machine.SetController2.assert_not_called();case.machine.GetControllerParameters.assert_not_called()
    assert not case.receipt.exists() and out['messages']['disconnected']


def test_selected_inspect_preserves_parameter_values_and_shape(case):
    out=case.run('inspect',controller_name='turn')
    assert out['status']=='ok'
    assert out['before']['selected_parameters']['entries']==[dict(key='program',value='9999',python_type='str')]
    assert not out['actual_loaded_file_verified']


def test_prepare_creates_no_files_or_changes(case):
    out=case.run('prepare')
    assert out['status']=='ok' and out['apply_eligible'] and len(out['state_sha256'])==64
    assert not case.receipt.exists() and not case.state['writes']


def test_exact_one_APT_assignment_and_no_more_operations(case):
    out=case.run()
    assert out['status']=='review_required' and out['readback_verified']
    assert out['immediate_controller_readback']==dict(is_apt=True,name='turn',success=True)
    assert not any(out[k] for k in ('productionNC','postprocess_attempted','cnc_send_attempted','model_saved','GOP_attempted','GTP_attempted','actual_loaded_file_verified','path_argument_semantics_qualified'))
    assert len(case.state['writes'])==1 and json.loads(case.receipt.read_text())==out
    assert out['before']['operation_identities']==out['after']['operation_identities']
    assert case.part.read_bytes()==b'isolated native copy'


@pytest.mark.parametrize('change',['pid','dirty','source_hash','catalogue','candidate_hash','candidate_name','prepared_hash','ack','path_ack'])
def test_fail_before_assignment(case,change):
    args={}
    if change=='pid':args['process_id']=732
    if change=='dirty':case.state['document']['needs_save']=True
    if change=='source_hash':args['expected_source_sha256']='0'*64
    if change=='catalogue':case.state['names']=('another',)
    if change=='candidate_hash':args['controller_file_sha256']='0'*64
    if change=='candidate_name':args['controller_name']='other'
    if change=='prepared_hash':args['expected_state_sha256']='0'*64
    if change=='ack':args['acknowledge_disposable_copy']=False
    if change=='path_ack':args['acknowledge_path_argument_qualification']=False
    out=case.run(**args)
    assert out['status']=='error' and not out['mutation_attempted']
    case.machine.SetController2.assert_not_called()


@pytest.mark.parametrize('raw',[False,0,1,None,'true'])
def test_setter_requires_strict_true_and_never_retries(case,raw):
    case.state['setter_return']=raw
    out=case.run()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert out['native_call_returned'] and len(case.state['writes'])==1


@pytest.mark.parametrize('controller',[(False,'turn',True),(True,'other',True),(True,'turn',False)])
def test_native_fallback_controller_rejected(case,controller):
    case.state['callbacks']['write']=lambda:case.state.update(controller=controller)
    out=case.run()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert len(case.state['writes'])==1


@pytest.mark.parametrize('change',['operation','nativeid','source','candidate','parameters','catalogue','event'])
def test_unrequested_changes_stop_without_post_or_save(case,change):
    def callback():
        if change=='operation':case.state['inventory']['operations'][0]['toolpath_record_counts']=[35]
        if change=='nativeid':case.state['op_id']=48
        if change=='source':case.part.write_bytes(b'changed')
        if change=='candidate':case.apt.write_bytes(b'changed')
        if change=='parameters':case.state['params']=(['program'],['100'],True)
        if change=='catalogue':case.state['names']=('turn',)
        if change=='event':case.status['event_count']=1
    case.state['callbacks']['write']=callback
    out=case.run()
    assert out['status']=='uncertain' and not out['readback_verified'] and len(case.state['writes'])==1


def test_existing_receipt_preserved_and_no_repeat(case):
    case.receipt.write_text('old uncertain receipt')
    out=case.run()
    assert out['status']=='error' and case.receipt.read_text()=='old uncertain receipt'
    case.machine.SetController2.assert_not_called()


def test_already_selected_is_not_written(case):
    case.state['controller']=(True,'turn',True)
    out=case.run()
    assert out['status']=='error' and not out['apply_eligible']
    case.machine.SetController2.assert_not_called()


@pytest.mark.parametrize('raw',[('turn',True),['turn','turn'],'turn',[None],tuple(str(i) for i in range(257))])
def test_catalogue_invalid_shape_or_ambiguity(raw):
    with pytest.raises(ValueError):cam._catalogue(raw)


@pytest.mark.parametrize('raw',[(None,None,1),(['a'],[],True),(['a'],[object()],True),(['a'],[float('nan')],True)])
def test_parameter_contract_rejects_unknown_shapes(raw):
    with pytest.raises(ValueError):cam._parameters(raw)


def test_parameter_false_is_honest_unavailable_not_path_proof():
    assert cam._parameters((None,None,False))['success'] is False


@pytest.mark.parametrize('change',['document','source','event','disconnect'])
def test_postcleanup_failure_has_no_CAM_reads(case,change):
    calls=[]
    def end():
        calls.append(case.machine.GetController2.call_count)
        if change=='document':case.state['document']['title']='other'
        if change=='source':case.part.write_bytes(b'changed')
        if change=='event':case.status['event_count']=1
        if change=='disconnect':case.status['disconnected']=False
    # Apply uses a preceding prepare; install callback only inside setter.
    case.state['callbacks']['write']=lambda:case.state['callbacks'].update(exit=end)
    out=case.run()
    assert out['status']=='uncertain' and not out['readback_verified']
    assert case.machine.GetController2.call_count==calls[-1]


def test_final_receipt_failure_remains_uncertain(case,monkeypatch):
    write=cam._write_receipt
    def fail(path,value,**kw):
        if value['phase']=='finished':raise OSError('disk failure')
        return write(path,value,**kw)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    out=case.run()
    assert out['status']=='uncertain' and not out['readback_verified'] and 'receipt_write_error' in out


@pytest.fixture
def installed(case,tmp_path,monkeypatch):
    base=tmp_path/'ProgramData';directory=base/'SOLIDWORKS'/'SOLIDWORKS CAM 2026'/'Posts'/'Turn';directory.mkdir(parents=True)
    apt=directory/'turn.aptctl';apt.write_bytes(b'installed APT fixture')
    monkeypatch.setenv('PROGRAMDATA',str(base));case.sw.RevisionNumber='34.4.1'
    case.base['catalogue_source']='installed_files_qualification'
    case.assignment.update(controller_file_path=str(apt),controller_file_sha256=cam._file_hash(apt))
    case.machine.GetPostProcessorList.side_effect=AssertionError('Do not retry E_FAIL catalogue')
    case.machine.GetControllerParameters.side_effect=AssertionError('No speculative parameter getter')
    def write(*args):
        assert args==(True,'turn',str(directory)+os.sep)
        assert json.loads(case.receipt.read_text())['mutation_attempted'] and case.status['active']
        case.state['writes'].append(args);case.state['controller']=(True,'turn',True);case.state['document']['needs_save']=True
        if case.state['callbacks'].get('write'):case.state['callbacks']['write']()
        return case.state.get('setter_return',True)
    case.machine.SetController2.side_effect=write
    case.installed_directory=directory;case.installed_apt=apt
    return case


def test_installed_file_inspect_is_explicit_not_native_catalogue(installed):
    out=installed.run('inspect')
    assert out['status']=='ok' and out['before']['apt_names']==['turn']
    assert out['before']['installed_candidates']['entries'][0]['sha256']==cam._file_hash(installed.installed_apt)
    assert not out['catalogue_names_native_verified'] and not out['actual_loaded_file_verified']
    installed.machine.GetPostProcessorList.assert_not_called();installed.machine.GetControllerParameters.assert_not_called()
    installed.machine.SetController2.assert_not_called()


def test_installed_file_apply_one_setter_exact_native_name(installed):
    out=installed.run()
    assert out['status']=='review_required' and out['readback_verified']
    assert out['immediate_controller_readback']==dict(is_apt=True,name='turn',success=True)
    assert len(installed.state['writes'])==1 and not out['actual_loaded_file_verified']
    installed.machine.GetPostProcessorList.assert_not_called();installed.machine.GetControllerParameters.assert_not_called()


@pytest.mark.parametrize('mode',['outside','hash','wrongyear','renamed','changed_after_set','different_native_name'])
def test_installed_file_source_and_readback_guards(installed,mode):
    changes={}
    if mode=='outside':changes['controller_file_path']=str(installed.apt)
    elif mode=='hash':changes['controller_file_sha256']='0'*64
    elif mode=='wrongyear':installed.sw.RevisionNumber='33.1.0'
    elif mode=='renamed':changes['controller_name']='turn.aptctl'
    elif mode=='changed_after_set':installed.state['callbacks']['write']=lambda:installed.installed_apt.write_bytes(b'changed')
    else:installed.state['callbacks']['write']=lambda:installed.state.update(controller=(True,'fallback',True))
    out=installed.run(**changes)
    assert out['status'] in ('error','uncertain') and not out['readback_verified']
    assert len(installed.state['writes'])==(1 if mode in ('changed_after_set','different_native_name') else 0)
    installed.machine.GetPostProcessorList.assert_not_called();installed.machine.GetControllerParameters.assert_not_called()


def test_native_catalogue_failure_does_not_switch_source_or_retry(case):
    case.machine.GetPostProcessorList.side_effect=OSError('native E_FAIL')
    out=case.run('inspect')
    assert out['status']=='error' and out['catalogue_source']=='native'
    case.machine.GetPostProcessorList.assert_called_once_with(True)
    case.machine.GetControllerParameters.assert_not_called();case.machine.SetController2.assert_not_called()


def test_installed_catalogue_ignores_non_APT_and_binds_all_APT_hashes(installed):
    (installed.installed_directory/'not.nc').write_text('not a candidate')
    (installed.installed_directory/'other.aptctl').write_bytes(b'other installed candidate')
    out=installed.run('inspect')
    assert out['before']['apt_names']==['other','turn']
    assert all(len(x['sha256'])==64 for x in out['before']['installed_candidates']['entries'])


@pytest.mark.parametrize("kind",["directory_with_trailing_separator","exact_aptctl_file_path"])
def test_explicit_path_kind_is_bound_and_exact_single_argument(installed,kind):
    installed.base["path_argument_kind"]=kind
    expected=str(installed.installed_apt) if kind=="exact_aptctl_file_path" else str(installed.installed_directory)+os.sep
    def write(*args):
        assert args==(True,"turn",expected)
        evidence=json.loads(installed.receipt.read_text())
        assert evidence["before"]["candidate_file"]["path_argument_kind"]==kind
        assert evidence["before"]["candidate_file"]["native_path_argument"]==expected
        installed.state["writes"].append(args)
        installed.state["controller"]=(True,"turn",True);installed.state["document"]["needs_save"]=True
        return True
    installed.machine.SetController2.side_effect=write
    out=installed.run()
    assert out["status"]=="review_required" and out["readback_verified"]
    assert out["path_argument_kind"]==kind and not out["path_argument_semantics_qualified"]
    assert len(installed.state["writes"])==1
    installed.machine.GetPostProcessorList.assert_not_called();installed.machine.GetControllerParameters.assert_not_called()


def test_changing_path_kind_requires_new_prepare_without_dispatch(installed):
    prepare=installed.run("prepare")
    assert prepare["status"]=="ok"
    result=installed.run(path_argument_kind="exact_aptctl_file_path",expected_state_sha256=prepare["state_sha256"])
    assert result["status"]=="error" and not result["mutation_attempted"]
    installed.machine.SetController2.assert_not_called()


@pytest.mark.parametrize("kind",[True,1,None,"full_file_path","auto","directory_with_trailing_separator_qualification_only"])
def test_path_kind_never_guessed_or_aliased(installed,kind):
    assert installed.run("prepare",path_argument_kind=kind)["status"]=="error"
    installed.machine.SetController2.assert_not_called()


def test_exact_file_mode_requires_installed_catalogue_and_not_inspect(case,installed):
    installed.base["catalogue_source"]="native"
    result=installed.run("prepare",path_argument_kind="exact_aptctl_file_path")
    assert result["status"]=="error"
    installed.base["catalogue_source"]="installed_files_qualification"
    assert installed.run("inspect",path_argument_kind="exact_aptctl_file_path")["status"]=="error"
    installed.machine.SetController2.assert_not_called()


def test_false_partial_controller_change_has_full_diagnostic_but_no_success(installed):
    installed.state["setter_return"]=False
    installed.state["callbacks"]["write"]=lambda:installed.state.update(controller=(True,"",False))
    out=installed.run()
    assert out["status"]=="uncertain" and not out["readback_verified"] and not out["controller_assignment_verified"]
    assert not out["apply_eligible"] and out["native_result_raw"] is False
    assert out["immediate_controller_readback"]==dict(is_apt=True,name="",success=False)
    assert out["after_false"]["capture_complete"] and out["false_return_diagnostic_complete"]
    assert out["after_false"]["current_controller"]==out["immediate_controller_readback"]
    assert out["after_false_inventory_unchanged"] and out["post_cleanup_document_file_verified"]
    assert not out["postprocess_attempted"] and out["messages"]["disconnected"]
    assert len(installed.state["writes"])==1 and json.loads(installed.receipt.read_text())==out
    installed.machine.GetPostProcessorList.assert_not_called();installed.machine.GetControllerParameters.assert_not_called()


def test_false_even_exact_name_readback_is_not_assignment_success(case):
    case.state["setter_return"]=False
    out=case.run()
    assert out["immediate_controller_readback"]==dict(is_apt=True,name="turn",success=True)
    assert out["status"]=="uncertain" and not out["controller_assignment_verified"] and not out["readback_verified"]


def test_false_event_disallows_any_diagnostic_native_read(installed):
    installed.state["setter_return"]=False;seen=[]
    def event():
        seen.append(installed.machine.GetController2.call_count);installed.status["event_count"]=1
    installed.state["callbacks"]["write"]=event
    out=installed.run()
    assert out["status"]=="uncertain" and not out["false_return_diagnostic_attempted"]
    assert installed.machine.GetController2.call_count==seen[0] and "after_false" not in out
    installed.machine.SetController2.assert_called_once()


@pytest.mark.parametrize("raw",[0,1,None,"false"])
def test_nonboolean_false_like_result_never_starts_diagnostic(installed,raw):
    installed.state["setter_return"]=raw;seen=[]
    installed.state["callbacks"]["write"]=lambda:seen.append(installed.machine.GetController2.call_count)
    out=installed.run()
    assert out["status"]=="uncertain" and not out["false_return_diagnostic_attempted"]
    assert installed.machine.GetController2.call_count==seen[0]
    installed.machine.SetController2.assert_called_once()


def test_false_first_diagnostic_native_error_has_no_retry(installed):
    installed.state["setter_return"]=False
    def arm():installed.machine.GetController2.side_effect=RuntimeError("readback failed")
    installed.state["callbacks"]["write"]=arm
    out=installed.run()
    assert out["status"]=="uncertain" and out["false_return_diagnostic_attempted"]
    assert not out["false_return_diagnostic_complete"] and "after_false" not in out
    assert out["failed_phase"]=="GetController2"
    installed.machine.SetController2.assert_called_once()


def test_false_later_capture_failure_preserves_immediate_readback_and_partial_document(installed,monkeypatch):
    installed.state["setter_return"]=False;original=cam._inventory
    def inventory(*args):
        if installed.state["writes"]:raise RuntimeError("capture inventory failed")
        return original(*args)
    monkeypatch.setattr(cam,"_inventory",inventory)
    out=installed.run()
    assert out["status"]=="uncertain" and "immediate_controller_readback" in out
    assert not out["after_false"]["capture_complete"] and "document" in out["after_false"]
    installed.machine.SetController2.assert_called_once()


def test_false_unexpected_inventory_change_is_reported_without_claiming_success(installed):
    installed.state["setter_return"]=False
    installed.state["callbacks"]["write"]=lambda:installed.state["inventory"]["operations"][0].update(toolpath_record_counts=[35])
    out=installed.run()
    assert out["false_return_diagnostic_complete"] and not out["after_false_inventory_unchanged"]
    assert out["status"]=="uncertain" and not out["readback_verified"]
    installed.machine.SetController2.assert_called_once()


@pytest.mark.parametrize("name_mode,name",[("stem","turn"),("filename_with_extension","turn.aptctl")])
@pytest.mark.parametrize("path_kind",["directory_with_trailing_separator","exact_aptctl_file_path"])
def test_explicit_name_and_path_form_single_exact_candidate(installed,name_mode,name,path_kind):
    installed.base.update(name_mode=name_mode,path_argument_kind=path_kind)
    installed.assignment["controller_name"]=name
    expected=str(installed.installed_apt) if path_kind=="exact_aptctl_file_path" else str(installed.installed_directory)+os.sep
    def write(*args):
        assert args==(True,name,expected)
        before=json.loads(installed.receipt.read_text())["before"]
        assert before["name_mode"]==name_mode and before["selected_name"]==name
        assert before["apt_names"]==[name] and before["candidate_file"]["sha256"]==cam._file_hash(installed.installed_apt)
        installed.state["writes"].append(args);installed.state["controller"]=(True,name,True)
        installed.state["document"]["needs_save"]=True
        return True
    installed.machine.SetController2.side_effect=write
    out=installed.run()
    assert out["status"]=="review_required" and out["readback_verified"] and len(installed.state["writes"])==1
    assert out["immediate_controller_readback"]["name"]==name
    assert not out["actual_loaded_file_verified"] and not out["catalogue_names_native_verified"]
    installed.machine.GetPostProcessorList.assert_not_called();installed.machine.GetControllerParameters.assert_not_called()


def test_filename_inspect_lists_only_exact_filenames_without_setter(installed):
    result=installed.run("inspect",name_mode="filename_with_extension")
    assert result["status"]=="ok" and result["before"]["apt_names"]==["turn.aptctl"]
    assert result["before"]["installed_candidates"]["name_mode"]=="filename_with_extension"
    installed.machine.SetController2.assert_not_called()


@pytest.mark.parametrize("mode,name",[("filename_with_extension","turn"),("stem","turn.aptctl"),
    ("filename_with_extension","TURN.aptctl"),("filename_with_extension","turn.ctl")])
def test_name_mode_requires_exact_installed_spelling_no_autocorrection(installed,mode,name):
    result=installed.run("prepare",name_mode=mode,controller_name=name)
    assert result["status"]=="error" and not result["mutation_attempted"]
    installed.machine.SetController2.assert_not_called()


@pytest.mark.parametrize("mode",[True,1,None,"filename","auto","full_file_path"])
def test_unknown_name_mode_rejected_before_native_calls(installed,mode):
    result=installed.run("prepare",name_mode=mode)
    assert result["status"]=="error";installed.machine.SetController2.assert_not_called()
    installed.machine.GetController2.assert_not_called()


def test_filename_mode_rejects_native_catalogue_without_guessing(case):
    result=case.run("prepare",name_mode="filename_with_extension",controller_name="turn.aptctl")
    assert result["status"]=="error"
    case.machine.GetPostProcessorList.assert_not_called();case.machine.SetController2.assert_not_called()


def test_name_mode_change_requires_fresh_state_hash(installed):
    prepare=installed.run("prepare")
    result=installed.run(name_mode="filename_with_extension",controller_name="turn.aptctl",expected_state_sha256=prepare["state_sha256"])
    assert result["status"]=="error" and not result["mutation_attempted"]
    installed.machine.SetController2.assert_not_called()


def test_filename_false_keeps_partial_state_and_no_stem_or_path_retry(installed):
    installed.base["name_mode"]="filename_with_extension";installed.assignment["controller_name"]="turn.aptctl"
    def write(*args):
        assert args==(True,"turn.aptctl",str(installed.installed_directory)+os.sep)
        installed.state["writes"].append(args);installed.state["controller"]=(True,"",False)
        installed.state["document"]["needs_save"]=True
        return False
    installed.machine.SetController2.side_effect=write
    result=installed.run()
    assert result["status"]=="uncertain" and result["false_return_diagnostic_complete"]
    assert result["after_false"]["selected_name"]=="turn.aptctl"
    assert result["after_false"]["current_controller"]==dict(is_apt=True,name="",success=False)
    assert not result["readback_verified"] and not result["postprocess_attempted"] and len(installed.state["writes"])==1
