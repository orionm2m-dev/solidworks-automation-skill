import pytest
from test_mcp_cam_mill_inventory import probe,MODEL,TOOL

FIELDS=('recognition_receipt_path','recognition_receipt_sha256','preservation_save_receipt_path','preservation_save_receipt_sha256')

def pair(probe):
    a=probe.tmp_path/'recognition.json';a.write_text('{}')
    b=probe.tmp_path/'save.json';b.write_text('{}')
    return dict(zip(FIELDS,(str(a),'b'*64,str(b),'c'*64)))

def test_optional_four_fields_forwarded_on_existing_readonly_route(probe):
    extra=pair(probe);model=MODEL(**(probe.data|extra));probe.ns[TOOL](model)
    assert all(probe.core.call_args.kwargs[k]==v for k,v in extra.items())
    assert probe.registry[TOOL]['annotations']['readOnlyHint'] is True

@pytest.mark.parametrize('key',FIELDS)
def test_partial_evidence_stops_before_target(probe,key):
    extra=pair(probe);extra.pop(key)
    with pytest.raises(ValueError):MODEL(**(probe.data|extra))
    probe.target.assert_not_called();probe.core.assert_not_called()

@pytest.mark.parametrize('key,value',[('recognition_receipt_sha256',True),('preservation_save_receipt_sha256','A'*64),('recognition_receipt_path','relative.json'),('preservation_save_receipt_path',4)])
def test_strict_optional_types(probe,key,value):
    extra=pair(probe);extra[key]=value
    with pytest.raises(ValueError):MODEL(**(probe.data|extra))
    probe.target.assert_not_called();probe.core.assert_not_called()
