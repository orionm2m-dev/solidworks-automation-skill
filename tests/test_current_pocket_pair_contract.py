"""Independent bounded-pair contracts; no application connections."""
import importlib, os, sys
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts')not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
c=importlib.import_module('scripts.sw_cam_current_pocket_pair_read')

def request(tmp_path):
    v=dict(process_id=123,expected_process_create_time=10.,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=66,expected_operation_native_ids=[114,115],receipt_path=str(tmp_path/'read.json'),qualification_only=True,message_policy='vendor_default')
    for prefix in c.AUTHORITY_PREFIXES:v.update({prefix+'_path':str(tmp_path/(prefix+'.json')),prefix+'_sha256':'b'*64})
    return v

def state(v):
    tool=dict(native_id=116,is_mill_tool=True,native_read_complete=True,cut_diameter_native=20.,protrusion_native=60.)
    rows=[dict(native_id=114+i,mill_operation_type=i,linked_feature_ids=[66],all_linked_features_observed=True,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],setup_native_id=65,assigned_tool=deepcopy(tool))for i in range(2)]
    return dict(document=dict(path=v['expected_document_path'],title='part.sldprt',type=1,needs_save=False),saved_file_sha256=v['expected_source_sha256'],operation_setups=[dict(native_id=65,operation_count=2)],operations=rows)

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_feature_native_id',0),('expected_process_create_time',float('nan')),('expected_operation_native_ids',[115,115]),('expected_operation_native_ids',[True,115]),('expected_operation_native_ids',[114]),('message_policy','dismiss'),('qualification_only',False),('expected_source_sha256','x'*64),('receipt_path','relative.json')])
def test_shape_rejects_wrong_identity_or_scope(tmp_path,key,value):
    v=request(tmp_path);v[key]=value
    with pytest.raises(ValueError):c.shape(v)

@pytest.mark.parametrize('change',[lambda s:s['operations'].reverse(),lambda s:s['operations'][0].update(mill_operation_type=True),lambda s:s['operations'][1].update(linked_feature_ids=[67]),lambda s:s['operations'][0].update(toolpath_generated=True),lambda s:s['operations'][1].update(toolpath_record_counts=[1]),lambda s:s['operations'][0]['assigned_tool'].update(native_read_complete=False),lambda s:s['operations'][1].update(setup_native_id=99),lambda s:s['document'].update(needs_save=True),lambda s:s.update(saved_file_sha256='c'*64)])
def test_pair_selection_rejects_unqualified_or_changed_rows(tmp_path,change):
    v=request(tmp_path);s=state(v);change(s)
    with pytest.raises(ValueError):c.select_pair(dict(saved_plan_inventory=s),v)

def test_selection_returns_detached_exact_pair(tmp_path):
    v=request(tmp_path);c.shape(v);s=state(v);rows=c.select_pair(dict(saved_plan_inventory=s),v);assert rows==s['operations'];rows[0]['assigned_tool']['native_id']=999;assert s['operations'][0]['assigned_tool']['native_id']==116

class Obj:
    def __init__(self,name,oid=0,rows=None,kind=None):self.name,self.oid,self.rows,self.kind=name,oid,rows,kind
class View:
    def __init__(self,raw,iid):self.raw,self.iid=raw,iid
class Graph:
    def __init__(self,targets):
        self.targets=targets;self.feature=Obj('feature',66);self.doc=Obj('doc');self.machine=Obj('machine');self.setup=Obj('setup',65);self.tool=Obj('tool',116)
        self.ops=[Obj('operation',r['native_id'],kind=r['mill_operation_type'])for r in targets];self.trace=[];self.boundaries=0
        self.gate=object.__new__(c.ReadGuard);self.gate._invalid=False;self.gate.calls=0;self.gate.report={};self.gate._observe=lambda f:f()
    def raw(self,x):return x.raw if isinstance(x,View)else x
    def typed(self,obj,iid):
        self.gate.reject(iid in c.INTERFACES,'unadmitted interface');raw=self.raw(obj);self.trace.append(('typed',raw.name,iid));return View(raw,iid)
    def read(self,obj,name,*args):return c.ReadGuard.read(self.gate,obj,name,*args)
    def _native_read(self,obj,name,*args):
        raw=self.raw(obj);iid=obj.iid if isinstance(obj,View)else None;self.trace.append(('read',raw.name,iid,name))
        if name=='QueryInterface':
            from comtypes.automation import IDispatch
            assert raw is self.feature and args==(IDispatch,);return raw
        if name=='GetCWObjectID':return self.raw(args[0]).oid,True
        if name=='GetCWObjectFromID':assert args[0]==3;return next(x for x in self.ops if x.oid==args[1]),True
        if name=='IGetMachine':assert iid=='ICWPartDoc';return self.machine
        if name=='IGetEnumOpSetups':assert iid=='ICWMachine';return Obj('collection',rows=[self.setup])
        if name=='IGetEnumOperations':assert iid=='ICWBaseOpSetup';return Obj('collection',rows=self.ops)
        if name=='Count':assert iid=='ICWDispatchCollection';return len(raw.rows)
        if name=='Item':assert iid=='ICWDispatchCollection';return raw.rows[args[0]]
        if name=='OpernType':assert iid=='ICWMillOperation';return raw.kind
        if name in('Suppressed','GetIsToolpathGenerated'):assert iid=='ICWOperation';return False
        if name=='IGetAllFeatures':assert iid=='ICWOperation';return Obj('collection',rows=[self.feature])
        raise AssertionError(('unexpected getter',raw.name,iid,name))
    def plane(self,*args):raise AssertionError('pointer getter must use existing stub in this cache test')
    def _boundary(self):self.boundaries+=1

@pytest.fixture
def graph_case(tmp_path,monkeypatch):
    v=request(tmp_path);s=state(v);g=Graph(s['operations']);calls=[]
    monkeypatch.setattr(c,'_member',g._native_read)
    def generic(raw,doc,read,typed):
        raw=g.raw(raw);r=next(x for x in s['operations']if x['native_id']==raw.oid);return deepcopy(r['assigned_tool']),g.tool
    def dimensions(tool,gen,batch):calls.append(g.raw(tool).oid);return dict(generic=deepcopy(gen),dimensions=dict(diameter=20.))
    monkeypatch.setattr(c.parameters,'read_generic_tool',generic);monkeypatch.setattr(c.parameters,'read_tool_dimensions',dimensions)
    monkeypatch.setattr(c.pocket,'read_levels',lambda *a,**k:dict(complete=True))
    monkeypatch.setattr(c.pocket.rough,'read_rough_entry_parameters',lambda *a,**k:dict(complete=True))
    monkeypatch.setattr(c.pocket,'read_finish_parameters',lambda *a,**k:dict(complete=True))
    monkeypatch.setattr(c.pocket,'read_nc_settings',lambda *a,**k:dict(read_complete=True))
    monkeypatch.setattr(c.fields,'read_cached_fields',lambda *a,**k:dict(complete=True))
    monkeypatch.setattr(c.protected,'read_protected',lambda *a,**k:dict(complete=True))
    monkeypatch.setattr(c.pocket.leads,'read_lead_details',lambda *a,**k:dict(complete=True))
    return s,g,dict(doc=g.doc,selected_feature=g.feature),calls

def test_actual_capture_rows_deduplicates_shared_tool_and_uses_public_owner(graph_case):
    s,g,n,calls=graph_case;r={};c.read_pair(deepcopy(s),n,s['operations'],g,r,lambda:None)
    assert calls==[116]and r['unique_tool_dimension_reads']==1
    assert [x['operation_native_id']for x in r['parameters']]==[114,115]and all(x['read_complete']for x in r['parameters'])
    assert ('read','setup','ICWBaseOpSetup','IGetEnumOperations')in g.trace
    assert all(x['nc']['read_complete']for x in r['parameters'])and 'finish_fields'in r['parameters'][1]and 'finish_fields'not in r['parameters'][0]
    r['parameters'][0]['tool']['dimensions']['diameter']=99;assert r['parameters'][1]['tool']['dimensions']['diameter']==20.

def test_failed_second_row_keeps_first_complete_observation(graph_case,monkeypatch):
    s,g,n,calls=graph_case;r={}
    def levels(raw,*a,**k):
        if g.raw(raw).oid==115:raise RuntimeError('second-level-getter')
        return dict(complete=True)
    monkeypatch.setattr(c.pocket,'read_levels',levels)
    with pytest.raises(RuntimeError):c.read_pair(deepcopy(s),n,s['operations'],g,r,lambda:None)
    assert len(r['parameters'])==2 and r['parameters'][0]['read_complete']is True and r['parameters'][1]['read_complete']is False and calls==[116]

@pytest.mark.parametrize('where',['setup','order'])
def test_native_pair_mismatch_stops_before_parameter_getters(graph_case,where):
    s,g,n,calls=graph_case
    if where=='setup':g.setup.oid=999
    else:g.ops.reverse()
    with pytest.raises(ValueError):c.read_pair(deepcopy(s),n,s['operations'],g,{},lambda:None)
    assert calls==[]

@pytest.mark.parametrize('member',['SaveActiveDocument','GenerateOpPlan','GenerateToolpath','SetTool','SetDepth','SetHomePosition','ImportCAMData'])
def test_mutating_or_unapproved_member_rejected_without_invocation(member):
    g=object.__new__(c.ReadGuard);g._invalid=False;g._observe=lambda f:(_ for _ in()).throw(AssertionError('invoked'))
    with pytest.raises(ValueError):g.read(object(),member)
    with pytest.raises(ValueError):g.dispatch_once(object(),'anything')

def test_query_interface_is_only_exact_IDispatch_and_budget_is_bounded():
    g=object.__new__(c.ReadGuard);g._invalid=False
    with pytest.raises(ValueError):g.read(object(),'QueryInterface',object())
    with pytest.raises(ValueError):g.typed(object(),'ICWProfilePktCircFeat')
    g.calls=c.MAX_CALLS;g.report={};g._observe=lambda f:(_ for _ in()).throw(AssertionError('over-budget invoke'))
    with pytest.raises(ValueError):g.observed(object(),'getter','anything',lambda:None)

class NoApp:
    def __getattr__(self,name):raise AssertionError('application access '+name)

def test_context_constructor_never_touches_application(tmp_path):
    v=request(tmp_path);b=dict(context={},targets=[],request=v,receipt=Path(v['receipt_path']),consumed=False)
    x=c.Context(NoApp(),'clsid','fake.tlb',v,b,{},lambda:None,lambda:None,{})
    assert x.session is None and not x.closed

@pytest.fixture
def flow(tmp_path,monkeypatch):
    v=request(tmp_path);s=state(v);d=dict(authority_scope='saved',pins=[],saved_plan_inventory=s);b=dict(context=d,targets=deepcopy(s['operations']),request=deepcopy(v),receipt=Path(v['receipt_path']),consumed=False)
    control=dict(failure=None,closes=0,captures=[])
    monkeypatch.setattr(c,'preflight',lambda tlb:dict(generated_pin=dict(path=str(tmp_path/'generated.py'),sha256='c'*64)))
    monkeypatch.setattr(c.definition,'verify_files',lambda d:None)
    monkeypatch.setattr(c.shared,'file_pin',lambda p,sha:dict(path=str(p),sha256=sha))
    monkeypatch.setattr(c,'_file_hash',lambda p:('f'*64 if control['failure']=='source'and str(p)==v['expected_document_path']else'a'*64))
    class Fake:
        def __init__(self,sw,cl,tl,v,b,r,p,rc,abi):self.r=r;self.expected=dict(document=deepcopy(s['document']),saved_file_sha256='a'*64);self.closed=False
        def start(self):
            self.r['document_before']=deepcopy(s['document'])
            if control['failure']=='start':raise ValueError('start')
        def capture(self,label):
            control['captures'].append(label);x=deepcopy(s)
            if control['failure']=='inventory'and label=='after':x['operations'][0]['native_id']=999
            self.r[label]=x;return x,{}
        def observe(self,*a):
            self.r['parameters']=[dict(operation_native_id=114,read_complete=False)]
            if control['failure']=='getter':raise ValueError('getter')
            self.r['parameters']=[dict(operation_native_id=x,read_complete=True)for x in(114,115)]
        def close(self):
            if self.closed:return
            self.closed=True;control['closes']+=1
            self.r['messages']=dict(subscribed=True,active=False,disconnected=True,event_count=1 if control['failure']=='event' else 0,events=[{}]if control['failure']=='event'else[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
            if control['failure']=='cleanup':raise ValueError('cleanup')
        def identity(self):
            out=deepcopy(self.expected)
            if control['failure']=='identity':out['document']['needs_save']=True
            return out
    checks=[]
    def runtime_check():
        checks.append(1)
        if control['failure']=='runtime'and len(checks)>1:raise ValueError('runtime')
    def run():return c.run_read(NoApp(),'x',str(tmp_path/'fake.tlb'),v,prepared=b,runtime_check=runtime_check,_context_factory=Fake)
    return v,b,control,run

def test_two_capture_lifecycle_success_and_consumed_preparation(flow):
    v,b,ctl,run=flow;r=run();assert r['status']=='observed'and all(r[k]is True for k in c.FLAGS)and ctl['captures']==['before','after']and ctl['closes']==1
    assert all(r[k]is False for k in('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','tool_creation_attempted','tool_assignment_attempted','physical_tool_qualified','cutting_conditions_qualified','island_geometry_verified','production_qualified'))
    with pytest.raises(ValueError):run()

@pytest.mark.parametrize('failure',['start','getter','inventory','event','cleanup','identity','runtime','source'])
def test_failure_clears_every_acceptance_flag_and_closes(flow,failure):
    v,b,ctl,run=flow;ctl['failure']=failure;r=run();assert r['status']=='error'and all(r[k]is False for k in c.FLAGS)and ctl['closes']==1
    assert not r['mutation_attempted']and not r['Save_attempted']
    if failure=='getter':assert r['parameters']==[dict(operation_native_id=114,read_complete=False)]


