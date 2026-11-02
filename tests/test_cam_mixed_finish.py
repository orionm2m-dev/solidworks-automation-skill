from cam_mixed_test_support import ROOT, SCRIPTS, evidence_file, evidence_json, server_nodes, synthetic_specs, synthetic_context
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace,ModuleType
import ast,inspect,os,sys,json,importlib.util
import pytest
from scripts import sw_cam_mixed_root_finish as m

@pytest.fixture(scope='session')
def actual():
    fp=evidence_file('SW_CAM_MIXED_FINISH_PARENT_ROOT','mixed_root_pocket_resume_20261102/ACTUAL_FIRST_NATIVE_POCKET_MATCH_STOP.json')
    rp=evidence_file('SW_CAM_MIXED_FINISH_PARENT_ROOT','mixed_feature_raw_diagnostic_20261102/ACTUAL_NATIVE_FEATURE339_RAW.json')
    return json.loads(fp.read_text(encoding='utf-8-sig')),json.loads(rp.read_text(encoding='utf-8-sig')),m.common._pin(fp),m.common._pin(rp)


def pocket(spec,ident):
    curves=[]
    for s in spec['profile']['segments']:
        c=dict(read_complete=True,curve_type=0 if s['kind']=='line'else 1,start_native=deepcopy(s['start_model_mm']),end_native=deepcopy(s['end_model_mm']))
        if s['kind']=='arc':c.update(mid_native=deepcopy(s['mid_model_mm']),centre_native=deepcopy(s['center_model_mm']),radius_native=s['radius_mm'],normal_native=[0,0,1],sense_raw=1)
        curves.append(c)
    v=dict(status='observed',declared_chain_count=1,chains=[dict(read_complete=True,declared_curve_count=len(curves),curves=curves)])
    return dict(owner_setup_native_id=69,header=dict(native_id=ident,volume_type=2,suppressed=False,depth_native=3.4,axis_native=[0,0,-1],start_native=deepcopy(curves[0]['start_native']),bounds_native=[4.,4.,3.4]),island_count=0,contours=dict(top=deepcopy(v),bottom=deepcopy(v)))


def rows(spec):return m.previous.contour_rows(pocket(spec,400)['contours']['top'])


def test_actual339_planar_definition_not_physical_depth(actual):
    failed,raw,fp,rp=actual;checked=m.diagnostic_contract(raw,failed)
    assert checked['native_bottom_contour_world_z_mm']==10.9 and checked['derived_nominal_floor_world_z_mm']==7.5
    assert checked['physical_floor_verified']is False and checked['actual_CL_depth_verification_required']is True

@pytest.mark.parametrize('fault',['owner','id','depth','bounds','axis','top','bottom','midpoint','radius','missing','island','normal'])
def test_native_definition_drift_rejected(synthetic,fault):
    f,r,*_=synthetic;v=deepcopy(r['raw_feature']);bottom=v['contours']['bottom']['chains'][0]['curves'];arc=next(x for x in bottom if x['curve_type']==1)
    if fault=='owner':v['owner_setup_native_id']=70
    elif fault=='id':v['header']['native_id']=340
    elif fault=='depth':v['header']['depth_native']=3.3
    elif fault=='bounds':v['header']['bounds_native'][2]=3.3
    elif fault=='axis':v['header']['axis_native']=[0,0,1]
    elif fault=='top':v['contours']['top']['chains'][0]['curves'][0]['start_native'][2]=7.5
    elif fault=='bottom':bottom[0]['start_native'][2]=7.5
    elif fault=='midpoint':arc['mid_native'][0]+=.01
    elif fault=='radius':arc['radius_native']+=.01
    elif fault=='missing':bottom.pop()
    elif fault=='island':v['island_count']=1
    elif fault=='normal':arc['normal_native']=[1,0,0]
    with pytest.raises(ValueError):m.verify_pocket(v,f['profile_specs'][0],native_id=339)


def test_real_constructor_callable_graph_and_existing_creation_forbidden(synthetic):
    f,r,*_=synthetic;loaded=deepcopy(f['initial_context']);b=m.NativeBackend(loaded,{},None,'x','tlb',{},lambda:None)
    assert isinstance(b.capture,ModuleType)
    tree=ast.parse(inspect.getsource(m.run_backend))
    for n in ast.walk(tree):
        if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend':assert callable(getattr(b,n.func.attr))
    for name in ('create_pocket','create_sketch'):
        with pytest.raises(ValueError):getattr(b,name)(loaded['root_pocket_specs'][0],lambda:None)
    with pytest.raises(ValueError):b.adopt_first_sketch()


class Fake:
    def __init__(self,l,s,r,fail=None):self.loaded=l;self.specs=s;self.report=r;self.fail=fail;self.calls=[];self.created=[];self.ids=[339];self.saved=False;self.session_active=False
    def start(self):self.session_active=True
    def boundary(self):pass
    def proof_boundary(self):pass
    def capture_binding(self,label):
        out=deepcopy(self.loaded['guide_parameters']['expected_parameters']['binding'])
        if self.fail=='before_binding':out['operations'][0]['suppressed']=True
        return out
    def capture_snapshot(self,label,full=False):
        self.calls.append('full:'+label);assert label in('configured','saved')and full
        out=deepcopy(self.loaded['guide_parameters']['expected_parameters'])
        if self.fail=='parameters':out['parameters'][0]['feature_native_id']+=1
        return out
    def catalogue(self):return self.loaded['tool_catalogue_ids']
    def headers(self):
        out=deepcopy(self.loaded['first_native_pocket_diagnostic']['headers'])
        if len(self.ids)==2:out.append(dict(owner_setup_native_id=69,header=pocket(self.specs[1],self.ids[1])['header']))
        return out
    def cad(self,spec):
        out=deepcopy(self.loaded['first_native_pocket_diagnostic']['after_cad']);out['features']+=self.created;out['needs_save']=not self.saved
        if self.fail=='solid'and self.created:out['solids'][0]['box_m'][0]+=1
        return out,None,None
    def create_sketch(self,spec,pending):
        self.calls.append('sketch');pending()
        if self.fail=='sketch_unknown':raise RuntimeError('unknown sketch')
        record=dict(name=spec['sketch_name'],type='ProfileFeature');self.created.append(record)
        return dict(created_features=[record],readback=dict(arc_interval_midpoint_verified=True,native_rotation_direction_assumed=False,native_rotation_direction_qualified=True,underlying_curve_trim_used=False,native_arc_trim_basis='native_endpoints_rotation_and_independent_length',entities=rows(spec)))
    def create_pocket(self,spec,pending):
        assert spec==self.specs[1];self.calls.append('pocket');pending()
        if self.fail=='pocket_unknown':raise RuntimeError('unknown pocket')
        self.ids.append(400);return 400
    def feature(self,ident):
        v=deepcopy(self.loaded['first_native_pocket_diagnostic']['raw_feature'])if ident==339 else pocket(self.specs[1],ident)
        if self.fail=='contour'and ident==400:v['header']['depth_native']=3.5
        return v
    def save(self):self.calls.append('save');self.saved=True;return 0
    def saved_hash(self,stage):
        self.report['source_transition']=dict(source_before_sha256=self.report['source_sha256'],source_after_sha256='b'*64,strict_save_return=0,document=deepcopy(self.loaded['root_pocket_saved_document']));return 'b'*64
    def export(self,*a):self.calls.append('export');return {'fixture':True}
    def finish(self):self.session_active=False
    def close(self):self.session_active=False

@pytest.fixture
def engine(synthetic,monkeypatch,tmp_path):
    failed,raw,fp,rp=synthetic;c=failed['initial_context'];specs=failed['profile_specs']
    l={k:deepcopy(c[k])for k in('guide_parameters','generated','tool_catalogue_ids','root_pocket_specs','root_pocket_saved_document','source_sha256')}
    l.update(first_native_pocket_failure={k:deepcopy(failed[k])for k in m.FAILURE_FIELDS},first_native_pocket_diagnostic={k:deepcopy(raw[k])for k in m.RAW_FIELDS},first_native_pocket_failure_pin=fp,first_native_pocket_diagnostic_pin=rp)
    monkeypatch.setattr(m.cl,'verify_all',lambda *a:{'all_fourteen_complete_streams_unchanged':True})
    def close(b,r):b.close();r['cleanup_session_active']=False
    monkeypatch.setattr(m.generation,'close_checked',close)
    def run(fail=None):
        report=dict(scope=m.SCOPE,module_pin=m.common._pin(m.__file__),source_path=failed['source_path'],source_sha256=failed['source_sha256'],ownership=deepcopy(failed['ownership']),profile_specs=deepcopy(specs),initial_context=deepcopy(l),messages={'subscribed':True,'disconnected':True,'active':False,'event_count':0})
        b=Fake(l,specs,report,fail);j=m.Journal(report,tmp_path/(str(fail)+'.json'),tmp_path/(str(fail)+'.once.json'));return m.run_backend(b,j,l,specs),b,j
    return run


def test_remaining_group_no_first_replay_and_no_full_before(engine):
    r,b,j=engine();assert r['status']=='saved_remaining_mixed_pocket_review_required',r.get('issue')
    assert b.calls==['sketch','pocket','full:configured','save','full:saved','export']
    assert list(r['actions'])==['CreateSketch:1','CreatePocket:1','SaveActiveDocument']
    assert m.validate_terminal(r)['continuation_ready']
    with pytest.raises(ValueError):j.pending('CreatePocket:1')

@pytest.mark.parametrize('fault',['before_binding','sketch_unknown','pocket_unknown','contour','parameters','solid'])
def test_failure_stops_without_save_or_replay(engine,fault):
    r,b,j=engine(fault);assert not r['continuation_ready']and 'save'not in b.calls
    if fault=='contour':assert len(r['new_features'])==2 and r['new_features'][1]['header']['depth_native']==3.5
    if fault=='before_binding':assert b.calls==[]

@pytest.mark.parametrize('fault',['first_id','adopted','baseline','old_route','saved_curve','saved_header','source','dirty','action','GTP','CL','cleanup'])
def test_terminal_rejects_false_acceptance(engine,fault):
    r,b,j=engine()
    if fault=='first_id':r['new_feature_ids'][0]=338
    elif fault=='adopted':r['adopted_first_pocket']['recreated']=True
    elif fault=='baseline':r['baseline_reused_from_failure_pin']['sha256']='f'*64
    elif fault=='old_route':r['saved']['binding']['operations'].reverse()
    elif fault=='saved_curve':r['saved_new_features'][0]['contours']['bottom']['chains'][0]['curves'][0]['start_native'][2]=7.5
    elif fault=='saved_header':r['saved_features'][0]['header']['native_id']=999
    elif fault=='source':r['source_transition']['source_before_sha256']='f'*64
    elif fault=='dirty':r['saved_cad']['needs_save']=True
    elif fault=='action':r['actions']['CreatePocket:0']={}
    elif fault=='GTP':r['GTP_attempted']=True
    elif fault=='CL':r['protected_cl']['all_fourteen_complete_streams_unchanged']=False
    elif fault=='cleanup':r['cleanup_session_active']=True
    with pytest.raises(ValueError):m.validate_terminal(r)

@pytest.fixture(scope='session')
def synthetic(tmp_path_factory):
    """Small invented data for workflow checks; not a machining qualification."""
    folder=tmp_path_factory.mktemp('mixed-finish-synthetic')
    specs=synthetic_specs();context=synthetic_context(specs)
    context['guide_parameters']['document']['needs_save']=True
    cad=dict(features=[dict(name='Original',type='Solid'),dict(name=specs[0]['plane_name'],type='RefPlane'),dict(name=specs[0]['sketch_name'],type='ProfileFeature')],solids=[{'box_m':[0]*6,'mass_raw':[1.,2.,3.,4.]}],needs_save=True)
    oldheaders=[dict(owner_setup_native_id=69,header={'native_id':80})]
    first=pocket(specs[0],339)
    failed=dict(scope=m.previous.SCOPE,module_pin=m.common._pin(m.previous.__file__),status='uncertain',phase='finished',cleanup_session_active=False,new_feature_ids=[339],actions={'CreatePocket:0':dict(status='pending',attempted=True,returned=False,readback_verified=False,native_dispatch_pending=True)},**{k:False for k in ('save_attempted','model_saved','readback_verified','continuation_ready','GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted')},issue={'type':'ValueError','locations':[dict(file='sw_cam_signed_mixed_profile.py',function='match_rows',line=164)]},adopted_first_sketch=dict(read_only=True,recreated=False),current_document=deepcopy(context['guide_parameters']['document']),created_cad_features=[],before=deepcopy(context['guide_parameters']['expected_parameters']),initial_context=context,ownership=deepcopy(context['ownership']),source_path='part',source_sha256='a'*64,profile_specs=specs,before_features=oldheaders,before_cad=cad)
    fp=folder/'failure.json';fp.write_text(json.dumps(failed),encoding='utf-8');failure_pin=m.common._pin(fp)
    raw=dict(scope=m.diagnostic.SCOPE,module_pin=m.common._pin(m.diagnostic.__file__),status='raw_feature_observed',phase='finished',cleanup_session_active=False,raw_feature_read_complete=True,readback_verified=True,feature_geometry_accepted=False,actions={},mutation_attempted=False,save_attempted=False,GTP_attempted=False,GOP_attempted=False,ownership=deepcopy(context['ownership']),source_path='part',source_sha256='a'*64,before_binding=deepcopy(failed['before']['binding']),after_binding=deepcopy(failed['before']['binding']),before_cad=deepcopy(cad),after_cad=deepcopy(cad),headers=oldheaders+[dict(owner_setup_native_id=69,header=deepcopy(first['header']))],raw_feature=first,failed_receipt_pin=failure_pin)
    rp=folder/'raw.json';rp.write_text(json.dumps(raw),encoding='utf-8')
    return failed,raw,failure_pin,m.common._pin(rp)
def test_planar_definition_rejects_historical_floor_assumption(synthetic):
    failed,raw,*_=synthetic
    value=m.verify_pocket(raw['raw_feature'],failed['profile_specs'][0],native_id=339)
    assert value['physical_floor_verified']is False
    assert value['native_bottom_contour_world_z_mm']==10.9
    assert value['derived_nominal_floor_world_z_mm']==7.5
    with pytest.raises(ValueError,match='mixed curve readback'):
        m.previous.verify_pocket(raw['raw_feature'],failed['profile_specs'][0],native_id=339)