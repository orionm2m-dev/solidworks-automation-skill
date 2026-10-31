"""Bounds and immutable evidence checks for completed approach receipt loading."""
from pathlib import Path
import hashlib
import importlib.util
import json
import pytest
from scripts.sw_cam_mill_stock_export_evidence import _decode

spec=importlib.util.spec_from_file_location('completed_approach_receipt',
    Path(__file__).resolve().parents[1]/'scripts/sw_cam_chamfer_receipt.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def payload():
    return dict(scope=m.writer.SCOPE,status='review_required',phase='finished',readback_verified=True,model_saved=True)


def encoded(value):return json.dumps(value).encode('utf8')


def test_scoped_reader_accepts_measured_large_shape_without_changing_generic_limit():
    value=payload();value['observations']=[[None]*8000 for _ in range(26)]
    raw=encoded(value)
    with pytest.raises(ValueError,match='structure'):_decode(raw)
    assert m.decode_completed(raw)==value


@pytest.mark.parametrize('field,value',[('scope','unrelated'),('status','uncertain'),('phase','running'),
    ('readback_verified',False),('model_saved',False),('readback_verified',1)])
def test_only_exact_completed_saved_scope(field,value):
    body=payload();body[field]=value
    with pytest.raises(ValueError):m.decode_completed(encoded(body))


def test_duplicate_keys_rejected():
    raw=encoded(payload());raw=raw[:-1]+b', "model_saved": true}'
    with pytest.raises(ValueError,match='Duplicate'):m.decode_completed(raw)


@pytest.mark.parametrize('bad',['NaN','Infinity','-Infinity','1e999'])
def test_nonfinite_json_rejected(bad):
    raw=encoded(payload())[:-1]+b', "bad":'+bad.encode()+b'}'
    with pytest.raises(ValueError):m.decode_completed(raw)


def test_maximum_nodes_is_still_bounded():
    body=payload();body['observations']=[[None]*8000 for _ in range(44)]
    with pytest.raises(ValueError,match='structure'):m.decode_completed(encoded(body))


def test_depth_bound():
    child=0
    for _ in range(34):child=[child]
    body=payload();body['deep']=child
    with pytest.raises(ValueError,match='structure'):m.decode_completed(encoded(body))


@pytest.mark.parametrize('field,value',[('long_list',[0]*8193),('long_string','x'*16385)])
def test_list_string_bounds(field,value):
    body=payload();body[field]=value
    with pytest.raises(ValueError):m.decode_completed(encoded(body))


def test_pin_checked_before_decode(tmp_path):
    p=tmp_path/'receipt.json';p.write_bytes(encoded(payload()))
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    value,pin=m.read_completed(str(p),digest)
    assert value==payload() and pin['sha256']==digest
    with pytest.raises(ValueError,match='SHA'):m.read_completed(str(p),'0'*64)


def test_writer_must_remain_the_pinned_runtime(monkeypatch):
    body=payload();body['module_pin']={'path':'other.py','sha256':'0'*64}
    monkeypatch.setattr(m,'read_completed',lambda p,d:(body,{}))
    with pytest.raises(ValueError,match='writer runtime'):
        m.load_completed('ignored','0'*64,process_id=1,expected_document_path='ignored',expected_source_sha256='0'*64)