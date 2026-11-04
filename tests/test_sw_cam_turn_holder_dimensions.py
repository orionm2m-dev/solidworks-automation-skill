"""Offline holder qualification: real collector/delta with synthetic native graph."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from scripts import sw_cam_turn_holder_dimensions as cam


def ref(index=0):
    return dict(setup_index=0, operation_index=index, expected_operation_type=6)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    copy = tmp_path / "qualification.sldprt"
    original = tmp_path / "original.sldprt"
    copy.write_bytes(b"saved copy")
    original.write_bytes(b"protected original")
    receipt = tmp_path / "holder.json"
    marker_root = tmp_path / "markers"
    marker_root.mkdir()
    state = dict(writes=[], qi=[], snapshots=0, on_write=None, after_write=None,
                 on_snapshot=None, on_exit=None, identity_swap=False, generated=False,
                 extra_assignment=False, missing_crib=False)
    document = dict(path=str(copy), title=copy.name, type=1, needs_save=False)
    sessions = []

    class Holder:
        def __init__(self, catalog_id=4, token=None):
            object.__setattr__(self, "catalog_id", catalog_id)
            object.__setattr__(self, "token", object() if token is None else token)
            object.__setattr__(self, "values", dict(BoringBarDiameter=20., ShankLength=250.,
                LeadAngle=-10., BackClearAngle=0., FrontClearAngle=0., ZInsertOffset=0.,
                XInsertOffset=0., Protrusion=0., GetHolderThickness=20., HolderShape=0))
        def QueryInterface(self, interface):
            state["qi"].append(interface)
            return self.token
        def GetHolderType(self):
            return state.get("kind_after_claim", 2) if list(marker_root.iterdir()) else 2
        def GetHolderId(self):
            return state.get("id_after_claim", self.catalog_id) if list(marker_root.iterdir()) else self.catalog_id
        def GetToolOrientationForOperation(self, operation): return 5
        @property
        def HolderShapeFilePath(self): return state.get("holder_file_path") if self.catalog_id==4 else None
        @property
        def HolderShapeFileUnit(self): return state.get("holder_file_unit",2)
        def __getattr__(self, key):
            if key in self.values:
                return self.values[key]
            raise AssertionError("Unexpected holder member: " + key)
        def __setattr__(self, key, value):
            assert key in cam.FIELDS, "Unexpected setter"
            assert sessions[-1].active, "Setter outside event subscription"
            durable = json.loads(receipt.read_text(encoding="utf-8"))
            assert durable["phase"] == "property_put"
            assert durable["native_dispatch_pending"] is True
            assert durable["setters"][-1]["field"] == key
            assert durable["setters"][-1]["attempted"] is True
            assert durable["setters"][-1]["returned"] is False
            assert list(marker_root.iterdir()), "Once marker must precede setter"
            state["writes"].append((key, value))
            if state["on_write"]: state["on_write"](key, value)
            self.values[key] = value
            document["needs_save"] = True
            if state["after_write"]: state["after_write"](key, value)

    first, other = Holder(), Holder(9)
    replacement = Holder()

    class Turn:
        ToolType = 1
        InsertType = 1
        def __init__(self, owner): self.owner = owner
        def IGetTurnToolHolder(self):
            if self.owner.native_id == 101 and state["identity_swap"] and list(marker_root.iterdir()):
                return replacement
            return self.owner.holder
        def __getattr__(self, key):
            if key in self.owner.dimensions: return self.owner.dimensions[key]
            raise AssertionError("Unexpected turn member: " + key)

    class Tool:
        ToolType = 15
        def __init__(self, native_id, holder):
            self.native_id, self.holder = native_id, holder
            self.dimensions = dict(Thickness=4.7625, IncludedAngle=55., NoseRadius=.4, InscribedCircle=12.7)
            self.turn = Turn(self)
        def GetToolInfoString(self): return "synthetic tool"

    tool, second = Tool(101, first), Tool(102, other)
    operation = NS(native_id=71, IGetTool=lambda: tool, IGetAllFeatures=lambda:[NS(native_id=51)])
    second_operation = NS(native_id=72, IGetTool=lambda: tool if state['extra_assignment'] else second, IGetAllFeatures=lambda:[NS(native_id=52)])
    setup=NS(IGetEnumOperations=lambda:[operation,second_operation])
    class Doc:
        def GetCWObjectID(self, obj): return obj.native_id, True
    doc = Doc()
    crib = NS(GetAllTools=lambda: [second] if state["missing_crib"] else [tool, second])
    machine = NS(IGetToolcrib=lambda: crib,IGetEnumOpSetups=lambda:[setup])
    app, sw = object(), object()
    def typed(obj, name, *unused):
        if name == "ICWTurnTool": return obj.turn if isinstance(obj, Tool) else obj
        return obj
    def selected_tool():
        return dict(present=True, tool_type_raw=15, turn_tool_type_raw=1, insert_type_raw=1,
            parameters_status="available", info_raw="synthetic tool", dimensions_native=deepcopy(tool.dimensions),
            holder=dict(present=True, holder_type_raw=2, holder_id_raw=4,
                orientation_for_operation_raw=5, shape_raw=first.values["HolderShape"],
                dimensions_native={k:v for k,v in first.values.items() if k != "HolderShape"}))
    def base_snapshot(*args, **kwargs):
        assert kwargs["guarded_readers"] is True
        assert sessions[-1].active
        kwargs["check"]()
        state["snapshots"] += 1
        affected = [ref()] + ([ref(1)] if state["extra_assignment"] else [])
        result = dict(document=deepcopy(document), selected_operation=ref(), selected_tool_group=0,
            inventory=dict(operations=[dict(setup_index=0, operation_index=i,
                turn_operation_type=6, toolpath_generated=state["generated"] and i == 1,toolpath_record_counts=[]) for i in range(2)]),
            affected_operations=affected, operation_tools=[dict(operation=ref(), operation_native_id=71,
                tool_group=0, tool_native_id=101),dict(operation=ref(1),operation_native_id=72,tool_group=0 if state["extra_assignment"] else 1,tool_native_id=101 if state["extra_assignment"] else 102)],
            tool_groups=[dict(cam_object_id=101, dimensions_native={k:v for k,v in tool.dimensions.items() if k != "IncludedAngle"})],
            linked_features=[dict(native_id=51, segments=[dict(start_native=[0., 1., 2.])])],
            selected_tool=selected_tool())
        if state["on_snapshot"]: state["on_snapshot"](result)
        return result, dict(app=app, native_doc=doc, operation=operation, tool=tool, turn_tool=tool.turn)
    class Session:
        def __init__(self, *args):
            self.active = False
            self.disconnected = False
            self.entered = False
            self.error = 0
            sessions.append(self)
        def __enter__(self):
            self.active = self.entered = True
            return self
        def __exit__(self, *args):
            self.active = False
            self.disconnected = True
            if state["on_exit"]: state["on_exit"](self)
        def summary(self):
            return dict(subscribed=self.entered, active=self.active, disconnected=self.disconnected,
                event_count=self.error, overflow=0, callback_error_count=0, callback_errors=[],
                subscription_error=None, disconnect_errors=[])
    def read_own_tool(raw,op,typelib,read,result,**unused):
        holder=raw.turn.IGetTurnToolHolder()
        result.update(present=True,tool_type_raw=15,turn_tool_type_raw=1,insert_type_raw=1,parameters_status="available",
            info_raw=raw.GetToolInfoString(),dimensions_native=deepcopy(raw.dimensions),
            holder=dict(present=True,holder_type_raw=holder.GetHolderType(),holder_id_raw=holder.GetHolderId(),
                orientation_for_operation_raw=5,shape_raw=holder.values['HolderShape'],
                dimensions_native={k:v for k,v in holder.values.items() if k!='HolderShape'}))
    def live_inventory(*args):
        return dict(operations=[dict(setup_index=0,operation_index=i,turn_operation_type=6,
            toolpath_generated=state['generated'] and i==1,toolpath_record_counts=[]) for i in range(2)])
    monkeypatch.setattr(cam,'_logical_abi',lambda path:dict(native_calls=0))
    monkeypatch.setattr(cam,'_inventory',live_inventory)
    monkeypatch.setattr(cam.profile,'_read_tool',read_own_tool)
    monkeypatch.setattr(cam.single, "_snapshot", base_snapshot)
    monkeypatch.setattr(cam.single, "_identity", lambda obj: obj.QueryInterface("canonical-IUnknown"))
    monkeypatch.setattr(cam, "_typed", typed)
    monkeypatch.setattr(cam, "_context", lambda *args: (deepcopy(document), doc, None, machine, app))
    monkeypatch.setattr(cam, "_items", lambda raw, *args, limit: list(raw) if len(raw) <= limit else (_ for _ in ()).throw(ValueError("Too many items")))
    monkeypatch.setattr(cam, "document_snapshot", lambda *args: deepcopy(document))
    monkeypatch.setattr(cam, "_bootstrap", lambda *args: app)
    monkeypatch.setattr(cam, "CamMessageSession", Session)
    monkeypatch.setattr(cam, "local_evidence_root", lambda: marker_root)
    def isolated(_sw, config, check):
        check()
        if config["process_id"] != 123 or config["expected_process_create_time"] != 456.:
            raise ValueError("Wrong process lifetime")
        if config["expected_document_path"] != str(copy): raise ValueError("Wrong copy")
    monkeypatch.setattr(cam.guard, "isolated", isolated)
    defaults = dict(process_id=123, expected_process_create_time=456., expected_document_path=str(copy),
        expected_source_sha256=hashlib.sha256(copy.read_bytes()).hexdigest(), setup_index=0, operation_index=0,
        expected_operation_type=6, expected_operation_native_id=71, expected_tool_native_id=101, expected_holder_id=4,
        protected_part_pins=[dict(path=str(original), sha256=hashlib.sha256(original.read_bytes()).hexdigest())],
        values_native=dict(BoringBarDiameter=25., ShankLength=200., LeadAngle=-3.),
        qualification_only=True, message_policy="vendor_default")
    def prepare(**changes):
        return cam.configure_turn_holder_dimensions(sw, "clsid", "verified.tlb", **(defaults | dict(action="prepare") | changes))
    def apply(prepared=None, **changes):
        if prepared is None: prepared = prepare()
        args = dict(action="apply", expected_state_sha256=prepared.get("state_sha256", "0"*64),
            allowed_affected_operations=prepared.get("affected_operations", [ref()]), receipt_path=str(receipt))
        return cam.configure_turn_holder_dimensions(sw, "clsid", "verified.tlb", **(defaults | args | changes))
    return NS(**locals())


def test_prepare_uses_real_crib_collector_and_canonical_identity_without_writes(probe):
    r = probe.prepare()
    assert r["status"] == "prepared", r
    assert r["apply_eligible"] and not r["mutation_attempted"]
    assert [x["native_id"] for x in r["before"]["toolcrib"]] == [101, 102]
    assert r["snapshot_diagnostics"][0]["holder_identity_observation"]["selected_crib_same_canonical_identity"] is True
    assert r["logical_binding_verified"] and len(probe.state["qi"]) == 6
    assert not probe.state["writes"] and not probe.receipt.exists()
    assert not list(probe.marker_root.iterdir())


def test_three_puts_are_durable_and_each_has_full_crib_readback(probe):
    p = probe.prepare(); r = probe.apply(p)
    assert r["status"] == "review_required" and r["readback_verified"], r
    assert probe.state["writes"] == [("BoringBarDiameter",25.), ("LeadAngle",-3.), ("ShankLength",200.)]
    assert r["native_calls_returned_count"] == 3
    assert all(x["returned"] and x["readback_verified"] for x in r["setters"])
    assert probe.state["snapshots"] == 10
    assert r["before"]["toolcrib"][1] == r["after"]["toolcrib"][1]
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == r
    for key in ("model_saved", "GOP_attempted", "GTP_attempted", "tool_assignment_attempted",
                "physical_tool_qualified", "all_holder_sharing_qualified", "storage_independence_verified"):
        assert r[key] is False


def test_two_tool_ids_sharing_one_canonical_holder_block_before_write(probe):
    object.__setattr__(probe.other, "token", probe.first.token)
    r = probe.prepare()
    assert r["status"] == "error" and not r["mutation_attempted"]
    assert r["issue"]["type"] == "ValueError" and r["failed_phase"] == "before"
    assert not probe.state["writes"]


def test_equal_catalogue_ids_are_reported_but_not_called_independent(probe):
    object.__setattr__(probe.other, "catalog_id", 4)
    r = probe.prepare()
    assert r["status"] == "prepared", r
    a = r["before"]["holder_alias_observation"]
    assert a["equal_catalogue_other_tool_ids"] == [102]
    assert a["catalogue_alias_storage_independence_verified"] is False


def test_hidden_other_holder_alias_stops_after_first_put(probe):
    object.__setattr__(probe.other, "catalog_id", 4)
    probe.state["after_write"] = lambda key, value: probe.other.values.__setitem__(key, value)
    r = probe.apply()
    assert r["status"] == "uncertain" and not r["readback_verified"], r
    assert len(probe.state["writes"]) == 1 and r["native_calls_returned_count"] == 1
    assert not r["setters"][0]["readback_verified"]


def test_changed_view_without_owner_crib_write_through_stops_after_one_put(probe):
    p = probe.prepare(); probe.state["identity_swap"] = True
    r = probe.apply(p)
    assert r["status"] == "uncertain" and r["mutation_attempted"], r
    assert r["issue"]["type"] == "ValueError" and not r["readback_verified"]
    assert len(probe.state["writes"])==1


def test_generated_operation_sharing_tool_blocks_apply(probe):
    probe.state.update(extra_assignment=True, generated=True)
    p = probe.prepare(); assert not p["apply_eligible"]
    r = probe.apply(p)
    assert r["status"] == "error" and not probe.state["writes"]


@pytest.mark.parametrize("position", [1, 2, 3])
def test_each_partial_put_failure_stops_without_later_write_or_rollback(probe, position):
    def fail(key, value):
        if len(probe.state["writes"]) == position: raise RuntimeError("synthetic native failure")
    probe.state["on_write"] = fail
    r = probe.apply()
    assert r["status"] == "uncertain" and not r["readback_verified"]
    assert len(probe.state["writes"]) == position
    assert r["native_calls_returned_count"] == position - 1
    assert r["native_dispatch_pending"] and not r["setters"][-1]["returned"]
    assert not r["automatic_retry"] and not r["automatic_rollback"]


@pytest.mark.parametrize("field", ["GetHolderThickness", "BackClearAngle", "XInsertOffset", "HolderShape"])
def test_unrequested_coupled_holder_scalar_change_is_not_normalized(probe, field):
    probe.state["after_write"] = lambda key, value: probe.first.values.__setitem__(field, 1 if field == "HolderShape" else 99.)
    r = probe.apply()
    assert r["status"] == "uncertain" and not r["readback_verified"]
    assert len(probe.state["writes"]) == 1


def test_terminal_receipt_write_failure_revokes_success(probe, monkeypatch):
    write = cam._write_receipt
    def fail(path, report, **kwargs):
        if str(path) == str(probe.receipt) and report.get("status") == "review_required":
            raise OSError("synthetic terminal write failure")
        return write(path, report, **kwargs)
    monkeypatch.setattr(cam, "_write_receipt", fail)
    r = probe.apply()
    assert r["status"] == "uncertain" and not r["readback_verified"] and not r["apply_eligible"]
    assert "receipt_write_error" in r and len(probe.state["writes"]) == 3


@pytest.mark.parametrize("change", ["source", "protected", "hash", "refs", "pid", "lifetime"])
def test_stale_binding_failures_never_put(probe, change):
    p = probe.prepare(); args = {}
    if change == "source": probe.copy.write_bytes(b"changed saved copy")
    if change == "protected": probe.original.write_bytes(b"changed original")
    if change == "hash": args["expected_state_sha256"] = "0"*64
    if change == "refs": args["allowed_affected_operations"] = [ref(1)]
    if change == "pid": args["process_id"] = 124
    if change == "lifetime": args["expected_process_create_time"] = 457.
    r = probe.apply(p, **args)
    assert r["status"] == "error" and not r["mutation_attempted"] and not probe.state["writes"]


def test_once_marker_blocks_new_receipt_replay(probe):
    p = probe.prepare(); first = probe.apply(p)
    assert first["readback_verified"]
    r = probe.apply(p, receipt_path=str(probe.tmp_path / "another.json"))
    assert r["status"] == "error" and r["failed_phase"] == "preflight"
    assert not (probe.tmp_path / "another.json").exists()
    assert len(probe.state["writes"]) == 3


@pytest.mark.parametrize("values", [{"HolderShape":1}, {"BoringBarDiameter":0.}, {"ShankLength":True},
                                    {"LeadAngle":float("nan")}, {"LeadAngle":float("inf")}, {}])
def test_only_finite_three_documented_properties(probe, values):
    r = probe.prepare(values_native=values)
    assert r["status"] == "error" and not probe.state["writes"]


def test_post_cleanup_event_revokes_success(probe):
    probe.state["on_exit"] = lambda session: setattr(session, "error", 1)
    p = probe.prepare()
    assert p["status"] == "error" and not p["apply_eligible"]


def test_missing_assigned_tool_from_crib_blocks_prepare(probe):
    probe.state["missing_crib"] = True
    r = probe.prepare()
    assert r["status"] == "error" and not r["apply_eligible"]


def test_duplicate_crib_id_blocks_prepare(probe):
    probe.second.native_id = 101
    r = probe.prepare()
    assert r["status"] == "error" and r["issue"]["type"] == "ValueError"
    assert any(x["function"] == "read_tools" for x in r["issue"]["locations"])


def test_own_vs_crib_holder_read_disagreement_blocks_prepare(probe):
    probe.state["on_snapshot"] = lambda value: value["selected_tool"]["holder"]["dimensions_native"].__setitem__("ShankLength", 1.)
    r = probe.prepare()
    assert r["status"] == "error" and r["issue"]["type"] == "ValueError"
    assert not r["apply_eligible"] and not probe.state["writes"]


def test_prepare_rejects_mutation_inputs(probe):
    r = probe.prepare(expected_state_sha256="0"*64)
    assert r["status"] == "error" and probe.state["snapshots"] == 0


@pytest.mark.parametrize("key,value", [("kind_after_claim", 2.0), ("id_after_claim", 4.0), ("id_after_claim", True)])
def test_prewrite_holder_classification_requires_native_integer(probe, key, value):
    p = probe.prepare(); probe.state[key] = value
    r = probe.apply(p)
    assert r["status"] == "error" and not r["mutation_attempted"]
    assert not probe.state["writes"] and not any(x["attempted"] for x in r["setters"])



def test_identity_diagnostic_distinguishes_missing_selected_crib_holder(probe):
    probe.state["missing_crib"] = True
    result = probe.prepare()
    diagnostic = result["snapshot_diagnostics"][0]
    identity = diagnostic["holder_identity_observation"]
    assert result["status"] == "error" and not result["apply_eligible"]
    assert identity["selected_crib_holder_present"] is False
    assert identity["selected_crib_same_canonical_identity"] is None
    assert [row["native_id"] for row in diagnostic["holder_crib_rows"]] == [102]
    assert diagnostic["holder_profile_observed"]["dimensions_native"]["ShankLength"] == 250.
    assert not probe.state["writes"] and not list(probe.marker_root.iterdir())


def test_identity_diagnostic_preserves_equal_scalars_with_distinct_canonical_objects(probe):
    returned = iter([probe.first, probe.replacement])
    probe.tool.turn.IGetTurnToolHolder = lambda: next(returned)
    result = probe.prepare()
    diagnostic = result["snapshot_diagnostics"][0]
    identity = diagnostic["holder_identity_observation"]
    assert result["status"] == "error" and not result["apply_eligible"]
    assert identity["selected_crib_holder_present"] is True
    assert identity["selected_crib_same_canonical_identity"] is False
    own = diagnostic["holder_profile_observed"]["dimensions_native"]
    crib = next(row for row in diagnostic["holder_crib_rows"] if row["native_id"] == 101)
    assert crib["holder_dimensions_native"]["ShankLength"] == own["ShankLength"] == 250.
    assert identity["scalar_equality_proves_identity"] is False
    assert identity["storage_independence_verified"] is False
    assert identity["crib_holder_identity_groups"] == [
        dict(tool_native_id=101,canonical_identity_group=1),
        dict(tool_native_id=102,canonical_identity_group=2)]
    assert len(probe.state["qi"]) == 3
    assert not probe.state["writes"] and not list(probe.marker_root.iterdir())
    json.dumps(result)


def test_identity_diagnostic_keeps_shared_canonical_holder_rejected(probe):
    object.__setattr__(probe.other, "token", probe.first.token)
    result = probe.prepare()
    identity = result["snapshot_diagnostics"][0]["holder_identity_observation"]
    assert result["status"] == "error" and not result["apply_eligible"]
    assert identity["selected_crib_same_canonical_identity"] is True
    assert identity["crib_holder_identity_groups"] == [
        dict(tool_native_id=101,canonical_identity_group=0),
        dict(tool_native_id=102,canonical_identity_group=0)]
    assert not probe.state["writes"] and not list(probe.marker_root.iterdir())
