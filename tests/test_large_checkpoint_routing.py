"""The existing 1MiB manifest reader must never decode a full CAM checkpoint."""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,os,sys
import pytest
from cam_public_test_support import add_runtime, required_test_module
ROOT=add_runtime()
def test_large_checkpoint_uses_scoped_authority_decoder_not_manifest_reader(tmp_path,monkeypatch):
    t=required_test_module('test_mill_host_lifecycle')
    prepared,_,_=t.case.__wrapped__(tmp_path);p,_,_,ref,_=prepared;m=t.M
    from scripts import sw_cam_long_cut_reconciliation as scoped
    path=tmp_path/'large_checkpoint.json';path.write_text(json.dumps({'test_payload':['x'*4096]*900}),encoding='utf-8')
    assert 1024*1024<path.stat().st_size<scoped.MAX_BYTES
    cp=m.pin(path);p=deepcopy(p);p['checkpoint_receipt_pin']=cp;ref=deepcopy(ref);ref['authority_pin']=cp
    calls=[];small=m.read_pin
    def manifest_read(value):
        assert value!=cp
        calls.append(value['path']);return small(value)
    monkeypatch.setattr(m,'read_pin',manifest_read)
    def provider(value):
        assert value==cp
        decoded,actual=scoped.read_pin(value['path'],value['sha256'])
        assert actual=={k:cp[k]for k in ('path','sha256')} and len(decoded['test_payload'])==900
        return ref
    result=m.prepare(p,reference_provider=provider)
    assert result[3]['authority_pin']==cp
    assert calls==[p['old_artifact_pin']['path'],p['new_artifact_pin']['path']]
    with pytest.raises(ValueError,match='Bounded evidence file'):small(cp)
    assert scoped.MAX_BYTES==32*1024*1024 and scoped.MAX_NODES==1000000