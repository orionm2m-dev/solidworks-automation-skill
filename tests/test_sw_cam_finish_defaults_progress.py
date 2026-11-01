"""Portable real-reader checks for compact Finish defaults diagnostics."""
from copy import deepcopy
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get("SOLIDWORKS_SKILL_ROOT",STAGE))
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("finish_defaults_progress_under_test",
    STAGE/"scripts/sw_cam_finish_defaults_progress.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class FakeBatch:
    """No native objects: exercises the real fixed 45-call defaults decoder."""
    def __init__(self, *, fail_member=None, fail_boundary=False, crash=False):
        self.calls=[];self.completed=False;self.fail_member=fail_member
        self.fail_boundary=fail_boundary;self.crash=crash
    def __enter__(self):return self
    def __exit__(self,*args):
        if self.fail_boundary:raise ValueError("boundary evidence changed")
        self.completed=args[0] is None
    def require_complete(self):
        if not self.completed or len(self.calls)!=45:raise ValueError("incomplete native scope")
    def summary(self):
        return dict(read_scope_complete=self.completed,native_calls=len(self.calls),read_only=True)
    def typed(self,obj,name):
        self.calls.append(("qi",name))
        if self.crash:os._exit(73)
        return name
    def read(self,obj,name,*args):
        self.calls.append(("getter",name))
        if name==self.fail_member:raise RuntimeError("getter failed")
        if name=="GetMachiningDepth":return 4.8
        if name=="GetOverrideMachiningDepth":return False
        if name=="GetToolpathParam":return "parameter-object"
        if name=="GetToolpathParameters":return (True,False,False,0,True,0.0,0.0)
        if name=="GetSetupParameters":return ("transform","origin","vector")
        if name=="GetCoordinates":return (0.0,0.0,-1.0) if obj=="ICWUnitVector" else (0.0,0.0,0.0)
        if name in m.defaults.BOOL_FIELDS:return False
        if name in m.defaults.INT_FIELDS:return 0
        return 0.0


def setup_phase(tmp_path, **batch_kwargs):
    source=tmp_path/"model.SLDPRT";source.write_bytes(b"saved bytes")
    receipt=tmp_path/"owner.json";progress=tmp_path/"defaults.read.json";marker=tmp_path/"once.json"
    diagnostic=dict(label="saved_defaults",operation_native_id=320,read={})
    report={"actions":{},"diagnostic":diagnostic};snapshots=[]
    def persist():
        snapshots.append(deepcopy(report));receipt.write_text(json.dumps(report),encoding="utf-8")
    return dict(source=source,receipt=receipt,progress=progress,marker=marker,report=report,
        diagnostic=diagnostic,snapshots=snapshots,persist=persist,batch=FakeBatch(**batch_kwargs))


def run_phase(f, **changes):
    p=dict(batch=f["batch"],diagnostic=f["diagnostic"],full_persist=f["persist"],
           progress_path=f["progress"],protected_paths=[f["source"],f["receipt"],f["marker"]])
    p.update(changes)
    return m.read_defaults_phase("operation","feature",**p)


def test_real_reader_keeps_45_calls_values_and_reduces_full_writes_121_to_2(tmp_path):
    old=FakeBatch();old_diagnostic={};legacy_writes=[]
    with old:
        old_value=m.defaults.read_defaults("operation","feature",read=old.read,typed=old.typed,
            persist=lambda:legacy_writes.append(1),diagnostic=old_diagnostic)
    old.require_complete()
    assert len(legacy_writes)==119  # Existing entry/finally add two more full writes.
    f=setup_phase(tmp_path);value=run_phase(f)
    assert value==old_value and f["batch"].calls==old.calls
    assert len(f["batch"].calls)==45 and len(f["snapshots"])==2
    assert f["snapshots"][-1]["diagnostic"]["batch"]["read_scope_complete"] is True
    assert f["snapshots"][-1]["diagnostic"]["read"]==old_diagnostic
    p=json.loads(f["progress"].read_text())
    assert p["status"]=="completed" and p["read_updates"]==119
    assert p["mutation_authority"] is False and p["last_read"]["native_call_count"]==45
    assert p["last_read"]["read_complete"] is True and p["last_read"]["elapsed_seconds"]>=0
    assert f["diagnostic"]["read_journal"]["started_utc"]<=f["diagnostic"]["read_journal"]["finished_utc"]


@pytest.mark.parametrize("boundary",[False,True])
def test_getter_or_boundary_failure_flushes_partial_and_failed_marker(tmp_path,boundary):
    f=setup_phase(tmp_path,fail_member=None if boundary else "DepthMethod",fail_boundary=boundary)
    with pytest.raises((RuntimeError,ValueError)):run_phase(f)
    assert len(f["snapshots"])==2
    last=json.loads(f["progress"].read_text())
    assert last["status"]=="failed" and last["mutation_authority"] is False
    assert f["snapshots"][-1]["diagnostic"]["read_journal"]["completed"] is False
    if not boundary:
        call=f["snapshots"][-1]["diagnostic"]["read"]["calls"][-1]
        assert call["name"]=="DepthMethod" and call["returned"] is False and call["issue_type"]=="RuntimeError"
    else:
        assert f["snapshots"][-1]["diagnostic"]["read"]["read_complete"] is True
        assert f["snapshots"][-1]["diagnostic"]["batch"]["read_scope_complete"] is False


def test_mutation_intent_return_save_and_once_marker_remain_immediate(tmp_path):
    f=setup_phase(tmp_path)
    f["report"].update(source_path=str(f["source"]),initial_source_sha256="0"*64,
        phase="prepared",feature_native_id=79,anchor_operation_native_id=144,
        mutation_attempted=False,readback_verified=False)
    journal=m.insert.Journal(f["report"],f["receipt"],f["marker"])
    journal.pending("InsertOperation")
    assert json.loads(f["marker"].read_text())["actions"]["InsertOperation"]["pending"] is True
    journal.returned("InsertOperation",object(),pointer=True)
    before=f["marker"].read_bytes()
    run_phase(f,full_persist=journal.persist)
    assert f["marker"].read_bytes()==before
    journal.pending("SaveActiveDocument")
    for p in (f["marker"],f["receipt"]):
        assert json.loads(p.read_text())["actions"]["SaveActiveDocument"]["pending"] is True
    journal.returned("SaveActiveDocument",0)
    for p in (f["marker"],f["receipt"]):
        action=json.loads(p.read_text())["actions"]["SaveActiveDocument"]
        assert action["returned"] is True and action["pending"] is False and action["native_return_value"]==0
    with pytest.raises(ValueError,match="repeated"):journal.pending("SaveActiveDocument")
    with pytest.raises(ValueError,match="replay"):m.insert.Journal(f["report"],f["receipt"],f["marker"]).claim()


def test_compact_publication_error_flushes_full_receipt_and_stops(tmp_path,monkeypatch):
    f=setup_phase(tmp_path);writer=m.progress._write_receipt;writes=[]
    def fail(path,row,**kw):
        writes.append(row["status"])
        if len(writes)==3:raise OSError("compact disk error")
        return writer(path,row,**kw)
    monkeypatch.setattr(m.progress,"_write_receipt",fail)
    with pytest.raises(OSError,match="compact disk error"):run_phase(f)
    assert len(f["snapshots"])==2
    assert json.loads(f["progress"].read_text())["status"]=="failed"
    assert f["batch"].calls==[]


def test_final_full_flush_failure_cannot_publish_completed(tmp_path):
    f=setup_phase(tmp_path);persist=f["persist"];calls=[]
    def failing():
        calls.append(1)
        if len(calls)==2:raise OSError("owner receipt error")
        persist()
    with pytest.raises(OSError,match="owner receipt error"):run_phase(f,full_persist=failing)
    assert json.loads(f["progress"].read_text())["status"]=="failed"


def test_fresh_progress_output_prevents_replay_without_reading(tmp_path):
    f=setup_phase(tmp_path);run_phase(f)
    repeat=dict(label="saved_defaults",operation_native_id=320,read={})
    with pytest.raises(ValueError,match="Fresh absolute"):
        run_phase(f,batch=FakeBatch(),diagnostic=repeat)
    assert repeat["read"]=={}


def test_mixin_preserves_existing_guard_prefix_and_has_no_write_methods():
    previous=ast.parse(Path(m.insert.__file__).read_text(encoding="utf-8"))
    new=ast.parse(Path(m.__file__).read_text(encoding="utf-8"))
    old_method=next(n for c in previous.body if isinstance(c,ast.ClassDef) and c.name=="NativeBackend"
        for n in c.body if isinstance(n,ast.FunctionDef) and n.name=="operation_defaults")
    cls=next(c for c in new.body if isinstance(c,ast.ClassDef) and c.name=="CompactDefaultsMixin")
    assert [n.name for n in cls.body if isinstance(n,ast.FunctionDef)]==["operation_defaults"]
    new_method=next(n for n in cls.body if isinstance(n,ast.FunctionDef))
    old_prefix=ast.get_source_segment(Path(m.insert.__file__).read_text(encoding="utf-8"),old_method)
    new_prefix=ast.get_source_segment(Path(m.__file__).read_text(encoding="utf-8"),new_method)
    old_prefix=old_prefix.split("diagnostic = dict(")[0]
    new_prefix=new_prefix.split("diagnostic = dict(")[0].replace("insert.DefaultsReadBatch(","DefaultsReadBatch(")
    assert old_prefix==new_prefix


def test_process_crash_leaves_last_attempt_and_durable_nonreplay_marker(tmp_path):
    child=tmp_path/"crash";child.mkdir()
    result=subprocess.run([sys.executable,"-X","utf8",__file__,"--simulate-crash",str(child)],
        env=os.environ.copy(),capture_output=True,text=True,timeout=45)
    assert result.returncode==73, result.stderr
    p=json.loads((child/"defaults.read.json").read_text())
    assert p["status"]=="reading" and p["mutation_authority"] is False
    assert p["last_read"]["member"]=="IDispatch" and p["last_read"]["attempted"] is True
    assert p["last_read"]["returned"] is False
    receipt=json.loads((child/"owner.json").read_text());marker=json.loads((child/"once.json").read_text())
    assert receipt["actions"]["InsertOperation"]["returned"] is True
    assert marker["actions"]["InsertOperation"]["returned"] is True
    assert marker["automatic_replay"] is False


if __name__=="__main__" and sys.argv[1:2]==["--simulate-crash"]:
    f=setup_phase(Path(sys.argv[2]),crash=True)
    f["report"].update(source_path=str(f["source"]),initial_source_sha256="0"*64,
        phase="prepared",feature_native_id=79,anchor_operation_native_id=144,
        mutation_attempted=False,readback_verified=False)
    j=m.insert.Journal(f["report"],f["receipt"],f["marker"])
    j.pending("InsertOperation");j.returned("InsertOperation",object(),pointer=True)
    run_phase(f,full_persist=j.persist)
