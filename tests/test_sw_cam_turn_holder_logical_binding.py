"""不同 COM 视图的文档绑定、STL 文件不变与一次失败后的实际证据。"""
from copy import deepcopy
from types import SimpleNamespace
import importlib,json
import pytest
from test_sw_cam_turn_holder_dimensions import probe,ref
from scripts import sw_cam_turn_holder_dimensions as cam

@pytest.fixture
def logical(probe):
    # Different canonical owner/crib views with shared backing fields and one document-native tool ID.
    crib_holder=probe.Holder(4)
    object.__setattr__(crib_holder,'values',probe.first.values)
    crib_tool=probe.Tool(101,crib_holder)
    probe.crib.GetAllTools=lambda:[crib_tool,probe.second]
    probe.state['extra_assignment']=True
    probe.first.values['HolderShape']=1
    probe.state['holder_file_path']=str(probe.tmp_path/'holder.stl')
    (probe.tmp_path/'holder.stl').write_bytes(b'preserved holder shape')
    probe.defaults['values_native']={'LeadAngle':-32.}
    probe.crib_holder=crib_holder;probe.crib_tool=crib_tool
    return probe


def test_distinct_canonical_valid_logical_ids_succeed_preserve_custom_STL(logical):
    p=logical.prepare();assert p['status']=='prepared' and p['apply_eligible'],p
    assert p['snapshot_diagnostics'][0]['holder_identity_observation']['selected_crib_same_canonical_identity'] is False
    assert len(p['before']['observed_operation_tools'])==2 and p['affected_operations']==[ref(),ref(1)]
    r=logical.apply(p);assert r['readback_verified'] and r['logical_binding_verified'] and r['holder_file_fields_preserved'],r
    assert logical.state['writes']==[('LeadAngle',-32.)]
    assert r['before']['selected_holder_file']==r['after']['selected_holder_file']
    assert r['after']['selected_holder_file']==dict(path_raw=logical.state['holder_file_path'],shape_raw=1,unit_raw=2)
    assert all(x['observed_tool']['holder']['dimensions_native']['LeadAngle']==-32. for x in r['after']['observed_operation_tools'])
    assert r['after']['toolcrib'][0]['observed_holder']['dimensions_native']['LeadAngle']==-32.
    assert json.loads(logical.receipt.read_text())==r

@pytest.mark.parametrize('which',['operation','tool','holder','linked','usage'])
def test_bad_logical_identity_never_put(logical,which):
    p=logical.prepare()
    if which=='operation':logical.operation.native_id=99
    elif which=='tool':logical.tool.native_id=777
    elif which=='holder':object.__setattr__(logical.first,'catalog_id',9)
    elif which=='linked':logical.operation.IGetAllFeatures=lambda:[SimpleNamespace(native_id=999)]
    else:logical.state['extra_assignment']=False
    r=logical.apply(p);assert r['status']=='error' and not logical.state['writes'] and not r['mutation_attempted']
    assert r['issue']['type']=='ValueError'

@pytest.mark.parametrize('field',['path','unit','shape','other_scalar','other_insert'])
def test_post_put_unrelated_or_custom_file_delta_keeps_actual_evidence(logical,field):
    def change(key,value):
        if field=='path':logical.state['holder_file_path']=str(logical.tmp_path/'changed.stl')
        elif field=='unit':logical.state['holder_file_unit']=0
        elif field=='shape':logical.first.values['HolderShape']=0
        elif field=='other_scalar':logical.other.values['ShankLength']=999.
        else:logical.second.dimensions['NoseRadius']=.8
    logical.state['after_write']=change;r=logical.apply()
    assert r['status']=='uncertain' and not r['readback_verified'] and len(logical.state['writes'])==1,r
    assert r['setters'][0]['after']==r['after'] and r['captures'][-1]['capture_complete']
    if field=='path':assert r['after']['selected_holder_file']['path_raw'].endswith('changed.stl')
    elif field=='unit':assert r['after']['selected_holder_file']['unit_raw']==0
    elif field=='shape':assert r['after']['selected_holder_file']['shape_raw']==0
    assert json.loads(logical.receipt.read_text())==r


def test_partial_setter_exception_after_mutation_preserves_fresh_owner_and_crib(logical):
    def fail(key,value):raise OSError('exception after write')
    logical.state['after_write']=fail;r=logical.apply()
    assert r['status']=='uncertain' and r['mutation_attempted'] and not r['readback_verified']
    assert r['native_calls_returned_count']==0 and r['native_dispatch_pending']
    assert r['after']['selected_tool']['holder']['dimensions_native']['LeadAngle']==-32.
    assert r['after']['toolcrib'][0]['observed_holder']['dimensions_native']['LeadAngle']==-32.
    assert 'setter_error' in r['setters'][0] and len(logical.state['writes'])==1
    assert json.loads(logical.receipt.read_text())==r
    retry=logical.apply(receipt_path=str(logical.tmp_path/'retry.json'))
    assert retry['status']=='error' and len(logical.state['writes'])==1


def test_event_after_put_never_reads_more_CAM(logical):
    logical.state['after_write']=lambda *args:setattr(logical.sessions[-1],'error',1)
    p=logical.prepare();before=logical.state['snapshots'];r=logical.apply(p)
    assert r['status']=='uncertain' and len(logical.state['writes'])==1
    assert logical.state['snapshots']==before+3 # two before captures, dispatch guard, no post-event capture
    assert not r['readback_verified']


def test_declared_scalar_and_file_ABI_without_native_calls(monkeypatch):
    from scripts import sw_cam_comtypes as bridge
    mod=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    monkeypatch.setattr(bridge,'_interface_class',lambda name,path:getattr(mod,name))
    assert cam._logical_abi('no-CAD')['scalar_write_allowlist']==['BoringBarDiameter','LeadAngle','ShankLength']
