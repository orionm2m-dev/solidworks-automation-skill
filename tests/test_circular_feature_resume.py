from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
import json,os,hashlib
import pytest
from test_current_circular_pocket import fixture,sketch_state,feature_state,insert_state,saved_state
from scripts import sw_cam_current_circular_pocket as m
from scripts import sw_cam_current_circular_resume_evidence as h
from scripts import sw_cam_current_circular_context as context
from scripts import sw_cam_current_circular_delta as d
from scripts.sw_cam_mill_selected_plan_evidence import read_pin


def write(path,value):path.write_text(json.dumps(value,indent=2),encoding='utf-8');return read_pin(str(path),m._file_hash(path))[1]


@pytest.fixture
def history(tmp_path):
    v,loaded,before=fixture(tmp_path);binding=m.binding(v);sketch=sketch_state(before,v);feature=feature_state(sketch,v)
    for key in ('target_header','target_geometry'):feature[key]['bounds_native']=[9.98,9.97,2.]
    messages=dict(active=False,subscribed=True,disconnected=True,event_count=0)
    prep=dict(scope=m.SCOPE,action='prepare',status='review_required',phase='finished',binding=deepcopy(binding),may_apply=True,readback_verified=True,runtime_unchanged=True,mutation_attempted=False,before=deepcopy(before),confirm_before=deepcopy(before),messages=messages)
    pins={};pins['original_prepare']=write(tmp_path/'original_prepare.json',prep)
    original_apply=dict(v,action='apply',addin_clsid=loaded['addin_clsid'],receipt_path=str(tmp_path/'partial.json'),prepare_receipt_path=pins['original_prepare']['path'],prepare_receipt_sha256=pins['original_prepare']['sha256'])
    request=dict(requests=[dict(name='solidworks_cam_add_circular_pocket_plan',arguments=dict(params=original_apply))]);pins['original_request']=write(tmp_path/'original_request.json',request)
    names=['BOUND_PLANE','BOUND_CIRCLE'];marker=tmp_path/('current_circle_'+m._digest(binding)+'.json')
    actions=[dict(kind='CreateSketch',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_result=dict(created_names=names)),dict(kind='CreateMillFeature2',attempted=True,returned=True,readback_verified=False,native_dispatch_pending=False,native_result=dict(nonnull=True,return_type='pointer'))]
    partial=dict(scope=m.SCOPE,action='apply',status='uncertain',phase='finished',binding=deepcopy(binding),request_pin=dict(kind='canonical_binding',sha256=m._digest(binding)),source_before_sha256='a'*64,guard_failure=dict(code='CURRENT_CIRCULAR_GUARD_REJECTED',reason='Pocket axis/start/radius/depth readback differs'),mutation_attempted=True,marker_created=True,native_dispatch_pending=False,readback_verified=False,model_saved=False,save_readback_verified=False,source_update_verified=False,GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,automatic_rollback=False,automatic_replay=False,new_operations=[],authority_pin=deepcopy(loaded['pin']),addin_clsid=loaded['addin_clsid'],dispatch_marker_path=str(marker),actions=actions,new_feature_native_id=22,created_names=names,messages=messages,before=deepcopy(before),confirm_before=deepcopy(before),after_sketch=deepcopy(sketch),confirm_after_sketch=deepcopy(sketch),after_feature=deepcopy(feature),confirm_after_feature=deepcopy(feature))
    pins['partial']=write(tmp_path/'partial.json',partial);oldmarker=dict(scope=m.SCOPE,status='uncertain',automatic_replay=False,receipt_path=pins['partial']['path'],receipt_sha256=pins['partial']['sha256']);pins['old_marker']=write(marker,oldmarker)
    values=dict(v,continuation_mode='after_feature',receipt_path=str(tmp_path/'resume_prepare.json'))
    for key,prefix in h.PIN_FIELDS.items():values[prefix+'_path']=pins[key]['path'];values[prefix+'_sha256']=pins[key]['sha256']
    records=dict(partial=partial,prepare=prep,request=request,old_marker=oldmarker)
    return dict(v=values,original_v=v,loaded=loaded,records=records,pins=pins,before=before,sketch=sketch,feature=feature)


def verified(e):return h.validate_history(**e['records'],pins=e['pins'],loaded=e['loaded'])


def test_real_history_and_analytic_radius_not_getboundparams(history):
    e=history;out=verified(e);assert out['new_feature_native_id']==22 and out['restore']['new_operations']==[]
    proof=d.verify_geometry(e['feature'],e['original_v'],22);assert proof['observed_GetBoundParams']==[9.98,9.97,2.] and not proof['GetBoundParams_used_as_analytic_diameter']
    assert h.load_history(e['v'],e['loaded'])==out


@pytest.mark.parametrize('defect',['extra_action','unreturned','pending','already_verified','save','generated','changed_marker','changed_request','changed_prepare','old_path','new_operation','radius','request_radius','start','depth','bounds_nan','bounds_mismatch','dirty_history_mismatch'])
def test_history_rejects_any_other_boundary_or_geometry(history,defect):
    e=history;p=e['records']['partial']
    if defect=='extra_action':p['actions'].append(deepcopy(p['actions'][1]))
    elif defect=='unreturned':p['actions'][1]['returned']=False
    elif defect=='pending':p['native_dispatch_pending']=True
    elif defect=='already_verified':p['actions'][1]['readback_verified']=True
    elif defect=='save':p['model_saved']=True
    elif defect=='generated':p['GTP_attempted']=True
    elif defect=='changed_marker':e['records']['old_marker']['receipt_sha256']='b'*64
    elif defect=='changed_request':e['records']['request']['requests'][0]['arguments']['params']['depth_native']=3.
    elif defect=='changed_prepare':e['records']['prepare']['runtime_unchanged']=False
    elif defect=='old_path':p['after_feature']['operations'][2]['toolpath_record_counts']=[100]
    elif defect=='new_operation':p['new_operations']=[dict(native_id=13)]
    elif defect=='request_radius':p['binding']['sketch_spec']['profile']['radius_mm']=4.
    elif defect=='dirty_history_mismatch':p['confirm_after_feature']['document']['needs_save']=False
    else:
        for key in ('after_feature','confirm_after_feature'):
            state=p[key]
            if defect=='radius':state['target_geometry']['top_curves_native'][0]['radius_native']=4.
            elif defect=='start':state['target_header']['start_native'][2]=3.
            elif defect=='depth':state['target_header']['depth_native']=3.
            elif defect=='bounds_nan':state['target_header']['bounds_native'][0]=float('nan')
            elif defect=='bounds_mismatch':state['target_header']['bounds_native'][0]=9.
    with pytest.raises((ValueError,KeyError)):verified(e)


@pytest.fixture
def resume_env(history,monkeypatch,tmp_path):
    e=history;e.update(calls=[],bad=None,hook=None)
    monkeypatch.setattr(m,'load_inputs',lambda *a,**k:deepcopy(e['loaded']));monkeypatch.setattr(m.batch,'load_inputs',lambda *a,**k:dict(authority=dict(definition_mode='selected_continue')));monkeypatch.setattr(m,'preflight',lambda *a:dict(native_calls=0))
    class Session:
        def summary(self):return dict(active=False,subscribed=True,disconnected=True,event_count=0)
    class Context:
        def __init__(self,sw,clsid,tlb,v,loaded,report,persist,runtime_check,*,restore,continuation_pins):
            assert restore['new_operations']==[] and restore['new_feature_native_id']==22 and len(continuation_pins)==4
            self.state=deepcopy(e['feature']);self.report=report;self.persist=persist;self.created_names=list(restore['created_names']);self.source='a'*64;self.session=Session()
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def identity(self):return self.state['document']
        def boundary(self):
            if e.get('unsafe'):raise ValueError('event/runtime/source stop')
        def capture(self,label):
            self.boundary();state=deepcopy(self.state)
            if e['bad']==label:state['target_header']['bounds_native'][0]+=1.
            self.report[label]=state;self.report['captures'].append(label);self.persist();return state
        def create_sketch(self,*a):raise AssertionError('Creation replay forbidden')
        def create_feature(self,*a):raise AssertionError('Factory replay forbidden')
        def insert_rough(self,state,pending,returned):
            e['calls'].append('insert');pending();self.state=insert_state(self.state,e['original_v']);returned(dict(nonnull=True,return_type='pointer'))
            if e['hook']=='insert':e['unsafe']=True
            self.boundary();return 13
        def save(self,pending,returned):
            e['calls'].append('save');pending();self.source='b'*64;self.state=saved_state(self.state);returned(0)
            if e['hook']=='save':e['unsafe']=True
            self.boundary()
    def run(action):
        v=dict(e['v'],action=action,receipt_path=str(tmp_path/('resume_'+action+'.json')))
        if action=='apply':v.update(prepare_receipt_path=e['pins']['original_prepare']['path'],prepare_receipt_sha256=e['pins']['original_prepare']['sha256'])
        return m.run_current_circular_pocket(None,e['loaded']['addin_clsid'],'metadata',runtime_check=lambda:None,context_factory=Context,**v)
    e['run']=run;return e


def test_prepare_then_only_insert_save_and_no_replay(resume_env):
    e=resume_env;old={k:Path(p['path']).read_bytes() for k,p in e['pins'].items()}
    p=e['run']('prepare');assert p['readback_verified'] and p['continuation_verified'] and p['actions']==[],p
    r=e['run']('apply');assert r['action']=='resume_after_feature' and r['readback_verified'] and r['model_saved'],r
    assert [x['kind'] for x in r['actions']]==['InsertOperation','SaveActiveDocument'] and e['calls']==['insert','save']
    assert r['historical_after_feature']==e['records']['partial']['confirm_after_feature'] and not r['creation_replayed']
    assert all(Path(e['pins'][k]['path']).read_bytes()==value for k,value in old.items())
    assert e['run']('apply')['status']=='error' and e['calls']==['insert','save']


@pytest.mark.parametrize('bad',['before','confirm_before','after_insert'])
def test_changed_fresh_or_postinsert_state_stops_and_retains(resume_env,bad):
    e=resume_env
    if bad=='after_insert':assert e['run']('prepare')['readback_verified']
    e['bad']=bad;r=e['run']('apply' if bad=='after_insert' else 'prepare')
    assert not r['readback_verified'] and not r['model_saved'] and e['calls']==(['insert'] if bad=='after_insert' else [])
    assert r[bad]['target_header']['bounds_native'][0]!=e['feature']['target_header']['bounds_native'][0]


@pytest.mark.parametrize('hook',['insert','save'])
def test_returned_resume_action_stops_on_unsafe_boundary(resume_env,hook):
    e=resume_env;assert e['run']('prepare')['readback_verified'];e['hook']=hook;r=e['run']('apply')
    assert r['status']=='uncertain' and r['actions'][-1]['returned'] and not r['readback_verified']
    assert e['calls']==(['insert'] if hook=='insert' else ['insert','save'])


@pytest.mark.parametrize('recovering,current_dirty,accepted',[(True,True,True),(True,False,False),(False,True,False)])
def test_actual_context_dirty_admission_requires_exact_verified_history(history,monkeypatch,recovering,current_dirty,accepted):
    e=history;loaded=deepcopy(e['loaded']);loaded['binding'].update(process_id=123,expected_document_path=e['v']['expected_document_path'])
    if recovering:loaded['_feature_resume']=verified(e)
    monkeypatch.setattr(context.batch,'load_inputs',lambda *a,**k:dict(authority=dict(definition_mode='selected_continue')))
    app=object();calls=[];sw=SimpleNamespace(GetAddInObject=lambda clsid:(calls.append('addin') or SimpleNamespace(GetCWApp=app)))
    ctx=context.NativeCircularContext(sw,loaded['addin_clsid'],'metadata',e['v'],loaded,dict(),lambda:None,lambda:None,restore=verified(e)['restore'])
    observed=deepcopy(e['feature']['document']);observed['needs_save']=current_dirty;ctx.identity=lambda:deepcopy(observed)
    class Lock:
        def __enter__(self):return self
        def __exit__(self,*a):return False
    monkeypatch.setattr(context.batch,'solidworks_operation_lock',lambda **kw:Lock());monkeypatch.setattr(context.batch,'_typed',lambda raw,*a:raw);monkeypatch.setattr(context.batch,'CamMessageSession',lambda *a:Lock())
    if accepted:
        with ctx:pass
        assert calls==['addin'] and ctx.data['recovery']['expected_state']['document']['needs_save'] is True
    else:
        with pytest.raises(ValueError):ctx.__enter__()
        assert calls==[]


def test_optional_actual_feature_partial_history_only():
    name=os.environ.get('SW_CAM_TEST_CIRCULAR_FEATURE_APPLY_REQUEST')
    if not name:pytest.skip('Optional external original feature apply request unavailable')
    request=json.loads(Path(name).read_text(encoding='utf-8'));v=request['requests'][1]['arguments']['params'];partial=json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))
    loaded=m.load_inputs(v,v['addin_clsid']);values={k:value for k,value in dict(v,continuation_mode='after_feature').items() if k not in ('addin_clsid','expected_document_title','response_format')}
    paths={'partial':v['receipt_path'],'old_marker':partial['dispatch_marker_path'],'original_request':name,'original_prepare':v['prepare_receipt_path']}
    for key,prefix in h.PIN_FIELDS.items():values[prefix+'_path']=paths[key];values[prefix+'_sha256']=m._file_hash(paths[key])
    result=h.load_history(values,loaded);assert result['new_feature_native_id']==partial['new_feature_native_id'] and result['restore']['new_operations']==[]


def test_direct_apply_consumes_original_prepare_only_six_captures(resume_env):
    e=resume_env;r=e['run']('apply')
    assert r['readback_verified'] and r['action']=='resume_after_feature' and len(r['captures'])==6,r
    assert e['calls']==['insert','save'] and not Path(e['v']['receipt_path']).exists()


def test_different_new_prepare_is_not_resume_authority(resume_env,tmp_path):
    e=resume_env;assert e['run']('prepare')['readback_verified']
    v=dict(e['v'],action='apply',receipt_path=str(tmp_path/'wrong_apply.json'),prepare_receipt_path=e['v']['receipt_path'],prepare_receipt_sha256=m._file_hash(e['v']['receipt_path']))
    with pytest.raises(ValueError):m.validate(v,e['loaded']['addin_clsid'])
    assert e['calls']==[]
