import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import pytest

S=Path(__file__).resolve().parents[1]
R=Path(os.environ.get('SW_SKILL_TEST_ROOT',str(S)))
sys.path.insert(0,str(R))
import scripts
scripts.__path__.insert(0,str(S/'scripts'))
from scripts import sw_cam_mill_selected_plan as m
from scripts import sw_cam_mill_selected_plan_evidence as e
from scripts import sw_cam_mill_selected_plan_context as c

SOURCE='a'*64
SAVED='b'*64
SELECTED=dict(feature_native_id=79,owner_setup_native_id=69,volume_type=2,shape=2,island_count=5,include_contours=False)

def state():
    feats=[]
    for i in range(18):
        fid=75+i
        feats.append(dict(setup_index=0,feature_index=i,setup_native_id=69,geometry=dict(
            native_id=fid,volume_type=2,subtype_raw=0,shape_raw=2,suppressed=False,name='f'+str(fid),
            axis_native=[0.,0.,1.],depth_native=4.8,bounds_native=[1.,2.,3.],start_native=[0.,0.,12.3])))
    d=dict(document=dict(path='C:/test/part.sldprt',title='part.sldprt',type=1,needs_save=False),
        saved_file_sha256=SOURCE,current_machine={'machine_type':1},mill_catalogue=[],
        feature_setups=[dict(native_id=69,feature_count=18)],material_raw='304L',
        extend_holes_to_stock=False,unit_record_raw=None,unit_record_status='unavailable',
        recognition_options={'option':True},recognition_method={'value':1},stock={'type':4},
        sw_reference={'feature_tree':[],'solids':[]},visible_solid_body_count=1,all_solid_body_count=1,
        features=feats,selected_profile_headers={'native_id':79,'sketch_count':6},
        operation_counts=[0],operation_setups=[dict(index=0,native_id=93,operation_count=0)],
        operation_count=0,operation_setup_count=1,operations=[],
        operation_inventory_scope='bounded_raw_id_links_flags_counts_and_generic_tool')
    return d

def planned(before):
    out=deepcopy(before)
    out['document']['needs_save']=True
    out['operations']=[dict(setup_index=0,setup_native_id=93,operation_index=0,native_id=110,
        mill_operation_type=0,base_operation_type=0,suppressed=False,toolpath_generated=False,
        linked_feature_ids=[79],toolpath_record_counts=[],
        assigned_tool={'native_id':111,'is_mill_tool':True,'cut_diameter_native':6.,'protrusion_native':25.})]
    out['operation_counts']=[1];out['operation_count']=1;out['operation_setups'][0]['operation_count']=1
    return out

@pytest.mark.parametrize('change',[
    lambda a:a['features'][0]['geometry'].update(depth_native=5.),
    lambda a:a['features'].reverse(),
    lambda a:a['features'][1].update(setup_native_id=99),
    lambda a:a['selected_profile_headers'].update(sketch_count=7),
    lambda a:a['stock'].update(type=3),
    lambda a:a['recognition_options'].update(option=False),
    lambda a:a.update(material_raw='AL'),
    lambda a:a.update(saved_file_sha256='c'*64),
    lambda a:a['operations'][0].update(linked_feature_ids=[80]),
    lambda a:a['operations'][0].update(linked_feature_ids=[79,80]),
    lambda a:a['operations'][0].update(suppressed=True),
    lambda a:a['operations'][0].update(toolpath_generated=True),
    lambda a:a['operations'][0].update(toolpath_record_counts=[1]),
    lambda a:a['operations'][0].update(native_id=True),
    lambda a:a['operations'][0].update(operation_index=3),
    lambda a:a['operations'][0].update(setup_native_id=71),
    lambda a:a['operation_setups'][0].update(native_id=71),
    lambda a:a.update(operation_counts=[2]),
    lambda a:a.update(operation_count=0),
    lambda a:a['operation_setups'].append(dict(index=1,native_id=72,operation_count=0))
])
def test_plan_rejects_each_unexpected_delta(change):
    b=state();a=planned(b);change(a)
    with pytest.raises(ValueError):m.verify_plan_delta(b,a,79,93)

def test_exact_delta_and_zero_record_container():
    b=state();a=planned(b);a['operations'][0]['toolpath_record_counts']=[0]
    assert len(m.verify_plan_delta(b,a,79,93))==1
    with pytest.raises(ValueError):m.verify_plan_delta(a,a,79,93)

def test_save_permits_only_source_and_dirty():
    b=planned(state());a=deepcopy(b);a['saved_file_sha256']=SAVED;a['document']['needs_save']=False
    assert e.same_saved_context(b,a)
    for target in ('features','operations','stock'):
        bad=deepcopy(a)
        if target=='features':bad[target][0]['geometry']['name']='changed'
        elif target=='operations':bad[target][0]['assigned_tool']['cut_diameter_native']=2.
        else:bad[target]['type']=2
        assert not e.same_saved_context(b,bad)

class Recovery:
    def check_files(self):pass
def evidence():
    b=state()
    return e.SelectedPlanEvidence([],SELECTED,b['selected_profile_headers'],e.observed_context(b),{},Recovery())

def test_evidence_verifies_observed_scope_not_whole_geometry():
    ev=evidence();a=planned(state());a['saved_file_sha256']=SAVED
    assert ev.verify(a)
    a['features'][17]['geometry']['axis_native']=[1.,0.,0.]
    with pytest.raises(ValueError):ev.verify(a)

class Session:
    def __init__(self,*args):self.active=False;self.entered=False
    def __enter__(self):self.active=True;self.entered=True;return self
    def __exit__(self,*args):self.active=False
    def summary(self):return dict(subscribed=self.entered,active=self.active,disconnected=self.entered and not self.active,event_count=0)

@pytest.fixture
def engine(monkeypatch,tmp_path):
    env=types.SimpleNamespace(current=state(),calls=[],captures=[],failure=None,event_failure=False,
        result=0,evidence=evidence(),plan=None,plan_pin=None)
    import scripts.sw_cam_events as events
    class ES(Session):
        def summary(self):
            out=super().summary()
            if env.event_failure:out['event_count']=1
            return out
    monkeypatch.setattr(events,'CamMessageSession',ES)
    monkeypatch.setattr(m,'validate_selected_plan_request',lambda **k:None)
    monkeypatch.setattr(m,'load_selected_plan_evidence',lambda **k:env.evidence)
    monkeypatch.setattr(m,'_bootstrap',lambda *a:'app')
    monkeypatch.setattr(m,'_typed',lambda raw,*a:raw)
    monkeypatch.setattr(m,'raw_part_identity',lambda sw:deepcopy(env.current['document']))
    monkeypatch.setattr(m,'_file_hash',lambda path:env.current['saved_file_sha256'])
    monkeypatch.setattr(m,'exact_dispatch_target',lambda *a:'feature79')
    def capture(*args,**kwargs):
        phase=kwargs['diagnostic']['phase'];env.captures.append(phase)
        if env.failure==phase:raise RuntimeError('capture failure')
        return deepcopy(env.current),dict(app='app',selected_feature='feature79')
    monkeypatch.setattr(m,'capture_selected_plan',capture)
    def member(obj,name,*args):
        if name=='GetProcessID':return 16516
        env.calls.append((obj,name,args))
        if name=='GenerateOpPlan':
            env.current=planned(env.current)
            if env.failure=='neighbor_delta':env.current['features'][0]['geometry']['name']='unexpected'
            if env.failure=='native':raise RuntimeError('native failure')
        elif name=='SaveActiveDocument':
            env.current['saved_file_sha256']=SAVED;env.current['document']['needs_save']=False
            if env.failure=='save_delta':env.current['operations'][0]['linked_feature_ids']=[80]
            if env.failure=='native':raise RuntimeError('native failure')
        else:raise AssertionError(name)
        if env.failure=='event':env.event_failure=True
        return env.result
    monkeypatch.setattr(m,'_member',member)
    monkeypatch.setattr(m,'load_plan_receipt',lambda *a,**k:(env.plan,env.plan_pin))
    monkeypatch.setattr(m,'read_pin',lambda *a:(env.plan,env.plan_pin))
    def run(action='plan_once'):
        n=len(list(tmp_path.glob('*.json')))
        args=dict(process_id=16516,expected_document_path='C:/test/part.sldprt',expected_source_sha256=SOURCE,
            expected_feature_native_id=79,expected_owner_setup_native_id=69,expected_volume_type=2,
            expected_shape=2,expected_island_count=5,expected_operation_setup_native_id=93,action=action,qualification_only=True,
            acknowledge_disposable_copy=True,receipt_path=str(tmp_path/(str(n)+'.json')),
            profile_headers_receipt_path='h',profile_headers_receipt_sha256=SOURCE,
            profile_indexed_receipt_path='i',profile_indexed_receipt_sha256=SOURCE,
            diagnostic_inventory_receipt_path='d',diagnostic_inventory_receipt_sha256=SOURCE)
        if action=='save_checked':args.update(plan_receipt_path='plan',plan_receipt_sha256=SOURCE)
        return m.selected_mill_plan_lifecycle('sw','clsid','tlb',**args)
    env.run=run;return env

def test_plan_then_save_exactly_two_mutations(engine):
    p=engine.run()
    assert p['readback_verified'] and p['operation_delta_verified']
    assert not p['model_saved'] and not p['GTP_attempted']
    assert engine.calls==[('feature79','GenerateOpPlan',(1,))]
    engine.plan=p;engine.plan_pin={'sha256':SOURCE};engine.captures=[]
    s=engine.run('save_checked')
    assert s['readback_verified'] and s['save_readback_verified'] and s['model_saved']
    assert s['saved_file_sha256']==SAVED and not s['reopen_persistence_verified']
    assert engine.calls==[('feature79','GenerateOpPlan',(1,)),('app','SaveActiveDocument',())]
    assert engine.captures==['before','after']

@pytest.mark.parametrize('failure',['before','after','native','neighbor_delta','event'])
def test_failed_plan_never_replays_or_saves(engine,failure):
    engine.failure=failure;r=engine.run()
    assert not r['readback_verified'] and not r['model_saved']
    assert len(engine.calls)==(0 if failure=='before' else 1)
    assert all(name=='GenerateOpPlan' for _,name,_ in engine.calls)
    assert r['status']==('error' if failure=='before' else 'uncertain')

@pytest.mark.parametrize('value',[True,False,None,1,-1,'0'])
def test_nonzero_or_noninteger_hresult_stops(engine,value):
    engine.result=value;r=engine.run()
    assert r['status']=='uncertain' and not r['readback_verified']
    assert len(engine.calls)==1 and engine.captures==['before']

def test_unknown_gop_second_request_cannot_replay(engine):
    engine.failure='after';r=engine.run();assert r['status']=='uncertain'
    engine.failure=None;r=engine.run()
    assert r['status']=='error' and len(engine.calls)==1

def test_save_rejects_preexisting_context_change(engine):
    p=engine.run();engine.plan=p;engine.plan_pin={'sha256':SOURCE}
    engine.current['operations'][0]['assigned_tool']['cut_diameter_native']=7.
    r=engine.run('save_checked')
    assert r['status']=='error' and len(engine.calls)==1

@pytest.mark.parametrize('failure',['after','native','save_delta','event'])
def test_failed_save_is_uncertain_and_never_retried(engine,failure):
    p=engine.run();engine.plan=p;engine.plan_pin={'sha256':SOURCE}
    engine.failure=failure;r=engine.run('save_checked')
    assert r['status']=='uncertain' and not r['model_saved']
    assert len(engine.calls)==2

def test_exact_dispatch_target_backcheck_and_owner(monkeypatch):
    native={'doc':'doc','selected_feature':'base'}
    calls=[]
    monkeypatch.setattr(c,'_object_id',lambda doc,obj,read: {'base':79,'raw':79,'owner':69}[obj])
    def read(obj,name,*args):
        calls.append(name)
        return {'GetCWObjectFromID':('raw',True),'GetOwner':'owner','Suppressed':False}[name]
    assert c.exact_dispatch_target(native,evidence(),read)=='base'
    assert calls==['GetCWObjectFromID','GetOwner','Suppressed']
    monkeypatch.setattr(c,'_object_id',lambda *a:80)
    with pytest.raises(ValueError):c.exact_dispatch_target(native,evidence(),read)

def test_no_forbidden_native_writes_in_source():
    modules=('sw_cam_mill_selected_plan.py','sw_cam_mill_selected_plan_context.py',
             'sw_cam_mill_selected_plan_evidence.py')
    texts=''.join((S/'scripts'/name).read_text(encoding='utf-8') for name in modules)
    for forbidden in ['GenerateToolpath','SetTool','GenerateAll','ExtractMachinableFeatures','DeleteFeature']:
        assert forbidden not in texts
    assert "method='GenerateOpPlan';args=(1,)" in texts
    assert "method='SaveActiveDocument';args=()" in texts

def test_schema_has_only_two_actions_and_nonread_only_tool():
    tree=ast.parse((S/'mcp-server'/'server.py').read_text(encoding='utf-8-sig'))
    schema=next(node for node in tree.body if isinstance(node,ast.ClassDef)
                and node.name=='SolidWorksCamSelectedMillPlanInput')
    action=next(node for node in schema.body if isinstance(node,ast.AnnAssign)
                and isinstance(node.target,ast.Name) and node.target.id=='action')
    assert isinstance(action.annotation,ast.Subscript)
    assert isinstance(action.annotation.value,ast.Name) and action.annotation.value.id=='Literal'
    assert ast.literal_eval(action.annotation.slice)==('plan_once','save_checked')
    tool=next(node for node in tree.body if isinstance(node,ast.FunctionDef)
              and node.name=='solidworks_cam_selected_mill_plan_lifecycle')
    decorator=next(node for node in tool.decorator_list if isinstance(node,ast.Call)
                   and isinstance(node.func,ast.Attribute) and node.func.attr=='tool')
    metadata={item.arg:ast.literal_eval(item.value) for item in decorator.keywords
              if item.arg in ('name','annotations')}
    assert metadata['name']=='solidworks_cam_selected_mill_plan_lifecycle'
    assert metadata['annotations']['readOnlyHint'] is False
    assert metadata['annotations']['idempotentHint'] is False

def test_real_saved_anchors_load_without_promoting_diagnostics():
    if not os.environ.get('CAM_SAVED_EVIDENCE_ROOT'):
        pytest.skip('Saved native evidence is not configured for this optional file-only case')
    base=Path(os.environ['CAM_SAVED_EVIDENCE_ROOT'])/'resume_20261028'
    names={'profile_headers_receipt':'12_profile_headers_receipt.json',
           'profile_indexed_receipt':'14_profile_indexed_receipt.json',
           'diagnostic_inventory_receipt':'13_diagnostic_inventory_receipt.json'}
    args={};hashes={}
    for key,name in names.items():
        p=base/name;b=p.read_bytes();sha=hashlib.sha256(b).hexdigest();hashes[p]=sha
        args[key+'_path']=str(p);args[key+'_sha256']=sha
    h=json.loads((base/names['profile_headers_receipt']).read_text(encoding='utf-8'))
    ev=e.load_selected_plan_evidence(process_id=h['process_id'],expected_document_path=h['document']['path'],
        expected_source_sha256=h['saved_file_sha256'],selected=h['selected'],**args)
    assert len(ev.context['features'])==18 and not ev.summary()['diagnostic_baseline_promoted']
    d=json.loads((base/names['diagnostic_inventory_receipt']).read_text(encoding='utf-8'))
    assert d['status']=='error' and d['readback_verified'] is False
    for p,sha in hashes.items():assert hashlib.sha256(p.read_bytes()).hexdigest()==sha
