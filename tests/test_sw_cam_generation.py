"""Bounded CAM qualification safety tests; no real CAD or COM objects."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_generation as generation
from scripts import sw_cam_events as events

CLSID = "{CCAC6208-0E19-6455-2022-2026CEB541FA}"
TLB = "verified/camworks.tlb"


def inventory(features=0, operations=0):
    return {"machine_type": 3, "feature_setup_count": int(features > 0),
            "feature_counts_by_setup": [features] if features else [], "feature_count": features,
            "operation_setup_count": int(operations > 0), "operation_count": operations,
            "operations": [{"turn_operation_type": 1, "toolpath_generated": False,
                            "toolpath_record_counts": []} for _ in range(operations)],
            "stock": {"type": 3, "parameters_modified": False,
                      "length_units": "native_API_units_not_assumed"}}


@pytest.fixture
def qualification(monkeypatch, tmp_path):
    state = {
        "document": {"path": r"C:\qualification\TURNING_PROBE.SLDPRT",
                     "title": "TURNING_PROBE.SLDPRT", "type": 1, "needs_save": False},
        "inventory": inventory(),
    }
    sw, part, machine = object(), object(), object()
    doc = SimpleNamespace(ExtractMachinableFeatures=Mock())
    app = SimpleNamespace(ActiveDocGOP=Mock())
    receipt = tmp_path / "unique.json"

    def context(*args):
        assert args == (sw, CLSID, TLB)
        return deepcopy(state["document"]), doc, part, machine, app

    context_mock = Mock(side_effect=context)
    monkeypatch.setattr(generation, "_context", context_mock)
    monkeypatch.setattr(generation, "_inventory", Mock(side_effect=lambda *_: deepcopy(state["inventory"])))
    monkeypatch.setattr(generation, "document_snapshot", Mock(side_effect=lambda _: deepcopy(state["document"])))

    class Session:
        def __init__(self):
            self.entered = False
            self.exited = False
            self.on_enter = None
            self.on_exit = None
            self.enter_error = None
            self.disconnect_failed = False
            self.report = {"subscribed": False, "disconnected": False, "active": False,
                           "event_count": 0, "overflow": 0, "callback_errors": [],
                           "callback_error_count": 0, "disconnect_errors": []}

        def __enter__(self):
            if self.enter_error:
                raise self.enter_error
            self.entered = True
            self.report.update(subscribed=True, active=True)
            if self.on_enter:
                self.on_enter()
            return self

        def __exit__(self, *args):
            self.exited = True
            if self.disconnect_failed:
                self.report["disconnect_errors"] = [{"type": "RuntimeError"}]
            else:
                self.report.update(disconnected=True, active=False)
            if self.on_exit:
                self.on_exit()
            return False

        def summary(self):
            return deepcopy(self.report)

    session = Session()
    session_factory = Mock(return_value=session)
    monkeypatch.setattr(events, "CamMessageSession", session_factory)

    def extract():
        state["inventory"] = inventory(features=2)
        state["document"]["needs_save"] = True
        return 2

    def gop(preference):
        assert preference == 2
        state["inventory"] = inventory(features=2, operations=1)
        state["document"]["needs_save"] = True

    doc.ExtractMachinableFeatures.side_effect = extract
    app.ActiveDocGOP.side_effect = gop

    def run(step="subscribe", expected_features=0, expected_operations=0, **overrides):
        kwargs = dict(step=step, expected_feature_count=expected_features,
                      expected_operation_count=expected_operations, receipt_path=receipt,
                      qualification_only=True, message_policy="vendor_default")
        kwargs.update(overrides)
        return generation.run_qualification_step(sw, CLSID, TLB, **kwargs)

    return SimpleNamespace(state=state, sw=sw, doc=doc, app=app, machine=machine,
                           receipt=receipt, session=session, session_factory=session_factory,
                           context=context_mock, run=run)


def test_subscribe_is_readonly_and_durable_without_saving(qualification):
    f = qualification
    before = deepcopy(f.state)
    report = f.run()
    assert report["status"] == "ok" and report["may_continue"] is True
    assert report["mutation_attempted"] is False and report["model_saved"] is False
    assert report["production_process_qualified"] is False
    assert f.state == before
    f.doc.ExtractMachinableFeatures.assert_not_called()
    f.app.ActiveDocGOP.assert_not_called()
    assert json.loads(f.receipt.read_text(encoding="utf-8")) == report


@pytest.mark.parametrize("override", [{"qualification_only": False}, {"qualification_only": 1},
                                      {"message_policy": "approve"}, {"step": "generate_toolpath"}])
def test_explicit_scope_policy_and_supported_step_required_before_receipt(qualification, override):
    f = qualification
    with pytest.raises(ValueError):
        f.run(**override)
    assert not f.receipt.exists()
    f.context.assert_not_called()
    f.session_factory.assert_not_called()


def test_exclusive_receipt_prevents_replay_before_any_native_access(qualification):
    f = qualification
    f.receipt.write_text("previous request must survive", encoding="utf-8")
    with pytest.raises(FileExistsError):
        f.run(step="extract_features")
    assert f.receipt.read_text(encoding="utf-8") == "previous request must survive"
    f.context.assert_not_called()
    f.session_factory.assert_not_called()
    f.doc.ExtractMachinableFeatures.assert_not_called()


def test_dirty_document_refused_before_subscription_or_mutation(qualification):
    f = qualification
    f.state["document"]["needs_save"] = True
    report = f.run(step="extract_features")
    assert report["status"] == "error" and report["may_continue"] is False
    assert report["mutation_attempted"] is False
    f.session_factory.assert_not_called()
    f.doc.ExtractMachinableFeatures.assert_not_called()


@pytest.mark.parametrize("expected_features,expected_operations", [(1, 0), (0, 1)])
def test_stale_expected_inventory_refused(qualification, expected_features, expected_operations):
    f = qualification
    report = f.run(step="extract_features", expected_features=expected_features,
                   expected_operations=expected_operations)
    assert report["status"] == "error" and report["mutation_attempted"] is False
    f.session_factory.assert_not_called()
    f.doc.ExtractMachinableFeatures.assert_not_called()


@pytest.mark.parametrize("step,features,operations", [("extract_features", 1, 0),
                                                     ("extract_features", 0, 1),
                                                     ("generate_operations", 0, 0),
                                                     ("generate_operations", 2, 1)])
def test_existing_or_inappropriate_plan_is_not_overwritten(qualification, step, features, operations):
    f = qualification
    f.state["inventory"] = inventory(features, operations)
    report = f.run(step, features, operations)
    assert report["status"] == "error" and report["mutation_attempted"] is False
    f.session_factory.assert_not_called()
    f.doc.ExtractMachinableFeatures.assert_not_called()
    f.app.ActiveDocGOP.assert_not_called()


def test_subscription_failure_prevents_mutation(qualification):
    f = qualification
    f.session.enter_error = RuntimeError("failed subscription")
    report = f.run(step="extract_features")
    assert report["status"] == "error" and report["mutation_attempted"] is False
    f.doc.ExtractMachinableFeatures.assert_not_called()


def test_document_rechecked_after_subscription_before_mutation(qualification):
    f = qualification
    f.session.on_enter = lambda: f.state["document"].update(path=r"C:\production\foreign.sldprt")
    report = f.run(step="extract_features")
    assert report["status"] == "error" and report["mutation_attempted"] is False
    f.doc.ExtractMachinableFeatures.assert_not_called()
    assert f.session.exited is True


def test_extract_has_durable_in_native_call_receipt_before_actual_mutation(qualification):
    f = qualification

    def extract():
        during = json.loads(f.receipt.read_text(encoding="utf-8"))
        assert during["status"] == "in_native_call"
        assert during["mutation_attempted"] is True
        assert f.session.entered and not f.session.exited
        f.state["inventory"] = inventory(features=3)
        f.state["document"]["needs_save"] = True
        return 3

    f.doc.ExtractMachinableFeatures.side_effect = extract
    report = f.run(step="extract_features")
    assert report["status"] == "ok" and report["may_continue"] is True
    assert report["after"]["feature_count"] == 3
    assert report["native_return"] == 3
    assert report["document_after"]["needs_save"] is True
    assert report["model_saved"] is False
    f.doc.ExtractMachinableFeatures.assert_called_once_with()
    f.app.ActiveDocGOP.assert_not_called()


def test_gop_uses_documented_regenerate_value_and_native_readback(qualification):
    f = qualification
    f.state["inventory"] = inventory(features=2)
    report = f.run("generate_operations", 2, 0)
    assert report["status"] == "ok" and report["may_continue"] is True
    assert report["after"]["operation_count"] == 1
    assert report["model_saved"] is False
    f.app.ActiveDocGOP.assert_called_once_with(2)
    f.doc.ExtractMachinableFeatures.assert_not_called()


@pytest.mark.parametrize("step", ["extract_features", "generate_operations"])
def test_zero_native_result_is_not_passed_even_if_call_returns_normally(qualification, step):
    f = qualification
    if step == "extract_features":
        f.doc.ExtractMachinableFeatures.side_effect = None
        f.doc.ExtractMachinableFeatures.return_value = 99  # Readback remains zero.
        report = f.run(step)
    else:
        f.state["inventory"] = inventory(features=2)
        f.app.ActiveDocGOP.side_effect = None
        report = f.run(step, 2, 0)
    assert report["status"] == "review_required"
    assert report["stage_result_present"] is False
    assert report["may_continue"] is False
    assert report["reason"] == "CAM_STAGE_HAS_NO_RESULT"


@pytest.mark.parametrize("condition", ["event", "overflow", "callback_error", "disconnect_failure"])
def test_event_or_cleanup_issue_blocks_continuation_despite_native_result(qualification, condition):
    f = qualification
    original_extract = f.doc.ExtractMachinableFeatures.side_effect

    def extract_with_message():
        result = original_extract()
        if condition == "event":
            f.session.report["event_count"] = 1
        elif condition == "overflow":
            f.session.report["overflow"] = 1
        elif condition == "callback_error":
            f.session.report["callback_errors"] = [{"type": "RuntimeError"}]
        else:
            f.session.disconnect_failed = True
        return result

    f.doc.ExtractMachinableFeatures.side_effect = extract_with_message
    report = f.run(step="extract_features")
    assert report["after"]["feature_count"] > 0
    assert report["status"] == "review_required"
    assert report["reason"] == "CAM_MESSAGES_REQUIRE_REVIEW"
    assert report["may_continue"] is False
    if condition == "disconnect_failure":
        assert report["messages"]["disconnected"] is False
        assert report["messages"]["active"] is True


def test_native_failure_disconnects_and_does_not_report_completed_stage(qualification):
    f = qualification
    f.doc.ExtractMachinableFeatures.side_effect = RuntimeError("SECRET_ERROR_PAYLOAD")
    report = f.run(step="extract_features")
    assert report["status"] == "error" and report["may_continue"] is False
    assert report["mutation_attempted"] is True
    assert report["messages"]["disconnected"] is True
    assert "SECRET_ERROR_PAYLOAD" not in json.dumps(report)


def test_subscribe_requires_full_document_state_immutability(qualification):
    f = qualification
    original_inventory = generation._inventory.side_effect
    calls = [0]

    def read_inventory(*args):
        calls[0] += 1
        if calls[0] == 2:
            f.state["document"]["needs_save"] = True
        return original_inventory(*args)

    generation._inventory.side_effect = read_inventory
    report = f.run()
    assert report["status"] != "ok"
    assert report["may_continue"] is False


def test_document_changed_during_disconnect_is_not_reported_clean(qualification):
    f = qualification
    f.session.on_exit = lambda: f.state["document"].update(path=r"C:\production\foreign.sldprt")
    report = f.run(step="extract_features")
    assert report["status"] != "ok"
    assert report["may_continue"] is False


class Collection:
    def __init__(self, items):
        self.Count = len(items)
        self.Item = Mock(side_effect=lambda index: items[index])


def test_inventory_uses_exact_collections_and_reports_only_native_stock_type(monkeypatch):
    typed = Mock(side_effect=lambda obj, *_: obj)
    monkeypatch.setattr(generation, "_typed", typed)
    feature_setup = SimpleNamespace(IGetEnumFeatures=Mock(return_value=Collection([object(), object()])))
    path = SimpleNamespace(RecordCount=12)
    operation = SimpleNamespace(GetIsToolpathGenerated=Mock(return_value=True),
                                IGetEnumToolpaths=Mock(return_value=Collection([path])), OpernType=1)
    op_setup = SimpleNamespace(IGetEnumOperations=Mock(return_value=Collection([operation])))
    stock = SimpleNamespace(GetTurnWorkpieceType=Mock(return_value=3))
    machine = SimpleNamespace(IGetEnumSetups=Mock(return_value=Collection([feature_setup])),
                              IGetEnumOpSetups=Mock(return_value=Collection([op_setup])),
                              IGetWorkpiece=Mock(return_value=stock))
    result = generation._inventory(machine, TLB)
    assert result["feature_count"] == 2 and result["operation_count"] == 1
    assert result["operations"][0]["toolpath_record_counts"] == [12]
    assert result["stock"] == {"type": 3, "parameters_modified": False,
                               "length_units": "native_API_units_not_assumed"}
    assert "ICWTurnOperation" in [call.args[1] for call in typed.call_args_list]
    stock.GetTurnWorkpieceType.assert_called_once_with()


@pytest.mark.parametrize("count", [-1, 513])
def test_collection_limit_rejects_before_indexing(monkeypatch, count):
    col = SimpleNamespace(Count=count, Item=Mock())
    monkeypatch.setattr(generation, "_typed", lambda obj, *_: obj)
    with pytest.raises(ValueError):
        generation._collection(col, TLB)
    col.Item.assert_not_called()


def test_subscribe_does_not_approve_changed_cam_inventory_with_unchanged_doc_flag(qualification):
    f = qualification
    reads = [0]

    def read_inventory(*_args):
        reads[0] += 1
        return inventory(features=0 if reads[0] == 1 else 2)

    generation._inventory.side_effect = read_inventory
    report = f.run()
    assert report["status"] != "ok"
    assert report["may_continue"] is False
    assert report["mutation_attempted"] is False


@pytest.mark.parametrize("condition", ["event", "overflow", "callback_error", "not_subscribed"])
def test_subscription_entry_issue_prevents_any_native_mutation(qualification, condition):
    f = qualification

    def entry_issue():
        if condition == "event":
            f.session.report["event_count"] = 1
        elif condition == "overflow":
            f.session.report["overflow"] = 1
        elif condition == "callback_error":
            f.session.report["callback_errors"] = [{"type": "RuntimeError"}]
        else:
            f.session.report["subscribed"] = False

    f.session.on_enter = entry_issue
    report = f.run(step="extract_features")
    assert report["status"] == "error"
    assert report["may_continue"] is False
    assert report["mutation_attempted"] is False
    f.doc.ExtractMachinableFeatures.assert_not_called()
    f.app.ActiveDocGOP.assert_not_called()
    assert f.session.exited is True


@pytest.mark.parametrize("step,setup_key,features", [
    ("extract_features", "feature_setup_count", 0),
    ("extract_features", "operation_setup_count", 0),
    ("generate_operations", "operation_setup_count", 2),
])
def test_unexpected_empty_setups_are_refused_with_default_expected_setup_count_zero(qualification, step, setup_key, features):
    f = qualification
    f.state["inventory"] = inventory(features=features)
    f.state["inventory"][setup_key] = 1
    report = f.run(step, features, 0)
    assert report["status"] == "error"
    assert report["may_continue"] is False
    assert report["mutation_attempted"] is False
    f.session_factory.assert_not_called()
    f.doc.ExtractMachinableFeatures.assert_not_called()
    f.app.ActiveDocGOP.assert_not_called()



def test_gop_accepts_explicit_expected_empty_operation_setup_created_by_emf(qualification):
    f = qualification
    f.state["inventory"] = inventory(features=3, operations=0)
    f.state["inventory"]["operation_setup_count"] = 1

    def generate(preference):
        assert preference == 2
        f.state["inventory"] = inventory(features=3, operations=5)
        f.state["document"]["needs_save"] = True

    f.app.ActiveDocGOP.side_effect = generate
    report = f.run("generate_operations", 3, 0, expected_operation_setup_count=1)
    assert report["status"] == "ok"
    assert report["may_continue"] is True
    assert report["before"]["operation_setup_count"] == 1
    assert report["before"]["operation_count"] == 0
    assert report["after"]["operation_count"] == 5
    assert report["mutation_attempted"] is True
    assert report["model_saved"] is False
    f.app.ActiveDocGOP.assert_called_once_with(2)
    f.doc.ExtractMachinableFeatures.assert_not_called()


def test_gop_refuses_changed_empty_setup_count_despite_explicit_expected_count(qualification):
    f = qualification
    f.state["inventory"] = inventory(features=3)
    f.state["inventory"]["operation_setup_count"] = 2
    report = f.run("generate_operations", 3, 0, expected_operation_setup_count=1)
    assert report["status"] == "error"
    assert report["mutation_attempted"] is False
    assert report["may_continue"] is False
    f.session_factory.assert_not_called()
    f.app.ActiveDocGOP.assert_not_called()


def test_ungenerated_operation_record_counts_are_not_read_or_inferred(monkeypatch):
    monkeypatch.setattr(generation, "_typed", lambda obj, *_: obj)
    operation = SimpleNamespace(
        GetIsToolpathGenerated=Mock(return_value=False),
        IGetEnumToolpaths=Mock(side_effect=AssertionError("Records must not be read before GTP")),
        OpernType=1,
    )
    op_setup = SimpleNamespace(IGetEnumOperations=Mock(return_value=Collection([operation])))
    stock = SimpleNamespace(GetTurnWorkpieceType=Mock(return_value=3))
    machine = SimpleNamespace(
        IGetEnumSetups=Mock(return_value=Collection([])),
        IGetEnumOpSetups=Mock(return_value=Collection([op_setup])),
        IGetWorkpiece=Mock(return_value=stock),
    )
    report = generation._inventory(machine, TLB)
    assert report["operation_count"] == 1
    assert report["operations"][0]["toolpath_generated"] is False
    assert report["operations"][0]["toolpath_record_counts"] == []
    operation.IGetEnumToolpaths.assert_not_called()
