from copy import deepcopy
from pathlib import Path
import hashlib,json
import pytest
from scripts import sw_cam_current_saved_parameter_batch as m
from test_current_saved_parameter_fields import fixture,assigned,actual_change


def alias(row,value):
    row['rough']['depth']['DepthAllow']['raw']=value
    obs=next(x for x in row['rough_diagnostic']['observations'] if x['member']=='DepthAllow')
    obs['raw_observation']['raw']=value;obs['value']['raw']=value

@pytest.fixture
def recovery(tmp_path,monkeypatch):
    old,plan,candidate=fixture();old['document']=dict(path=str(tmp_path/'part.sldprt'),type=1,title='part',needs_save=False);old['capture_complete']=True
    actual=assigned(old,candidate)
    for change in plan['rows'][0]['fields']:actual_change(actual['operation_parameters'][0],change['field'],change['new'])
    alias(actual['operation_parameters'][0],.2)
    baseline=deepcopy(old);baseline.pop('parameter_batch')
    partial=tmp_path/'partial.json';partial.write_text('{"immutable":"original partial"}')
    oldmarker=tmp_path/'old_once.json';oldmarker.write_text('{"immutable":"old claim"}')
    original={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in (partial,oldmarker)}
    pins={name:dict(path=str(partial if name!='old_marker' else oldmarker),sha256=original[str(partial if name!='old_marker' else oldmarker)]) for name in ('partial','old_marker','original_request','original_prepare')}
    data=dict(baseline=baseline,plan=plan,pins={},authority=dict(definition_mode='selected_continue'),recovery=dict(expected_state=deepcopy(actual),historical_before=old,consumer_ids=[10]),recovery_pins=pins)
    marker=tmp_path/'recovery_once.json';calls=[];control=dict(failure=None,hostflag=False)
    v={k:None for k in m.READ_KEYS+m.EXTRA};v.update({k:'pinned' for k in m.RECOVERY_KEYS});v.update(process_id=7,expected_source_sha256='a'*64,expected_feature_native_id=20,expected_document_path=old['document']['path'],candidate_tool_native_id=32,expected_candidate_consumer_ids=[],configuration_mode='current_saved')
    def validate(values,clsid=None):
        if marker.exists():raise ValueError('No recovery replay')
        inputs=deepcopy(data);inputs['recovery']['expected_state']['document']['needs_save']=control['hostflag']
        if values['action']=='recover_save':inputs['prepare']=json.loads((tmp_path/'prepare_recover_save.json').read_text())
        return marker,inputs
    monkeypatch.setattr(m,'validate',validate)
    monkeypatch.setattr(m.current,'_abi',lambda _:None);monkeypatch.setattr(m.parameters,'preflight',lambda *_:None);monkeypatch.setattr(m.fields,'preflight',lambda _:None);monkeypatch.setattr(m.append,'save_abi',lambda _:None)
    class Session:
        def summary(self):return dict(active=False,subscribed=True,disconnected=True,event_count=0)
    class Context:
        def __init__(self,sw,clsid,tlb,values,inputs,report,persist,runtime):
            self.state=deepcopy(actual);self.state['document']['needs_save']=control['hostflag'];self.report=report;self.persist=persist;self.source='a'*64;self.session=Session()
            if control['failure']=='fresh_nc':self.state['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']=101.
            if control['failure']=='fresh_alias':alias(self.state['operation_parameters'][0],.25)
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def boundary(self):
            if control['failure']=='runtime_before_save' and self.report.get('marker_created'):raise ValueError('runtime changed')
            return deepcopy(self.state['document'])
        def identity(self):return deepcopy(self.state['document'])
        def capture(self,label,consumers):
            calls.append(label);assert consumers==[10];self.boundary();out=deepcopy(self.state);self.report[label]=out;self.report['captures'].append(label);self.persist();return out
        def set_tool(self,*a):raise AssertionError('SetTool replay prohibited')
        def set_field(self,*a):raise AssertionError('Field replay prohibited')
        def save(self,pending,returned):
            pending();self.boundary();calls.append('Save');value=None if control['failure']=='save_unknown' else 0;returned(value)
            if value is None:raise ValueError('Unknown Save outcome')
            if control['failure']=='save_event':raise ValueError('Event after native Save returned')
            self.source='b'*64;self.report['source_after_sha256']=self.source;self.state['document']['needs_save']=False
            if control['failure']=='saved_delta':self.state['operations'][2]['toolpath_record_counts']=[100]
            self.persist()
    def run(action='prepare_recover_save'):
        values=dict(v,action=action,save_after_verified=action=='recover_save',receipt_path=str(tmp_path/(action+'.json')))
        result=m.run_current_saved_configuration(None,'id','tlb',runtime_check=lambda:None,_context_factory=Context,**values);m.runtime_finish(result)
        assert original=={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in original}
        return result
    return dict(run=run,calls=calls,control=control,data=data,marker=marker,path=tmp_path)

@pytest.mark.parametrize('hostflag',[False,True])
def test_recovery_two_fresh_then_only_save_preserves_old_evidence(recovery,hostflag):
    e=recovery;e['control']['hostflag']=hostflag;prep=e['run']();assert prep['readback_verified'] and prep['recovery_verified'] and not prep['actions'] and not e['marker'].exists()
    result=e['run']('recover_save');assert result['status']=='review_required',result.get('issue')
    assert result['action']=='recover_save' and result['setters_replayed'] is False
    assert result['recovery_verified'] and result['parameter_delta_verified'] and result['model_saved']
    assert [a['kind'] for a in result['actions']]==['SaveActiveDocument'] and e['calls'].count('Save')==1
    assert result['captures']==['before','confirm_before','saved','confirm_saved']
    assert result['after_capture_references']==['before','confirm_before'] and result['after']==result['before']
    assert result['saved']==result['confirm_saved'];assert result['historical_before']==e['data']['recovery']['historical_before']
    again=e['run']('recover_save');assert again['status']=='error' and e['calls'].count('Save')==1

@pytest.mark.parametrize('failure',['fresh_nc','fresh_alias'])
def test_unexpected_fresh_state_stops_before_save_claim(recovery,failure):
    e=recovery;e['control']['failure']=failure;result=e['run']()
    assert result['status']=='error' and not result['readback_verified'] and not e['marker'].exists() and 'Save' not in e['calls']

@pytest.mark.parametrize('failure',['runtime_before_save','save_unknown','save_event','saved_delta'])
def test_recovery_stops_unknown_or_drift_and_keeps_durable_actual(recovery,failure):
    e=recovery;assert e['run']()['readback_verified'];e['control']['failure']=failure;result=e['run']('recover_save')
    assert result['status'] in ('error','uncertain') and not result['model_saved'] and e['marker'].exists()
    durable=json.loads((e['path']/'recover_save.json').read_text())
    if failure=='runtime_before_save':assert 'Save' not in e['calls']
    else:assert durable['save_call_returned'] and e['calls'].count('Save')==1
    if failure=='saved_delta':assert durable['saved']['operations'][2]['toolpath_record_counts']==[100]


def test_observed_floor_alias_optin_does_not_relax_normal_guard():
    before,plan,candidate=fixture();after=assigned(before,candidate)
    for change in plan['rows'][0]['fields']:actual_change(after['operation_parameters'][0],change['field'],change['new'])
    alias(after['operation_parameters'][0],.2)
    with pytest.raises(ValueError):m.fields.verify_final(before,after,plan,{32:candidate})
    m.fields.verify_final(before,after,plan,{32:candidate},observed_floor_alias=True)
    alias(after['operation_parameters'][0],.25)
    with pytest.raises(ValueError):m.fields.verify_final(before,after,plan,{32:candidate},observed_floor_alias=True)
