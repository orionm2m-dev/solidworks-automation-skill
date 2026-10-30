"""Offline fault injection: no process, COM server or native document is used."""
import gc
import hashlib
import os
from pathlib import Path
import sys
import weakref
from copy import deepcopy
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/"scripts"))
from scripts import sw_cam_read_batch_guard as m
from scripts import sw_cam_dispatch_guard as base

class Obj: pass

def pin(path,raw):
    path.write_bytes(raw)
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())

@pytest.fixture
def env(tmp_path,monkeypatch):
    source=pin(tmp_path/"part.SLDPRT",b"saved CAD")
    evidence=pin(tmp_path/"receipt.json",b"immutable")
    doc=dict(path=source["path"],title="part.SLDPRT",type=1,needs_save=True)
    state=dict(pid=123,document=deepcopy(doc),event_ok=True,owned_ok=True,
               evidence_ok=True,binding_ok=True,native_error=False,result=7)
    counts=dict(identity=0,owned=0,evidence=0,binding=0,event=0,native=0,qi=0)
    root=Obj();sw=Obj()
    def base_member(obj,name,*args):
        assert obj is sw and name=="GetProcessID"
        return state["pid"]
    def current_doc(obj):
        assert obj is sw;counts["identity"]+=1
        return deepcopy(state["document"])
    def check(label,flag):
        counts[label]+=1
        if not state[flag]:raise ValueError(label+" changed")
    def native(obj,name,*args):
        counts["native"]+=1
        if state["native_error"]:raise RuntimeError("native getter failed")
        action=state.get("on_native")
        if action:action()
        return state["result"]
    def typed(obj,name,path):
        counts["qi"]+=1
        action=state.get("on_qi")
        if action:action()
        return state.get("qi_result",obj)
    monkeypatch.setattr(base,"_member",base_member)
    monkeypatch.setattr(base,"raw_part_identity",current_doc)
    monkeypatch.setattr(m,"_member",native)
    monkeypatch.setattr(m,"_typed",typed)
    kwargs=dict(process_id=123,expected_document=doc,source_sha256=source["sha256"],
        evidence_pins=[evidence],verify_evidence=lambda:check("evidence","evidence_ok"),
        verify_owned_process=lambda:check("owned","owned_ok"),
        check_events=lambda:check("event","event_ok"),
        verify_retained_binding=lambda:check("binding","binding_ok"),
        retained_objects=(root,),max_native_calls=8)
    def make(**changes):return m.ScopedCamReadBatch(sw,"not-loaded.tlb",**(kwargs|changes))
    return SimpleNamespace(source=source,evidence=evidence,state=state,counts=counts,
        root=root,sw=sw,kwargs=kwargs,make=make)


def test_success_has_strong_entry_exit_and_no_per_getter_identity(env):
    g=env.make()
    with g:
        assert env.counts["identity"]==3
        for _ in range(4):assert g.read(env.root,"Count")==7
        assert g.typed(env.root,"ICWTool") is env.root
        assert env.counts["identity"]==3
        assert not g.summary()["read_scope_complete"]
        with pytest.raises(ValueError):g.require_complete()
    assert g.require_complete() is True
    assert env.counts["identity"]==6
    assert env.counts["owned"]==2 and env.counts["binding"]==2
    s=g.summary()
    assert s["complete_boundary_checks"]==2 and s["content_hash_reads"]==4
    assert s["getter_calls"]==4 and s["query_interface_calls"]==1
    assert not s["active"] and not s["invalid"]
    assert not s["dispatch_available"] and not s["atomic_snapshot"]
    assert all(v>=0 for v in s["timer_seconds"].values())
    assert s["timer_counts"]["getter"]==4 and s["timer_counts"]["qi"]==1
    assert s["timer_counts"]["identity"]==6
    assert s["timer_counts"]["boundary_inclusive"]==2
    assert s["retained_reference_count"]==0


@pytest.mark.parametrize("change",["pid","document","dirty","source","pin","event","owned","binding"])
@pytest.mark.parametrize("phase",["entry","exit"])
def test_boundary_changes_refuse_data(env,change,phase):
    def mutate():
        if change=="pid":env.state["pid"]=999
        elif change=="document":env.state["document"]["title"]="other.SLDPRT"
        elif change=="dirty":env.state["document"]["needs_save"]=False
        elif change=="source":Path(env.source["path"]).write_bytes(b"changed CAD")
        elif change=="pin":Path(env.evidence["path"]).write_bytes(b"changed evidence")
        else:env.state[change+"_ok"]=False
    g=env.make()
    if phase=="entry":mutate()
    with pytest.raises(ValueError):
        with g:
            if phase=="exit":
                assert g.read(env.root,"Count")==7
                mutate()
    with pytest.raises(ValueError):g.require_complete()
    assert g.summary()["invalid"] and not g.summary()["active"]
    assert g.summary()["retained_reference_count"]==0
    if phase=="entry":assert env.counts["native"]==0


def test_same_path_rebound_doc_is_rejected_by_binding(env):
    g=env.make();before=deepcopy(env.state["document"])
    with pytest.raises(ValueError,match="binding"):
        with g:
            g.read(env.root,"Count")
            env.state["binding_ok"]=False
    assert env.state["document"]==before
    with pytest.raises(ValueError):g.require_complete()


@pytest.mark.parametrize("kind",["getter","qi"])
@pytest.mark.parametrize("when",["before","after"])
def test_each_call_checks_events_and_stops(env,kind,when):
    g=env.make()
    with pytest.raises(ValueError):
        with g:
            if when=="before":env.state["event_ok"]=False
            else:env.state["on_native" if kind=="getter" else "on_qi"]=lambda:env.state.update(event_ok=False)
            if kind=="getter":g.read(env.root,"Count")
            else:g.typed(env.root,"ICWTool")
    assert env.counts["native" if kind=="getter" else "qi"]==(0 if when=="before" else 1)
    with pytest.raises(ValueError):g.require_complete()


def test_swallowed_callback_error_still_invalidates_exit(env):
    g=env.make()
    with pytest.raises(ValueError,match="invalidated"):
        with g:
            env.state["native_error"]=True
            with pytest.raises(RuntimeError):g.read(env.root,"Count")
            env.state["native_error"]=False
    assert g.summary()["invalid"]
    with pytest.raises(ValueError):g.require_complete()


def test_outer_error_cannot_complete(env):
    g=env.make()
    with pytest.raises(RuntimeError):
        with g:
            g.read(env.root,"Count")
            raise RuntimeError("consumer failed")
    with pytest.raises(ValueError):g.require_complete()


def test_shared_getter_qi_budget_prevents_extra_callback(env):
    g=env.make(max_native_calls=2)
    with pytest.raises(ValueError,match="budget"):
        with g:
            g.read(env.root,"Count");g.typed(env.root,"ICWTool")
            g.read(env.root,"Count")
    assert env.counts["native"]==1 and env.counts["qi"]==1


@pytest.mark.parametrize("name",["ActiveDoc","IGetActiveDoc","GetUseDocumentUnit","GetUnits",
    "SetTool","SetTypeOfFirstCutZ","CreateSTLOfCuttingPortion","Save","GTP","unknown"])
def test_global_and_mutating_getters_are_forbidden(env,name):
    g=env.make()
    with pytest.raises(ValueError,match="scope"):
        with g:g.read(env.root,name)
    assert env.counts["native"]==0
    with pytest.raises(ValueError):g.require_complete()


def test_dispatch_is_unavailable_even_with_valid_callback(env):
    g=env.make();calls=[]
    with pytest.raises(ValueError,match="cannot dispatch"):
        with g:g.dispatch_once(lambda:calls.append("mutation"),persist_pending=lambda:calls.append("pending"))
    assert calls==[]
    with pytest.raises(ValueError):g.require_complete()


def test_unknown_interface_is_forbidden(env):
    g=env.make()
    with pytest.raises(ValueError,match="Interface"):
        with g:g.typed(env.root,"ICWApp4")
    assert env.counts["qi"]==0


def test_unknown_object_cannot_enter_retained_graph(env):
    g=env.make()
    with pytest.raises(ValueError,match="retained document graph"):
        with g:g.read(Obj(),"Count")
    assert env.counts["native"]==0


def test_returned_native_objects_and_qi_are_retained(env):
    child=Obj();grandchild=Obj();env.state["result"]=[child];env.state["qi_result"]=grandchild
    g=env.make()
    with g:
        assert g.read(env.root,"Item")==[child]
        assert g.typed(child,"ICWTool") is grandchild
        assert g.read(grandchild,"Count")==[child]
    assert g.require_complete()


def test_only_canonical_iunknown_query_is_allowed(env):
    from comtypes import IUnknown
    g=env.make()
    with g:g.read(env.root,"QueryInterface",IUnknown)
    assert g.require_complete() and env.counts["native"]==1
    other=env.make()
    with pytest.raises(ValueError,match="IUnknown"):
        with other:other.read(env.root,"QueryInterface",Obj)
    assert env.counts["native"]==1


def test_strong_root_survives_until_closed(env):
    obj=Obj();reference=weakref.ref(obj)
    g=env.make(retained_objects=(obj,));del obj;gc.collect()
    assert reference() is not None
    with g:g.read(reference(),"Count")
    gc.collect();assert reference() is None


def test_reenter_and_read_after_close_rejected(env):
    g=env.make()
    with g:g.read(env.root,"Count")
    with pytest.raises(ValueError):
        with g:pass
    with pytest.raises(ValueError):g.read(env.root,"Count")
    assert env.counts["native"]==1


@pytest.mark.parametrize("budget",[0,-1,6001,True,1.0,None])
def test_bad_budgets_refused(env,budget):
    with pytest.raises(ValueError):env.make(max_native_calls=budget)


@pytest.mark.parametrize("roots",[(),[],(None,),(1,),(True,),("doc",)])
def test_invalid_roots_refused(env,roots):
    with pytest.raises(ValueError):env.make(retained_objects=roots)


def test_binding_callback_required(env):
    with pytest.raises(ValueError):env.make(verify_retained_binding=None)


def test_parent_guard_implementation_remains_unchanged():
    p=ROOT/"scripts/sw_cam_dispatch_guard.py"
    benchmark = os.environ.get("SOLIDWORKS_GUARD_TEST_BENCHMARK")
    if not benchmark:
        pytest.skip("Archived native benchmark requires SOLIDWORKS_GUARD_TEST_BENCHMARK")
    proof=__import__("json").loads(Path(benchmark).read_text(encoding="utf-8"))
    expected=next(x["sha256"] for x in proof["source_pins"] if Path(x["path"]).name==p.name)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==expected