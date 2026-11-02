from pathlib import Path
from contextlib import nullcontext
import pytest
from scripts import sw_cam_saved18_serial_dirty_verify as m
from scripts import sw_operation_guard, sw_connect

def test_terminal_failure_revokes_saved_equivalence_without_changing_source_fact(monkeypatch,tmp_path):
    p=dict(process_id=25208);loaded=dict(pins=[],phase_proof_pins=[])
    prepared=(p,loaded,{},'unused.tlb',tmp_path/'receipt.json',tmp_path/'marker.json')
    original=dict(status='saved_eighteen_serial_dirty_verified',phase='finished',readback_verified=True,persistence_after_reopen_verified=True,saved_cam_equivalence_verified=True,source_unchanged_verified=True)
    writes=[]
    monkeypatch.setattr(m,'prepare',lambda request:prepared)
    monkeypatch.setattr(m.common,'_check',lambda pins:None)
    monkeypatch.setattr(m.common,'_pin',lambda path:dict(path=str(path),sha256='a'*64,bytes=1))
    monkeypatch.setattr(sw_operation_guard,'solidworks_operation_lock',lambda **kwargs:nullcontext())
    monkeypatch.setattr(sw_connect,'connect_solidworks',lambda **kwargs:(object(),None))
    monkeypatch.setattr(m,'run_prepared',lambda prep,**kwargs:dict(original))
    def reject(*args):raise ValueError('synthetic terminal verification failure')
    monkeypatch.setattr(m,'validate_completed',reject)
    monkeypatch.setattr(m,'_write_receipt',lambda path,report,**kwargs:writes.append((str(path),dict(report))))
    result=m.dispatch_request({})
    assert result['status']=='error' and 'terminal_issue' in result
    assert result['readback_verified'] is False
    assert result['persistence_after_reopen_verified'] is False
    assert result['saved_cam_equivalence_verified'] is False
    assert result['source_unchanged_verified'] is True
    assert len(writes)==2 and writes[0][1]==result
    assert writes[1][1]['status']=='error'and writes[1][1]['automatic_replay']is False
