"""无 CAD 的结构、轴归属、动画时间游标与 COM 调用回归。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

from scripts import sw_native_assembly_audit as audit

I = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


class PropertyObject(N):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._oleobj_ = object()

    def __call__(self, *args):
        raise AssertionError("Default COM member must never run")


@pytest.fixture
def graph(tmp_path, monkeypatch):
    path = tmp_path / "assembly.sldasm"; path.write_bytes(b"saved assembly")
    part = tmp_path / "part.sldprt"; part.write_bytes(b"saved part")
    receipt = tmp_path / "readback.json"
    state = N(timestamp=0.0, active=False, playing=False)
    def transform():
        matrix = list(I); matrix[9] = state.timestamp
        return PropertyObject(ArrayData=matrix)
    component = PropertyObject(Name2="part-1", ComponentReference="ITEM",
        ReferencedConfiguration="Default", GetPathName=Mock(return_value=str(part)),
        GetID=Mock(return_value=17), GetModelDoc2=Mock(return_value=PropertyObject()),
        IsSuppressed=Mock(return_value=False), IsFixed=Mock(return_value=True),
        GetTotalTransform=Mock(side_effect=lambda total: transform()))
    surface = PropertyObject(IsCylinder=Mock(return_value=True), CylinderParams=[0, 0, 0, 0, 0, 1, .02])
    entity = PropertyObject(GetType=Mock(return_value=2), GetComponent=Mock(return_value=component),
        GetSurface=Mock(return_value=surface))
    step = PropertyObject(Name="Separate", ExplodeDistance=.1, RotationAngle=.2,
        GetComponents=Mock(return_value=(component,)), GetExplodeDirection=Mock(return_value=(entity, 2)),
        GetRotationAxis=Mock(return_value=(entity, 0)))
    cfg = PropertyObject(Name="Default", GetNumberOfExplodeSteps=Mock(return_value=1),
        GetExplodeStep=Mock(side_effect=lambda index: step if index == 0 else None))
    class Study(PropertyObject):
        @property
        def IsActive(self): return state.active
        @property
        def IsPlaying(self): return state.playing
    def activate(): state.active = True; return True
    def set_time(value): state.timestamp = value; return True
    study = Study(GetDuration=Mock(return_value=1.), Activate=Mock(side_effect=activate),
        SetTime=Mock(side_effect=set_time), GetTime=Mock(side_effect=lambda: state.timestamp),
        Calculate=Mock(side_effect=AssertionError("no Calculate")), Play=Mock(side_effect=AssertionError("no Play")),
        Stop=Mock(side_effect=AssertionError("no Stop")))
    manager = PropertyObject(GetMotionStudyNames=Mock(return_value=("Existing",)),
        GetMotionStudy=Mock(return_value=study))
    model = PropertyObject(GetPathName=Mock(return_value=str(path)), GetTitle=Mock(return_value=path.name),
        GetType=Mock(return_value=2), GetSaveFlag=Mock(return_value=False),
        ConfigurationManager=PropertyObject(ActiveConfiguration=cfg),
        GetConfigurationNames=Mock(return_value=("Default", "Alternate")),
        GetExplodedViewNames2=Mock(return_value=("Disassembly",)),
        GetComponents=Mock(return_value=(component,)), ShowExploded2=Mock(return_value=True),
        Save3=Mock(side_effect=AssertionError("no Save")),
        Extension=PropertyObject(GetMotionStudyManager=Mock(return_value=manager)))
    sw = PropertyObject(GetProcessID=Mock(return_value=123), ActiveDoc=model)
    monkeypatch.setattr(audit, "_native_interface", lambda obj, name: obj)
    monkeypatch.setattr(audit, "_motion_manager", lambda model: manager)
    inspect_args = dict(process_id=123, expected_document_path=str(path), expected_file_sha256=audit._file_hash(path), receipt_path=str(receipt))
    rows = []
    for time in (0., .5, 1.):
        matrix = list(I); matrix[9] = time
        rows.append(dict(time=time, transforms={"item": matrix}))
    baseline = {"sampled_transforms": rows, "initial_closed_poses": {"part-1": list(I)}}
    baseline_path = tmp_path / "baseline.json"; baseline_path.write_text(json.dumps(baseline), encoding="utf8")
    animation_args = {**inspect_args, "study_name": "Existing", "explode_view_name": "Disassembly",
        "baseline_samples_path": str(baseline_path), "baseline_samples_sha256": audit._file_hash(baseline_path),
        "tracked_components": [{"key": "item", "reference": "ITEM", "path": str(part)}]}
    return N(**locals())


def inspect(graph, **updates):
    return audit.inspect_native_assembly(graph.sw, **{**graph.inspect_args, **updates})


def animate(graph, **updates):
    return audit.audit_native_animation(graph.sw, **{**graph.animation_args, **updates})


def rewrite_baseline(graph, mutate):
    baseline = deepcopy(graph.baseline); mutate(baseline)
    graph.baseline_path.write_text(json.dumps(baseline), encoding="utf8")
    graph.animation_args["baseline_samples_sha256"] = audit._file_hash(graph.baseline_path)


def test_complete_structural_readback_preserves_native_ids_and_axes(graph):
    report = inspect(graph)
    assert report["status"] == "review_required"
    assert report["mutation_attempted"] is False
    snapshot = report["snapshot"]
    assert snapshot["configuration_names"] == ["Default", "Alternate"]
    assert snapshot["components"][0]["native_id"] == 17
    assert snapshot["components"][0]["matrix"] == I
    axis = snapshot["native_step_sequence"][0]["axes"]["GetExplodeDirection"]
    assert axis["owner"] == {"name": "part-1", "path": str(graph.part), "reference": "ITEM"}
    assert axis["cylinder_parameters"] == [0, 0, 0, 0, 0, 1, .02]
    assert snapshot["studies"] == [{"name": "Existing", "duration_seconds": 1.}]
    assert report["snapshot_matches_expected"] is None
    assert report["source_file_unchanged"] is True
    assert json.loads(graph.receipt.read_text("utf8")) == report
    graph.study.Activate.assert_not_called(); graph.model.ShowExploded2.assert_not_called()
    graph.model.Save3.assert_not_called()


def test_snapshot_compares_exactly_with_only_explicit_path_replacements(graph):
    baseline = audit._snapshot(graph.model, {})
    old = str(graph.tmp_path / "old-part.sldprt")
    baseline["components"][0]["path"] = old
    for axis in baseline["native_step_sequence"][0]["axes"].values(): axis["owner"]["path"] = old
    evidence = graph.tmp_path / "snapshot.json"; evidence.write_text(json.dumps({"snapshot": baseline}))
    report = inspect(graph, expected_snapshot_path=str(evidence), expected_snapshot_sha256=audit._file_hash(evidence),
                     path_replacements={old: str(graph.part)})
    assert report["snapshot_matches_expected"] is True
    assert report["internal_document_id_verified"] is False


@pytest.mark.parametrize("field,value", [("native_id", 99), ("configuration", "Other"), ("fixed", False), ("reference", "OTHER")])
def test_unapproved_component_identity_changes_fail(graph, field, value):
    baseline = audit._snapshot(graph.model, {}); baseline["components"][0][field] = value
    evidence = graph.tmp_path / "snapshot.json"; evidence.write_text(json.dumps(baseline))
    report = inspect(graph, expected_snapshot_path=str(evidence), expected_snapshot_sha256=audit._file_hash(evidence))
    assert report["status"] == "error" and report["snapshot_matches_expected"] is False


def test_axis_owner_mismatch_stops_before_other_axis_and_studies(graph):
    graph.entity.GetComponent.return_value = PropertyObject(Name2="part-1", ComponentReference="FOREIGN", GetPathName=lambda: str(graph.part))
    report = inspect(graph)
    assert report["status"] == "error"
    graph.step.GetRotationAxis.assert_not_called(); graph.manager.GetMotionStudyNames.assert_not_called()


@pytest.mark.parametrize("kind", ["null", "edge", "noncylinder"])
def test_axis_does_not_query_unsupported_surface(graph, kind):
    if kind == "null":
        graph.step.GetExplodeDirection.return_value = (None, -1)
        graph.step.GetRotationAxis.return_value = (None, -1)
    elif kind == "edge": graph.entity.GetType.return_value = 1
    else: graph.surface.IsCylinder.return_value = False
    report = inspect(graph)
    assert report["status"] == "review_required"
    axis = report["snapshot"]["native_step_sequence"][0]["axes"]["GetExplodeDirection"]
    assert axis["cylinder_parameters"] is None
    if kind != "noncylinder": graph.entity.GetSurface.assert_not_called()


@pytest.mark.parametrize("returned", [None, (1,), (None, True), (None, 0, 1)])
def test_axis_tuple_abi_is_strict(graph, returned):
    graph.step.GetExplodeDirection.return_value = returned
    assert inspect(graph)["status"] == "error"
    graph.step.GetRotationAxis.assert_not_called()


@pytest.mark.parametrize("count", [513, -1, True, 1.0])
def test_step_bounds_reject_before_step_getter(graph, count):
    graph.cfg.GetNumberOfExplodeSteps.return_value = count
    assert inspect(graph)["status"] == "error"
    graph.cfg.GetExplodeStep.assert_not_called()


def test_readonly_one_based_steps_supported_without_repeating_zero(graph):
    graph.cfg.GetExplodeStep.side_effect = lambda index: graph.step if index == 1 else None
    report = inspect(graph)
    assert report["snapshot"]["native_step_sequence"][0]["index"] == 1
    assert [call.args for call in graph.cfg.GetExplodeStep.call_args_list] == [(0,), (1,)]


@pytest.mark.parametrize("change", ["pid", "path", "dirty", "hash"])
def test_guards_block_before_readback(graph, change):
    if change == "pid": graph.sw.GetProcessID.return_value = 777
    elif change == "path": graph.model.GetPathName.return_value = str(graph.part)
    elif change == "dirty": graph.model.GetSaveFlag.return_value = True
    else: graph.path.write_bytes(b"modified")
    assert inspect(graph)["status"] == "error"
    graph.model.GetComponents.assert_not_called()


@pytest.mark.parametrize("function", [inspect, animate])
def test_existing_receipt_remains_immutable_without_com_calls(graph, function):
    graph.receipt.write_bytes(b"previous evidence")
    assert function(graph)["status"] == "error"
    assert graph.receipt.read_bytes() == b"previous evidence"
    graph.sw.GetProcessID.assert_not_called()


def test_final_document_drift_blocks_structural_success(graph):
    graph.model.GetSaveFlag.side_effect = [False, True]
    report = inspect(graph)
    assert report["status"] == "error"
    assert report["document_after"]["needs_save"] is True


def test_animation_compares_all_requested_frames_and_restores_all_closed_poses(graph, monkeypatch):
    real = audit._write_receipt
    stages = []
    def write(path, report, **kwargs): stages.append(report["phase"]); return real(path, report, **kwargs)
    monkeypatch.setattr(audit, "_write_receipt", write)
    def collapse(*args):
        assert stages[-1] == "collapse_explode_intent"
        return True
    graph.model.ShowExploded2.side_effect = collapse
    report = animate(graph)
    assert report["status"] == "review_required"
    assert report["animation_comparison_verified"] is True
    assert report["sampled_transforms"] == graph.baseline["sampled_transforms"]
    assert report["maximum_matrix_delta"] == {"item": 0}
    assert report["closed_poses_verified"] and report["time_zero_restored"]
    assert report["source_file_unchanged"] and not report["production_release"] and not report["collision_verified"]
    assert report["final_closed_poses"] == {"part-1": I}
    assert [item.args for item in graph.study.SetTime.call_args_list] == [(.05,), (0.,), (.5,), (1.,), (0.,)]
    graph.model.Save3.assert_not_called(); graph.study.Calculate.assert_not_called()
    graph.study.Play.assert_not_called(); graph.study.Stop.assert_not_called()
    assert json.loads(graph.receipt.read_text("utf8")) == report


def test_optional_closed_pose_baseline_never_claims_full_verification(graph):
    rewrite_baseline(graph, lambda baseline: baseline.pop("initial_closed_poses"))
    report = animate(graph)
    assert report["animation_comparison_verified"] is True
    assert report["closed_poses_verified"] is False


def test_frame_mismatch_keeps_partial_raw_and_restores_zero(graph):
    rewrite_baseline(graph, lambda baseline: baseline["sampled_transforms"][1]["transforms"]["item"].__setitem__(9, 8.))
    report = animate(graph)
    assert report["status"] == "error"
    assert len(report["sampled_transforms"]) == 2
    assert report["sampled_transforms"][1]["transforms"]["item"][9] == .5
    assert report["time_zero_restored"] is True
    assert not report["sampled_transforms_complete"] and not report["animation_comparison_verified"]


def test_wrong_closed_pose_rejects_without_full_motion(graph):
    rewrite_baseline(graph, lambda baseline: baseline["initial_closed_poses"]["part-1"].__setitem__(9, .1))
    report = animate(graph)
    assert report["status"] == "error" and report["time_zero_restored"]
    assert len(report["sampled_transforms"]) == 1


def test_component_identity_changes_before_motion_block_mutations(graph):
    graph.component.ComponentReference = "WRONG"
    assert animate(graph)["status"] == "error"
    graph.model.ShowExploded2.assert_not_called(); graph.study.Activate.assert_not_called()


def test_already_playing_never_stopped_or_taken_over(graph):
    graph.state.playing = True
    assert animate(graph)["status"] == "error"
    graph.model.ShowExploded2.assert_not_called(); graph.study.Stop.assert_not_called()


def test_changed_pid_during_sampling_prevents_restore_on_foreign_session(graph):
    original = graph.study.SetTime.side_effect
    def change(value):
        result = original(value)
        if value == .5: graph.sw.GetProcessID.return_value = 777
        return result
    graph.study.SetTime.side_effect = change
    report = animate(graph)
    assert report["status"] == "error" and not report["time_zero_restored"]
    assert graph.study.SetTime.call_args_list[-1].args == (.5,)


def test_final_restore_failure_cannot_report_success(graph):
    original = graph.study.SetTime.side_effect
    def fail(value):
        if value == 0 and graph.state.timestamp == 1: raise RuntimeError("restore failed")
        return original(value)
    graph.study.SetTime.side_effect = fail
    report = animate(graph)
    assert report["status"] == "error" and not report["animation_comparison_verified"]
    assert not report["time_zero_restored"]
    assert [item.args for item in graph.study.SetTime.call_args_list].count((0.,)) == 2


@pytest.mark.parametrize("mutate", [
    lambda value: value["sampled_transforms"].clear(),
    lambda value: value["sampled_transforms"][0].__setitem__("time", .2),
    lambda value: value["sampled_transforms"][1].__setitem__("time", 0),
    lambda value: value["sampled_transforms"][0]["transforms"].__setitem__("other", I),
    lambda value: value["initial_closed_poses"].__setitem__("extra-1", I),
])
def test_invalid_baseline_blocks_all_mutations(graph, mutate):
    rewrite_baseline(graph, mutate)
    assert animate(graph)["status"] == "error"
    graph.study.SetTime.assert_not_called(); graph.model.ShowExploded2.assert_not_called()


@pytest.mark.parametrize("value", [True, "0.01", 0, -1, float("inf"), 1e-5])
def test_invalid_matrix_tolerance_blocks_com(graph, value):
    assert animate(graph, matrix_tolerance=value)["status"] == "error"
    graph.sw.GetProcessID.assert_not_called()


def test_set_time_retries_only_native_false_and_requires_matching_readback(graph):
    graph.state.active = True
    graph.study.SetTime.side_effect = [False, True, True]
    graph.study.GetTime.side_effect = [0., .3, .5]
    clock = Mock(side_effect=[0, 0, 0, .1, .1, .2])
    result = audit._set_time(graph.study, .5, Mock(), clock=clock, sleeper=Mock())
    assert result["attempt"] == 3


def test_set_time_exception_is_not_replayed(graph):
    graph.state.active = True; graph.study.SetTime.side_effect = RuntimeError("native failure")
    with pytest.raises(RuntimeError): audit._set_time(graph.study, .5, Mock())
    graph.study.SetTime.assert_called_once_with(.5)


def test_set_time_timeout_is_bounded(graph):
    graph.state.active = True; graph.study.SetTime.side_effect = None; graph.study.SetTime.return_value = False
    with pytest.raises(TimeoutError):
        audit._set_time(graph.study, .5, Mock(), timeout_seconds=.1, clock=Mock(side_effect=[0., .2]), sleeper=Mock())
    graph.study.SetTime.assert_called_once()


def test_path_mapping_rejects_chains_aliases_and_nonabsolute(graph):
    a, b, c = [str(graph.tmp_path / name) for name in ("a", "b", "c")]
    for value in ({a: b, b: c}, {a: b, c: b}, {a: a}, {"relative": b}, [(a, b)]):
        with pytest.raises(ValueError): audit._path_map(value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pywin32 dispatch ABI")
def test_real_cdispatch_does_not_invoke_default_callable_properties(graph, monkeypatch):
    import pythoncom
    from win32com.client.dynamic import CDispatch
    from win32com.client.build import DispatchItem
    methods = {"GetProcessID", "GetPathName", "GetTitle", "GetType", "GetSaveFlag", "GetConfigurationNames",
        "GetExplodedViewNames2", "GetComponents", "GetID", "GetModelDoc2", "IsSuppressed", "IsFixed", "GetTotalTransform",
        "GetNumberOfExplodeSteps", "GetExplodeStep", "GetExplodeDirection", "GetRotationAxis", "GetComponent",
        "GetSurface", "IsCylinder", "GetMotionStudyNames", "GetMotionStudy", "GetDuration"}
    defaults, bad_flags, observed, cache = [], [], set(), {}
    def wrap(value):
        if isinstance(value, (list, tuple)): return type(value)(wrap(item) for item in value)
        if not isinstance(value, PropertyObject): return value
        if id(value) not in cache: cache[id(value)] = CDispatch(Raw(value), DispatchItem())
        return cache[id(value)]
    class Raw:
        def __init__(self, target): self.target, self.names = target, {}
        def GetIDsOfNames(self, locale, name):
            if name not in self.names.values(): self.names[len(self.names)+1] = name
            return next(key for key, value in self.names.items() if value == name)
        def Invoke(self, dispid, locale, flags, result, *args):
            if dispid == 0:
                defaults.append(self.target); raise AssertionError("default dispatch invoked")
            name = self.names[dispid]; value = getattr(self.target, name)
            if name in methods:
                observed.add(name)
                if flags != pythoncom.DISPATCH_METHOD: bad_flags.append(name); return wrap(PropertyObject())
                return wrap(value(*args))
            return wrap(value)
    monkeypatch.setattr(audit, "_motion_manager", lambda model: wrap(graph.manager))
    report = audit.inspect_native_assembly(wrap(graph.sw), **graph.inspect_args)
    assert report["status"] == "review_required"
    assert observed == methods
    assert defaults == [] and bad_flags == []


def test_animation_reenumerates_instances_after_sampling(graph):
    original = graph.study.SetTime.side_effect
    def change(value):
        result = original(value)
        if value == 1.0: graph.component.ComponentReference = "CHANGED"
        return result
    graph.study.SetTime.side_effect = change
    report = animate(graph)
    assert report["status"] == "error"
    assert report["component_identities_unchanged"] is False
    assert report["animation_comparison_verified"] is False
    assert graph.model.GetComponents.call_count == 2


def test_assembly_sha_change_during_preflight_blocks_first_presentation_mutation(graph):
    def duration():
        graph.path.write_bytes(b"changed outside")
        return 1.
    graph.study.GetDuration.side_effect = duration
    report = animate(graph)
    assert report["status"] == "error"
    graph.model.ShowExploded2.assert_not_called()
    graph.study.Activate.assert_not_called()
