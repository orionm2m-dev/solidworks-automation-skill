from copy import deepcopy
import inspect,ast,json,os,sys,types
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module, fixture_path
R=add_runtime()
m=required_module("sw_cam_serial_flat_finished_context")

@pytest.fixture
def evidence():
    binding=json.loads(fixture_path('cam_route17.json').read_text('utf-8-sig'))
    body={'box_m':[0.]*6,'mass_raw':[1.,2.,3.,4.]}
    doc={'path':'qualification/current.sldprt','title':'current.sldprt','type':1,'needs_save':False}
    owner={'process_id':123,'create_time':123.5,'executable':'SolidWorks.exe','alive':True}
    old=[dict(setup_index=0,feature_index=i,setup_native_id=69,geometry=dict(native_id=75+i,name='existing'+str(i),depth_native=1.))for i in range(2)]
    rows=[dict(owner_setup_native_id=69,header=deepcopy(r['geometry']))for r in old]
    full=[dict(owner_setup_native_id=69,header=dict(native_id=900+i,name='added'+str(i),depth_native=3.4),contours={'top':{},'bottom':{}})for i in range(2)]
    inventory=rows+[dict(owner_setup_native_id=69,header=deepcopy(v['header']))for v in full]
    state=dict(operations=deepcopy(binding['operations']),operation_setups=deepcopy(binding['operation_setups']),features=old,
        feature_setups=[dict(native_id=69,feature_count=2,name='setup',axis_native=[0.,0.,-1.])],document=doc,
        sw_reference={'feature_tree':[{'name':'body','type':'BaseBody'}],'solids':[body]})
    catalogue=[dict(native_id=250+i,CutDiameter=1.,tool_type_raw=1,Protrusion=10.)for i in range(18)]+[dict(native_id=273,CutDiameter=2.,tool_type_raw=1,Protrusion=26.),dict(native_id=338,CutDiameter=2.,tool_type_raw=1,Protrusion=22.)]
    source={k:{}for k in m.group.CURRENT_KEYS};source.update(state=state,ownership=owner,source_sha256='a'*64,
        long_cut_tool_checkpoint={'catalogue':catalogue,'registration':{}},deep_targets=[])
    creation=dict(checkpoint={'context':source},final_observation={'tools':deepcopy(catalogue)})
    current=dict(guide_parameters={'expected_parameters':{'binding':deepcopy(binding),'parameters':[{'operation_native_id':v}for v in (322,324,326,328,330,332,334,336)]},'document':deepcopy(doc),'configuration':{}},
        ownership=deepcopy(owner),tool_catalogue_ids=[v['native_id']for v in catalogue],root_pocket_native_inventory=inventory,root_pocket_full_features=full,
        root_pocket_cad={'features':[{'name':'body','type':'BaseBody'},{'name':'newsketch','type':'ProfileFeature'}],'solids':[deepcopy(body)],'needs_save':False},
        root_pocket_checkpoint_pin={'path':'authority.json','sha256':'b'*64},source_sha256='b'*64,deep_targets=[],first_sketch_failure={'large_history':'kept by immutable pin'},generated={'saved_cl':{}})
    return creation,current


def test_projection_uses_actual_inventory_and_preserves_inputs(evidence):
    creation,current=evidence;before=deepcopy(evidence);out=m.project_context(creation,current)
    assert evidence==before
    assert [v['geometry']for v in out['state']['features']]==[v['header']for v in current['root_pocket_native_inventory']]
    assert out['state']['feature_setups'][0]['feature_count']==4
    assert out['state']['operations']==current['guide_parameters']['expected_parameters']['binding']['operations']
    assert out['state']['document']==current['guide_parameters']['document']
    assert out['parent_pin']==current['root_pocket_checkpoint_pin']
    assert 'first_sketch_failure'not in out['deep_loaded']
    assert out['native_feature_inventory_verified']is True

@pytest.mark.parametrize('fault',['old_header','old_owner','missing','duplicate','new_id','new_header','new_owner','new_count','order','setup','tool_ids','catalogue','route','operation_setup','owner','solid','dirty'])
def test_projection_rejects_unverified_changes(evidence,fault):
    creation,current=evidence;rows=current['root_pocket_native_inventory'];full=current['root_pocket_full_features']
    if fault=='old_header':rows[0]['header']['depth_native']=2.
    if fault=='old_owner':rows[0]['owner_setup_native_id']=70
    if fault=='missing':rows.pop()
    if fault=='duplicate':rows.append(deepcopy(rows[-1]))
    if fault=='new_id':full[0]['header']['native_id']=75
    if fault=='new_header':full[0]['header']['depth_native']=4.
    if fault=='new_owner':full[0]['owner_setup_native_id']=70
    if fault=='new_count':full.pop()
    if fault=='order':rows[0],rows[1]=rows[1],rows[0]
    if fault=='setup':rows[-1]['owner_setup_native_id']=70;full[-1]['owner_setup_native_id']=70
    if fault=='tool_ids':current['tool_catalogue_ids'].reverse()
    if fault=='catalogue':creation['final_observation']['tools'][0]['CutDiameter']=99.
    if fault=='route':current['guide_parameters']['expected_parameters']['binding']['operations'][0]['suppressed']=True
    if fault=='operation_setup':current['guide_parameters']['expected_parameters']['binding']['operation_setups'][0]['native_id']=1
    if fault=='owner':current['ownership']['create_time']+=1
    if fault=='solid':current['root_pocket_cad']['solids'][0]['box_m'][0]=1.
    if fault=='dirty':current['root_pocket_cad']['needs_save']=True
    with pytest.raises(ValueError):m.project_context(creation,current)


def test_native_constructor_has_no_shadowed_callable(evidence):
    loaded=m.project_context(*evidence)
    backend=m.serial.NativeBackend(loaded,{},None,'clsid','tlb',{},lambda:None)
    assert isinstance(backend.capture,types.ModuleType)
    tree=ast.parse(inspect.getsource(m.serial.run_backend))
    names={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend'}
    assert names
    for name in names:assert callable(getattr(backend,name)),name


def test_dispatch_requires_explicit_authority_and_never_imports_requested_module():
    with pytest.raises(ValueError):m.dispatch_request({'action':m.ACTION,'params':{}})
    tree=ast.parse(Path(m.__file__).read_text('utf-8-sig'))
    assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id in ('eval','exec','__import__')for n in ast.walk(tree))


def test_unfinished_mixed_loader_failure_stops_before_projection(monkeypatch):
    monkeypatch.setattr(m.reconciliation,'verified_terminal',lambda *a,**k:({},None,{'path':'creator','sha256':'a'*64},{}))
    monkeypatch.setattr(m.mixed,'load_completed',lambda *a,**k:(_ for _ in ()).throw(ValueError('mixed packet not saved')))
    monkeypatch.setattr(m,'project_context',lambda *a:pytest.fail('No synthetic fallback projection allowed'))
    with pytest.raises(ValueError,match='not saved'):m.prepare_provider({'context_receipt_path':'part','context_receipt_sha256':'b'*64},{'path':'creator','sha256':'a'*64})

def test_exact_reviewed_live_partition_retains_all_other_roles():
    roles=sorted(m.PROOF_ONLY)+['retained_'+str(i)+'.py'for i in range(61)]
    live=[{'path':str((Path('fixture')/name).resolve()),'sha256':'a'*64}for name in roles]
    active,proof,audit=m.partition_pins(live,[])
    assert len(active)==63 and len(proof)==3
    assert {Path(v['path']).name for v in proof}==m.PROOF_ONLY
    assert {Path(v['path']).name for v in active}.issuperset({'retained_'+str(i)+'.py'for i in range(61)})
    assert audit['source_included_by_guard']is True


def test_missing_reviewed_phase_role_cannot_be_replaced_by_arbitrary_retirement():
    roles=sorted(m.PROOF_ONLY)+['retained_'+str(i)+'.py'for i in range(61)]
    live=[{'path':str((Path('fixture')/name).resolve()),'sha256':'a'*64}for name in roles]
    live[0]['path']=str((Path('fixture')/'still_live_unknown.py').resolve())
    with pytest.raises(ValueError):m.partition_pins(live,[])



def test_compact_current_adoption_carriers_keep_exact_proof_pins(evidence):
    creation,current=evidence
    current['first_native_pocket_failure']={'large':'historical projection'}
    current['first_native_pocket_diagnostic']={'large':'historical raw projection'}
    current['first_native_pocket_failure_pin']={'path':'immutable/failure.json','sha256':'a'*64}
    current['first_native_pocket_diagnostic_pin']={'path':'immutable/raw.json','sha256':'b'*64}
    out=m.project_context(creation,current)['deep_loaded']
    assert 'first_native_pocket_failure'not in out and 'first_native_pocket_diagnostic'not in out
    assert out['first_native_pocket_failure_pin']==current['first_native_pocket_failure_pin']
    assert out['first_native_pocket_diagnostic_pin']==current['first_native_pocket_diagnostic_pin']
