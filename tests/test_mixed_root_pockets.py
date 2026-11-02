from copy import deepcopy
import ast,inspect,json,os,types
from pathlib import Path
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
from scripts import sw_cam_mixed_root_pockets as p
import importlib.util
_fixture_path=Path(__file__).parent/'test_mixed_profile.py'
_fixture_spec=importlib.util.spec_from_file_location('public_legacy_mixed_profile',_fixture_path)
_fixture=importlib.util.module_from_spec(_fixture_spec);_fixture_spec.loader.exec_module(_fixture)
rows=_fixture.rows


@pytest.fixture(scope='session')
def specs():
    path=required_evidence(evidence_root('SW_CAM_MIXED_ROOT_EVIDENCE_ROOT'),'EXPECTED_NATIVE_SKETCH_SPECS.json')
    return json.loads(path.read_text(encoding='utf-8-sig'))['specifications']


def pocket(spec,native_id=400):
    def contour(z):
        curves=[]
        for s in spec['profile']['segments']:
            v={'curve_type':0 if s['kind']=='line' else 1,'read_complete':True,'start_native':[*s['start_model_mm'][:2],z],'end_native':[*s['end_model_mm'][:2],z]}
            if s['kind']=='arc':v.update(mid_native=[*s['mid_model_mm'][:2],z],centre_native=[*s['center_model_mm'][:2],z],radius_native=s['radius_mm'],normal_native=[0.,0.,1.],sense_raw=1)
            curves.append(v)
        return dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=len(curves),curves=curves)])
    return dict(owner_setup_native_id=69,header=dict(native_id=native_id,volume_type=2,suppressed=False,axis_native=[0,0,-1],depth_native=3.4,start_native=[0,0,10.9]),island_count=0,contours={'top':contour(10.9),'bottom':contour(7.5)})


@pytest.mark.parametrize('i',[0,1])
def test_exact_native_top_bottom(specs,i):assert p.verify_pocket(pocket(specs[i]),specs[i],native_id=400)['physical_depth_mm']==3.4


@pytest.mark.parametrize('fault',['owner','id','depth','axis','top','bottom','midpoint','radius','missing','spline','island','chain','units'])
def test_native_feature_failures(specs,fault):
    r=pocket(specs[0]);c=r['contours']['bottom']['chains'][0]['curves'];arc=next(x for x in c if x['curve_type']==1)
    if fault=='owner':r['owner_setup_native_id']=70
    if fault=='id':r['header']['native_id']=401
    if fault=='depth':r['header']['depth_native']=3.3
    if fault=='axis':r['header']['axis_native']=[0,0,1]
    if fault=='top':r['header']['start_native'][2]-=26
    if fault=='bottom':c[0]['start_native'][2]+=3.4
    if fault=='midpoint':arc['mid_native'][0]+=.01
    if fault=='radius':arc['radius_native']+=.1
    if fault=='missing':c.pop()
    if fault=='spline':c[0]['curve_type']=3
    if fault=='island':r['island_count']=1
    if fault=='chain':r['contours']['bottom']['declared_chain_count']=2
    if fault=='units':arc['radius_native']/=1000
    with pytest.raises(ValueError):p.verify_pocket(r,specs[0],native_id=400)


def test_header_protection():
    a=[{'header':{'native_id':1,'depth':2},'owner_setup_native_id':69}]
    b=a+[{'header':{'native_id':4},'owner_setup_native_id':69}]
    p.verify_headers(a,b,[4]);b=deepcopy(b);b[0]['header']['depth']=3
    with pytest.raises(ValueError):p.verify_headers(a,b,[4])


def test_real_backend_constructor_callable_graph():
    from scripts import sw_cam_raw_mill_face_operation as capture
    loaded={'deep_targets':[],'guide_parameters':{'document':{'path':'part','type':1,'title':'part','needs_save':False}}}
    backend=p.NativeBackend(loaded,{},None,'x','tlb',{},lambda:None)
    assert isinstance(backend.capture,types.ModuleType) and backend.capture is capture
    tree=ast.parse(inspect.getsource(p.run_backend));names={x.func.attr for x in ast.walk(tree)if isinstance(x,ast.Call)and isinstance(x.func,ast.Attribute)and isinstance(x.func.value,ast.Name)and x.func.value.id=='backend'}
    assert names
    for name in names:assert callable(getattr(backend,name)),name
    for name in ('generate','assign','set_field','set_nc'):
        with pytest.raises(ValueError):getattr(backend,name)()


class Fake:
    def __init__(self,loaded,specs,report,fail=None):
        self.loaded,self.specs,self.report,self.fail=loaded,specs,report,fail;self.created=[];self.identifiers=[];self.saved=False;self.calls=[];self.session_active=False
        self.basecad={'features':[{'name':'Original','type':'Solid'}],'solids':[{'box_m':[0]*6,'mass_raw':[1.,2.,3.,4.]}],'needs_save':False}
    def start(self):self.calls.append('start');self.session_active=True
    def boundary(self):pass
    def proof_boundary(self):self.calls.append('proof')
    def capture_snapshot(self,label,full=False):
        value=deepcopy(self.loaded['guide_parameters']['expected_parameters'])
        if self.fail=='parameters'and self.identifiers:value['parameters'][0]['feed']=1
        return value
    def capture_binding(self,label):
        r=deepcopy(self.loaded['guide_parameters']['expected_parameters']['binding'])
        if self.fail=='auto_GOP':r['operations'].append({'native_id':999})
        return r
    def catalogue(self):return self.loaded['tool_catalogue_ids']
    def headers(self):return [{'owner_setup_native_id':69,'header':{'native_id':80}}]+[{'owner_setup_native_id':69,'header':{'native_id':i}}for i in self.identifiers]
    def cad(self,spec):
        value=deepcopy(self.basecad);value['features']+=deepcopy(self.created);value['needs_save']=bool(self.created)and not self.saved
        if self.fail=='solid'and self.created:value['solids'][0]['box_m'][0]=1
        return value,None,[]
    def create_sketch(self,spec,pending):
        self.calls.append('sketch');pending()
        if self.fail=='sketch_unknown':raise RuntimeError('unknown sketch mutation')
        r={'name':spec['sketch_name'],'type':'ProfileFeature'};self.created.append(r)
        return {'created_features':[r],'readback':{'arc_interval_midpoint_verified':True,'native_rotation_direction_assumed':False,'entities':rows(spec)}}
    def create_pocket(self,spec,pending):
        self.calls.append('pocket');pending()
        if self.fail=='feature_unknown':raise RuntimeError('unknown feature mutation')
        ident=400+len(self.identifiers);self.identifiers.append(ident);return ident
    def feature(self,ident):
        value=pocket(self.specs[self.identifiers.index(ident)],ident)
        if self.fail=='contour':value['header']['depth_native']=3.5
        return value
    def save(self):self.calls.append('save');self.saved=True;return 0
    def saved_hash(self,save_report):
        self.report['source_transition']={'source_before_sha256':'a'*64,'source_after_sha256':'b'*64,'strict_save_return':0,'document':{'path':'part','type':1,'title':'part','needs_save':False}};return 'b'*64
    def export(self,*args):self.calls.append('export');return {'test':True}
    def finish(self):self.session_active=False
    def close(self):self.session_active=False


@pytest.fixture
def engine(monkeypatch,tmp_path,specs):
    loaded={'guide_parameters':{'expected_parameters':{'binding':{'operations':[{'native_id':1}]},'parameters':[{'feed':500}]}},'generated':{'saved_cl':{'test':True}},'tool_catalogue_ids':[273,338],'root_pocket_specs':specs}
    monkeypatch.setattr(p.cl,'verify_all',lambda *a:{'all_fourteen_complete_streams_unchanged':True})
    def close(backend,r):backend.close();r['cleanup_session_active']=False
    monkeypatch.setattr(p.generation,'close_checked',close)
    def run(fail=None):
        r={'scope':p.SCOPE,'module_pin':p.common._pin(p.__file__),'source_path':'part','source_sha256':'a'*64,'profile_specs':specs,'initial_context':deepcopy(loaded)}
        backend=Fake(loaded,specs,r,fail);journal=p.Journal(r,tmp_path/(str(fail)+'.json'),tmp_path/(str(fail)+'.once.json'))
        return p.run_backend(backend,journal,loaded,specs),backend,journal
    return run


def test_grouped_five_actions_one_save_no_generation(engine):
    r,b,j=engine();assert r['status']=='saved_two_mixed_pockets_review_required';assert r['continuation_ready'];assert b.calls.count('save')==1 and b.calls.count('export')==1
    assert list(r['actions'])==['CreateSketch:0','CreatePocket:0','CreateSketch:1','CreatePocket:1','SaveActiveDocument']
    assert all(v['readback_verified']for v in r['actions'].values());assert r['GTP_attempted']is False and r['GOP_attempted']is False
    with pytest.raises(ValueError):j.pending('CreateSketch:0')


@pytest.mark.parametrize('failure',['sketch_unknown','feature_unknown','contour','parameters','auto_GOP','solid'])
def test_partial_unknown_never_saved_or_replayed(engine,failure):
    r,b,j=engine(failure);assert r['status']=='uncertain'and not r['continuation_ready'];assert 'save'not in b.calls and'export'not in b.calls
    assert j.marker.exists()
    if failure in('feature_unknown','contour','auto_GOP'):assert b.calls.count('pocket')==1


def test_no_hidden_mutation_calls_in_native_adapter():
    src=inspect.getsource(p.NativeBackend)
    assert "'CreateMillFeature2'"in src
    assert 'GenerateOpPlan'not in src and 'GenerateToolpath'not in src and "'SetTool'"not in src
    # QI must occur before dispatch claim; callback contains only the prebound method.
    tree=ast.parse(inspect.getsource(p));calls=[x for x in ast.walk(tree)if isinstance(x,ast.Call)and isinstance(x.func,ast.Attribute)and x.func.attr=='dispatch_once']
    assert len(calls)==1
    assert 'typed'not in ast.unparse(calls[0].args[0])
@pytest.fixture(scope='session')
def current_context():
    f=required_evidence(evidence_root('SW_CAM_MIXED_ROOT_EVIDENCE_ROOT'),'ACTUAL_PARENT_CONTEXT.json')
    return json.loads(f.read_text(encoding='utf-8-sig'))['context']


@pytest.fixture
def terminal(engine,current_context,specs):
    r,b,j=engine();c=deepcopy(current_context);c['root_pocket_specs']=deepcopy(specs)
    r['initial_context']=c;r['before']=deepcopy(c['guide_parameters']['expected_parameters']);r['configured']=deepcopy(r['before']);r['saved']=deepcopy(r['before'])
    r['source_sha256']=c['source_sha256'];r['source_transition']['source_before_sha256']=r['source_sha256'];r['source_transition']['document']=deepcopy(c['guide_parameters']['document'])
    r['saved_tool_ids']=r['before_tool_ids']=deepcopy(c['tool_catalogue_ids'])
    r['messages']={'subscribed':True,'disconnected':True,'active':False,'event_count':0}
    return r


def test_terminal_complete_contract(terminal):assert p.validate_terminal(terminal)['continuation_ready']is True


@pytest.mark.parametrize('fault',['count','sketch_readback','pocket_action','source','owner_document','old_parameter','old_route','profile','event','cleanup','GTP','production','save_return','catalogue','CL','action_order'])
def test_terminal_rejects_false_acceptance(terminal,fault):
    r=deepcopy(terminal)
    if fault=='count':r['saved_new_features'].pop()
    if fault=='sketch_readback':r['actions']['CreateSketch:0']['observed']['readback']['entities'].pop()
    if fault=='pocket_action':r['actions']['CreatePocket:0']['observed']['native_id']+=1
    if fault=='source':r['source_sha256']='f'*64
    if fault=='owner_document':r['source_transition']['document']['title']='other'
    if fault=='old_parameter':r['saved']['parameters'][0]['operation_native_id']=1
    if fault=='old_route':r['saved']['binding']['operations'].reverse()
    if fault=='profile':r['profile_specs'][0]['plane_offset_mm']=11
    if fault=='event':r['messages']['event_count']=1
    if fault=='cleanup':r['cleanup_session_active']=True
    if fault=='GTP':r['GTP_attempted']=True
    if fault=='production':r['production_qualified']=True
    if fault=='save_return':r['source_transition']['strict_save_return']=1
    if fault=='catalogue':r['saved_tool_ids']=[]
    if fault=='CL':r['protected_cl']['all_fourteen_complete_streams_unchanged']=False
    if fault=='action_order':r['actions']=dict(reversed(list(r['actions'].items())))
    with pytest.raises(ValueError):p.validate_terminal(r)