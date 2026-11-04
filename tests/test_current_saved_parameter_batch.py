from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_current_saved_parameter_batch as m
from test_current_saved_parameter_fields import fixture,assigned,actual_change


@pytest.fixture
def harness(tmp_path,monkeypatch):
    state,recipe,candidate=fixture();state['document']=dict(path=str(tmp_path/'part.sldprt'),title='part',type=1,needs_save=False)
    state['capture_complete']=True
    data=dict(baseline=deepcopy(state),authority=dict(definition_mode='selected_continue'),plan=recipe,pins={})
    data['baseline'].pop('parameter_batch')
    v={k:None for k in m.READ_KEYS+m.EXTRA}
    v.update(process_id=7,expected_source_sha256='a'*64,expected_feature_native_id=20,expected_document_path=state['document']['path'],parameter_operation_native_ids=[10,11],candidate_tool_native_id=32,expected_candidate_consumer_ids=[],configuration_mode='current_saved',action='prepare',save_after_verified=False,receipt_path=str(tmp_path/'prepare.json'))
    marker=tmp_path/'once.json';calls=[];control=dict(failure=None,hostflag=False,drift=False)
    def validate(values,clsid=None):
        if marker.exists():raise ValueError('Prior attempt, no replay')
        if Path(values['receipt_path']).exists():raise ValueError('Receipt exists')
        current=deepcopy(data)
        if values['action']=='apply':current['prepare']=json.loads((tmp_path/'prepare.json').read_text())
        return marker,current
    monkeypatch.setattr(m,'validate',validate)
    monkeypatch.setattr(m.current,'_abi',lambda _:calls.append('abi'))
    monkeypatch.setattr(m.parameters,'preflight',lambda *_:calls.append('parameter_preflight'))
    monkeypatch.setattr(m.fields,'preflight',lambda _:calls.append('field_preflight'))
    monkeypatch.setattr(m.append,'save_abi',lambda _:calls.append('save_preflight'))
    def runtime():
        if control['drift']:raise ValueError('runtime drift')
    class Session:
        def summary(self):return dict(active=False,subscribed=True,disconnected=True,event_count=0)
    class Context:
        def __init__(self,sw,clsid,tlb,values,inputs,report,persist,runtime_check):
            self.state=deepcopy(state);self.v=values;self.report=report;self.persist=persist;self.source=values['expected_source_sha256'];self.session=Session();self.runtime=runtime_check
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def boundary(self):self.runtime();return deepcopy(self.state['document'])
        def identity(self):return deepcopy(self.state['document'])
        def capture(self,label,consumers):
            calls.append(label);self.boundary();assert consumers==self.state['parameter_batch']['candidate_consumer_ids']
            result=deepcopy(self.state);self.report[label]=result;self.report['captures'].append(label);self.persist()
            if control['failure']=='capture_partial' and label.startswith('after_tool'):
                result['parameter_batch']['read_complete']=False;self.persist();raise ValueError('partial capture')
            return result
        def set_tool(self,row,tool,pending,returned):
            pending();calls.append('SetTool');self.state=assigned(self.state,tool);self.state['document']['needs_save']=control['hostflag'];returned(0)
            if control['failure']=='tool_nc':self.state['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']=101.
            if control['failure']=='tool_rough':actual_change(self.state['operation_parameters'][0],'side_allowance',.7)
            if control['failure']=='tool_event':raise ValueError('event after SetTool returned')
            if control['failure']=='tool_runtime':control['drift']=True
        def set_field(self,row,change,pending,returned):
            assert m.fields.equal(m.fields.field_value(self.state['operation_parameters'][0],change['field']),change['expected'])
            pending();calls.append('field:'+change['field']);actual_change(self.state['operation_parameters'][0],change['field'],change['new']);returned(0)
            if control['failure']=='field_event':raise ValueError('event after field returned')
            if control['failure']=='field_runtime':control['drift']=True
            if control['failure']=='unexpected_alias':self.state['operation_parameters'][0]['rough']['depth']['DepthAllow']['raw']=.2
            if control['failure']=='old_path':self.state['operations'][2]['toolpath_record_counts']=[100]
        def read_field(self,row,change,diagnostic):
            value=m.fields.field_value(self.state['operation_parameters'][0],change['field']);diagnostic.update(returned=True,raw=value);self.persist();self.boundary();return value
        def save(self,pending,returned):
            pending();calls.append('Save');self.state['document']['needs_save']=False;returned(0)
            if control['failure']=='save_event':raise ValueError('event after Save returned')
            if control['failure']=='save_runtime':control['drift']=True;self.boundary()
            self.source='b'*64;self.report['source_after_sha256']=self.source;self.persist()
    def run(action='prepare'):
        values=dict(v,action=action,save_after_verified=action=='apply',receipt_path=str(tmp_path/(action+'.json')))
        result=m.run_current_saved_configuration(None,'id','tlb',runtime_check=runtime,_context_factory=Context,**values)
        return m.runtime_finish(result)
    return run,calls,control,tmp_path,data,marker


def prepare(h):
    run,calls,control,path,data,marker=h
    result=run();assert result['status']=='review_required' and result['readback_verified']
    assert not marker.exists() and not any(x in calls for x in ('SetTool','Save'))
    return result

@pytest.mark.parametrize('hostflag',[False,True])
def test_actual_shaped_tool_fields_checked_save_two_host_flags(harness,hostflag):
    prepare(harness);run,calls,control,path,data,marker=harness;control['hostflag']=hostflag
    result=run('apply');assert result['status']=='review_required',result.get('issue')
    assert result['parameter_delta_verified'] and result['model_saved'] and result['save_readback_verified']
    assert result['saved']==result['confirm_saved'] and result['saved_file_sha256']=='b'*64
    assert calls.count('SetTool')==1 and calls.count('Save')==1
    assert len([x for x in calls if x.startswith('field:')])==3
    assert not any(x.startswith('after_field') for x in calls)
    assert result['saved']['operations'][2]['toolpath_record_counts']==[99]
    assert result['saved']['operation_parameters'][1]==data['baseline']['operation_parameters'][1]
    assert json.loads((path/'apply.json').read_text())['saved']==result['saved']
    assert marker.exists()
    # Fresh output paths cannot bypass the source/feature claim.
    replay=run('apply');assert replay['status']=='error' and calls.count('SetTool')==1

@pytest.mark.parametrize('failure',['tool_nc','tool_rough','tool_event','tool_runtime','capture_partial'])
def test_tool_barrier_failure_preserves_actual_return_and_blocks_fields(harness,failure):
    prepare(harness);run,calls,control,path,_,marker=harness;control['failure']=failure
    result=run('apply');assert result['status']=='uncertain' and not result['model_saved']
    assert not any(x.startswith('field:') for x in calls) and 'Save' not in calls
    assert result['actions'][0]['attempted'] and result['actions'][0]['returned']
    durable=json.loads((path/'apply.json').read_text());assert durable['actions'][0]['return_value']==0 and marker.exists()
    if failure=='tool_nc':assert durable['after_tool_10']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']==101.
    if failure=='capture_partial':assert durable['after_tool_10']['parameter_batch']['read_complete'] is False

@pytest.mark.parametrize('failure',['field_event','field_runtime','unexpected_alias','old_path'])
def test_field_failure_keeps_outcome_and_no_save(harness,failure):
    prepare(harness);run,calls,control,path,_,_=harness;control['failure']=failure
    result=run('apply');assert result['status']=='uncertain' and not result['parameter_delta_verified'] and 'Save' not in calls
    assert result['actions'][1]['returned'] and json.loads((path/'apply.json').read_text())['actions'][1]['return_value']==0
    if failure in ('field_event','field_runtime'):assert len([x for x in calls if x.startswith('field:')])==1

@pytest.mark.parametrize('failure',['save_event','save_runtime'])
def test_save_returned_before_late_failure_is_durable_no_repeat(harness,failure):
    prepare(harness);run,calls,control,path,_,_=harness;control['failure']=failure
    result=run('apply');assert result['status']=='uncertain' and result['save_call_returned'] and result['save_hresult']==0
    assert not result['save_readback_verified'] and not result['source_update_verified'] and calls.count('Save')==1
    assert json.loads((path/'apply.json').read_text())['save_call_returned'] is True


def test_preflight_missing_interface_stops_before_bootstrap(harness,monkeypatch):
    run,calls,_,_,_,_=harness
    def missing(_):raise ValueError('Unmapped NC interface')
    monkeypatch.setattr(m.fields,'preflight',missing)
    result=run();assert result['status']=='error' and 'before' not in calls and not result['mutation_attempted']


def test_runtime_changed_during_prepare_prevents_claim(harness):
    prepare(harness);run,calls,control,_,_,marker=harness;control['drift']=True
    result=run('apply');assert result['status']=='error' and not marker.exists() and 'SetTool' not in calls


def test_post_wrapper_drift_preserves_completed_evidence_and_revokes(harness):
    prepare(harness);run,calls,_,path,_,_=harness;result=run('apply')
    assert result['model_saved'];m.runtime_finish(result,ValueError('runtime changed after core'))
    assert result['status']=='uncertain' and not result['model_saved'] and result['saved']==result['confirm_saved']
    durable=json.loads((path/'apply.json').read_text());assert durable['save_call_returned'] and durable['runtime_unchanged'] is False
    assert calls.count('Save')==1


def test_native_capture_read_retains_raw_before_post_event_failure(monkeypatch):
    ctx=m.NativeBatchContext.__new__(m.NativeBatchContext);ctx.report={'native_read_count':0};ctx.persist=lambda:None
    seen=[]
    def check():
        seen.append(1)
        if len(seen)>1:raise ValueError('post getter event')
    ctx.check=check;monkeypatch.setattr(m,'_member',lambda *a:123.5)
    with pytest.raises(ValueError):ctx.read(object(),'XYFeed')
    assert ctx.report['last_returned_read']['returned'] and ctx.report['last_returned_read']['raw']['raw']==123.5
