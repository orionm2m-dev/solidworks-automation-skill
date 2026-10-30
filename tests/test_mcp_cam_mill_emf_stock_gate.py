import pytest
from test_mcp_cam_mill_afr import probe,MODEL,TOOL

def test_optional_pair_forwarded_on_existing_locked_route(probe):
    p=probe.tmp_path/'export.json';p.write_text('{}')
    data=probe.data|dict(stock_export_receipt_path=str(p),stock_export_receipt_sha256='b'*64)
    model=MODEL(**data);probe.ns[TOOL](model)
    assert probe.core.call_args.kwargs['stock_export_receipt_path']==str(p)
    assert probe.core.call_args.kwargs['stock_export_receipt_sha256']=='b'*64

@pytest.mark.parametrize('kind',['path_only','sha_only','relative','bad_sha','actual_wip','not_exact_material','missing'])
def test_invalid_optional_pair_never_reaches_native_target(probe,kind):
    p=probe.tmp_path/'export.json';p.write_text('{}')
    extra=dict(stock_export_receipt_path=str(p),stock_export_receipt_sha256='b'*64)
    if kind=='path_only':extra.pop('stock_export_receipt_sha256')
    if kind=='sha_only':extra.pop('stock_export_receipt_path')
    if kind=='relative':extra['stock_export_receipt_path']='export.json'
    if kind=='bad_sha':extra['stock_export_receipt_sha256']='BAD'
    if kind=='actual_wip':extra['stock_basis']='actual_turning_wip'
    if kind=='not_exact_material':extra['expected_material_raw']='OTHER304L'
    if kind=='missing':extra['stock_export_receipt_path']=str(probe.tmp_path/'absent.json')
    with pytest.raises(ValueError):MODEL(**(probe.data|extra))
    probe.target.assert_not_called();probe.core.assert_not_called()
