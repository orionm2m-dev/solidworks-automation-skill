import ast,json
from pathlib import Path
import pytest
from test_current_saved_parameter_schema import server,context,fake,params
from scripts import sw_cam_current_saved_parameter_batch as core

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'));assert len(tree.body)==1 and isinstance(tree.body[0],ast.ClassDef)
    exec(compile(tree,str(SOURCE),'exec'),server.__dict__)

def recovery_params(context,**changes):
    values=dict(action='prepare_recover_save',partial_receipt_path='partial.json',partial_receipt_sha256='a'*64,partial_attempt_marker_path='old.json',partial_attempt_marker_sha256='b'*64,original_apply_request_path='applied.json',original_apply_request_sha256='c'*64)
    values.update(changes);return params(context,**values)

@pytest.mark.parametrize('action',['prepare_recover_save','recover_save'])
def test_existing_endpoint_forwards_explicit_recovery_action(context,fake,action):
    p=recovery_params(context,action=action,save_after_verified=action=='recover_save')
    result=json.loads(server.solidworks_cam_configure_guide_definitions(p));assert result['readback_verified']
    assert fake.call_args.kwargs['action']==action and fake.call_args.kwargs['partial_receipt_sha256']=='a'*64
    assert fake.call_count==1

@pytest.mark.parametrize('change',[{'action':'recover_setters'},{'partial_receipt_sha256':'bad'},{'partial_receipt_path':True},{'partial_attempt_marker_sha256':None,'unknown':1},{'original_apply_request_sha256':123}])
def test_recovery_schema_rejects_untyped_or_extra_inputs(context,fake,change):
    with pytest.raises(ValueError):recovery_params(context,**change)
    fake.assert_not_called()
