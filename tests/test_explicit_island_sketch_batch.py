import ast,copy,hashlib,importlib.util,json,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
RT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT))
sys.path.insert(0,str(RT))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
COMP=Path(os.environ.get('SWMCP_ISLAND_COMPONENT_ROOT',ROOT.parent/'cam_explicit_island_sketch_20261111'))
if (COMP/'scripts').is_dir():scripts.__path__.insert(0,str(COMP/'scripts'))
from scripts import sw_cam_explicit_island_sketch_batch as m

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):p.write_text(json.dumps(value),encoding='utf8');return sha(p)
def specs():
    import math
    loops=[]
    for a in (20.,110.,200.,290.):
        t=math.radians(a)
        def p(u,v):return [u*math.cos(t)-v*math.sin(t),u*math.sin(t)+v*math.cos(t),7.]
        A,B,C,D=p(math.sqrt(24),-1),p(math.sqrt(24),1),p(math.sqrt(8),1),p(math.sqrt(8),-1)
        loops.append(dict(angle_deg=a,edges=[dict(kind='Circle',start=A,end=B,centre=[0.,0.,7.],radius_mm=5.,ccw=True),dict(kind='Line',start=B,end=C),dict(kind='Circle',start=C,end=D,centre=[0.,0.,7.],radius_mm=3.,ccw=False),dict(kind='Line',start=D,end=A)]))
    return loops

def observed(spec):
    rows=[]
    for s in spec['profile']['segments']:
        row=dict(type=s['kind'],points_model_m=[[v/1000 for v in s[k]]for k in ('start_model_mm','end_model_mm')],mid_model_m=[v/1000 for v in s['mid_model_mm']],length_m=m.component.mixed.length(s)/1000)
        if s['kind']=='arc':row.update(center_model_m=[v/1000 for v in s['center_model_mm']],radius_m=s['radius_mm']/1000,native_trim=dict(independent_native_length_verified=True,underlying_curve_trim_used=False))
        rows.append(row)
    return dict(entities=rows,expected_segment_to_native_index=list(range(4)),model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.],readback_tolerance_m=1e-8,arc_interval_midpoint_verified=True,native_rotation_direction_assumed=False,native_rotation_direction_qualified=True,underlying_curve_trim_used=False)

@pytest.fixture
def data(tmp_path):
    source=tmp_path/'source.sldprt';target=tmp_path/'copy.sldprt';source.write_bytes(b'CAD');target.write_bytes(b'CAD')
    cp=tmp_path/'copy.json';ch=write(cp,dict(scope='EXCLUSIVE_INITIALIZED_CAM_SKETCH_COPY_V1',source=dict(path=str(source),sha256=sha(source)),target=dict(path=str(target),sha256=sha(target)),exclusive_creation_verified=True,source_unchanged=True))
    gp=tmp_path/'geometry.json';gh=write(gp,dict(loops=specs()))
    plan=tmp_path/'plan.json';ph=write(plan,dict(scope='FOUR_EXPLICIT_ISLAND_SKETCH_PLAN_V1',geometry_contract_pin=dict(path=str(gp),sha256=gh),loops_pointer='/loops',plane_z_mm=7.,sketch_names=['A','B','C','D'],plane_names=['PA','PB','PC','PD']))
    v=dict(process_id=123,expected_process_create_time=123.5,expected_document_path=str(target),expected_source_sha256=sha(target),expected_sw_configuration='Default',expected_cam_configuration='Mill0',expected_setup_native_id=50,expected_setup_axis_native=[0.,0.,-1.],expected_setup_origin_native=[0.,0.,0.],copy_receipt_path=str(cp),copy_receipt_sha256=ch,sketch_plan_path=str(plan),sketch_plan_sha256=ph,receipt_path=str(tmp_path/'out.json'),save_after_creation=True,qualification_only=True,acknowledge_isolated_copy=True,acknowledge_four_sketches=True,message_policy='vendor_default')
    return m.prepare(v)

def cam(v):return dict(capture_complete=True,machine_type=1,cam_configuration_name=v['expected_cam_configuration'],associated_sw_configuration=v['expected_sw_configuration'],configuration_name=v['expected_cam_configuration'],features=[],operations=[],feature_count=0,operation_count=0,generated_operation_count=0,total_record_count=0,unique_tool_count=0,feature_setups=[dict(index=0,native_id=v['expected_setup_native_id'],axis_native=copy.deepcopy(v['expected_setup_axis_native']),origin_native=copy.deepcopy(v['expected_setup_origin_native']),feature_ids=[])],operation_setups=[dict(index=0,native_id=51,operation_count=0)])

def test_real_inventory_row_schema_has_feature_ids(data):
    s=cam(data['request']);assert 'feature_count'not in s['feature_setups'][0];m.verify_empty(s,data['request'])

@pytest.mark.parametrize('change',[lambda x:x['feature_setups'][0]['feature_ids'].append(5),lambda x:x.update(operation_count=1),lambda x:x.update(unique_tool_count=True),lambda x:x['feature_setups'][0].update(native_id=51),lambda x:x['feature_setups'][0]['origin_native'].__setitem__(2,26),lambda x:x.update(associated_sw_configuration='Other')])
def test_nonempty_or_wrong_setup_rejected(data,change):
    s=cam(data['request']);change(s)
    with pytest.raises(ValueError):m.verify_empty(s,data['request'])

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_setup_native_id',50.0),('expected_process_create_time',float('inf')),('save_after_creation',1),('qualification_only',False),('expected_setup_axis_native',[0,0,0]),('message_policy','suppress')])
def test_shape_rejects_unsafe_inputs(data,key,value):
    v=copy.deepcopy(data['request']);v[key]=value
    with pytest.raises(ValueError):m.shape(v)

class Fake:
    def __init__(self,data,r,persist,fail=None):
        self.data,self.report,self.persist=data,r,persist;self.source=data['request']['expected_source_sha256'];self.pins=copy.deepcopy(data['pins']);self.fail=fail;self.saved=False;self.closed=False;self.creates=0;self.saves=0;self.calls=[]
        self.expected=dict(path=data['request']['expected_document_path'],title='copy',type=1,needs_save=False)
        self.base=dict(pid=123,path=str(Path(self.expected['path']).resolve()),saved_file_sha256=self.source,needs_save=False,features=[dict(name='Origin',type='OriginProfileFeature')],planes=[],solids=[dict(box_m=[0.,1.],mass_raw=[1.,2.])],spec=data['specs'][0])
    def start(self):self.calls.append('start');self.boundary()
    def boundary(self):
        if self.fail=='event'and self.creates:raise ValueError('event')
    def capture_inventory(self,label):self.calls.append(label);return cam(self.data['request'])
    def capture(self,label,read_sketches=False):
        self.calls.append(label)
        if self.fail==label:raise ValueError(label)
        c=copy.deepcopy(self.base);c.update(saved_file_sha256=self.source,needs_save=self.expected['needs_save'])
        created=[dict(name=s['sketch_name'],type='ProfileFeature')for s in self.data['specs'][:self.creates]];c['features']+=created
        if self.saved:c['solids'][0]['mass_raw'][0]+=1e-12
        out=dict(inventory=cam(self.data['request']),cad=c)
        if read_sketches:out['sketches']=[dict(spec=s,sketch_readback=observed(s))for s in self.data['specs']]
        return out
    def create_sketch(self,i,journal):
        journal.pending('CreateSketch:'+str(i));self.creates+=1;self.expected['needs_save']=True
        out=dict(status='sketch_observed',native_readback_verified=True,created_features=[dict(name=self.data['specs'][i]['sketch_name'],type='ProfileFeature')]);self.report['sketches'].append(out)
        if self.fail=='create'+str(i):raise RuntimeError('native unknown')
        return out
    def save(self):
        self.saves+=1;self.report['Save_attempted']=True
        if self.fail=='save':raise RuntimeError('unknown save')
        return True if self.fail=='save_bool'else 0
    def adopt_saved_source(self):
        self.saved=True;Path(self.expected['path']).write_bytes(b'SAVED_SKETCHES')
        self.source=sha(self.expected['path']);self.report.update(saved_file_sha256_after_native_return=self.source,model_saved=True);self.expected['needs_save']=False
        for p in self.pins:
            if m.same_path(p['path'],self.expected['path']):p.update(m.inventory.file_pin(p['path'],self.source))
        if self.fail=='after_raw_save':raise RuntimeError('after raw Save')
        return self.source
    def close(self):
        if self.closed:return
        self.closed=True
        if self.fail=='cleanup':raise RuntimeError('cleanup')
    def runtime_check(self):
        if self.fail=='runtime':raise RuntimeError('runtime')
    def identity(self):return dict(self.expected)
    def events(self,active=False):self.report['messages']=dict(subscribed=True,active=False,disconnected=True,event_count=0,events=[],overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    def files(self):
        if self.fail=='files':raise RuntimeError('files')

def flow(data,fail=None):
    r=m.new_report(data,{});j=m.Journal(data['receipt'],data['marker'],r);j.create();b=Fake(data,r,j.persist,fail);return m.run_backend(b,j,data),b

def test_real_orchestrator_uses_four_once_actions_one_save_and_fresh_readbacks(data):
    r,b=flow(data);assert r['status']=='review_required',r.get('reason');assert all(r[k]for k in m.FLAGS)
    assert b.creates==4 and b.saves==1 and b.calls==['start','before','after_sketch_0','after_sketch_1','after_sketch_2','after_sketch_3','save_before','save_after']
    assert r['native_save']['native_return_type']=='int'and r['save_readback_verified']and r['model_saved']
    assert r['after']['inventory']==r['before']['inventory'];assert all(not r[k]for k in ('AddIsland_attempted','GTP_attempted','GOP_attempted','production_qualified'))
    with pytest.raises(ValueError):m.prepare(dict(data['request'],receipt_path=str(data['receipt'].with_name('other.json'))))

@pytest.mark.parametrize('fail',['create0','create2','event','save_before','save','save_bool','after_raw_save','save_after','cleanup','runtime','files'])
def test_uncertainty_never_replays_and_late_save_facts_survive(data,fail):
    r,b=flow(data,fail);assert r['status']=='uncertain';assert all(r[k]is False for k in m.FLAGS);assert b.saves<=1 and b.creates<=4
    if fail in ('after_raw_save','save_after','cleanup','runtime','files'):assert r['model_saved']is True and r['native_save']['native_return_value']==0 and r['saved_file_sha256_after_native_return']==sha(data['request']['expected_document_path'])

def test_explicit_false_never_saves(data):
    data['request']['save_after_creation']=False;r,b=flow(data);assert r['status']=='review_required'and b.saves==0;assert r['model_saved']is False and r['save_readback_verified']is False and r['after']['cad']['needs_save']is True

def test_save_source_pin_transition_refreshes_byte_length(data):
    r=m.new_report(data,{});b=m.Backend(object(),'','',data,r,lambda:None,lambda:None)
    b.identity=lambda:dict(type=1,path=data['request']['expected_document_path'],title='copy',needs_save=False);b.boundary=lambda:None
    target=Path(data['request']['expected_document_path']);target.write_bytes(b'longer_saved_native_document')
    b.adopt_saved_source();row=next(p for p in b.pins if m.same_path(p['path'],str(target)))
    assert row['sha256']==sha(target) and row['sha256']!=data['request']['expected_source_sha256']
    assert next(p for p in b.pins if m.same_path(p['path'],data['copy']['source']['path']))['sha256']==data['request']['expected_source_sha256']

def test_no_application_constructor_and_public_save_abi(data):
    class NoApp:
        def __getattribute__(self,n):raise AssertionError(n)
    m.Backend(NoApp(),'','',data,{},lambda:None,lambda:None)
    tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH');assert tlb,'Explicit public typelib required for ABI test'
    assert m.preflight(tlb)['SaveActiveDocument_public_ABI_verified']is True

def schema():
    from enum import Enum
    from typing import Literal,Optional
    from pydantic import BaseModel,Field,ConfigDict,field_validator,model_validator
    class ResponseFormat(str,Enum):JSON='json'
    class SolidWorksCamTargetInput(BaseModel):
        addin_clsid:str
        expected_document_path:Optional[str]=None
        expected_document_title:Optional[str]=None
    source=ROOT/'server.fragment.py'
    text=source.read_text(encoding='utf-8-sig')if source.is_file()else(RT/'mcp-server/server.py').read_text(encoding='utf-8-sig')
    tree=ast.parse(text);node=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='SolidWorksCamExplicitIslandSketchBatchInput')
    env=locals().copy();exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),env)
    return env[node.name]

def test_actual_endpoint_schema_strict_and_complete(data):
    cls=schema();v=dict(data['request'],addin_clsid='{00000000-0000-0000-0000-000000000001}')
    assert cls(**v).model_dump()['save_after_creation']is True
    for delta in (dict(process_id=123.),dict(expected_setup_native_id=True),dict(expected_setup_axis_native=[0,False,-1]),dict(extra='x'),dict(expected_document_title='copy')):
        with pytest.raises(ValueError):cls(**dict(v,**delta))


def test_inventory_progress_callback_accepts_actual_diagnostic(data,monkeypatch):
    r=m.new_report(data,{});b=m.Backend(object(),'','',data,r,lambda:None,lambda:None);b.app=object();b.expected=dict(type=1,needs_save=False,path=data['request']['expected_document_path'])
    b.boundary=lambda:None
    class Guard:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
    monkeypatch.setattr(m.read_scope,'ReadGuard',Guard)
    def capture(app,tlb,guard,diagnostic,progress):progress(diagnostic);return cam(data['request'])
    monkeypatch.setattr(m.inventory,'capture_import_inventory',capture)
    assert b.capture_inventory('probe')['feature_setups'][0]['feature_ids']==[]
