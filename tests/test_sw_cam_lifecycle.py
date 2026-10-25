"""CAM 保存/关闭生命周期离线回归；原生对象均为替身。"""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

from scripts import sw_cam_events as events
from scripts import sw_cam_lifecycle as cam

TLB = "verified/camworks.tlb"


@pytest.fixture
def probe(monkeypatch, tmp_path):
    path = tmp_path / "qualification.sldprt"
    path.write_bytes(b"initial saved qualification file")
    receipt = tmp_path / "lifecycle.json"
    document = dict(path=str(path),title=path.name,type=1,needs_save=False)
    inventory = dict(feature_count=3,operation_count=2,operation_setup_count=1,
        operations=[dict(turn_operation_type=2,toolpath_generated=True,toolpath_record_counts=[31]),
                    dict(turn_operation_type=3,toolpath_generated=True,toolpath_record_counts=[7])])
    before = dict(document=deepcopy(document),inventory=deepcopy(inventory),saved_file_sha256=cam._file_hash(path))
    state = dict(document=deepcopy(document),inventory=deepcopy(inventory),open_documents=[],
                 on_enter=None,on_exit=None,on_native=None,on_document=None,on_inventory=None)
    forbidden = [Mock(side_effect=AssertionError("Forbidden direct SW action or generation")) for _ in range(4)]
    sw = N(CloseDoc=forbidden[0],CloseAllDocuments=forbidden[1],Save3=forbidden[2],UserControl=True)
    other_path = tmp_path / "unrelated.sldprt"
    other_document = dict(path=str(other_path),title=other_path.name,type=1,needs_save=False)
    def metadata(data):
        return N(GetPathName=Mock(return_value=data["path"]),GetTitle=Mock(return_value=data["title"]),
                 GetType=Mock(return_value=data["type"]))
    other = metadata(other_document)
    sw.GetDocuments = Mock(side_effect=lambda: state["open_documents"])
    app = N(ActiveDocGTP=forbidden[3])
    class Session:
        def __init__(self):
            self.data=dict(subscribed=False,disconnected=False,event_count=0,overflow=0,
                          callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
        def __enter__(self):
            self.data["subscribed"]=True
            if state["on_enter"]:state["on_enter"]()
            return self
        def __exit__(self,*_):
            self.data["disconnected"]=True
            if state["on_exit"]:state["on_exit"]()
        def summary(self):return deepcopy(self.data)
    session = Session()
    factory=Mock(return_value=session)
    native_records=[]
    def native(action):
        durable=json.loads(receipt.read_text())
        assert durable["phase"]==("SaveActiveDocument" if action=="save" else "CloseActiveDocument")
        assert durable["mutation_attempted"] and durable["native_call_attempted"]
        assert not durable["native_call_returned"]
        assert session.data["subscribed"] and not session.data["disconnected"]
        native_records.append(dict(action=action,inventory_calls=inventories.call_count,
                                   document_calls=documents.call_count,context_calls=contexts.call_count))
        if action=="save":
            state["document"]["needs_save"]=False
            path.write_bytes(b"native save mock updated file")
        else:
            state["document"]=deepcopy(other_document)
            state["open_documents"]=[other]
        if state["on_native"]:state["on_native"]()
    app.SaveActiveDocument=Mock(side_effect=lambda:native("save"))
    app.CloseActiveDocument=Mock(side_effect=lambda:native("close"))
    def snapshot(*_):
        if state["on_document"]:state["on_document"]()
        return deepcopy(state["document"])
    documents=Mock(side_effect=snapshot)
    machine=object()
    contexts=Mock(side_effect=lambda *_:(deepcopy(state["document"]),object(),object(),machine,app))
    def inventory_read(*_):
        if state["on_inventory"]:state["on_inventory"]()
        return deepcopy(state["inventory"])
    inventories=Mock(side_effect=inventory_read)
    typed=Mock(side_effect=lambda obj,*_:obj)
    monkeypatch.setattr(cam,"document_snapshot",documents)
    monkeypatch.setattr(cam,"_context",contexts)
    monkeypatch.setattr(cam,"_inventory",inventories)
    monkeypatch.setattr(cam,"_typed",typed)
    monkeypatch.setattr(events,"CamMessageSession",factory)
    def call(action="prepare",**changes):
        options=dict(expected_document_path=str(path),action=action)
        if action!="prepare":options.update(expected_state_sha256=cam._digest(before),receipt_path=str(receipt))
        return cam.document_lifecycle(sw,"clsid",TLB,**(options|changes))
    return N(**locals())


def no_other_actions(p,result,action):
    assert not result["may_continue"] and not result["persistence_verified"] and not result["generation_attempted"]
    assert result["response"]=="default_unknown" and result["cam_save_restore_flag"]=="unknown"
    for fn in p.forbidden:fn.assert_not_called()
    if action!="save":p.app.SaveActiveDocument.assert_not_called()
    if action!="close":p.app.CloseActiveDocument.assert_not_called()


def test_prepare_snapshots_saved_target_inventory_hash_readonly(probe):
    result=probe.call()
    assert result["status"]=="ok" and result["before"]==probe.before
    assert result["state_sha256"]==cam._digest(probe.before)
    assert not result["mutation_attempted"] and not probe.receipt.exists()
    probe.factory.assert_not_called()
    no_other_actions(probe,result,"prepare")


def test_save_subscribes_before_exactly_one_durable_native_call(probe):
    result=probe.call("save")
    assert result["status"]=="review_required" and result["save_readback_verified"]
    assert result["native_save_call_returned"] and not result["close_verified"]
    assert result["saved_file_changed"] and result["native_outcome"]=="save_returned_readback_verified"
    assert result["state_sha256"]==cam._digest(result["final_state"])
    assert result["final_state"]["inventory"]==probe.inventory
    assert json.loads(probe.receipt.read_text())["save_readback_verified"]
    probe.app.SaveActiveDocument.assert_called_once_with()
    assert probe.contexts.call_count==4
    no_other_actions(probe,result,"save")


def test_save_allows_prepared_dirty_state_and_only_dirty_file_changes(probe):
    probe.state["document"]["needs_save"]=True
    probe.before["document"]["needs_save"]=True
    result=probe.call("save")
    assert result["save_readback_verified"]
    assert result["before"]["document"]["needs_save"] is True
    assert result["final_state"]["document"]["needs_save"] is False


def test_close_verifies_absence_twice_without_cam_on_activated_other_document(probe):
    result=probe.call("close")
    assert result["status"]=="review_required" and result["close_verified"]
    assert result["native_close_call_returned"] and not result["native_save_call_returned"]
    assert result["native_outcome"]=="target_absent_from_open_documents"
    probe.app.CloseActiveDocument.assert_called_once_with()
    assert probe.contexts.call_count==2 and probe.inventories.call_count==4
    assert probe.documents.call_count==probe.native_records[0]["document_calls"]
    assert probe.sw.GetDocuments.call_count==2
    assert result["open_documents_after"]==[dict(path=str(probe.other_path),title=probe.other_path.name,type=1)]
    no_other_actions(probe,result,"close")


def test_close_rejects_sw_dirty_flag_without_trying_to_save(probe):
    probe.state["document"]["needs_save"]=True;probe.before["document"]["needs_save"]=True
    result=probe.call("close")
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.factory.assert_not_called()
    no_other_actions(probe,result,"prepare")


@pytest.mark.parametrize("changes",[dict(expected_document_path="relative.sldprt"),
    dict(expected_document_path="C:/part.step"),dict(expected_document_path=None),
    dict(message_policy="yes"),dict(action="abort"),dict(receipt_path="unused.json"),
    dict(expected_state_sha256="0"*64)])
def test_invalid_prepare_inputs_fail_before_document_access(probe,changes):
    result=probe.call(**changes)
    assert result["status"]=="error"
    probe.documents.assert_not_called();probe.contexts.assert_not_called()
    no_other_actions(probe,result,"prepare")


@pytest.mark.parametrize("changes",[dict(expected_state_sha256="A"*64),dict(expected_state_sha256=None),
    dict(expected_state_sha256="short"),dict(receipt_path="relative.json"),dict(receipt_path=None)])
def test_invalid_action_inputs_never_capture_or_create_receipt(probe,changes):
    result=probe.call("save",**changes)
    assert result["status"]=="error"
    probe.contexts.assert_not_called();assert not probe.receipt.exists()


def test_existing_receipt_remains_byte_exact_even_in_finally(probe):
    probe.receipt.write_bytes(b"previous immutable attempt")
    result=probe.call("close")
    assert result["status"]=="error"
    assert probe.receipt.read_bytes()==b"previous immutable attempt"
    probe.documents.assert_not_called();probe.factory.assert_not_called()


def test_wrong_target_rejected_before_cam_context(probe):
    probe.state["document"]["path"]=str(probe.other_path)
    result=probe.call()
    assert result["status"]=="error"
    probe.contexts.assert_not_called()


@pytest.mark.parametrize("change",["inventory","file","document"])
def test_prepared_hash_gates_changed_state_before_subscription(probe,change):
    if change=="inventory":probe.state["inventory"]["feature_count"]+=1
    elif change=="file":probe.path.write_bytes(b"changed on disk")
    else:probe.state["document"]["title"]="Changed title"
    result=probe.call("save")
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.factory.assert_not_called();probe.app.SaveActiveDocument.assert_not_called()


def test_resnapshot_drift_after_subscription_stops_before_native_write(probe):
    probe.state["on_enter"]=lambda:probe.state["inventory"].__setitem__("feature_count",4)
    result=probe.call("save")
    assert result["status"]=="error" and not result["mutation_attempted"]
    probe.app.SaveActiveDocument.assert_not_called()


def test_initial_snapshot_detects_unstable_inventory(probe):
    probe.state["on_inventory"]=lambda:probe.state["inventory"].__setitem__("feature_count",probe.inventories.call_count)
    result=probe.call()
    assert result["status"]=="error"
    probe.factory.assert_not_called()


def test_initial_snapshot_detects_saved_file_changing_during_read(probe,monkeypatch):
    monkeypatch.setattr(cam,"_file_hash",Mock(side_effect=["a"*64,"b"*64]))
    assert probe.call()["status"]=="error"


@pytest.mark.parametrize("action",["save","close"])
def test_events_on_native_return_stop_all_later_cad_reads(probe,action):
    probe.state["on_native"]=lambda:probe.session.data.__setitem__("event_count",1)
    result=probe.call(action)
    assert result["status"]=="review_required" and result["native_call_returned"]
    assert result["native_outcome"]=="unknown"
    assert not result["close_verified"] and not result["save_readback_verified"]
    assert probe.inventories.call_count==probe.native_records[0]["inventory_calls"]
    assert probe.documents.call_count==probe.native_records[0]["document_calls"]
    assert probe.contexts.call_count==probe.native_records[0]["context_calls"]
    probe.sw.GetDocuments.assert_not_called()
    assert probe.session.data["disconnected"]
    durable=json.loads(probe.receipt.read_text())
    assert durable["native_call_returned"] and durable["messages"]["event_count"]==1


@pytest.mark.parametrize("issue,value",[("event_count",1),("overflow",1),("callback_error_count",1),
    ("callback_errors",[{"type":"error"}]),("subscription_error",{"type":"error"})])
def test_event_problem_before_action_never_mutates(probe,issue,value):
    probe.state["on_enter"]=lambda:probe.session.data.__setitem__(issue,value)
    result=probe.call("save")
    assert result["status"]=="review_required" and not result["mutation_attempted"]
    probe.app.SaveActiveDocument.assert_not_called()


def test_event_during_before_action_inventory_stops_next_read(probe):
    def inject():
        if probe.inventories.call_count==3:probe.session.data["event_count"]=1
    probe.state["on_inventory"]=inject
    result=probe.call("save")
    assert result["status"]=="review_required"
    assert probe.inventories.call_count==3
    probe.app.SaveActiveDocument.assert_not_called()


@pytest.mark.parametrize("action",["save","close"])
def test_attempt_receipt_failure_never_calls_native(probe,monkeypatch,action):
    original=cam._write_receipt
    def writer(path,result,**options):
        if result["phase"] in {"SaveActiveDocument","CloseActiveDocument"}:raise OSError("write failed")
        return original(path,result,**options)
    monkeypatch.setattr(cam,"_write_receipt",writer)
    result=probe.call(action)
    assert result["status"]=="uncertain" and not result["native_call_returned"]
    no_other_actions(probe,result,"prepare")


def test_event_arriving_during_durable_intent_stops_native_call(probe,monkeypatch):
    original=cam._write_receipt
    def writer(path,result,**options):
        value=original(path,result,**options)
        if result["phase"]=="CloseActiveDocument":probe.session.data["event_count"]=1
        return value
    monkeypatch.setattr(cam,"_write_receipt",writer)
    result=probe.call("close")
    assert result["status"]=="review_required"
    probe.app.CloseActiveDocument.assert_not_called()


def test_event_from_final_document_getter_blocks_native_call(probe):
    def inject():
        if probe.receipt.exists() and json.loads(probe.receipt.read_text()).get("phase")=="CloseActiveDocument":
            probe.session.data["event_count"]=1
    probe.state["on_document"]=inject
    result=probe.call("close")
    assert result["status"]=="review_required"
    probe.app.CloseActiveDocument.assert_not_called()


@pytest.mark.parametrize("action",["save","close"])
def test_native_exception_has_no_readback_retry_or_other_action(probe,action):
    method=probe.app.SaveActiveDocument if action=="save" else probe.app.CloseActiveDocument
    method.side_effect=RuntimeError("native fault")
    result=probe.call(action)
    assert result["status"]=="uncertain" and not result["native_call_returned"]
    method.assert_called_once_with()
    assert probe.contexts.call_count==2
    probe.sw.GetDocuments.assert_not_called()
    no_other_actions(probe,result,action)


@pytest.mark.parametrize("kind",["inventory","identity"])
def test_save_readback_rejects_inventory_or_identity_change(probe,kind):
    if kind=="inventory":probe.state["on_native"]=lambda:probe.state["inventory"].__setitem__("feature_count",99)
    else:probe.state["on_native"]=lambda:probe.state["document"].__setitem__("path",str(probe.other_path))
    result=probe.call("save")
    assert result["status"]=="uncertain" and not result["save_readback_verified"]
    if kind=="identity":assert probe.contexts.call_count==2  # 不访问另一个文档的 CAM。


def test_close_target_still_open_is_not_success(probe):
    probe.state["on_native"]=lambda:probe.state.__setitem__("open_documents",[probe.metadata(probe.document)])
    result=probe.call("close")
    assert result["status"]=="uncertain" and not result["close_verified"]
    assert probe.contexts.call_count==2


def test_close_empty_document_array_is_valid_absence(probe):
    probe.state["on_native"]=lambda:probe.state.__setitem__("open_documents",None)
    assert probe.call("close")["close_verified"]


@pytest.mark.parametrize("documents",["not an array",[None]*257])
def test_close_unbounded_or_invalid_document_array_is_not_verified(probe,documents):
    probe.state["on_native"]=lambda:probe.state.__setitem__("open_documents",documents)
    result=probe.call("close")
    assert result["status"]=="uncertain" and not result["close_verified"]


@pytest.mark.parametrize("action",["save","close"])
def test_disconnect_failure_blocks_cleanup_readback(probe,action):
    def failed_disconnect():
        probe.session.data.update(disconnected=False,disconnect_errors=[{"type":"COMError"}])
    probe.state["on_exit"]=failed_disconnect
    result=probe.call(action)
    assert result["status"]=="review_required" and not result["save_readback_verified"] and not result["close_verified"]
    if action=="save":assert probe.contexts.call_count==3
    else:assert probe.sw.GetDocuments.call_count==1


def test_event_cleanup_drift_invalidates_save_readback(probe):
    probe.state["on_exit"]=lambda:probe.state["inventory"].__setitem__("feature_count",99)
    result=probe.call("save")
    assert result["status"]=="uncertain" and not result["save_readback_verified"]


def test_close_cleanup_reappearance_is_not_verified(probe):
    probe.state["on_exit"]=lambda:probe.state.__setitem__("open_documents",[probe.metadata(probe.document)])
    result=probe.call("close")
    assert result["status"]=="uncertain" and not result["close_verified"]


def test_final_receipt_failure_clears_success_claims(probe,monkeypatch):
    original=cam._write_receipt
    def write(path,result,**kwargs):
        if result["phase"]=="finished":raise OSError("final receipt fault")
        return original(path,result,**kwargs)
    monkeypatch.setattr(cam,"_write_receipt",write)
    result=probe.call("save")
    assert result["status"]=="uncertain" and not result["save_readback_verified"]
    assert "receipt_write_error" in result



@pytest.mark.parametrize("value", [False, None, 0, 1, "true"])
def test_close_requires_strict_user_control_without_changing_it(probe, value):
    probe.sw.UserControl = value
    result = probe.call("close")
    assert result["status"] == "error" and not result["mutation_attempted"]
    assert probe.sw.UserControl is value
    probe.factory.assert_not_called()
    probe.app.CloseActiveDocument.assert_not_called()


def test_close_missing_user_control_fails_before_native_action(probe):
    del probe.sw.UserControl
    result = probe.call("close")
    assert result["status"] == "error" and not result["native_call_attempted"]
    probe.app.CloseActiveDocument.assert_not_called()


def test_user_control_change_after_subscription_blocks_close(probe):
    probe.state["on_enter"] = lambda: setattr(probe.sw, "UserControl", False)
    result = probe.call("close")
    assert not result["native_call_returned"] and not result["close_verified"]
    assert probe.sw.UserControl is False
    probe.app.CloseActiveDocument.assert_not_called()


def test_save_does_not_require_or_mutate_user_control(probe):
    del probe.sw.UserControl
    assert probe.call("save")["save_readback_verified"]
    assert not hasattr(probe.sw, "UserControl")
