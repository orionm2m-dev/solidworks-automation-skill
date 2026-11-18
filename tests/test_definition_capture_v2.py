"""Versioned capture parity and bounded mocked readbacks; no COM/native calls."""
import ast
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
BASE=Path(os.environ['SWMCP_RUNTIME_ROOT'])/'scripts/sw_cam_pocket_definition_context.py'
CANDIDATE=ROOT/'scripts/sw_cam_pocket_definition_capture_v2.py'
BASE_SHA='c5e938d5e6311a98fdc25f01ac3f01d86c81072bab026866fa64bddda11aee28'
OP_KEYS=('operation_setups','operations','operation_count','generated_operation_count','total_record_count','unique_tool_count')

def node(path):
    return next(x for x in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(x,ast.FunctionDef)and x.name=='capture')

def test_exact_parent_source_and_single_keyword_delta():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==BASE_SHA
    candidate=node(CANDIDATE);found=[]
    for call in ast.walk(candidate):
        if isinstance(call,ast.Call)and isinstance(call.func,ast.Name)and call.func.id=='ScopedCamDispatchGuard':
            selected=[k for k in call.keywords if k.arg=='evidence_pin_limit'];found+=selected
            call.keywords=[k for k in call.keywords if k.arg!='evidence_pin_limit']
    assert len(found)==1 and ast.literal_eval(found[0].value)==128
    assert ast.dump(candidate,include_attributes=False)==ast.dump(node(BASE),include_attributes=False)

def run(path,count=68,fault=None,saved_caps=True):
    trace=[];diagnostic={};observed={'document':{'needs_save':False},'saved_file_sha256':'a'*64}
    generic=dict(cam_configuration_name='cam',associated_sw_configuration='sw',feature_setups=[{'native_id':64}],features=[{'native_id':66}],operation_setups=[],operations=[],operation_count=0,generated_operation_count=0,total_record_count=0,unique_tool_count=0)
    snap={'needs_save':False,'solids':[{'volume':1.0}],'features':['profile']}
    request=dict(process_id=10,expected_cam_configuration='cam',expected_sw_configuration='sw',owner_setup_native_id=64,expected_document_path='part')
    if saved_caps:request['source_variant']='saved_cam_caps'
    c=dict(request=request,creator={'feature_header':{'native_id':66},'circle_readback':{'current_circle':1},'status':'uncertain'},pins=[{}for _ in range(count)],expected_source_sha256='a'*64,expected_inventory=dict(deepcopy(generic),sw_reference={},all_solid_body_count=1),current_sketch_baseline=deepcopy(snap),spec={'sketch_name':'profile'},sketch={'sketch_readback':{'legacy_circle':1}},evidence={'sha256':'b'*64},save_pin={'sha256':'c'*64},origin_kind='recovery')
    identity_count=[0]
    def require(ok,message):
        if not ok:raise ValueError(message)
    def identity(sw,context):
        trace.append('identity');identity_count[0]+=1
        return dict(observed,changed=True)if fault=='owner_changed'and identity_count[0]>1 else deepcopy(observed)
    def verify(context):
        trace.append('files');require(fault!='files_changed','file changed')
    def check():
        trace.append('events');require(fault!='event','event')
    class Guard:
        def __init__(self,sw,tlb,*,evidence_pins,evidence_pin_limit=64,verify_evidence,verify_owned_process,check_events,**kw):
            trace.append(('limit',evidence_pin_limit));require(1<=len(evidence_pins)<=evidence_pin_limit,'pin capacity')
            self.verify,self.owned,self.events=verify_evidence,verify_owned_process,check_events
        def __enter__(self):self.verify();self.owned();self.events();return self
        def __exit__(self,*args):trace.append('guard_exit')
        def typed(self,obj,name):trace.append(('typed',name));return obj
        def read(self,obj,name,*args):
            trace.append(('read',obj,name))
            table={('sw','GetAddInObject'):'addin',('addin','GetCWApp'):'app',('app','IGetActiveDoc'):'doc',('doc','IGetMachine'):'machine',('machine','IGetEnumSetups'):['setup'],('setup','IGetEnumFeatures'):['feature'],('model','FeatureByName'):'sketch_feature',('sketch_feature','GetTypeName2'):'ProfileFeature',('sketch_feature','GetSpecificFeature2'):'sketch'}
            value=table[(obj,name)]
            if fault=='setup_count'and name=='IGetEnumSetups':return []
            if fault=='feature_count'and name=='IGetEnumFeatures':return []
            if fault=='sketch_type'and name=='GetTypeName2':return 'Boss'
            return value
        def _observe(self,callback):trace.append('observe');return callback()
        def _boundary(self):trace.append('boundary');self.verify();self.owned();self.events()
    def inventory_capture(*args):
        trace.append('full_inventory');state=deepcopy(generic)
        if fault=='configuration':state['cam_configuration_name']='other'
        if fault=='feature_membership':state['features']=[{'native_id':67}]
        return state
    def snapshot(*args):
        trace.append('body_sketch_snapshot');actual=deepcopy(snap)
        if fault=='body':actual['solids'][0]['volume']=2.
        if fault=='snapshot':actual['features']=['other']
        return actual,'model',[]
    def profile(*args):
        trace.append('analytic_profile')
        if fault=='profile':return {'wrong':1}
        return {'current_circle':1}if saved_caps else {'legacy_circle':1}
    ns=dict(deepcopy=deepcopy,require=require,identity=identity,verify_files=verify,ScopedCamDispatchGuard=Guard,inventory=SimpleNamespace(capture_import_inventory=inventory_capture,_items=lambda raw,*args:raw),OP_KEYS=OP_KEYS,_object_id=lambda *args:65 if fault=='owner_setup'else 64,_feature_header=lambda *args:({'native_id':67 if fault=='header'else 66},'feature'),_snapshot=snapshot,_same_bodies=lambda a,b:a==b,_read_sketch=profile,creator=SimpleNamespace(saved_caps=lambda v:v.get('source_variant')=='saved_cam_caps'),SCOPE='legacy_authority')
    executable=ast.Module(body=[node(path)],type_ignores=[]);exec(compile(ast.fix_missing_locations(executable),str(path),'exec'),ns)
    try:return ns['capture']('sw','clsid','tlb',c,check,diagnostic),trace,diagnostic
    except Exception as error:
        error.trace=trace;error.diagnostic=diagnostic;raise

@pytest.mark.parametrize('saved_caps',[False,True])
def test_legacy_equivalent_results_and_read_sequence(saved_caps):
    old,old_trace,old_diag=run(BASE,count=64,saved_caps=saved_caps)
    new,new_trace,new_diag=run(CANDIDATE,count=64,saved_caps=saved_caps)
    assert old==new and old_diag==new_diag
    assert [x for x in old_trace if not(isinstance(x,tuple)and x[0]=='limit')]==[x for x in new_trace if not(isinstance(x,tuple)and x[0]=='limit')]
    assert new[0]['definition_authority']['scope']=='legacy_authority'
    assert new[0]['definition_authority']['physical_depth_verified']is False

@pytest.mark.parametrize('count',[1,64,65,68,128])
def test_explicit_versioned_capacity_only(count):
    result,trace,diagnostic=run(CANDIDATE,count=count)
    assert ('limit',128)in trace and diagnostic['capture_complete']is True
    if count>64:
        with pytest.raises(ValueError,match='pin capacity'):run(BASE,count=count)

@pytest.mark.parametrize('count',[0,129])
def test_outside_fixed_budget_fails_before_getters(count):
    with pytest.raises(ValueError,match='pin capacity')as caught:run(CANDIDATE,count=count)
    assert not any(isinstance(x,tuple)and x[0]=='read'for x in caught.value.trace)

@pytest.mark.parametrize('fault',['configuration','feature_membership','setup_count','feature_count','owner_setup','header','body','snapshot','sketch_type','profile','owner_changed','files_changed','event'])
def test_all_existing_semantic_gates_fail_closed(fault):
    with pytest.raises(ValueError)as caught:run(CANDIDATE,fault=fault)
    assert caught.value.diagnostic.get('capture_complete')is not True
