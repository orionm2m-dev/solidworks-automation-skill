"""Pure admission and real Pydantic parse regressions; no COM application calls."""
import copy,json,hashlib,os,sys,ast
from pathlib import Path
from enum import Enum
from typing import *
import pytest
from pydantic import *
ROOT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',str(Path.home()/'.codex/skills/solidworks-automation')))
STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
# The sketch component is installed with its batch before this consumer.
component_stage=STAGE.parent/'cam_explicit_island_sketch_20261111'/'scripts'
if component_stage.exists():scripts.__path__.append(str(component_stage))
from scripts import sw_cam_explicit_island_authority as a
from scripts.sw_operation_guard import absolute_document_path

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,value):p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return digest(p)
def events():
    return dict(subscribed=True,active=False,disconnected=True,event_count=0,events=[],
        overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
def circle_spec():
    return dict(plane_axis='Z',plane_offset_mm=5.,sketch_name='OUTER',plane_name='OUTER_PLANE',
        profile=dict(kind='circle',center_model_mm=[0.,0.,5.],radius_mm=20.))
def cad(spec=None):
    return dict(pid=1234,path='C:/cad/qualification.SLDPRT',saved_file_sha256='b'*64,needs_save=False,
        spec=spec or circle_spec(),features=[dict(name='ISLAND_A',type='ProfileFeature')],solids=[],
        planes=[])
def circle_sequence():
    base=cad();before=copy.deepcopy(base);after=copy.deepcopy(before)
    created=[dict(name='OUTER_PLANE',type='RefPlane'),dict(name='OUTER',type='ProfileFeature')]
    after['features']+=created;after['needs_save']=True
    c=dict(status='ok',phase='finished',native_readback_verified=True,saved=False,
        CAD_solid_edit_attempted=False,CAM_calls=0,before=before,after=after,created_features=created)
    state=dict(document=dict(path=base['path'],title='qualification.SLDPRT',type=1,needs_save=True),
        saved_file_sha256='b'*64,feature_setups=[dict(native_id=10,feature_count=0)],operation_counts=[0],
        process_id=1234,machine_kind='mill_qualification')
    final=copy.deepcopy(state);final['document']['needs_save']=False;final['saved_file_sha256']='c'*64
    s=dict(status='review_required',phase='finished',action='save',machine_kind='mill_qualification',
        process_id=1234,messages=events(),native_call_returned=True,native_return_type='int',
        native_return_value=0,save_readback_verified=True,before=state,after=final,final_state=final,
        GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,generation_attempted=False,native_dispatch_pending=False)
    b=dict(source_sha256='b'*64,saved_cad=base)
    v=dict(process_id=1234,expected_document_path=base['path'],expected_source_sha256='c'*64)
    return b,c,s,v

def test_real_save_envelope_and_only_recorded_hash_transition():
    b,c,s,v=circle_sequence();spec,state=a.verify_circle_save(b,c,s,v)
    assert state['saved_file_sha256']=='c'*64 and state['needs_save']is False
    assert state['features']==c['after']['features']
    assert b['saved_cad']['saved_file_sha256']=='b'*64

@pytest.mark.parametrize('mutation',[
    lambda b,c,s,v:s.update(native_return_value=True),
    lambda b,c,s,v:s.update(save_readback_verified=False),
    lambda b,c,s,v:s.update(status='uncertain'),
    lambda b,c,s,v:s.update(native_dispatch_pending=True),
    lambda b,c,s,v:s['after'].update(operation_counts=[1]),
    lambda b,c,s,v:s.update(after={}),
    lambda b,c,s,v:s['before'].update(saved_file_sha256='d'*64),
    lambda b,c,s,v:c['before'].update(path='C:/cad/other.SLDPRT'),
    lambda b,c,s,v:c['before']['features'].append(dict(name='unwanted',type='Boss')),
    lambda b,c,s,v:c.update(CAM_calls=True),
    lambda b,c,s,v:s['messages'].update(subscription_error='late failure'),
    lambda b,c,s,v:s.update(GTP_attempted=True),
])
def test_saved_circle_admission_failclosed(mutation):
    b,c,s,v=circle_sequence();mutation(b,c,s,v)
    with pytest.raises((ValueError,KeyError)):a.verify_circle_save(b,c,s,v)

def batch_fixture(tmp_path):
    marker=tmp_path/'marker.json';receipt=tmp_path/'producer.json'
    specs=[dict(sketch_name='ISLAND_'+x)for x in 'ABCD'];v=dict(save_after_creation=True,
        expected_document_path='C:/cad/qualification.SLDPRT',expected_source_sha256='a'*64)
    cm=cad(specs[0]);cm['needs_save']=True;cm['saved_file_sha256']='a'*64
    iv=dict(capture_complete=True,features=[],operations=[])
    saved=copy.deepcopy(cm);saved['needs_save']=False;saved['saved_file_sha256']='b'*64
    observed=[dict(spec=spec,sketch_readback={'test_only':True})for spec in specs]
    before=dict(inventory=copy.deepcopy(iv),cad=copy.deepcopy(cm),sketches=copy.deepcopy(observed))
    after=dict(inventory=copy.deepcopy(iv),cad=copy.deepcopy(saved),sketches=copy.deepcopy(observed))
    actions={name:dict(attempted=True,returned=True,native_dispatch_pending=False)
        for name in ['CreateSketch:'+str(i)for i in range(4)]+['SaveActiveDocument']}
    actions['SaveActiveDocument'].update(native_return_type='int',native_return_value=0)
    r=dict(scope=a.BATCH_SCOPE,status='review_required',phase='finished',request=v,messages=events(),
        native_dispatch_pending=False,source_before_sha256='a'*64,source_after_sha256='b'*64,
        native_save=dict(native_call_returned=True,native_return_type='int',native_return_value=0,
            save_readback_verified=True,saved_file_sha256='b'*64),
        save_snapshots=dict(before=before,after=after),before=dict(inventory=iv,cad=cm),after=after,
        specs=specs,sketches=[],actions=actions,marker_path=str(marker),after_cleanup_document=dict(
            path=v['expected_document_path'],needs_save=False),initial_pins=[dict(path=v['expected_document_path'],sha256='a'*64)],
        current_pins=[dict(path=v['expected_document_path'],sha256='b'*64)])
    r.update({k:True for k in a.FLAGS})
    r.update({k:False for k in ('GOP_attempted','GTP_attempted','CAM_feature_creation_attempted','AddIsland_attempted','import_attempted','explicit_rebuild_attempted','tool_mutation_attempted','stock_edit_attempted')})
    for spec in specs:
        r['sketches'].append(dict(status='sketch_observed',native_readback_verified=True,before={'spec':spec},
            sketch_readback={},Save_attempted=False,CAM_feature_creation_attempted=False,
            AddIsland_attempted=False,GOP_attempted=False,GTP_attempted=False))
    put(marker,dict(scope=a.BATCH_SCOPE,target=v['expected_document_path'],receipt_path=str(receipt),
        actions=actions,status=r['status'],phase='finished'))
    return r,receipt,marker

def test_batch_durable_proof_does_not_recheck_historical_live_target(tmp_path,monkeypatch):
    r,p,_=batch_fixture(tmp_path);monkeypatch.setattr(a.sketches,'verify_readback',lambda *args:{})
    d=a.verify_completed_receipt(str(p),put(p,r))
    assert d['source_sha256']=='b'*64 and d['saved_cad']['needs_save']is False

@pytest.mark.parametrize('mutation',[
    lambda r:r.update(runtime_unchanged=False),
    lambda r:r.update(native_dispatch_pending=True),
    lambda r:r.update(status='uncertain'),
    lambda r:r['native_save'].update(native_return_value=True),
    lambda r:r['actions']['CreateSketch:2'].update(returned=False),
    lambda r:r['actions']['CreateSketch:2'].update(native_dispatch_pending=True),
    lambda r:r['current_pins'][0].update(path='C:/cad/other.SLDPRT'),
    lambda r:r['save_snapshots']['after']['inventory'].update(changed=True),
    lambda r:r['after_cleanup_document'].update(needs_save=True),
    lambda r:r['sketches'][0].update(native_readback_verified=False),
    lambda r:r['sketches'][0].update(AddIsland_attempted=True),
    lambda r:r['messages'].update(event_count=1,events=[{}]),
    lambda r:r.update(CAM_feature_creation_attempted=True),
])
def test_batch_invalid_partial_or_drift(tmp_path,monkeypatch,mutation):
    r,p,_=batch_fixture(tmp_path);monkeypatch.setattr(a.sketches,'verify_readback',lambda *args:{})
    mutation(r)
    with pytest.raises((ValueError,KeyError)):a.verify_completed_receipt(str(p),put(p,r))

def schema():
    text=(ROOT/'mcp-server/server.py').read_text(encoding='utf-8')
    nodes={n.name:n for n in ast.parse(text).body if isinstance(n,ast.ClassDef)}
    names=[]
    def take(name):
        if name in names:return
        node=nodes[name]
        for base in node.bases:
            if isinstance(base,ast.Name)and base.id in nodes:take(base.id)
        names.append(name)
    take('ResponseFormat');take('SolidWorksCamTargetInput')
    env=dict(globals());exec(compile(ast.Module(body=[nodes[n]for n in names],type_ignores=[]),'actual_schema_parents','exec'),env)
    fragment=(STAGE/'server.fragment').read_text(encoding='utf-8') if (STAGE/'server.fragment').exists() else text
    cls=next(n for n in ast.parse(fragment).body if isinstance(n,ast.ClassDef)and n.name=='SolidWorksCamExplicitIslandsInput')
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'explicit_schema','exec'),env)
    return env['SolidWorksCamExplicitIslandsInput']

def schema_request():
    d=dict(process_id=1234,expected_process_create_time=1234.5,addin_clsid='{00000000-0000-0000-0000-000000000001}',
        expected_sw_configuration='Default',expected_cam_configuration='Mill',qualification_only=True,
        acknowledge_definition_only=True,message_policy='vendor_default')
    for k in a.KEYS:
        if k.endswith('_path'):d[k]='C:/cad/'+k+'.json'
        if k.endswith('_sha256'):d[k]='a'*64
    d['expected_document_path']='C:/cad/qualification.SLDPRT'
    return d

def test_actual_inherited_schema_parses_and_retains_required_clsid():
    cls=schema();d=schema_request();assert cls(**d).process_id==1234
    d.pop('addin_clsid')
    with pytest.raises(ValidationError):cls(**d)

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_process_create_time',float('nan')),
    ('qualification_only',False),('expected_document_title','Other'),('unexpected',1)])
def test_actual_schema_rejects_wrong_scope(key,value):
    d=schema_request();d[key]=value
    with pytest.raises(ValidationError):schema()(**d)