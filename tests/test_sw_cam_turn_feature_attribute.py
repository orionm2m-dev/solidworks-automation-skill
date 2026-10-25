"""策略目录、单属性写入与完整回读的离线回归；不连接 CAD。"""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_cam_turn_feature_attribute as cam
from scripts import sw_cam_events as events

REAL_ITEMS = cam._items
REAL_INVENTORY = cam._inventory
REAL_CONTEXT = cam._context


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = tmp_path / "part.sldprt"; path.write_bytes(b"saved part")
    receipt = tmp_path / "attribute.json"
    document = dict(path=str(path), title=path.name, type=1, needs_save=False)
    state = dict(document=document, on_write=None, on_exit=None, on_enter=None,
                 model_features=[dict(name="NativeLine", type="ProfileFeature")],
                 solids=[dict(box_model_m=[0.,0.,0.,.1,.1,.1],mass_properties_native=[0.,0.,0.,.001])])
    line = dict(curve_type_raw=0, curve_parameters_available=True, start_native=[30.,0.,10.],
                end_native=[30.,0.,5.], line_native=dict(start_diameter=60.,end_diameter=60.,true_length=5.))
    class Feature:
        def __init__(self, native_id):
            self.native_id = native_id
            self.profile = dict(turn_feature_type_raw=1,segment_count=1,segments=[deepcopy(line)],
                attribute_id_raw=0,attribute_name="Rough-Finish")
            self.IGetAllAttributes = Mock(return_value=("Rough-Finish", "Thread"))
            self.GetTdbIdForAttribute = Mock(return_value=17)
            self.writes = []
        @property
        def Attribute(self): return self.profile["attribute_id_raw"]
        @Attribute.setter
        def Attribute(self, value):
            durable = json.loads(receipt.read_text())
            assert durable["phase"] == "Attribute" and durable["mutation_attempted"]
            assert session.data["subscribed"] and not session.data["disconnected"]
            self.writes.append(value)
            self.profile.update(attribute_id_raw=value,attribute_name="Thread")
            state["document"]["needs_save"] = True
            if state["on_write"]: state["on_write"]()
        def GetAttributeName(self): return self.profile["attribute_name"]
    old, target = Feature(51), Feature(382)
    feature_setup = N(IGetEnumFeatures=Mock(return_value=[old,target]))
    operation = N(native_id=91, IGetAllFeatures=Mock(return_value=[old]))
    operation_setup = N(IGetEnumOperations=Mock(return_value=[operation]))
    machine = N(IGetEnumSetups=Mock(return_value=[feature_setup]), IGetEnumOpSetups=Mock(return_value=[operation_setup]))
    inventory = dict(feature_count=2,feature_counts_by_setup=[2],operation_count=1,
        operation_setup_count=1,operations=[dict(turn_operation_type=2,toolpath_generated=True,toolpath_record_counts=[79])])
    model = N(GetActiveSketch2=None)
    sw = N(ActiveDoc=model)
    app = N(IGetTechDBPath=Mock(return_value="C:/native/catalog.mdb"))
    forbidden = [Mock(side_effect=AssertionError("No save/GOP/GTP/insertion/update")) for _ in range(5)]
    app.SaveActiveDocument,app.ActiveDocGOP,app.ActiveDocGTP,app.SetTechDBPath,app.Rebuild = forbidden
    doc = N(GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    class Session:
        def __init__(self):
            self.data=dict(subscribed=False,disconnected=False,active=False,event_count=0,overflow=0,
                callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
        def __enter__(self):
            self.data["subscribed"]=True
            self.data["active"]=True
            if state["on_enter"]: state["on_enter"]()
            return self
        def __exit__(self,*_):
            self.data["disconnected"]=True
            self.data["active"]=False
            if state["on_exit"]: state["on_exit"]()
        def summary(self): return deepcopy(self.data)
    session=Session(); factory=Mock(return_value=session)
    documents=Mock(side_effect=lambda *_:deepcopy(state["document"]))
    contexts=Mock(side_effect=lambda *_:(deepcopy(state["document"]),doc,object(),machine,app))
    def read_profile(raw, _path, read, budget, result, **kwargs):
        budget[0] += raw.profile["segment_count"]
        result.update(deepcopy(raw.profile))
        result["attribute_id_raw"] = read(raw,"Attribute")
        result["attribute_name"] = read(raw,"GetAttributeName")
    monkeypatch.setattr(cam,"_context",contexts)
    monkeypatch.setattr(cam,"_inventory",lambda *_:deepcopy(inventory))
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    monkeypatch.setattr(cam,"_items",lambda obj,*_,**_kwargs:list(obj))
    monkeypatch.setattr(cam,"_read_profile",read_profile)
    monkeypatch.setattr(cam,"_body_state",lambda *_:deepcopy(state["solids"]))
    monkeypatch.setattr(cam,"_model_features",lambda *_:deepcopy(state["model_features"]))
    monkeypatch.setattr(cam,"document_snapshot",documents)
    monkeypatch.setattr(events,"CamMessageSession",factory)
    defaults=dict(expected_document_path=str(path),feature_setup_index=0,expected_feature_native_id=382,
        expected_turn_feature_type=1,qualification_only=True,message_policy="vendor_default",attribute_name="Thread")
    def call(action="inspect",**changes):
        return cam.configure_turn_feature_attribute(sw,"clsid","registered/camworks.tlb",**(defaults|dict(action=action)|changes))
    def apply(**changes):
        before=call("prepare")
        assert before["status"] == "ok", before
        return call("apply",**(dict(expected_state_sha256=before["state_sha256"],receipt_path=str(receipt))|changes))
    return N(**locals())


def no_mutation(p):
    assert p.target.writes == []
    for method in p.forbidden: method.assert_not_called()


def test_inspect_reads_exact_catalog_dynamic_id_and_optional_techdb_only(probe):
    result=probe.call(read_techdb_path=True)
    assert result["status"]=="ok" and result["phase"]=="inspected"
    assert result["catalog"]["names"]==["Rough-Finish","Thread"]
    assert result["catalog"]["requested_id"]==17
    probe.target.GetTdbIdForAttribute.assert_called_once_with("Thread")
    probe.app.IGetTechDBPath.assert_called_once_with()
    assert result["techdb"]["path_raw"]=="C:/native/catalog.mdb"
    assert result["linked_operations"]==[] and not result["apply_eligible"]
    assert not result["thread_condition_verified"] and not result["thread_depth_verified"]
    probe.factory.assert_not_called(); no_mutation(probe)


def test_inspect_without_name_never_guesses_lookup_or_techdb(probe):
    result=probe.call(attribute_name=None)
    assert result["catalog"]["requested_id"] is None
    probe.target.GetTdbIdForAttribute.assert_not_called()
    probe.app.IGetTechDBPath.assert_not_called(); no_mutation(probe)


def test_prepare_is_readonly_binds_complete_state(probe):
    result=probe.call("prepare")
    assert result["phase"]=="prepared" and result["apply_eligible"]
    assert result["state_sha256"]==cam._state_digest(result["before"])
    assert result["old_attribute"]==dict(id=0,name="Rough-Finish")
    assert result["requested_attribute"]==dict(id=17,name="Thread")
    assert not probe.receipt.exists()
    probe.factory.assert_not_called(); no_mutation(probe)


def test_apply_writes_dynamic_id_once_with_explicit_before_disconnect_cam_scope(probe):
    result=probe.apply()
    assert result["status"]=="review_required" and result["readback_verified"]
    assert probe.target.writes==[17]
    assert cam._target_profile(result["final_state"])["attribute_name"]=="Thread"
    assert result["final_state"]["inventory"]==probe.inventory
    assert result["final_state"]["saved_file_sha256"]==result["before"]["saved_file_sha256"]
    assert result["messages"]["disconnected"] and not result["messages"]["active"]
    assert not result["model_saved"]
    assert result["full_cam_snapshot_scope"] == "before_event_disconnect"
    assert result["post_cleanup_cam_read_performed"] is False
    assert result["post_cleanup_document_and_file_verified"] is True
    assert not result["thread_condition_verified"] and not result["generation_attempted"]
    assert json.loads(probe.receipt.read_text())["readback_verified"]
    assert probe.documents.call_count < 30
    for method in probe.forbidden: method.assert_not_called()


@pytest.mark.parametrize("field,value",[("feature_setup_index",True),("expected_feature_native_id",False),
    ("expected_feature_native_id",0),("expected_turn_feature_type","1"),("qualification_only",1),
    ("message_policy","yes"),("read_techdb_path",1),("attribute_name",""),("attribute_name",17),
    ("expected_document_path","relative.sldprt"),("action","save")])
def test_strict_inputs_fail_before_context(probe,field,value):
    result=probe.call(**{field:value})
    assert result["status"]=="error"; probe.contexts.assert_not_called(); no_mutation(probe)


@pytest.mark.parametrize("action",["prepare","apply"])
def test_techdb_path_is_inspect_only(probe,action):
    result=probe.call(action,read_techdb_path=True)
    assert result["status"]=="error"; probe.contexts.assert_not_called(); no_mutation(probe)


@pytest.mark.parametrize("raw", [False,17,(("Thread",),),["Thread","Thread"],[""],["Thread"]*65])
def test_unknown_or_ambiguous_catalog_shape_is_preserved_but_never_looked_up(probe,raw):
    probe.target.IGetAllAttributes.return_value=raw
    result=probe.call()
    assert not result["catalog"]["names_resolved"]
    assert result["catalog"]["converted_result_shape"]["python_type"]==type(raw).__name__
    probe.target.GetTdbIdForAttribute.assert_not_called()
    assert probe.call("prepare")["status"]=="error"; no_mutation(probe)


def test_catalog_string_is_one_exact_name_not_split_or_trimmed(probe):
    probe.target.IGetAllAttributes.return_value=" Thread "
    result=probe.call(attribute_name="Thread")
    assert result["catalog"]["reason"]=="exact_requested_name_absent"
    probe.target.GetTdbIdForAttribute.assert_not_called()
    result=probe.call(attribute_name=" Thread ")
    assert result["catalog"]["requested_id"]==17
    probe.target.GetTdbIdForAttribute.assert_called_once_with(" Thread ")


@pytest.mark.parametrize("value",[0,-1,True,"17"])
def test_nonpositive_or_noninteger_lookup_never_authorizes_write(probe,value):
    probe.target.GetTdbIdForAttribute.return_value=value
    assert probe.call("prepare")["status"]=="error"; no_mutation(probe)


@pytest.mark.parametrize("change",["dirty","linked","wrong_setup","wrong_type","wrong_id","two_segments","arc","duplicate_feature"])
def test_preconditions_before_any_subscription_or_write(probe,change):
    if change=="dirty": probe.state["document"]["needs_save"]=True
    elif change=="linked": probe.operation.IGetAllFeatures.return_value=[probe.target]
    elif change=="wrong_setup": probe.defaults["feature_setup_index"]=1
    elif change=="wrong_type": probe.target.profile["turn_feature_type_raw"]=2
    elif change=="wrong_id": probe.defaults["expected_feature_native_id"]=999
    elif change=="two_segments": probe.target.profile["segment_count"]=2
    elif change=="arc": probe.target.profile["segments"][0]["curve_type_raw"]=1
    else: probe.feature_setup.IGetEnumFeatures.return_value.append(probe.target)
    assert probe.call("prepare")["status"]=="error"
    probe.factory.assert_not_called(); no_mutation(probe)


def test_same_attribute_is_not_written_again(probe):
    probe.target.profile.update(attribute_id_raw=17,attribute_name="Thread")
    assert probe.call("prepare")["status"]=="error"; no_mutation(probe)


def test_wrong_hash_and_existing_receipt_never_write(probe):
    result=probe.apply(expected_state_sha256="a"*64)
    assert result["status"]=="error"; no_mutation(probe)
    probe.receipt.write_bytes(b"immutable")
    result=probe.apply()
    assert result["status"]=="error" and probe.receipt.read_bytes()==b"immutable"; no_mutation(probe)


@pytest.mark.parametrize("when",["enter","write","exit"])
def test_events_stop_next_native_read_or_write(probe,when):
    def event(): probe.session.data["event_count"]=1
    probe.state[{"enter":"on_enter","write":"on_write","exit":"on_exit"}[when]]=event
    result=probe.apply()
    assert not result["readback_verified"]
    if when=="enter": no_mutation(probe)
    else: assert probe.target.writes==[17]
    if when=="write":
        assert [row["phase"] for row in result["snapshot_diagnostics"]]==["initial","before_write"]


@pytest.mark.parametrize("change",["wrong_id","wrong_name","geometry","old_feature","inventory","file","body","model"])
def test_any_unrequested_change_or_wrong_readback_rejects_success(probe,change):
    def mutate():
        if change=="wrong_id": probe.target.profile["attribute_id_raw"]=18
        elif change=="wrong_name": probe.target.profile["attribute_name"]="Other"
        elif change=="geometry": probe.target.profile["segments"][0]["start_native"][0]+=1
        elif change=="old_feature": probe.old.profile["attribute_name"]="Other"
        elif change=="inventory": probe.inventory["operations"][0]["toolpath_record_counts"]=[0]
        elif change=="file": probe.path.write_bytes(b"unexpected save")
        elif change=="body": probe.state["solids"][0]["box_model_m"][0]=1
        else: probe.state["model_features"].append(dict(name="unexpected",type="Boss"))
    probe.state["on_write"]=mutate
    result=probe.apply()
    assert result["status"]=="uncertain" and not result["readback_verified"]
    assert probe.target.writes==[17]


def test_no_cam_getter_after_disconnect_and_scope_does_not_claim_later_cam_state(probe, monkeypatch):
    original_member = cam._member
    original_snapshot = cam._snapshot
    def member(obj, name, *args):
        if probe.session.data["disconnected"] and obj is not probe.sw and obj is not probe.model:
            raise AssertionError("CAM getter after event disconnect")
        return original_member(obj, name, *args)
    def snapshot(*args, **kwargs):
        assert not probe.session.data["disconnected"], "No CAM snapshot after event disconnect"
        return original_snapshot(*args, **kwargs)
    monkeypatch.setattr(cam, "_member", member)
    monkeypatch.setattr(cam, "_snapshot", snapshot)
    probe.state["on_exit"] = lambda: probe.target.profile.__setitem__("attribute_name", "Later unobserved change")
    result = probe.apply()
    assert result["status"] == "review_required" and result["readback_verified"]
    assert result["full_cam_snapshot_scope"] == "before_event_disconnect"
    assert result["post_cleanup_cam_read_performed"] is False
    assert result["post_cleanup_document_and_file_verified"] is True
    assert cam._target_profile(result["final_state"])["attribute_name"] == "Thread"
    assert probe.target.profile["attribute_name"] == "Later unobserved change"
    assert "after_cleanup" not in [row["phase"] for row in result["snapshot_diagnostics"]]


@pytest.mark.parametrize("change", ["document_identity", "document_dirty", "saved_file"])
def test_cleanup_document_or_file_changes_revoke_verification(probe, change):
    def mutate():
        if change == "document_identity": probe.state["document"]["path"] = str(probe.path.with_name("other.sldprt"))
        elif change == "document_dirty": probe.state["document"]["needs_save"] = False
        else: probe.path.write_bytes(b"unexpected save during cleanup")
    probe.state["on_exit"] = mutate
    result = probe.apply()
    assert result["status"] == "uncertain" and not result["readback_verified"]
    assert not result["post_cleanup_document_and_file_verified"]
    assert probe.target.writes == [17]


def test_receipt_failure_before_put_never_writes(probe,monkeypatch):
    original=cam._write_receipt
    def fail(path,result,**kwargs):
        if result["phase"]=="Attribute": raise OSError("disk unavailable")
        return original(path,result,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",fail)
    assert not probe.apply()["native_call_returned"]; no_mutation(probe)


def test_final_receipt_failure_revokes_verified_result(probe,monkeypatch):
    original=cam._write_receipt
    def fail(path,result,**kwargs):
        if result["phase"]=="finished": raise OSError("disk unavailable")
        return original(path,result,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",fail)
    result=probe.apply()
    assert not result["readback_verified"] and result["status"]=="uncertain"


def test_native_read_exception_preserves_partial_and_stops_lookup(probe):
    probe.target.IGetAllAttributes.side_effect=RuntimeError("native catalog fault")
    result=probe.call()
    assert result["failed_stage"]=="IGetAllAttributes"
    assert len(result["snapshot_diagnostics"][0]["features"])==2
    probe.target.GetTdbIdForAttribute.assert_not_called(); no_mutation(probe)


@pytest.mark.parametrize("count", [65, -1, True])
def test_bounded_collection_rejects_count_before_any_item(monkeypatch, count):
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    collection=N(Count=count,Item=Mock())
    with pytest.raises(ValueError): REAL_ITEMS(collection,"tlb",cam._member,limit=64)
    collection.Item.assert_not_called()


def test_message_during_collection_item_stops_later_items(monkeypatch):
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    calls=[]; stopped=False
    collection=N(Count=3,Item=Mock(return_value=object()))
    def read(obj,name,*args):
        nonlocal stopped
        if stopped: raise ValueError("CAM event")
        calls.append((name,args))
        value=cam._member(obj,name,*args)
        if name=="Item": stopped=True; raise ValueError("CAM event")
        return value
    with pytest.raises(ValueError): REAL_ITEMS(collection,"tlb",read)
    assert calls==[("Count",()),("Item",(0,))]
    collection.Item.assert_called_once_with(0)


def test_inventory_uses_guarded_reader_for_all_native_calls(monkeypatch):
    monkeypatch.setattr(cam,"_typed",lambda obj,*_:obj)
    def collection(values):return N(Count=len(values),Item=lambda index:values[index])
    operation=N(GetIsToolpathGenerated=Mock(return_value=True),IGetEnumToolpaths=Mock(),OpernType=2)
    feature_setup=N(IGetEnumFeatures=lambda:collection([object()]))
    operation_setup=N(IGetEnumOperations=lambda:collection([operation]))
    machine=N(IGetEnumSetups=lambda:collection([feature_setup]),IGetEnumOpSetups=lambda:collection([operation_setup]),
              IGetWorkpiece=Mock())
    calls=[]
    def read(obj,name,*args):
        calls.append(name)
        value=cam._member(obj,name,*args)
        if name=="GetIsToolpathGenerated":raise ValueError("event after native return")
        return value
    with pytest.raises(ValueError): REAL_INVENTORY(machine,"tlb",read)
    assert calls[-1]=="GetIsToolpathGenerated" and "Count" in calls and "Item" in calls
    operation.IGetEnumToolpaths.assert_not_called(); machine.IGetWorkpiece.assert_not_called()


def test_immediate_scalar_readback_precedes_large_snapshot(probe,monkeypatch):
    original=cam._snapshot
    def snapshot(*args,**kwargs):
        if kwargs["diagnostic"]["phase"]=="after_write":
            receipt=json.loads(probe.receipt.read_text())
            assert receipt["attribute_readback"]==dict(id=17,name="Thread")
            assert receipt["scalar_readback_verified"]
        return original(*args,**kwargs)
    monkeypatch.setattr(cam,"_snapshot",snapshot)
    result=probe.apply()
    assert result["readback_verified"] and not result["toolpath_coordinates_verified"]


def test_wrong_scalar_readback_stops_before_large_after_snapshot(probe):
    probe.state["on_write"]=lambda:probe.target.profile.__setitem__("attribute_id_raw",18)
    result=probe.apply()
    assert result["attribute_readback"]["id"]==18 and not result["readback_verified"]
    assert [row["phase"] for row in result["snapshot_diagnostics"]]==["initial","before_write"]


@pytest.mark.parametrize("stop_after", [None, "GetAddInObject", "GetCWApp", "IGetActiveDoc", "GetDocType", "IGetMachine", "MachType"])
def test_local_context_routes_every_getter_through_guard_and_stops_on_event(monkeypatch, stop_after):
    machine = N(MachType=Mock(return_value=3))
    document = N(GetDocType=Mock(return_value=1), IGetMachine=Mock(return_value=machine))
    app = N(IGetActiveDoc=Mock(return_value=document))
    addin = N(GetCWApp=Mock(return_value=app))
    sw = N(GetAddInObject=Mock(return_value=addin))
    snapshot = dict(path="C:/qualification/part.sldprt", title="part.sldprt", type=1, needs_save=False)
    monkeypatch.setattr(cam, "document_snapshot", Mock(return_value=snapshot))
    monkeypatch.setattr(cam, "_typed", lambda obj, *_: obj)
    methods = [(sw, "GetAddInObject"), (addin, "GetCWApp"), (app, "IGetActiveDoc"),
               (document, "GetDocType"), (document, "IGetMachine"), (machine, "MachType")]
    calls = []
    def read(obj, name, *args):
        calls.append(name)
        value = cam._member(obj, name, *args)
        if name == stop_after:
            raise ValueError("event after context getter")
        return value
    if stop_after is None:
        result = REAL_CONTEXT(sw, "exact-clsid", "registered.tlb", read)
        assert result == (snapshot, document, document, machine, app)
        assert calls == [name for _, name in methods]
    else:
        with pytest.raises(ValueError, match="event after context getter"):
            REAL_CONTEXT(sw, "exact-clsid", "registered.tlb", read)
        index = [name for _, name in methods].index(stop_after)
        assert calls == [name for _, name in methods[:index+1]]
        for obj, name in methods[index+1:]:
            getattr(obj, name).assert_not_called()
    sw.GetAddInObject.assert_called_once_with("exact-clsid")


_MASS_PREPARE = 1.7184100371658502e-14
_MASS_APPLY = 1.71841003715857e-14


def _set_last_mass_component(probe, value):
    """保留实际证据中的第 12 项，不把测试缩成不同量级的标量。"""
    mass = probe.state["solids"][0]["mass_properties_native"]
    mass.extend([0.0] * (12-len(mass)))
    mass[11] = value


def test_observed_mass_noise_has_same_fingerprint_and_apply_retains_raw_values(probe):
    _set_last_mass_component(probe, _MASS_PREPARE)
    prepared = probe.call("prepare")
    assert prepared["status"] == "ok"
    _set_last_mass_component(probe, _MASS_APPLY)
    fresh = probe.call("prepare")
    assert cam._states_equal(prepared["before"], fresh["before"])
    assert prepared["state_sha256"] == fresh["state_sha256"]
    assert prepared["before"]["solids"][0]["mass_properties_native"][11] == _MASS_PREPARE
    assert fresh["before"]["solids"][0]["mass_properties_native"][11] == _MASS_APPLY
    result = probe.call("apply", expected_state_sha256=prepared["state_sha256"], receipt_path=str(probe.receipt))
    assert result["status"] == "review_required" and result["readback_verified"]
    assert probe.target.writes == [17]
    assert result["final_state"]["solids"][0]["mass_properties_native"][11] == _MASS_APPLY
    assert result["mass_comparison"] == {
        "raw_values_retained": True, "hash_significant_digits": 11,
        "relative_tolerance": 1e-10, "absolute_tolerance": 0.0,
        "scope": "solids.mass_properties_native_only", "other_state_fields": "exact",
        "rounding_boundary_mismatch": "stop_and_prepare_again_no_automatic_retry"}
    durable = json.loads(probe.receipt.read_text())
    assert durable["before"]["solids"][0]["mass_properties_native"][11] == _MASS_APPLY


def test_mass_change_above_tolerance_rejects_prepared_hash_before_write(probe):
    _set_last_mass_component(probe, _MASS_PREPARE)
    prepared = probe.call("prepare")
    _set_last_mass_component(probe, _MASS_PREPARE * (1.0+1e-8))
    fresh = probe.call("prepare")
    assert not cam._states_equal(prepared["before"], fresh["before"])
    assert prepared["state_sha256"] != fresh["state_sha256"]
    result = probe.call("apply", expected_state_sha256=prepared["state_sha256"], receipt_path=str(probe.receipt))
    assert result["status"] == "error" and not result["mutation_attempted"]
    probe.factory.assert_not_called()
    no_mutation(probe)


@pytest.mark.parametrize("change", ["geometry", "saved_file"])
def test_mass_rounding_does_not_relax_geometry_or_file_fingerprint(probe, change):
    _set_last_mass_component(probe, _MASS_PREPARE)
    prepared = probe.call("prepare")
    _set_last_mass_component(probe, _MASS_APPLY)
    if change == "geometry":
        probe.state["solids"][0]["box_model_m"][0] = 1e-14
    else:
        probe.path.write_bytes(b"changed saved part")
    result = probe.call("apply", expected_state_sha256=prepared["state_sha256"], receipt_path=str(probe.receipt))
    assert result["status"] == "error" and not result["mutation_attempted"]
    probe.factory.assert_not_called()
    no_mutation(probe)


def test_rounding_boundary_can_fail_closed_even_when_mass_comparison_is_close(probe):
    """十一个有效位不是容差等价关系；边界两侧仍可能要求重新 prepare。"""
    _set_last_mass_component(probe, 1.00000000004)
    before = probe.call("prepare")["before"]
    after = deepcopy(before)
    after["solids"][0]["mass_properties_native"][11] = 1.00000000006
    assert cam._states_equal(before, after)
    assert cam._state_digest(before) != cam._state_digest(after)
