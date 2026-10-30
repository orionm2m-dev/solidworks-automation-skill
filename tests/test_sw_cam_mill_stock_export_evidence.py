"""Synthetic unit data only: no native Q16, personal paths or project geometry."""
from copy import deepcopy
from pathlib import Path
import hashlib,importlib.util,json,sys
import pytest
from scripts import sw_cam_mill_stock_export_evidence as g
from scripts.sw_cam_stock_mesh_compare import compare_stock_meshes
import struct


def synthetic_receipt(tmp_path):
    # Explicitly synthetic cube and empty CAM context. No native/project artifacts.
    native_dir=tmp_path/'native';native_dir.mkdir()
    a=tmp_path/'input.stl';b=native_dir/'stock.stl'
    xy=[(-1.,-1.),(1.,-1.),(1.,1.),(-1.,1.)]
    bottom=[(x,y,-1.) for x,y in xy];top=[(x,y,1.) for x,y in xy]
    triangles=[(bottom[0],bottom[i+1],bottom[i]) for i in (1,2)]
    triangles += [(top[0],top[i],top[i+1]) for i in (1,2)]
    for i in range(4):
        j=(i+1)%4;triangles += [(bottom[i],bottom[j],top[j]),(bottom[i],top[j],top[i])]
    def stl(path,header,rows):
        raw=bytearray(header.ljust(80,b' '))+struct.pack('<I',len(rows))
        for row in rows:raw+=struct.pack('<12fH',0.,0.,0.,*(v for xyz in row for v in xyz),0)
        path.write_bytes(raw)
    stl(a,b'SYNTHETIC UNIT FIXTURE EXPECTED',triangles)
    stl(b,b'SYNTHETIC UNIT FIXTURE OUTPUT',list(reversed(triangles)))
    mesh=compare_stock_meshes(a,b);ip=mesh['expected_file'];op=mesh['actual_file']
    doc=dict(path=str(tmp_path/'synthetic_qualification.sldprt'),title='synthetic_qualification.sldprt',type=1,needs_save=False)
    bounds=[-.001,-.001,-.001,.001,.001,.001]
    stock=dict(type_raw=4,bounds_native=bounds,stl_path=str(a),stl_sha256=ip['sha256'],length_units_raw=0,coordinate_system='',
        offset_read_status='unavailable_native_false',offsets_native=None,uniform_flags=None)
    before=dict(document=doc,saved_file_sha256='a'*64,current_machine=dict(machine_type=1,name='Synthetic MILL'),mill_catalogue=[],
        feature_setups=[],features=[],operation_counts=[],operation_count=0,operation_setups=[],material_raw='304L',stock=stock,
        recognition_method=dict(value=1,name='MFGVIEW',status='observed_via_ICWDoc3_FeatureCreationStyle'),
        recognition_options=dict(GetEMFFeatTypeOptions=[dict(enum_value=0,enabled=True)]),
        sw_reference=dict(feature_tree=[dict(name='SyntheticBody',type='Body')],solids=[dict(box_m=[-.0005]*3+[.0005]*3,mass_raw=[0.,0.,0.,1.,1.])]),
        visible_solid_body_count=1,all_solid_body_count=1)
    request=dict(process_id=731,expected_document_path=doc['path'],expected_source_sha256='a'*64,
        expected_stock_path=str(a),expected_stock_sha256=ip['sha256'],expected_stock_bounds_native=bounds,output_dir=str(native_dir))
    data=dict(scope='MILL_EMPTY_EXISTING_STOCK_EXPORT_V1',status='review_required',phase='finished',action='apply',
        synthetic_unit_fixture=True,mutation_attempted=True,native_call_attempted=True,native_call_returned=True,
        readback_verified=True,export_files_verified=True,mesh_content_verified=True,
        may_continue=False,apply_eligible=False,native_dispatch_pending=False,offsets_verified=False,
        model_saved=False,stock_edit_attempted=False,material_edit_attempted=False,AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,
        TechDB_write_attempted=False,production_qualified=False,physical_depth_verified=False,incoming_turn_WIP_verified=False,
        AFR_gate_opened=False,post_cleanup_CAM_getters=False,offset_read_status='unavailable_native_false',native_return=dict(python_type='bool',value=True),
        messages=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],
            overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]),
        request=request,before=before,after=deepcopy(before),mesh_comparison=mesh,
        files=[dict(path=str(b),native_path=str(b),canonical_path=op['canonical_path'],bytes=op['bytes'],sha256=op['sha256'],content_reviewed=False)])
    return data,a,b


@pytest.fixture
def fixture(tmp_path):
    data,a,b=synthetic_receipt(tmp_path)
    kw=dict(process_id=data['request']['process_id'],expected_document_path=data['request']['expected_document_path'],
        expected_source_sha256=data['request']['expected_source_sha256'],expected_material_raw='304L',
        expected_stock_sha256=g._digest(data['before']['stock']),stock_basis='documented_raw_stock')
    path=tmp_path/'receipt.json'
    def load(value=None,**overrides):
        raw=json.dumps(data if value is None else value,ensure_ascii=False).encode('utf-8');path.write_bytes(raw)
        return g.load_stock_export_evidence(str(path),hashlib.sha256(raw).hexdigest(),**dict(kw,**overrides))
    return data,kw,path,a,b,load


def setpath(data,path,value):
    keys=path.split('.');node=data
    for key in keys[:-1]:node=node[int(key)] if type(node) is list else node[key]
    if type(node) is list:node[int(keys[-1])]=value
    else:node[keys[-1]]=value


def test_positive_pins_full_initial_and_summary_is_detached(fixture):
    d,kw,p,a,b,load=fixture;gate=load()
    assert gate.check_files() is True and gate.verify_initial(deepcopy(d['before'])) is True
    out=gate.summary();assert out['offsets_verified'] is False and out['incoming_turn_WIP_verified'] is False
    assert out['stock_snapshot_sha256']==kw['expected_stock_sha256']
    out['recognition_method']['value']=0;assert gate.summary()['recognition_method']['value']==1


@pytest.mark.parametrize('field,value',[
 ('scope','wrong'),('action','prepare'),('status','uncertain'),('phase','preflight'),
 ('native_return.value',1),('native_return.python_type','int'),('native_call_returned',1),
 ('readback_verified',1),('export_files_verified',False),('mesh_content_verified',False),
 ('offsets_verified',True),('offset_read_status','observed_native_true'),('model_saved',True),
 ('stock_edit_attempted',True),('AFR_attempted',True),('TechDB_write_attempted',True),
 ('messages.active',True),('messages.event_count',False),('messages.disconnect_errors',['failure']),
 ('request.process_id',1),('request.expected_source_sha256','c'*64),
 ('before.material_raw','6061-T6'),('before.recognition_method.value',True),
 ('after.recognition_method.value',0),('after.document.needs_save',True),
 ('after.operation_count',False),('after.recognition_options.GetEMFFeatTypeOptions.0.enabled',1),
 ('mesh_comparison.verification_tolerance_mm',0.001),('mesh_comparison.coordinate_frame','FCS'),
 ('mesh_comparison.alignment_performed',True),('mesh_comparison.expected_mesh.closed_connected_oriented_manifold',False),
 ('mesh_comparison.actual_mesh.max_outward_vertex_plane_mm',0.01),
 ('mesh_comparison.mutual_containment.expected_vertices_in_actual_max_signed_distance_mm',0.01),
 ('mesh_comparison.actual_file.path','C:/archive/stock.stl'),('files.0.native_path','C:/archive/stock.stl'),
 ('files.0.sha256','a'*64)])
def test_bad_receipt_cannot_open_gate(fixture,field,value):
    d,_,_,_,_,load=fixture;setpath(d,field,value)
    with pytest.raises(ValueError):load()


@pytest.mark.parametrize('key,value',[('process_id',True),('expected_material_raw','6061-T6'),
 ('expected_source_sha256','c'*64),
 ('stock_basis','actual_incoming_WIP')])
def test_binding_mismatch_and_raw_sha_in_place_of_snapshot_digest_rejected(fixture,key,value):
    with pytest.raises(ValueError):fixture[-1](**{key:value})


@pytest.mark.parametrize('which',[2,3,4])
def test_boundary_file_change_is_detected(fixture,which):
    gate=fixture[-1]();path=fixture[which];path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):gate.check_files()


@pytest.mark.parametrize('field,value',[('material_raw','6061-T6'),('stock.coordinate_system','FCS'),
 ('recognition_options.GetEMFFeatTypeOptions.0.enabled',1),('sw_reference.solids.0.mass_raw.0',1.0)])
def test_initial_snapshot_changes_fail(fixture,field,value):
    gate=fixture[-1]();state=deepcopy(fixture[0]['before']);setpath(state,field,value)
    with pytest.raises(ValueError):gate.verify_initial(state)


def test_stock_reader_is_stock_only_and_does_not_rehash_receipt_on_getters(fixture,monkeypatch):
    d=fixture[0];gate=fixture[-1]();native=object();calls=[]
    def observer(w,t,r,diag):calls.append((w,t));diag['observed']=True;return deepcopy(d['before']['stock']),native
    monkeypatch.setattr(g,'_export_stock',observer)
    monkeypatch.setattr(gate,'check_files',lambda:pytest.fail('Boundary rehash called by stock getter'))
    diag={};stock,handle=gate.read_stock(object(),'tlb',None,diag)
    assert handle is native and diag['observed'] and len(calls)==1
    stock['coordinate_system']='bad'
    assert gate.read_stock(object(),'tlb',None,{})[0]['coordinate_system']==''
    def bad(*args):s=deepcopy(d['before']['stock']);s['offset_read_status']='observed_native_true';return s,native
    monkeypatch.setattr(g,'_export_stock',bad)
    with pytest.raises(ValueError):gate.read_stock(None,None,None,{})


@pytest.mark.parametrize('raw',[b'{"scope":1,"scope":2}',b'{"x":NaN}',b'{"x":1e999}',b'{"x":'+b'['*70+b'0'+b']'*70+b'}'])
def test_duplicate_nonfinite_and_deep_json_fail_closed(fixture,raw):
    _,kw,path,_,_,_=fixture;path.write_bytes(raw)
    with pytest.raises(ValueError):g.load_stock_export_evidence(str(path),hashlib.sha256(raw).hexdigest(),**kw)


def test_geometry_anchor_survives_feature_creation_without_rolling_tolerance(fixture):
    gate=fixture[-1]();state=deepcopy(fixture[0]['before'])
    state['features']=[{'new_feature_after_EMF':True}]
    original=state['sw_reference']['solids'][0]['mass_raw'][3]
    state['sw_reference']['solids'][0]['mass_raw'][3]=original*(1+8e-11)
    assert gate.verify_geometry(state) is True
    state['sw_reference']['solids'][0]['mass_raw'][3]=original*(1+16e-11)
    with pytest.raises(ValueError,match='immutable'):gate.verify_geometry(state)


@pytest.mark.parametrize('field,value',[('mesh_comparison.actual_mesh.triangles',True),
    ('mesh_comparison.actual_mesh.vertices',9999),('mesh_comparison.mutual_containment.vertex_plane_tests',0)])
def test_mesh_proof_counts_are_bounded_strict_integers(fixture,field,value):
    data=fixture[0];setpath(data,field,value)
    with pytest.raises(ValueError):fixture[-1]()


def test_raw_stl_hash_is_not_stock_snapshot_digest(fixture):
    with pytest.raises(ValueError):fixture[-1](expected_stock_sha256=fixture[0]["request"]["expected_stock_sha256"])
