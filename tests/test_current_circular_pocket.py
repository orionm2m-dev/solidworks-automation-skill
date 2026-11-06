from pathlib import Path
from copy import deepcopy
import json
import pytest
from test_current_saved_parameter_fields import fixture as parameter_fixture
from scripts import sw_cam_current_circular_pocket as m
from scripts import sw_cam_current_circular_delta as d


def fixture(tmp_path):
    original,_,candidate=parameter_fixture();original.pop('own_nc')
    generic=dict(native_id=30,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,tool_type_raw=1,cut_diameter_native=12.,protrusion_native=50.)
    for i,row in enumerate(original['operations']):
        row.update(setup_index=0,setup_native_id=50,operation_index=i,mill_operation_type=0 if i!=1 else 1,base_operation_type=0)
        row['assigned_tool']=deepcopy(generic)
    for row in original['operation_parameters']:row['tool']['generic']=deepcopy(generic)
    original['parameter_batch']['source_tools']['30']['generic']=deepcopy(generic)
    original['parameter_batch']['toolcrib_catalogue'][0]=deepcopy(generic)
    document=dict(path=str(tmp_path/'part.sldprt'),title='part',type=1,needs_save=False)
    header=dict(native_id=20,volume_type=11,subtype_raw=0,shape_raw=2,suppressed=False,name='reference',axis_native=[0.,0.,1.],depth_native=7.6,bounds_native=[-1.,-1.,7.6],start_native=[0.,0.,0.])
    original.update(document=document,capture_complete=True,target_header=header,number_of_steps_raw=3,profile=dict(complete_step_coverage=True,steps=[1,2,3]),features=[dict(setup_native_id=40,geometry=dict(native_id=x)) for x in (20,21)],feature_setups=[dict(index=0,native_id=40,axis_native=[0.,0.,1.],origin_native=[0.,0.,0.],feature_ids=[20,21])],operation_setups=[dict(index=0,native_id=50,operation_count=3)],selected_operation_setup=dict(native_id=50,feature_setup_native_id=40,operation_count=3),operation_counts=[3],operation_count=3,operation_setup_count=1,operation_inventory_scope='observed',strategy_diagnostics={},default_operation_catalogues=[])
    spec=dict(plane_axis='Z',plane_offset_mm=2.,plane_name='BOUND_PLANE',sketch_name='BOUND_CIRCLE',profile=dict(kind='circle',center_model_mm=[0.,0.,2.],radius_mm=5.))
    v=dict(mode='current_saved',action='prepare',process_id=123,expected_process_create_time=100.25,expected_document_path=document['path'],expected_source_sha256='a'*64,configuration_receipt_path=str(tmp_path/'config.json'),configuration_receipt_sha256='c'*64,anchor_operation_native_id=10,owner_setup_native_id=40,operation_setup_native_id=50,insert_after_operation_native_id=12,expected_setup_axis=[0.,0.,1.],sketch_spec=spec,depth_native=2.,reverse_direction=False,rough_definition=dict(default_operation_name='Cavity',default_operation_id=135),expected_default_tool=dict(tool_type_raw=1,cut_diameter_native=12.,protrusion_native=50.),candidate_tool_native_id=32,expected_candidate_consumer_ids=[],receipt_path=str(tmp_path/'prepare.json'),attempt_registry_path=str(tmp_path),prepare_receipt_path=None,prepare_receipt_sha256=None,qualification_only=True,save_after_verified=True,message_policy='vendor_default')
    oldbinding=dict(expected_process_create_time=100.25,expected_feature_setup_native_id=40,expected_operation_setup_native_id=50,candidate_tool_native_id=32,expected_operation_native_ids=[10,11,12])
    loaded=dict(state=original,binding=oldbinding,pin=dict(path=str(tmp_path/'config.json'),sha256='c'*64),pins={},recovery_pins={},addin_clsid='{11111111-2222-3333-4444-555555555555}')
    before=m.reference_baseline(original)
    before['sketch_state']=dict(pid=123,path=document['path'],saved_file_sha256='a'*64,needs_save=False,features=[dict(name='Origin',type='OriginProfileFeature'),dict(name='XY',type='RefPlane')],planes=[dict(name='XY',origin_m=[0.,0.,0.],normal=[0.,0.,1.])],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.,2.,3.,4.])],spec=deepcopy(spec))
    return v,loaded,before


def sketch_state(before,v):
    out=deepcopy(before);out['document']['needs_save']=True;out['sketch_state']['needs_save']=True
    out['sketch_state']['features'] += [dict(name='BOUND_PLANE',type='RefPlane'),dict(name='BOUND_CIRCLE',type='ProfileFeature')]
    out['sketch_state']['planes'].append(dict(name='BOUND_PLANE',origin_m=[0.,0.,.002],normal=[0.,0.,1.]))
    out['measured_circle']=dict(center_model_m=[0.,0.,.002],radius_m=.005,normal_model=[0.,0.,1.])
    out['measured_sketch']=dict(entities=[dict(type='circle',center_model_m=[0.,0.,.002],radius_m=.005)],model_to_sketch_transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,-.002,1.,0.,0.,0.],readback_tolerance_m=1e-8)
    return out

def feature_state(sketch,v):
    out=deepcopy(sketch);out['features'].append(dict(setup_native_id=40,geometry=dict(native_id=22)));out['feature_setups'][0]['feature_ids'].append(22)
    out['target_header']=dict(native_id=22,volume_type=2,subtype_raw=0,shape_raw=2,suppressed=False,name='pocket',axis_native=[0.,0.,1.],start_native=[0.,0.,2.],depth_native=2.,bounds_native=[10.,10.,2.])
    curve=dict(curve_type=2,centre_native=[0.,0.,2.],radius_native=5.,normal_native=[0.,0.,1.],direction_raw=0)
    out['target_geometry']=dict(out['target_header'],island_count=0,top_curves_native=[deepcopy(curve)],bottom_curves_native=[deepcopy(curve)])
    out['target_catalogues']=[dict(operation_type=0,entries=[dict(name='Cavity',default_operation_id=135)])]
    return out

def insert_state(feature,v,new_tool=False):
    out=deepcopy(feature);row=deepcopy(out['operations'][0]);row.update(native_id=13,operation_index=3,linked_feature_ids=[22])
    if new_tool:row['assigned_tool']['native_id']=33;out['reference_parameter_observation']['parameter_batch']['toolcrib_catalogue'].append(deepcopy(row['assigned_tool']))
    out['operations'].append(row);out['operation_count']+=1;out['operation_counts'][0]+=1;out['operation_setups'][0]['operation_count']+=1;out['selected_operation_setup']['operation_count']+=1
    old=out['reference_parameter_observation'];param=deepcopy(old['operation_parameters'][0]);param.update(operation_native_id=13,feature_native_id=22);param['tool']['generic']=deepcopy(row['assigned_tool']);param['levels']=dict(depth=2.)
    out['operation_parameters']=[param];out['parameter_capture_complete']=True;out['parameter_batch']=deepcopy(old['parameter_batch']);out['parameter_batch']['target_nc']={'13':deepcopy(old['parameter_batch']['target_nc']['10'])};out['parameter_batch']['target_nc']['13']['operation_native_id']=13
    if new_tool:out['parameter_batch']['toolcrib_catalogue'].append(deepcopy(row['assigned_tool']));out['parameter_batch']['source_tools']={'33':deepcopy(param['tool'])}
    return out


def saved_state(after):
    out=deepcopy(after);out['document']['needs_save']=False;out['sketch_state']['needs_save']=False;out['sketch_state']['saved_file_sha256']='b'*64;return out


def test_real_delta_chain_and_native_shaped_single_rough(tmp_path):
    v,loaded,a=fixture(tmp_path);b=sketch_state(a,v);c=feature_state(b,v);e=insert_state(c,v);f=saved_state(e)
    d.verify_sketch(a,b,['BOUND_PLANE','BOUND_CIRCLE']);d.verify_feature(b,c,v,22);row=d.verify_insert(c,e,v,13,22);d.verify_saved(e,f,'b'*64)
    assert row['native_id']==13 and d.verify_geometry(c,v,22)['nominal_end_is_measured_bottom'] is False

@pytest.mark.parametrize('sign',[1,-1])
def test_signed_separated_bottom(tmp_path,sign):
    v,_,a=fixture(tmp_path);c=feature_state(sketch_state(a,v),v);c['target_geometry']['bottom_curves_native'][0]['centre_native']=[0.,0.,2.+sign*2.]
    if sign==1:assert d.verify_geometry(c,v,22)['nominal_end_is_measured_bottom'] is True
    else:
        with pytest.raises(ValueError):d.verify_geometry(c,v,22)

@pytest.mark.parametrize('defect',['axis','start','depth','radius','old_path','old_suppression','old_nc','old_tool','body','reference_profile'])
def test_unexpected_delta_rejected(tmp_path,defect):
    v,_,a=fixture(tmp_path);b=sketch_state(a,v);c=feature_state(b,v)
    if defect=='axis':c['target_header']['axis_native']=[0.,0.,-1.]
    elif defect=='start':c['target_header']['start_native'][2]+=1
    elif defect=='depth':c['target_header']['depth_native']+=1
    elif defect=='radius':c['target_geometry']['top_curves_native'][0]['radius_native']+=1
    elif defect=='old_path':c['operations'][2]['toolpath_record_counts']=[100]
    elif defect=='old_suppression':c['operations'][0]['suppressed']=True
    elif defect=='old_nc':c['reference_parameter_observation']['parameter_batch']['target_nc']['10']['feeds_compensation']['XYFeed']+=1
    elif defect=='old_tool':c['operations'][0]['assigned_tool']['cut_diameter_native']+=1
    elif defect=='body':c['sketch_state']['solids'][0]['mass_raw'][0]+=1
    else:c['reference_profile']['steps'][0]=4
    with pytest.raises(ValueError):d.verify_feature(b,c,v,22)


def test_one_observed_new_default_tool_allowed_old_crib_preserved(tmp_path):
    v,_,a=fixture(tmp_path);c=feature_state(sketch_state(a,v),v);e=insert_state(c,v,True);assert d.verify_insert(c,e,v,13,22)['assigned_tool']['native_id']==33
    e['reference_parameter_observation']['parameter_batch']['toolcrib_catalogue'][0]['cut_diameter_native']=13.
    with pytest.raises(ValueError):d.verify_insert(c,e,v,13,22)


@pytest.fixture
def env(tmp_path,monkeypatch):
    v,loaded,before=fixture(tmp_path);e=dict(v=v,loaded=loaded,before=before,calls=[],fail=None,hook=None)
    monkeypatch.setattr(m,'load_inputs',lambda *a,**k:deepcopy(loaded));monkeypatch.setattr(m.batch,'load_inputs',lambda *a,**k:dict(authority=dict(definition_mode='selected_continue')));monkeypatch.setattr(m,'preflight',lambda *a:dict(native_calls=0))
    class Session:
        def summary(self):return dict(active=False,subscribed=True,disconnected=True,event_count=0)
    class Context:
        def __init__(self,sw,clsid,tlb,request,loaded,report,persist,runtime_check):self.request=request;self.state=deepcopy(before);self.report=report;self.persist=persist;self.source='a'*64;self.created_names=[];self.session=Session()
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def boundary(self):
            if e.get('unsafe'):raise ValueError('event/runtime/source stop')
        def identity(self):return self.state['document']
        def capture(self,label,*a,**k):
            self.boundary();state=deepcopy(self.state)
            if e.get('mass_jitter'):
                e['mass_capture_count']=e.get('mass_capture_count',0)+1
                state['sketch_state']['solids'][0]['mass_raw'][0] *= 1.+e['mass_capture_count']*1e-13
            if e.get('mass_bad_stage')==label:state['sketch_state']['solids'][0]['mass_raw'][0] *= 1.01
            if e['fail']==label:state['operations'][2]['toolpath_record_counts']=[100]
            self.report[label]=state;self.report['captures'].append(label);self.persist();return state
        def dispatch(self,name,pending,returned,update):
            e['calls'].append(name);pending();update();returned(dict(return_type='pointer',nonnull=True))
            if e['hook']==name:e['unsafe']=True
            self.boundary()
        def create_sketch(self,b,pending,returned):
            def change():self.state=sketch_state(self.state,v);self.created_names=['BOUND_PLANE','BOUND_CIRCLE']
            self.dispatch('sketch',pending,returned,change)
        def create_feature(self,pending,returned):self.dispatch('feature',pending,returned,lambda:setattr(self,'state',feature_state(self.state,v)));return 22
        def insert_rough(self,state,pending,returned):self.dispatch('insert',pending,returned,lambda:setattr(self,'state',insert_state(self.state,v)));return 13
        def save(self,pending,returned):
            e['calls'].append('save');pending();self.source='b'*64;self.state=saved_state(self.state);returned(0)
            if e['hook']=='save':e['unsafe']=True
            self.boundary()
    def run(action,**kw):
        args=dict(v,action=action,receipt_path=str(tmp_path/(action+'.json')),**kw)
        if action=='apply':args.update(prepare_receipt_path=str(tmp_path/'prepare.json'),prepare_receipt_sha256=m._file_hash(tmp_path/'prepare.json'))
        return m.run_current_circular_pocket(None,loaded['addin_clsid'],'metadata',runtime_check=lambda:None,context_factory=Context,**args)
    e['run']=run;return e


def test_lifecycle_prepare_single_apply_checked_save_no_replay(env):
    p=env['run']('prepare');assert p['may_apply'] and p['readback_verified'],p
    r=env['run']('apply');assert r['readback_verified'] and r['model_saved'],r
    assert env['calls']==['sketch','feature','insert','save'] and [x['kind'] for x in r['actions']]==['CreateSketch','CreateMillFeature2','InsertOperation','SaveActiveDocument']
    assert r['saved']==r['confirm_saved'] and all(x['readback_verified'] for x in r['actions']) and r['new_feature_native_id']==22 and r['new_operations'][0]['native_id']==13
    again=env['run']('apply');assert again['status']=='error' and env['calls']==['sketch','feature','insert','save']

@pytest.mark.parametrize('stage,allowed',[('after_sketch',['sketch']),('after_feature',['sketch','feature']),('after_insert',['sketch','feature','insert'])])
def test_bad_capture_stops_next_mutation_durable_partial(env,stage,allowed):
    assert env['run']('prepare')['readback_verified'];env['fail']=stage;r=env['run']('apply')
    assert r['status']=='uncertain' and not r['readback_verified'] and not r['model_saved'] and env['calls']==allowed
    stored=json.loads(Path(env['v']['receipt_path']).with_name('apply.json').read_text(encoding='utf-8'));assert stored[stage]['operations'][2]['toolpath_record_counts']==[100]

@pytest.mark.parametrize('stage',['sketch','feature','insert','save'])
def test_returned_native_outcome_preserved_on_unsafe_boundary(env,stage):
    assert env['run']('prepare')['readback_verified'];env['hook']=stage;r=env['run']('apply')
    assert r['status']=='uncertain' and not r['model_saved'] and r['actions'][-1]['returned'] and not r['actions'][-1]['readback_verified']
    assert env['calls']==['sketch','feature','insert','save'][:['sketch','feature','insert','save'].index(stage)+1]
    stored=json.loads(Path(env['v']['receipt_path']).with_name('apply.json').read_text(encoding='utf-8'));assert stored['actions'][-1]['returned']
