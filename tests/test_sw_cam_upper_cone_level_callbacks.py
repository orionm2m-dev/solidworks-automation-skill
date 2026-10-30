"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_cam_upper_cone_feature as module
from scripts.sw_cam_mill_levels import read_mill_level_values


def payload_environment(monkeypatch, fault=None):
    feature, doc, machine, operation, tool, model, parameters, transform, origin, vector = [object() for _ in range(10)]
    generic = {"native_id": 249}
    state = {"document": {"needs_save": True}, "operations": [{"native_id": 248, "assigned_tool": generic}]}
    native = {"doc": doc, "machine": machine, "operations": {248: operation}}
    metric = {"metric": True}
    finish_levels = dict(levels=dict(machining_depth_native=13.2, override_machining_depth=False,
        toolpath_parameters=dict(use_setup_definition_for_top_Z=False, use_minimum_Z=False,
            adjust_feature_height=False, first_cut_Z_type_raw=0, use_setup_definition_for_bottom_Z=False,
            minimum_Z_native=12.6, start_Z_native=25.8)),
        setup=dict(transform_present=True, transform_matrix_decoded=False, origin_native=[0., 0., 0.],
            axis_native=[0., 0., -1.], axis_magnitude=1., axis_normalized_for_report_only=[0., 0., -1.],
            native_axis_modified=False))
    expected = dict(rough=dict(candidate={"same": "candidate"}, levels={"same": "rough_levels"}, entry={"same": "entry"}),
        finish=dict(details={"same": "details"}, levels=finish_levels, leads={"same": "leads"},
            full_tool={"same": "full_tool"}, unit_record=metric))
    calls = []
    class Batch:
        def __init__(self, *args, **kwargs): self.complete = False
        def __enter__(self): return self
        def __exit__(self, *args): self.complete = args[0] is None
        def feature_dispatch(self, value):
            assert value is feature
            calls.append(("IDispatch", feature))
            return feature
        def typed(self, value, interface):
            allowed = {"ICWFeature": feature, "ICWMillOperation": operation, "ICWMillOperation3": operation,
                "ICWToolpathParam": parameters, "ICWPosition": origin, "ICWUnitVector": vector}
            assert interface in allowed and value is allowed[interface]
            return value
        def read(self, value, name, *args):
            calls.append((name, value))
            if value is doc and name == "GetCWObjectFromID":
                assert args == (1, 244)
                return feature, True
            if value is operation:
                if name == "GetMachiningDepth":
                    assert args == (feature,)
                    return float("nan") if fault == "nonfinite_depth" else 13.2
                if name == "GetOverrideMachiningDepth":
                    assert args == (feature,)
                    return 0 if fault == "nonboolean_override" else False
                if name == "GetToolpathParam":
                    assert not args
                    return None if fault == "null_interface" else parameters
                if name == "GetSetupParameters":
                    assert not args
                    return (transform, origin, None if fault == "null_setup_axis" else vector)
            if value is parameters and name == "GetToolpathParameters":
                assert not args
                return (False, False, False, 0, False, 12.6, 25.8)
            if value is origin and name == "GetCoordinates": return [0., 0., 0.]
            if value is vector and name == "GetCoordinates": return [0., 0., 0.] if fault == "zero_axis" else [0., 0., -1.]
            pytest.fail("Unexpected getter: " + name)
        def lead_interface(self, *args): pytest.fail("Lead reader is outside this focused level test")
        def require_complete(self): assert self.complete
        def summary(self): return {"complete": self.complete, "read_names": [row[0] for row in calls]}
    class Guard:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, value, name, *args):
            assert name == "ActiveDoc"
            return model
    args=dict(process_id=23824,expected_source_sha256="1"*64,target_feature_native_id=244,
        target_operation_native_id=247,expected_candidate_tool_native_id=263,finish_operation_native_id=248)
    ctx=SimpleNamespace(args=args,sw=object(),typelib_path="offline",app=object(),guard=lambda:Guard(),
        loaded=dict(pins=[],payload=deepcopy(expected["rough"]),finish_payload=deepcopy(expected["finish"]),observation_pin={}),
        identity=lambda:state["document"],files=lambda:None,owned=lambda:None,events=lambda:None)
    monkeypatch.setattr(module,"ScopedFinishReadBatch",Batch)
    monkeypatch.setattr(module,"read_document_cam_unit_scope",lambda *a,**k:deepcopy(metric))
    monkeypatch.setattr(module,"capture_assignment_snapshot",lambda *a,**k:(state,native,{"same":"rough_levels"},{},{"same":"entry"}))
    monkeypatch.setattr(module,"read_assignment_candidate",lambda *a,**k:{"same":"candidate"})
    monkeypatch.setattr(module,"read_generic_tool",lambda *a,**k:(generic,tool))
    monkeypatch.setattr(module,"_object_id",lambda given_doc,given_feature,read:244 if given_doc is doc and given_feature is feature else pytest.fail("Wrong ID target"))
    monkeypatch.setattr(module,"read_finish_details",lambda *a,**k:{"same":"details"})
    monkeypatch.setattr(module,"read_lead_details",lambda *a,**k:{"same":"leads"})
    monkeypatch.setattr(module,"read_full_mill_tool",lambda *a,**k:{"same":"full_tool"})
    # The real level reader must never be replaced in this integration test.
    assert module.read_mill_level_values is read_mill_level_values
    return ctx,state,native,expected,calls


def test_real_level_reader_crosses_interface_keyword_boundary(monkeypatch):
    ctx,state,native,expected,calls=payload_environment(monkeypatch)
    diagnostic={}
    result=module._capture_payload(ctx,state,native,diagnostic)
    assert result==expected and diagnostic["observed_payload"]==expected
    assert diagnostic["full_parent_payload_matched"] is True
    assert [name for name,_ in calls]==["GetCWObjectFromID","IDispatch","GetMachiningDepth",
        "GetOverrideMachiningDepth","GetToolpathParam","GetToolpathParameters","GetSetupParameters","GetCoordinates","GetCoordinates"]
    assert diagnostic["read_batch"]["complete"] is True


@pytest.mark.parametrize("fault,last",[("nonfinite_depth","GetMachiningDepth"),
    ("nonboolean_override","GetOverrideMachiningDepth"),("null_interface","GetToolpathParam"),
    ("null_setup_axis","GetSetupParameters"),("zero_axis","GetCoordinates")])
def test_real_level_reader_rejects_bad_values_without_next_getter(monkeypatch,fault,last):
    ctx,state,native,expected,calls=payload_environment(monkeypatch,fault)
    diagnostic={}
    with pytest.raises(ValueError):module._capture_payload(ctx,state,native,diagnostic)
    assert calls[-1][0]==last
    assert diagnostic["read_batch"]["complete"] is False
    assert "observed_payload" not in diagnostic


def test_full_payload_mismatch_preserves_observed_level_data(monkeypatch):
    ctx,state,native,expected,calls=payload_environment(monkeypatch)
    ctx.loaded["finish_payload"]["levels"]["levels"]["machining_depth_native"]=1.0
    diagnostic={}
    with pytest.raises(ValueError,match="Protected completed"):
        module._capture_payload(ctx,state,native,diagnostic)
    assert diagnostic["observed_payload"]==expected
    assert diagnostic["read_batch"]["complete"] is True


def test_level_callback_keyword_names_do_not_collide():
    tree=ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    payload=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_capture_payload")
    getter=next(n for n in ast.walk(payload) if isinstance(n,ast.FunctionDef) and n.name=="getter")
    positional={arg.arg for arg in getter.args.posonlyargs+getter.args.args}
    assert not positional & {"interface","decoder","validator"}


def test_pre_fix_callback_reproduces_reported_error_before_next_native_read(monkeypatch):
    import inspect
    ctx,state,native,expected,calls=payload_environment(monkeypatch)
    source=inspect.getsource(module._capture_payload)
    fixed="def getter(obj,interface_name,name,*values,**kw):return read_native(interface_name+"
    broken="def getter(obj,interface,name,*values,**kw):return read_native(interface+"
    assert source.count(fixed)==1
    namespace=dict(module.__dict__)
    exec(compile(source.replace(fixed,broken),"<historical callback regression>","exec"),namespace)
    diagnostic={}
    with pytest.raises(TypeError,match="multiple values for argument 'interface'"):
        namespace["_capture_payload"](ctx,state,native,diagnostic)
    assert calls[-1][0]=="GetOverrideMachiningDepth"
    assert "GetToolpathParam" not in [name for name,_ in calls]
    assert diagnostic["read_batch"]["complete"] is False
