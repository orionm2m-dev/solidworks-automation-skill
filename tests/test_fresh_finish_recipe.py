"""Synthetic recipe protocol tests; no CAD/native calls."""
from copy import deepcopy
import importlib.util,json,os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_fresh_finish_recipe as m
spec=importlib.util.spec_from_file_location('fresh_insert_fixture',RUNTIME/'tests/test_fresh_finish_insert.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)


def values():
    result=dict(side_allowance=0.,final_side=0.,spring_passes=0,first_depth=[.3,False],max_depth=[.3,False],
        final_depth=0.,side_step=[.25,False],previous_allowance=.5,override_previous=True,perimeter=2,apply_all=True,out_independent=False)
    for side in ('lead_in','lead_out'):
        result.update({side+'_angle':90.,side+'_radius':[.5,False,0.],side+'_straight':[0.,False,0.],side+'_overlap':[0.,False,0.]})
    return result


class Fake:
    def __init__(self,loaded,p,r,source):
        self.loaded,self.p,self.report,self.source=loaded,p,r,source
        self.current_state=deepcopy(loaded['state']);self.calls=[];self.fault=None;self.empty=False;self.save_return=0;self.generated=False
        self.protected=dict(gouge_check=False,single_depth=False,depth_process=1,rest_method=0,add_tool_radius=False,lead_types=[4,4],compensation=[1,0])
        self.fields=values();self.fields.update(side_allowance=1.,spring_passes=2,first_depth=[1.,False],max_depth=[1.,False],final_depth=1.,final_side=1.,side_step=[10.,False],previous_allowance=1.,override_previous=False,perimeter=1,apply_all=False,out_independent=True)
        self.defaults=deepcopy(loaded['fresh_finish_definition']['defaults']);self.target_tool=deepcopy(loaded['state']['operations'][-1]['assigned_tool'])
    def call(self,name):
        self.calls.append(name)
        if self.fault==name:raise RuntimeError('injected '+name)
    def start(self):self.call('start')
    def boundary(self):self.call('boundary')
    def refresh_dirty(self):self.call('refresh_dirty')
    def snapshot(self,label):
        self.call('snapshot:'+label);route=m.insert.base.expected_route(self.loaded)
        route['operations'][-1].update(assigned_tool=deepcopy(self.target_tool),toolpath_generated=self.generated,toolpath_record_counts=[300] if self.generated else [])
        if self.fault=='old_drift:'+label:route['operations'][0]['toolpath_record_counts']=[999]
        for key in ('operations','operation_counts','operation_setups'):self.current_state[key]=deepcopy(route[key])
        self.current_state['operation_count']=len(route['operations'])
        source=self.loaded['source_defaults_fixture']
        result=dict(route=route,tools=deepcopy(self.loaded['neck_tool_checkpoint']['catalogue']),feature=deepcopy(self.loaded['state']['features'][0]),
            source_defaults=deepcopy(source),source_restrictions={'LeadInOutApplyToAll':True,'GougeCheck':True},target_defaults=deepcopy(self.defaults),
            fields=deepcopy(self.fields),protected=deepcopy(self.protected))
        if self.fault=='tool_drift:'+label:result['tools'][0]['CutDiameter']+=1
        if self.fault=='gouge:'+label:result['protected']['gouge_check']=label=='before'
        if self.fault=='source:'+label:result['source_defaults']['finish']['GetChamferLength']+=1
        if self.fault=='defaults:'+label:result['target_defaults']['finish']['DepthAllow']+=1
        return result
    def current_tool(self):return deepcopy(self.target_tool)
    def assign(self,pending):pending();self.call('assign');self.target_tool=m.wanted_tool(self.loaded,self.p);return 0
    def field(self,spec):
        self.call('read:'+spec[0])
        if spec[0]=='gouge_check':return self.protected['gouge_check']
        if spec[0] in ('lead_in_type','lead_out_type'):return self.protected['lead_types'][0 if spec[0]=='lead_in_type' else 1]
        return deepcopy(self.fields[spec[0]])
    def set_field(self,spec,value,pending):
        pending();self.call('write:'+spec[0])
        if spec in m.SCOPE_FIELDS:
            actual='wrong' if self.fault=='wrong_readback:'+spec[0] else value
            if spec[0]=='gouge_check':self.protected['gouge_check']=actual
            else:self.protected['lead_types'][0 if spec[0]=='lead_in_type' else 1]=actual
            return 0
        self.fields[spec[0]]=deepcopy(value)
        if spec[0] in m.DEFAULT_FIELDS:self.defaults['finish'][m.DEFAULT_FIELDS[spec[0]]]=value[0] if spec[4]=='depth_pair' else value
        if self.fault=='wrong_readback:'+spec[0]:self.fields[spec[0]]='wrong'
        return 0
    def outcome(self):
        self.call('outcome');return dict(operation_native_id=self.p['operation_native_id'],feature_native_id=self.p['feature_native_id'],
            generated=self.generated,generated_for_feature=self.generated,record_counts=[300] if self.generated else [])
    def generate(self,pending):pending();self.call('generate');self.generated=not self.empty;return 0
    def save(self):
        self.call('save')
        if self.fault!='unchanged_bytes':self.source.write_bytes(b'fresh-finish-saved')
        return self.save_return
    def saved_hash(self,stage):
        self.call('saved_hash');sha=m._file_hash(self.source);self.current_state['saved_file_sha256']=sha
        self.report['source_transition']=dict(source_before_sha256=self.loaded['source_sha256'],source_after_sha256=sha,strict_save_return=0)
        return sha
    def finish(self):
        self.call('finish');self.report['messages']=dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=False,callback_errors=[],callback_error_count=0)
    def close(self):self.call('close')


@pytest.fixture
def case(tmp_path,monkeypatch):
    c=old.case.__wrapped__(tmp_path,monkeypatch);prior=old.complete(c)
    loaded=m.parent.load_completed(c.p['receipt_path'],m._file_hash(c.p['receipt_path']),process_id=c.p['process_id'],expected_document_path=str(c.source),expected_source_sha256=prior['saved_source_sha256'])
    loaded['state']['operations'][-1]['assigned_tool']=dict(next(x for x in loaded['state']['operations'] if x['native_id']==90)['assigned_tool'],native_id=121)
    loaded['neck_tool_candidate']={'native_id':120};loaded['source_defaults_fixture']=deepcopy(prior['final_observation']['source_defaults'])
    p=dict(process_id=123,expected_document_path=str(c.source),expected_source_sha256=loaded['source_sha256'],addin_clsid=c.p['addin_clsid'],
        checkpoint_receipt_path=c.p['receipt_path'],checkpoint_receipt_sha256=m._file_hash(c.p['receipt_path']),source_operation_native_id=90,
        operation_native_id=100,feature_native_id=70,tool_native_id=120,recipe_path=str(tmp_path/'recipe.json'),recipe_sha256='0'*64,
        module_sha256=m._file_hash(m.__file__),receipt_path=str(tmp_path/'recipe-result.json'),protected_receipt_path=str(tmp_path/'protected.json'),protected_receipt_sha256='0'*64)
    recipe=dict(scope='FRESH_FINISH_WALL_RECIPE_V2',binding={k:p[k] for k in ('source_operation_native_id','operation_native_id','feature_native_id','tool_native_id')},
        field_values=values(),scope_values={'gouge_check':True,'lead_in_type':1,'lead_out_type':1},bottom_finish=False,gouge_check=True,save_empty_result=True,maximum_gtp_calls=1,production_feeds_qualified=False)
    Path(p['recipe_path']).write_text(json.dumps(recipe));p['recipe_sha256']=m._file_hash(p['recipe_path'])
    loaded.update(recipe=recipe,recipe_pin=m.common._pin(p['recipe_path']),protected_baseline=dict(gouge_check=False,single_depth=False,depth_process=1,rest_method=0,add_tool_radius=False,lead_types=[4,4],compensation=[1,0]))
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',process_id=123,source_path=str(c.source),initial_source_sha256=loaded['source_sha256'],
        request=p,module_pin=m.common._pin(m.__file__),parent_pin=loaded['parent_pin'],recipe_pin=loaded['recipe_pin'],loaded_context_before=loaded,
        live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],
        actions={},mutation_attempted=False,configuration_readback_verified=False,generation_verified=False,readback_verified=False,model_saved=False,**{k:False for k in m.FORBIDDEN})
    marker=tmp_path/'recipe.marker.json';monkeypatch.setattr(m,'marker_path',lambda *a:marker)
    return SimpleNamespace(p=p,r=r,loaded=loaded,b=Fake(loaded,p,r,c.source),j=m.Journal(r,p['receipt_path'],marker),source=c.source)


def run(c):return m.run_backend(c.b,c.j,c.loaded,c.p)
def complete(c):
    r=run(c);assert r['readback_verified'],r.get('issue');r['phase_proofs_verified']=True
    result=m.validate_terminal(r);r['checkpoint_digest']=m._digest(m.group.current_projection(result));c.j.persist()
    r['marker_pin']=m.common._pin(c.j.marker);c.j.persist();return r


@pytest.mark.parametrize('empty',[False,True])
def test_one_selected_gtp_and_save_even_if_empty(case,empty):
    case.b.empty=empty;r=complete(case)
    assert case.b.calls.count('assign')==case.b.calls.count('generate')==case.b.calls.count('save')==1
    assert len([x for x in case.b.calls if x.startswith('write:')])==23
    assert r['status']==('saved_configuration_no_toolpath' if empty else 'saved_generated_review_required')
    assert r['generation_verified'] is not empty and all(r[k] is False for k in m.FORBIDDEN)
    ctx=m.load_completed(case.p['receipt_path'],m._file_hash(case.p['receipt_path']),process_id=123,expected_document_path=str(case.source),expected_source_sha256=r['saved_source_sha256'])
    assert ctx['fresh_finish_result']['generated'] is not empty and ctx['fresh_finish_result']['geometry_acceptance_complete'] is False

@pytest.mark.parametrize('fault',['start','snapshot:before','old_drift:before','tool_drift:before','gouge:before','source:before'])
def test_preflight_aborts_without_mutation(case,fault):
    case.b.fault=fault;r=run(case);assert not r['readback_verified'] and not r['actions'] and 'assign' not in case.b.calls

@pytest.mark.parametrize('fault',['assign','write:gouge_check','write:lead_in_type','write:lead_out_type','write:side_allowance','write:final_depth','write:lead_out_overlap','generate','save'])
def test_pending_mutation_never_replayed(case,fault):
    case.b.fault=fault;r=run(case);assert not r['readback_verified'] and case.b.calls.count(fault)==1
    with pytest.raises(ValueError):m.Journal(r,Path(case.p['receipt_path']).with_name('other.json'),case.j.marker).claim()

@pytest.mark.parametrize('fault',['wrong_readback:gouge_check','wrong_readback:lead_in_type','wrong_readback:lead_out_type','wrong_readback:side_allowance','old_drift:configured','tool_drift:configured','source:configured','defaults:configured','gouge:configured'])
def test_uncertain_configuration_never_generates_or_saves(case,fault):
    case.b.fault=fault;r=run(case);assert not r['readback_verified'] and 'generate' not in case.b.calls and 'save' not in case.b.calls

@pytest.mark.parametrize('fault',['old_drift:generated','tool_drift:generated','source:generated','defaults:generated'])
def test_uncertain_generated_result_not_saved(case,fault):
    case.b.fault=fault;r=run(case);assert not r['readback_verified'] and case.b.calls.count('generate')==1 and 'save' not in case.b.calls

@pytest.mark.parametrize('value',[False,True,None,1,0.,'0'])
def test_strict_save_return(case,value):
    case.b.save_return=value;r=run(case);assert not r['readback_verified'] and case.b.calls.count('save')==1

@pytest.mark.parametrize('fault',['unchanged_bytes','old_drift:saved','tool_drift:saved','source:saved','defaults:saved','finish'])
def test_postsave_uncertainty_no_replay(case,fault):
    case.b.fault=fault;r=run(case);assert not r['readback_verified'] and case.b.calls.count('save')==1

@pytest.mark.parametrize('key',['gouge_check','bottom_finish','maximum_gtp_calls','save_empty_result'])
def test_recipe_cannot_expand_scope(case,key):
    recipe=deepcopy(case.loaded['recipe']);recipe[key]=False if key in ('gouge_check','save_empty_result') else True if key=='bottom_finish' else 2
    with pytest.raises(ValueError):m.validate_recipe(recipe,case.p)

def test_no_global_generation_action(case):
    with pytest.raises(ValueError):case.j.pending('ActiveDocGTP')


def test_only_skipped_compatibility_tests_rejected(tmp_path):
    xml=tmp_path/'regression.xml';xml.write_text('<testsuite tests="4" skipped="4" failures="0" errors="0"/>')
    evidence=tmp_path/'compat.json';evidence.write_text(json.dumps({'regression_pin':m.common._pin(xml)}))
    loaded={'runtime_compatibility_pin':m.common._pin(evidence)}
    with pytest.raises(ValueError):m.executed_regressions(loaded)
    xml.write_text('<testsuite tests="4" skipped="3" failures="0" errors="0"/>');evidence.write_text(json.dumps({'regression_pin':m.common._pin(xml)}))
    m.executed_regressions({'runtime_compatibility_pin':m.common._pin(evidence)})


def test_scope_configuration_does_not_change_nc_or_other_protected_fields(case):
    before=deepcopy(case.b.protected);r=complete(case)
    expected=m.expected_protected(before)
    assert r['final']['protected']==expected
    assert r['final']['protected']['compensation']==[1,0]
    for key in ('gouge_check','lead_in_type','lead_out_type'):
        assert case.b.calls.index('write:'+key)<case.b.calls.index('generate')

@pytest.mark.parametrize('key,value',[('gouge_check',False),('lead_in_type',4),('lead_out_type',0)])
def test_reject_wrong_scope_recipe(case,key,value):
    recipe=deepcopy(case.loaded['recipe']);recipe['scope_values'][key]=value
    with pytest.raises(ValueError):m.validate_recipe(recipe,case.p)

def make_diagnostic(case):
    target=case.loaded['state']['operations'][-1]
    row=dict(native_id=case.p['operation_native_id'],suppressed=False,generated=False,feature_ids=[case.p['feature_native_id']],tool_id=target['assigned_tool']['native_id'],record_counts=[],mill_type=1)
    data=dict(scope='SAVED_FRESH_FINISH_PROTECTED_READ_V1',status='observed',readback_verified=True,read_only=True,mutation_attempted=False,GTP_attempted=False,save_attempted=False,
      process_id=case.p['process_id'],operation_native_id=case.p['operation_native_id'],feature_native_id=case.p['feature_native_id'],source_path=case.p['expected_document_path'],source_sha256=case.p['expected_source_sha256'],checkpoint_pin=case.loaded['parent_pin'],before=row,after=deepcopy(row),batch={'read_scope_complete':True,'invalid':False},cleanup={'session_active':False,'messages':{'disconnected':True}},messages={'subscribed':True,'active':False,'disconnected':True,'event_count':0},runtime_pins=[],protected=deepcopy(case.loaded['protected_baseline']))
    return data

@pytest.mark.parametrize('fault',['scope','source','target','checkpoint','batch','mutation','before','cleanup','protected','message'])
def test_reject_untrusted_protected_evidence(case,fault):
    data=make_diagnostic(case)
    if fault=='scope':data['scope']='other'
    if fault=='source':data['source_sha256']='f'*64
    if fault=='target':data['operation_native_id']+=1
    if fault=='checkpoint':data['checkpoint_pin']=dict(data['checkpoint_pin'],sha256='f'*64)
    if fault=='batch':data['batch']['read_scope_complete']=False
    if fault=='mutation':data['mutation_attempted']=True
    if fault=='before':data['before']=dict(data['before'],tool_id=999)
    if fault=='cleanup':data['cleanup']['session_active']=True
    if fault=='protected':data['protected']['lead_types']=[0,0]
    if fault=='message':data['messages']['event_count']=1
    path=Path(case.p['protected_receipt_path']);path.write_text(json.dumps(data));case.p['protected_receipt_sha256']=m._file_hash(path)
    with pytest.raises(ValueError):m.protected_evidence(case.loaded,case.p)

def test_accept_exact_protected_evidence(case):
    data=make_diagnostic(case);path=Path(case.p['protected_receipt_path']);path.write_text(json.dumps(data));case.p['protected_receipt_sha256']=m._file_hash(path)
    value,pin=m.protected_evidence(case.loaded,case.p);assert value==case.loaded['protected_baseline'] and pin['sha256']==case.p['protected_receipt_sha256']
