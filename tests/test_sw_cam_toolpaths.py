"""Single-operation CAM toolpath lifetime tests, entirely fake; no CAD/COM calls."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from scripts import sw_cam_toolpaths as tp


def inventory():
    return {
        "machine_type": 3, "feature_setup_count": 1, "feature_counts_by_setup": [3],
        "feature_count": 3, "operation_setup_count": 1, "operation_count": 2,
        "stock": {"type": 3},
        "operations": [
            {"setup_index": 0, "operation_index": i, "name": "Turn " + str(i),
             "turn_operation_type": i + 1, "toolpath_generated": False,
             "toolpath_record_counts": []} for i in range(2)],
    }


@pytest.fixture
def job(monkeypatch):
    state = {
        "document": {"path": r"C:\qualification\TURNING_PROBE.SLDPRT",
                     "title": "TURNING_PROBE.SLDPRT", "type": 1, "needs_save": False},
        "inventory": inventory(), "started": False, "complete": False,
        "completion_values": [False, True], "clock": 0.0, "events": [],
        "feed": 10.0, "on_native": None, "summary_error": None, "background_flag": False,
    }
    config = dict(qualification_only=True, message_policy="vendor_default", typelib_path="verified/camworks.tlb",
                  addin_clsid="verified-clsid", expected_document_path=state["document"]["path"],
                  expected_feature_count=3, expected_operation_count=2, expected_operation_setup_count=1,
                  setup_index=0, operation_index=0, expected_operation_type=1,
                  process_id=123, process_create_time="start-123", attention_seconds=0.1)
    sw, machine = object(), object()

    def complete():
        state["events"].append("selected_completion_query")
        assert state["started"], "selected completion must be queried after the native call"
        value = state["completion_values"].pop(0) if state["completion_values"] else True
        if isinstance(value, Exception):
            raise value
        state["complete"] = bool(value)
        return value

    app = SimpleNamespace(IsBackgroundProcessForGTPOver=Mock(side_effect=lambda: state["background_flag"]))
    operation = SimpleNamespace(ToolpathFeedLength=Mock(side_effect=lambda: state["feed"]),
                                GetIsToolpathGenerated=Mock(side_effect=complete))

    def generate():
        assert session.report["active"]
        state["started"] = True
        state["events"].append("generate")
        op = state["inventory"]["operations"][0]
        op.update(toolpath_generated=True, toolpath_record_counts=[2, 4])
        state["document"]["needs_save"] = True
        if state["on_native"]:
            state["on_native"]()

    operation.GenerateToolpath = Mock(side_effect=generate)
    context = Mock(side_effect=lambda *_: (deepcopy(state["document"]), object(), object(), machine, app))
    monkeypatch.setattr(tp, "_context", context)
    monkeypatch.setattr(tp, "_inventory", Mock(side_effect=lambda *_: deepcopy(state["inventory"])))
    monkeypatch.setattr(tp, "document_snapshot", Mock(side_effect=lambda _: deepcopy(state["document"])))
    selected = Mock(return_value=operation)
    monkeypatch.setattr(tp, "_selected_operation", selected)
    typed = Mock(side_effect=lambda obj, *_: obj)
    monkeypatch.setattr(tp, "_typed", typed)
    monkeypatch.setattr(tp, "time", SimpleNamespace(
        monotonic=lambda: state["clock"],
        sleep=lambda seconds: state.update(clock=state["clock"] + seconds)))

    def pump(seconds):
        assert session.report["active"]
        assert not session.exited
        state["events"].append("pump")
        state["clock"] += seconds

    pump_mock = Mock(side_effect=pump)
    monkeypatch.setattr(tp, "_pump_wait", pump_mock)
    gone = Mock(return_value=False)
    monkeypatch.setattr(tp, "_process_gone", gone)

    class Session:
        def __init__(self):
            self.exited = False
            self.on_enter = None
            self.on_exit = None
            self.report = dict(subscribed=False, disconnected=False, active=False, event_count=0,
                               callback_errors=[], overflow=0, disconnect_errors=[], subscription_error=None)

        def __enter__(self):
            self.report.update(subscribed=True, active=True)
            state["events"].append("subscribe")
            if self.on_enter:
                self.on_enter()
            return self

        def __exit__(self, *args):
            self.exited = True
            state["events"].append(("disconnect", state["complete"]))
            self.report.update(disconnected=True, active=False)
            if self.on_exit:
                self.on_exit()
            return False

        def summary(self):
            if state["started"] and state["summary_error"]:
                error, state["summary_error"] = state["summary_error"], None
                raise error
            return deepcopy(self.report)

    session = Session()
    factory = Mock(return_value=session)
    monkeypatch.setattr(tp, "CamMessageSession", factory)
    receipts = []
    publish = Mock(side_effect=lambda report: receipts.append(deepcopy(report)))

    def run(*, stop_observation=None, **changes):
        return tp.run_toolpath_job(sw, {**config, **changes}, publish, stop_observation=stop_observation)

    return SimpleNamespace(state=state, config=config, sw=sw, machine=machine, app=app,
                           operation=operation, session=session, factory=factory,
                           context=context, selected=selected, typed=typed, pump=pump_mock,
                           gone=gone, publish=publish, receipts=receipts, run=run)


def assert_not_started(f):
    f.operation.GenerateToolpath.assert_not_called()
    assert not f.state["started"]


def test_one_selected_operation_and_independent_readback_without_save(job):
    f = job
    before_other = deepcopy(f.state["inventory"]["operations"][1])
    report = f.run()
    assert report["status"] == "completed" and report["may_continue"]
    assert report["completion_observed"] and report["result_verified"]
    assert report["other_operations_unchanged"]
    assert report["selected_result"]["toolpath_record_counts"] == [2, 4]
    assert report["selected_result"]["feed_length_native_units"] == 10.0
    assert not report["selected_result"]["length_units_verified"]
    assert not report["model_saved"] and not report["nc_exported"]
    assert not report["production_process_qualified"]
    assert f.state["inventory"]["operations"][1] == before_other
    f.operation.GenerateToolpath.assert_called_once_with()
    assert all(call.args == (f.machine, f.config["typelib_path"], 0, 0) for call in f.selected.call_args_list)
    assert f.state["events"].index("pump") < f.state["events"].index(("disconnect", True))
    assert f.receipts[0]["phase"] == "in_native_call"
    assert any(r["status"] == "pending" for r in f.receipts)


@pytest.mark.parametrize("change", [{"qualification_only": False}, {"qualification_only": 1},
                                    {"message_policy": "approve"}])
def test_policy_required_before_context(job, change):
    with pytest.raises(ValueError):
        job.run(**change)
    job.context.assert_not_called()
    assert_not_started(job)


@pytest.mark.parametrize("change", [
    {"expected_feature_count": 4}, {"expected_operation_count": 1},
    {"expected_operation_setup_count": 2}, {"setup_index": 1},
    {"operation_index": 9}, {"expected_operation_type": 7},
    {"expected_document_path": r"C:\production\BASE.SLDPRT"},
])
def test_exact_target_inventory_selection_and_type_required(job, change):
    report = job.run(**change)
    assert report["status"] == "error" and not report["may_continue"]
    assert not report["mutation_attempted"]
    job.factory.assert_not_called()
    assert_not_started(job)


@pytest.mark.parametrize("blocker", ["dirty", "generated"])
def test_no_dirty_part_or_regeneration(job, blocker):
    if blocker == "dirty":
        job.state["document"]["needs_save"] = True
    else:
        job.state["inventory"]["operations"][0]["toolpath_generated"] = True
    report = job.run()
    assert report["status"] == "error" and not report["mutation_attempted"]
    job.factory.assert_not_called()
    assert_not_started(job)


@pytest.mark.parametrize("problem", ["document", "event", "unsubscribed"])
def test_preentry_document_or_message_problem_blocks_mutation(job, problem):
    def on_enter():
        if problem == "document":
            job.state["document"]["needs_save"] = True
        elif problem == "event":
            job.session.report["event_count"] = 1
        else:
            job.session.report["subscribed"] = False
    job.session.on_enter = on_enter
    report = job.run()
    assert report["status"] == "error" and not report["mutation_attempted"]
    assert_not_started(job)


def test_precall_receipt_failure_prevents_native_mutation(job):
    job.publish.side_effect = OSError("receipt storage unavailable")
    report = job.run()
    assert report["status"] == "error" and not report["may_continue"]
    assert_not_started(job)
    assert job.session.exited


@pytest.mark.parametrize("problem", ["message", "native_error", "query_error", "receipt_error"])
def test_errors_during_generation_retain_sink_until_completion(job, problem):
    f = job
    if problem == "message":
        f.state["on_native"] = lambda: f.session.report.update(event_count=1)
    elif problem == "native_error":
        def fail_native():
            raise RuntimeError("native GTP failed after scheduling")
        f.state["on_native"] = fail_native
    elif problem == "query_error":
        f.state["completion_values"] = [RuntimeError("temporarily unavailable"), False, True]
    else:
        f.publish.side_effect = [None, OSError("disk full")]
    report = f.run()
    assert report["completion_observed"]
    assert ("disconnect", False) not in f.state["events"]
    assert ("disconnect", True) in f.state["events"]
    assert f.pump.call_count >= 1
    if problem in ("message", "native_error"):
        assert not report["may_continue"]
    if problem == "receipt_error":
        assert report.get("receipt_write_error")


@pytest.mark.parametrize("failure", ["process_identity", "message_summary", "message_pump"])
def test_transient_infrastructure_error_never_disconnects_before_completion(job, failure):
    f = job
    if failure == "process_identity":
        f.gone.side_effect = [OSError("process query denied"), False, False]
    elif failure == "message_summary":
        f.state["summary_error"] = RuntimeError("summary temporarily unavailable")
    else:
        original_pump = f.pump.side_effect
        attempts = []
        def first_pump_fails(seconds):
            attempts.append(seconds)
            if len(attempts) == 1:
                raise RuntimeError("COM message pump temporarily unavailable")
            original_pump(seconds)
        f.pump.side_effect = first_pump_fails
    report = f.run()
    assert ("disconnect", False) not in f.state["events"]
    assert report["completion_observed"]
    assert f.session.exited


def test_confirmed_process_exit_is_terminal_and_does_not_read_dead_document(job):
    job.gone.return_value = True
    report = job.run()
    assert report["status"] == "error" and report["reason"] == "CAM_PROCESS_EXITED"
    assert not report["completion_observed"] and not report["may_continue"]
    assert "after" not in report
    assert report["document_after"] is None
    assert job.session.exited


@pytest.mark.parametrize("bad_result", ["flag", "records", "zero_feed", "negative_feed", "nan_feed",
                                       "inf_feed", "type", "other_path", "other_name", "count"])
def test_incomplete_path_or_changed_other_operation_is_not_passed(job, bad_result):
    def alter_result():
        inv = job.state["inventory"]
        selected = inv["operations"][0]
        if bad_result == "flag": selected["toolpath_generated"] = False
        elif bad_result == "records": selected["toolpath_record_counts"] = []
        elif bad_result == "type": selected["turn_operation_type"] = 7
        elif bad_result == "other_path": inv["operations"][1]["toolpath_generated"] = True
        elif bad_result == "other_name": inv["operations"][1]["name"] = "changed operation"
        elif bad_result == "count": inv["feature_count"] += 1
        else: job.state["feed"] = {"zero_feed": 0, "negative_feed": -1,
                                  "nan_feed": float("nan"), "inf_feed": float("inf")}[bad_result]
    job.state["on_native"] = alter_result
    report = job.run()
    assert report["completion_observed"] and not report["may_continue"]
    assert report["status"] == "error" and not report.get("result_verified", False)


def test_changed_plan_during_subscription_is_refused_before_native_call(job):
    def change_plan():
        job.state["inventory"]["operations"][0]["toolpath_generated"] = True
    job.session.on_enter = change_plan
    report = job.run()
    assert_not_started(job)
    assert not report["may_continue"]


def test_document_change_after_completion_is_rejected(job):
    job.session.on_exit = lambda: job.state["document"].update(path=r"C:\production\BASE.SLDPRT")
    report = job.run()
    assert report["status"] == "error" and not report["may_continue"]
    assert report["reason"] == "CAM_DOCUMENT_CHANGED"


def test_failed_disconnect_is_not_clean_completion(job):
    job.session.on_exit = lambda: job.session.report.update(disconnected=False,
                                                           disconnect_errors=[{"type": "RuntimeError"}])
    report = job.run()
    assert report["status"] == "review_required" and not report["may_continue"]
    assert report["messages"]["disconnect_errors"]


@pytest.mark.parametrize("current,expected", [
    ({"alive": False}, True), ({"alive": True, "create_time": "new-process"}, True),
    ({"alive": True, "create_time": "original"}, False), ({"alive": None}, False),
    ({"alive": True, "create_time": None}, False), ({"alive": True}, False),
])
def test_process_gone_requires_evidence_of_exit_or_reuse(monkeypatch, current, expected):
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_jobs", SimpleNamespace(process_identity=Mock(return_value=current)))
    assert tp._process_gone({"process_id": 123, "process_create_time": "original"}) is expected


def test_selected_operation_uses_exact_zero_based_setup_and_operation(monkeypatch):
    selected, other = object(), object()
    setup0 = SimpleNamespace(IGetEnumOperations=lambda: [other])
    setup1 = SimpleNamespace(IGetEnumOperations=lambda: [other, selected])
    machine = SimpleNamespace(IGetEnumOpSetups=lambda: [setup0, setup1])
    monkeypatch.setattr(tp, "_collection", lambda value, _: value)
    monkeypatch.setattr(tp, "_typed", lambda value, *_: value)
    assert tp._selected_operation(machine, "verified.tlb", 1, 1) is selected


def test_pump_wait_only_pumps_com_and_uses_short_sleeps(monkeypatch):
    clock = [0.0]
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    pump = Mock()
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace(PumpWaitingMessages=pump))
    monkeypatch.setattr(tp, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    tp._pump_wait(0.12)
    assert pump.call_count == len(sleeps) >= 2
    assert all(0 < seconds <= 0.05 for seconds in sleeps)
    assert clock[0] >= 0.12



def test_attention_threshold_is_not_cancellation_or_disconnect(job):
    job.state["completion_values"] = [False] * 7 + [True]
    report = job.run(attention_seconds=0.1)
    assert report["completion_observed"] and report["attention_required"]
    assert report["elapsed_seconds"] >= 1.75
    assert job.pump.call_count == 7
    assert ("disconnect", False) not in job.state["events"]
    assert any(r["status"] == "pending" and r["attention_required"] for r in job.receipts)


def test_global_flag_change_during_subscription_is_diagnostic_only(job):
    job.state["background_flag"] = True
    job.session.on_enter = lambda: job.state.update(background_flag=False)
    report = job.run()
    assert report["status"] == "completed" and report["may_continue"]
    assert report["background_completion_flag_before"] is True
    assert report["background_completion_flag"] is False
    job.operation.GenerateToolpath.assert_called_once_with()


def test_readback_failure_occurs_only_after_confirmed_completion(job):
    job.operation.ToolpathFeedLength.side_effect = RuntimeError("readback failed")
    report = job.run()
    assert report["status"] == "error" and not report["may_continue"]
    assert report["completion_observed"]
    assert ("disconnect", False) not in job.state["events"]


@pytest.mark.parametrize("feed", [float("nan"), float("inf")])
def test_nonfinite_readback_is_never_serialized_as_result(job, feed):
    import json
    job.state["feed"] = feed
    report = job.run()
    assert report["status"] == "error" and not report["may_continue"]
    assert "selected_result" not in report
    json.dumps(report, allow_nan=False)



@pytest.mark.parametrize("background_flag", [False, True])
def test_selected_completion_controls_lifetime_regardless_of_global_flag(job, background_flag):
    job.state["background_flag"] = background_flag
    job.state["completion_values"] = [False, False, True]
    report = job.run()
    assert report["status"] == "completed" and report["may_continue"]
    assert report["background_completion_flag_before"] is background_flag
    assert report["background_completion_flag"] is background_flag
    assert report["completion_source"] == "selected_operation_generated_false_to_true_after_native_return"
    assert job.pump.call_count == 2
    assert job.operation.GetIsToolpathGenerated.call_count == 3
    assert ("disconnect", False) not in job.state["events"]
    assert job.state["events"].index("generate") < job.state["events"].index("selected_completion_query")
    assert all(r["may_continue"] is False for r in job.receipts)


def test_global_true_alone_never_releases_unknown_selected_operation(job):
    job.state["background_flag"] = True
    job.state["completion_values"] = [False] * 4
    job.gone.side_effect = [False] * 4 + [True]
    report = job.run()
    assert report["status"] == "error" and report["reason"] == "CAM_PROCESS_EXITED"
    assert not report["completion_observed"] and not report["may_continue"]
    assert "completion_source" not in report
    assert job.pump.call_count == 4
    assert job.operation.GetIsToolpathGenerated.call_count == 4
    assert "after" not in report
    assert job.gone.call_count == 5


def test_global_true_does_not_override_selected_getter_error(job):
    job.state["background_flag"] = True
    job.state["completion_values"] = [RuntimeError("selected result unavailable"), False, True]
    report = job.run()
    assert report["completion_observed"] and report["status"] == "completed"
    assert report["completion_query_error_count"] == 1
    assert job.pump.call_count == 2
    assert ("disconnect", False) not in job.state["events"]


def test_global_getter_error_after_native_call_does_not_hide_selected_success(job):
    job.app.IsBackgroundProcessForGTPOver.side_effect = [False, RuntimeError("global flag unavailable"), False]
    report = job.run()
    assert report["status"] == "completed" and report["completion_observed"]
    assert report["background_flag_error"]
    assert report["completion_source"] == "selected_operation_generated_false_to_true_after_native_return"
    assert ("disconnect", False) not in job.state["events"]



def test_explicit_stop_after_native_return_disconnects_with_uncertain_outcome(job):
    callback = Mock(return_value=True)
    report = job.run(stop_observation=callback)
    assert report["status"] == "uncertain"
    assert report["reason"] == "OBSERVATION_STOPPED_NATIVE_OUTCOME_UNKNOWN"
    assert report["phase"] == "finished" and report["observation_stopped"]
    assert not report["native_cancelled"] and not report["completion_observed"]
    assert not report["may_continue"] and not report["result_verified"]
    assert report["messages"]["disconnected"] and not report["messages"]["active"]
    assert job.session.exited
    assert "after" not in report and "selected_result" not in report
    job.operation.GetIsToolpathGenerated.assert_not_called()
    job.operation.ToolpathFeedLength.assert_not_called()
    job.operation.GenerateToolpath.assert_called_once_with()
    callback.assert_called_once_with()


def test_stop_is_only_observed_after_native_call_returns(job):
    inside_native = [False]
    stop_calls = []
    def callback():
        assert not inside_native[0]
        assert job.state["started"] and job.session.report["active"]
        stop_calls.append("after_native_return")
        return True
    def native_body():
        inside_native[0] = True
        assert not stop_calls
        assert not job.session.exited
        inside_native[0] = False
    job.state["on_native"] = native_body
    report = job.run(stop_observation=callback)
    assert stop_calls == ["after_native_return"]
    assert report["status"] == "uncertain" and not report["native_cancelled"]


def test_stop_during_pending_observation_releases_sink_and_owner_finally(job):
    from contextlib import contextmanager
    cleanup = []
    @contextmanager
    def worker_owner():
        try:
            yield
        finally:
            assert job.session.exited
            cleanup.extend(["release_pid_lock", "uninitialize_apartment"])
    callback = Mock(side_effect=[False, False, True])
    job.state["completion_values"] = [False, False, True]
    with worker_owner():
        report = job.run(stop_observation=callback)
    assert report["status"] == "uncertain" and report["phase"] == "finished"
    assert not report["may_continue"] and not report["native_cancelled"]
    assert job.pump.call_count == 2
    assert job.operation.GetIsToolpathGenerated.call_count == 2
    assert cleanup == ["release_pid_lock", "uninitialize_apartment"]


def test_stop_callback_error_retains_context_until_later_explicit_stop(job):
    callback = Mock(side_effect=[OSError("stop request unavailable"), False, True])
    job.state["completion_values"] = [False, False, True]
    report = job.run(stop_observation=callback)
    assert report["status"] == "uncertain" and report["observation_stopped"]
    assert report["stop_observation_error_count"] == 1
    assert report["stop_observation_error"]["type"] == "OSError"
    assert job.pump.call_count == 2
    assert job.operation.GetIsToolpathGenerated.call_count == 2
    assert report["messages"]["disconnected"]


@pytest.mark.parametrize("not_true", [False, None, 1, "true", object()])
def test_stop_requires_actual_true_not_truthy_data(job, not_true):
    callback = Mock(side_effect=[not_true, True])
    job.state["completion_values"] = [False, True]
    report = job.run(stop_observation=callback)
    assert report["status"] == "uncertain" and report["observation_stopped"]
    assert job.pump.call_count == 1
    assert job.operation.GetIsToolpathGenerated.call_count == 1


def test_stop_callback_error_does_not_release_before_selected_completion(job):
    callback = Mock(side_effect=OSError("stop request unreadable"))
    report = job.run(stop_observation=callback)
    assert report["completion_observed"] and report["status"] == "completed"
    assert not report["observation_stopped"] and not report["native_cancelled"]
    assert report["stop_observation_error_count"] == 2
    assert ("disconnect", False) not in job.state["events"]


@pytest.mark.parametrize("cleanup_issue", ["event", "disconnect_failure"])
def test_stopped_unknown_outcome_stays_uncertain_with_message_issues(job, cleanup_issue):
    if cleanup_issue == "event":
        job.state["on_native"] = lambda: job.session.report.update(event_count=1)
    else:
        job.session.on_exit = lambda: job.session.report.update(
            disconnected=False, active=True, disconnect_errors=[{"type": "RuntimeError"}])
    report = job.run(stop_observation=lambda: True)
    assert report["status"] == "uncertain" and not report["may_continue"]
    assert report["reason"] == "OBSERVATION_STOPPED_NATIVE_OUTCOME_UNKNOWN"
    assert report["message_review_required"]
    assert report["observation_stopped"] and not report["native_cancelled"]
    assert not report["completion_observed"]
    assert job.session.exited
    if cleanup_issue == "disconnect_failure":
        assert not report["messages"]["disconnected"]


def test_native_exception_then_explicit_stop_is_never_success_or_cancellation(job):
    def failed_native():
        raise RuntimeError("native outcome unknown")
    job.state["on_native"] = failed_native
    report = job.run(stop_observation=lambda: True)
    assert report["status"] == "uncertain" and report["native_call_error"]
    assert report["observation_stopped"] and not report["native_cancelled"]
    assert not report["completion_observed"] and not report["may_continue"]
    assert report["messages"]["disconnected"]
