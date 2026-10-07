"""胶囊识别、输入门禁、事务失败及 MCP 注册回归。"""
import copy
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_capsule_sketch as capsule

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
import server


def profile(angle=0.0):
    """生成不依赖项目文件的四段胶囊。"""
    a, r = 0.003, 0.001
    segments = [
        dict(type=1, center=[-a, 0, 0], start=[-a, r, 0], end=[-a, -r, 0],
             direction=1, radius=r, length=math.pi*r),
        dict(type=1, center=[a, 0, 0], start=[a, -r, 0], end=[a, r, 0],
             direction=1, radius=r, length=math.pi*r),
        dict(type=0, start=[-a, -r, 0], end=[a, -r, 0], length=2*a),
        dict(type=0, start=[a, r, 0], end=[-a, r, 0], length=2*a),
    ]
    for seg in segments:
        seg["construction"] = False
        for key in ("start", "end", "center"):
            if key in seg:
                x, y, z = seg[key]
                seg[key] = [x*math.cos(angle)-y*math.sin(angle)+0.017,
                            x*math.sin(angle)+y*math.cos(angle)-0.021, z]
    return segments


@pytest.mark.parametrize("angle", [0, math.pi/2, -math.pi/2, 0.37, math.pi])
def test_capsule_rotated_translated_and_reordered(angle):
    segments = profile(angle)
    for rows in (segments, list(reversed(segments))):
        result = capsule.analyze_capsule(rows)
        assert result["length_mm"] == pytest.approx(8)
        assert result["width_mm"] == pytest.approx(2)
        assert result["center_m"] == pytest.approx([0.017, -0.021, 0])


@pytest.mark.parametrize("change", ["gap", "inward", "unequal", "construction", "extra", "nonplanar"])
def test_invalid_profiles_are_rejected(change):
    rows = profile()
    if change == "gap":
        rows[2]["start"][1] += 0.0001
    elif change == "inward":
        rows[0]["direction"] *= -1
    elif change == "unequal":
        rows[0]["radius"] *= 2
    elif change == "construction":
        rows[2]["construction"] = True
    elif change == "extra":
        rows.append(copy.deepcopy(rows[0]))
    else:
        rows[1]["center"][2] = 0.001
    with pytest.raises(ValueError):
        capsule.analyze_capsule(rows)


def fixture_model(monkeypatch):
    """用确定性的 COM 替身检查失败路径，无原生几何断言。"""
    before = dict(capsule.analyze_capsule(profile()), relations=0, has_dimensions=False,
                  slot_count=0, read_only=False, segments=profile())
    segments = [SimpleNamespace(Select=Mock(return_value=True)) for _ in range(4)]
    sketch = SimpleNamespace(_oleobj_=object(), GetSketchSegments=lambda: segments)
    manager = SimpleNamespace(ActiveSketch=None, AddToDB=False,
                              CreateArc=Mock(return_value=object()), CreateLine=Mock(return_value=object()))
    manager.InsertSketch = lambda update: setattr(manager, "ActiveSketch", None)
    feature = SimpleNamespace(Select2=lambda a, b: True, GetSpecificFeature2=lambda: sketch)
    extension = SimpleNamespace(StartRecordingUndoObject=Mock(), FinishRecordingUndoObject2=Mock(return_value=True),
                                DeleteSelection2=Mock(return_value=True))
    model = SimpleNamespace(SketchManager=manager, GetConfigurationNames=lambda: ["Default"], Extension=extension,
                            ClearSelection2=Mock(), EditSketch=lambda: setattr(manager, "ActiveSketch", sketch),
                            EditRebuild3=lambda: True, EditUndo2=Mock(), GraphicsRedraw2=Mock())
    health = dict(solid_bodies=1, body_checks=[0], feature_errors=[])
    monkeypatch.setattr(capsule, "_health", lambda model: health)
    monkeypatch.setattr(capsule, "_read", lambda model, name: (before, feature, []))
    return model, before, feature


@pytest.mark.parametrize("key,value", [("relations", 1), ("has_dimensions", True), ("slot_count", 1), ("read_only", True)])
def test_unsafe_sketch_does_not_start_transaction(monkeypatch, key, value):
    model, before, _ = fixture_model(monkeypatch)
    before[key] = value
    with pytest.raises(ValueError):
        capsule.resize_capsule_sketch(model, "Slot", 6, 2)
    model.Extension.StartRecordingUndoObject.assert_not_called()


@pytest.mark.parametrize("length,width", [(2, 2), (1, 2), (6, 0), (float('nan'), 2), (6, float('inf'))])
def test_invalid_size_does_not_access_model(length, width):
    with pytest.raises(ValueError):
        capsule.resize_capsule_sketch(None, "Slot", length, width)


def test_failed_readback_rolls_back_and_verifies(monkeypatch):
    model, before, _ = fixture_model(monkeypatch)
    monkeypatch.setattr(capsule, "inspect_capsule_sketch", lambda model, name: before)
    result = capsule.resize_capsule_sketch(model, "Slot", 6, 2)
    assert not result["success"]
    assert result["rollback_verified"]
    assert not result["saved"]
    model.EditUndo2.assert_called_once_with(1)


def test_failed_rollback_is_reported(monkeypatch):
    model, before, _ = fixture_model(monkeypatch)
    wrong = dict(before, width_mm=3)
    monkeypatch.setattr(capsule, "inspect_capsule_sketch", lambda model, name: wrong)
    result = capsule.resize_capsule_sketch(model, "Slot", 6, 2)
    assert not result["success"] and not result["rollback_verified"]


def test_idempotent_resize_does_not_start_transaction(monkeypatch):
    model, _, _ = fixture_model(monkeypatch)
    result = capsule.resize_capsule_sketch(model, "Slot", 8, 2)
    assert result["success"] and not result["changed"]
    model.Extension.StartRecordingUndoObject.assert_not_called()


def test_capsule_mcp_registration_and_target_guard(monkeypatch):
    names = {"solidworks_inspect_capsule_sketch", "solidworks_resize_capsule_sketch"}
    assert names <= set(server.mcp._tool_manager._tools)
    def reject(params):
        raise ValueError("target rejected")
    monkeypatch.setattr(server, "_active_model_required", reject)
    monkeypatch.setattr(server, "_run_locked", lambda op, fmt: op())
    writer = Mock()
    monkeypatch.setattr(capsule, "resize_capsule_sketch", writer)
    with pytest.raises(ValueError, match="target rejected"):
        server.solidworks_resize_capsule_sketch(server.SolidWorksCapsuleResizeInput(
            sketch_name="Slot", length_mm=6, width_mm=2, expected_document_path=r"C:\work\part.sldprt"))
    writer.assert_not_called()


def test_success_preserves_sketch_but_reports_replaced_segments(monkeypatch):
    model, before, _ = fixture_model(monkeypatch)
    after = dict(before, length_mm=6.0, width_mm=2.0)
    monkeypatch.setattr(capsule, "inspect_capsule_sketch", lambda model, name: after)
    model.Extension.FinishRecordingUndoObject2.return_value = False
    result = capsule.resize_capsule_sketch(model, "Slot", 6, 2)
    assert result["success"] and not result["undo_record_created"]
    assert not result["segment_references_preserved"] and not result["saved"]
    assert model.SketchManager.CreateArc.call_count == 2
    assert model.SketchManager.CreateLine.call_count == 2
    assert not model.SketchManager.AddToDB
    model.EditUndo2.assert_not_called()


def test_creation_failure_restores_add_to_db_and_attempts_undo(monkeypatch):
    model, before, _ = fixture_model(monkeypatch)
    model.SketchManager.CreateArc.return_value = None
    monkeypatch.setattr(capsule, "inspect_capsule_sketch", lambda model, name: before)
    result = capsule.resize_capsule_sketch(model, "Slot", 6, 2)
    assert not result["success"] and result["rollback_verified"]
    assert not model.SketchManager.AddToDB
    model.EditUndo2.assert_called_once_with(1)
