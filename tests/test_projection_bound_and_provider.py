from copy import deepcopy
import importlib.util,json,os,sys,types
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module, fixture_path
R=add_runtime()
@pytest.fixture
def fixture():
    p=required_module('sw_cam_mill_packet_projection')
    f=json.loads(fixture_path('cam_mill_packet17_8_synthetic.json').read_text(encoding='utf-8-sig'))
    return p,f

def sized(f,count):
    req=deepcopy(f['request']);packet=deepcopy(f['packet'])
    row=packet['parameters'][0];op=next(x for x in packet['binding']['operations']if x['native_id']==row['operation_native_id'])
    setup=deepcopy(packet['binding']['operation_setups'][op['setup_index']]);setup.update(index=0,operation_count=count)
    ops=[];rows=[];targets=[]
    for i in range(count):
        oid=10000+i;r=deepcopy(row);r['operation_native_id']=oid;r['setup_native_id']=setup['native_id']
        o=deepcopy(op);o.update(native_id=oid,setup_index=0,operation_index=i,setup_native_id=setup['native_id'])
        rows.append(r);ops.append(o)
        targets.append({k:r[k]for k in ('operation_native_id','feature_native_id','operation_type','tool_native_id','setup_native_id')})
    req.update(expected_operation_ids=[x['native_id']for x in ops],parameter_targets=targets)
    packet['binding'].update(operations=ops,operation_setups=[setup])
    packet['parameters']=rows;packet['validated_request']=deepcopy(req)
    return packet,req

@pytest.mark.parametrize('count',[8,12,16])
def test_explicit_group_bound_accepts(count,fixture):
    p,f=fixture;packet,request=sized(f,count)
    result=p.project_packet(packet,request)
    assert len(result['snapshot']['parameters'])==count

def test_seventeen_groups_rejected(fixture):
    p,f=fixture;packet,request=sized(f,17)
    with pytest.raises(ValueError,match='Bounded complete parameter'):p.project_packet(packet,request)

def test_projector_comes_from_installed_runtime(fixture):
    p,_=fixture
    assert Path(p.__file__).resolve()==(R/'scripts/sw_cam_mill_packet_projection.py').resolve()


def test_original_golden_eight_remains_exact(fixture):
    p,f=fixture;result=p.project_packet(f['packet'],f['request'])
    assert result['snapshot']==f['expected_snapshot']

def test_checkpoint_uses_actual_cam_name_and_actual_eight_parameters(monkeypatch,fixture):
    p,f=fixture
    provider=required_module('sw_cam_mill_host_checkpoint')
    binding=f['expected_snapshot']['binding'];doc=deepcopy(f['packet']['document_before']);doc.pop('configuration')
    expected_cam='Mill - Metric - 0';sw=f['request']['expected_sw_configuration']
    tlb='D:/CAM/camworks.tlb'
    ctx=dict(guide_parameters=dict(document=doc,configuration=dict(cam_configuration_name=expected_cam,
        configuration_object_name=expected_cam,associated_sw_configuration_name=sw,sw_configuration_name=sw,
        names_consistent=True,associated_sw_configuration_matches=True),
        expected_parameters=deepcopy(f['expected_snapshot']),targets=[]),
        ownership=dict(process_id=f['request']['expected_process_id'],create_time=1,alive=True,executable='SLDWORKS.exe'),
        source_sha256='a'*64,
        root_pocket_native_inventory=[dict(owner_setup_native_id=69,header=deepcopy(row))for row in binding['features'].values()],
        root_pocket_registration=dict(clsid=p.CAM_CLASS,addin_path='D:/CAM/cwaddinu.dll'),
        pins=[dict(path=tlb,sha256='b'*64,bytes=1)],checkpoint_pins=[])
    result=provider.reference_from_loaded(ctx,dict(path='checkpoint.json',sha256='c'*64,bytes=1))
    assert result['mill_request']['expected_cam_configuration']==expected_cam
    assert result['mill_request']['expected_sw_configuration']==sw
    assert len(result['mill_request']['parameter_targets'])==8
    assert result['expected_snapshot']==f['expected_snapshot']
    ctx['root_pocket_native_inventory'][0]['owner_setup_native_id']=70
    with pytest.raises(ValueError,match='Single actual feature setup'):provider.reference_from_loaded(ctx,{})

