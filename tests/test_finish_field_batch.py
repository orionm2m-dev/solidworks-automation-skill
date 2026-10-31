"""Fault injection for retained finish-field reads; no COM server is used."""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

import scripts
scripts.__path__.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import sw_cam_finish_field_batch as m
from scripts import sw_cam_dispatch_guard as guard
from scripts import sw_cam_read_batch_guard as base_batch


class Obj:
    def __init__(self, role, state):
        self.role, self.state = role, state
    def QueryInterface(self, cls):
        self.state["qi"].append((self.role, cls.__name__))
        if self.state.get("null_qi"): return None
        return cls(self.role, self.state)


def pin(path, content):
    path.write_bytes(content)
    return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest()}


@pytest.fixture
def env(tmp_path, monkeypatch):
    source = pin(tmp_path / "part.SLDPRT", b"immutable part")
    evidence = pin(tmp_path / "authority.json", b"immutable proof")
    own = {"path": m.__file__, "sha256": m.finish._file_hash(m.__file__)}
    document = dict(path=source["path"], title="part.SLDPRT", type=1, needs_save=False)
    state = dict(pid=123, document=deepcopy(document), events_ok=True, owned_ok=True,
                 evidence_ok=True, op_id=144, feature_id=79, suppressed=False,
                 op_type=1, found=True, qi=[], calls=[], persists=0)
    objects = {name: Obj(name, state) for name in
               ("doc", "operation", "feature", "collection", "lead_in", "lead_out", "sw")}
    classes = {name: type(name, (Obj,), {}) for name in m.INTERFACES}
    values = {spec[0]:deepcopy(spec[6]) for spec in m.finish.FIELDS}
    by_owner = {(spec[1], spec[2]):spec[0] for spec in m.finish.FIELDS}

    def query_class(name, *args):
        if state.get("class_error"): raise ValueError("interface metadata changed")
        return classes[name]
    def native(obj, name, *args):
        state["calls"].append((obj.role, name))
        if obj is objects["sw"]:
            assert name == "GetProcessID"; return state["pid"]
        if name == "GetCWObjectFromID":
            return (objects["operation"] if args[0] == 3 else objects["feature"], state["found"])
        if name == "GetCWObjectID":
            return (state["op_id"] if args[0].role == "operation" else state["feature_id"], True)
        if name == "Suppressed": return state["suppressed"]
        if name == "OpernType": return state["op_type"]
        if name == "IGetAllFeatures": return objects["collection"]
        if name == "Count": return 1
        if name == "Item": return objects["feature"]
        if name in ("IGetLeadin", "IGetLeadout"):
            return objects["lead_in" if name == "IGetLeadin" else "lead_out"]
        owner = obj.role if obj.role.startswith("lead_") else type(obj).__name__
        key = by_owner[(owner, name)]
        result = deepcopy(values[key])
        if key == "lead_out_overlap" and state.get("on_last"):
            state["on_last"]()
        return tuple(result) if isinstance(result, list) else result

    monkeypatch.setattr(guard, "_member", native)
    monkeypatch.setattr(guard, "_typed", lambda obj, name, path: obj.QueryInterface(classes[name]))
    monkeypatch.setattr(guard, "raw_part_identity", lambda sw:deepcopy(state["document"]))
    monkeypatch.setattr(m, "_member", native)
    monkeypatch.setattr(m.finish, "interface_class", query_class)
    def check(key):
        if not state[key]: raise ValueError(key + " changed")
    kwargs = dict(process_id=123, expected_document=document, source_sha256=source["sha256"],
        evidence_pins=[evidence, own], verify_evidence=lambda:check("evidence_ok"),
        verify_owned_process=lambda:check("owned_ok"), check_events=lambda:check("events_ok"))
    ctx = SimpleNamespace(guard=lambda:guard.ScopedCamDispatchGuard(objects["sw"], "unused.tlb", **kwargs),
        identity=lambda:deepcopy(state["document"]), args={"expected_source_sha256":source["sha256"]},
        files=lambda:check("evidence_ok"), owned=lambda:check("owned_ok"))
    backend = SimpleNamespace(ctx=ctx, sw=objects["sw"], typelib_path="unused.tlb",
        native={"doc":objects["doc"],"operations":{}}, report={},
        args=dict(process_id=123, expected_document_path=source["path"],
                  progress_path=str(tmp_path/"progress.json"), receipt_path=str(tmp_path/"receipt.json")),
        loaded=dict(pins=[evidence,own],generated_pin={}), events=lambda:check("events_ok"))
    backend.persist = lambda:state.update(persists=state["persists"]+1)
    backend.target = lambda g, oid:m.finish.prior.NativeBackend.target(backend,g,oid)
    return SimpleNamespace(state=state, objects=objects, values=values, backend=backend,
                           source=source,evidence=evidence,kwargs=kwargs,classes=classes,tmp=tmp_path)


def test_full_field_batch_retains_boundaries_and_caches_owners(env):
    result = m.read_fields(env.backend, "inspect")
    assert result == env.values
    d = env.backend.report["direct_field_batches"][0]
    s = d["batch"]
    assert d["complete"] and d["field_count"] == 15
    assert s["read_scope_complete"] and s["complete_boundary_checks"] == 2
    assert s["content_hash_reads"] == 6 and s["timer_counts"]["identity"] == 6
    assert s["timer_counts"]["binding"] == 2
    assert s["getter_calls"] < 50 and s["query_interface_calls"] == 11
    assert s["retained_reference_count"] == 0 and not s["dispatch_available"]
    for name in ("ICWFinishMillOp","ICWFinishMillOp2","ICWFinishMillOp3"):
        assert env.state["qi"].count(("operation",name)) == 1
    assert env.state["qi"].count(("lead_in","ICWLeadInOut")) == 1
    assert env.state["qi"].count(("lead_out","ICWLeadInOut")) == 1
    assert all(not name.startswith("Set") and name not in ("GenerateToolpath","SaveActiveDocument")
               for _,name in env.state["calls"])


@pytest.mark.parametrize("change",["pid","document","dirty","source","evidence","events",
                                  "owned","operation","feature","suppressed","type","found"])
def test_exit_changes_never_release_values(env,change):
    def mutate():
        if change == "pid":env.state["pid"]=999
        elif change == "document":env.state["document"]["title"]="other.SLDPRT"
        elif change == "dirty":env.state["document"]["needs_save"]=True
        elif change == "source":Path(env.source["path"]).write_bytes(b"changed part")
        elif change == "evidence":Path(env.evidence["path"]).write_bytes(b"changed proof")
        elif change == "events":env.state["events_ok"]=False
        elif change == "owned":env.state["owned_ok"]=False
        elif change == "operation":env.state["op_id"]=145
        elif change == "feature":env.state["feature_id"]=80
        elif change == "suppressed":env.state["suppressed"]=True
        elif change == "type":env.state["op_type"]=0
        elif change == "found":env.state["found"]=False
    env.state["on_last"]=mutate
    with pytest.raises(ValueError):m.read_fields(env.backend,"inspect")
    d=env.backend.report["direct_field_batches"][0]
    assert not d["complete"] and d["batch"]["invalid"] and not d["batch"]["read_scope_complete"]


@pytest.mark.parametrize("key,bad",[
    ("bottom_finish",1),("out_independent",None),("first_depth",[.3,1]),
    ("side_step",[float("nan"),False]),("lead_in_radius",[.5,False]),
    ("lead_out_angle",float("inf")),("previous_allowance",False)])
def test_bad_field_shapes_fail_closed(env,key,bad):
    env.values[key]=bad
    with pytest.raises(ValueError,match="scalar shape"):m.read_fields(env.backend,"inspect")
    assert not env.backend.report["direct_field_batches"][0]["complete"]


def test_false_bottom_is_observed_not_replaced_with_recipe_value(env):
    env.values["bottom_finish"]=False
    result=m.read_fields(env.backend,"inspect")
    assert result["bottom_finish"] is False


def make_batch(env):
    return m.FinishFieldReadBatch(env.objects["sw"],"unused.tlb",**env.kwargs,
        generated_pin={},retained_objects=(env.objects["operation"],),
        verify_retained_binding=lambda:None,max_native_calls=128,
        progress=lambda:None,progress_state={})


@pytest.mark.parametrize("name",["SetSideCutAmt","BottomFinOpt_set","ActiveDoc","GetUnits","Save","GTP"])
def test_extra_getters_rejected(env,name):
    b=make_batch(env)
    with pytest.raises(ValueError):
        with b:b.read(env.objects["operation"],name)
    assert b.summary()["invalid"]


def test_dispatch_rejected_before_callback(env):
    b=make_batch(env);calls=[]
    with pytest.raises(ValueError):
        with b:b.dispatch_once(lambda:calls.append("write"),persist_pending=lambda:calls.append("pending"))
    assert calls==[] and b.summary()["invalid"]


@pytest.mark.parametrize("method",["sw_typed","plane","feature_dispatch"])
def test_inherited_unrelated_accessors_rejected(env,method):
    b=make_batch(env)
    with pytest.raises(ValueError):
        with b:getattr(b,method)(env.objects["operation"],"anything")
    assert b.summary()["invalid"]


def test_foreign_owner_cannot_be_read(env):
    b=make_batch(env)
    with pytest.raises(ValueError,match="retained document graph"):
        with b:b.read(Obj("foreign",env.state),"BottomFinOpt")


def test_metadata_failure_cannot_be_swallowed_into_success(env):
    b=make_batch(env)
    with pytest.raises(ValueError,match="invalidated"):
        with b:
            env.state["class_error"]=True
            with pytest.raises(ValueError):b.typed(env.objects["operation"],"ICWFinishMillOp")
    assert b.summary()["invalid"]


def test_missing_reader_pin_stops_before_native(env):
    env.backend.loaded["pins"]=env.backend.loaded["pins"][:1]
    with pytest.raises(ValueError,match="pinned live dependency"):m.read_fields(env.backend,"inspect")
    assert env.state["calls"]==[]


@pytest.mark.parametrize("label",["../path","",None,"x"*49])
def test_invalid_labels_stop_before_native(env,label):
    with pytest.raises(ValueError):m.read_fields(env.backend,label)
    assert env.state["calls"]==[]



def test_bad_bottom_raw_value_preserved_before_shape_rejection(env):
    env.values['bottom_finish'] = 1
    with pytest.raises(ValueError, match='scalar shape'):
        m.read_fields(env.backend, 'inspect')
    diagnostic = env.backend.report['direct_field_batches'][0]
    assert diagnostic['raw_fields']['bottom_finish'] == {
        'python_type':'int', 'value_recorded':True, 'value':1}
    assert not diagnostic['complete'] and env.state['persists'] > 0


def test_raw_observations_do_not_serialize_arbitrary_native_objects():
    class Unsafe:
        def __repr__(self): raise AssertionError('native repr forbidden')
    assert m.raw_observation(Unsafe()) == {'python_type':'Unsafe','value_recorded':False}
    assert m.raw_observation([Unsafe()])['items'] == [{'python_type':'Unsafe','value_recorded':False}]
    assert m.raw_observation(float('nan'))['nonfinite'] == 'nan'
    assert m.raw_observation('x' * 129)['value_recorded'] is False


@pytest.mark.parametrize('bottom,success', [(False, True), (1, False)])
def test_read_only_wrapper_persists_actual_bottom_and_never_promotes_error(env, monkeypatch, bottom, success):
    import json
    env.values['bottom_finish'] = bottom
    env.backend.args['expected_source_sha256'] = env.source['sha256']
    env.backend.loaded.update(state={'document':deepcopy(env.state['document'])},
                              offline_export_proof_pins=[], bootstrap_export_pins=[])
    env.backend.start = lambda:None
    env.backend.close = lambda:None
    env.backend.boundary = lambda:None
    env.backend.current_tool = lambda:{'assigned':273}
    def make_backend(loaded, params, sw, clsid, typelib, report, persist):
        env.backend.report = report
        env.backend.persist = persist
        return env.backend
    monkeypatch.setattr(m.finish, 'NativeBackend', make_backend)
    monkeypatch.setattr(m.finish, 'wanted_assignment', lambda loaded:{'assigned':273})
    result = m.run_inspection(None, '', '', params=env.backend.args,
                             loaded=env.backend.loaded, failed_pin=env.evidence)
    saved = json.loads(Path(env.backend.args['receipt_path']).read_text(encoding='utf-8-sig'))
    assert saved['readback_verified'] is success
    assert saved['direct_field_batches'][0]['raw_fields']['bottom_finish']['value'] == bottom
    assert not any(saved[k] for k in ('setter_attempted','GTP_attempted','model_saved','automatic_replay','mutation_authority'))
    if success:
        assert saved['fields']['bottom_finish'] is False
        assert saved['matches_requested_value']['bottom_finish'] is False
    else:
        assert saved['status'] == 'error' and 'fields' not in saved
    assert saved == result

