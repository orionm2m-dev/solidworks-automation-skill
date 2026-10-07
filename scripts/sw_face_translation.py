"""用原生 Move Face 平移明确包围盒内的面，不替换实体或自动保存。"""
from __future__ import annotations

import math

from .sw_connect import get_com_member as member


def validate_request(bounds_mm, translation_mm, expected_face_count):
    """验证毫米输入，拒绝空区域、非有限数和零位移。"""
    if len(bounds_mm) != 6 or len(translation_mm) != 3:
        raise ValueError("需要六个边界值和三个平移值")
    if not all(math.isfinite(v) for v in [*bounds_mm, *translation_mm]):
        raise ValueError("坐标必须为有限值")
    if any(bounds_mm[i] >= bounds_mm[i+3] for i in range(3)):
        raise ValueError("包围盒必须具有正体积")
    if math.sqrt(sum(v*v for v in translation_mm)) < 1e-6 or expected_face_count < 1:
        raise ValueError("位移或面数无效")


def contained(bounds, region, tolerance=1e-5):
    """仅接受整个面包围盒位于区域中的情况，不接受仅相交的面。"""
    return all(bounds[i] >= region[i]-tolerance and bounds[i+3] <= region[i+3]+tolerance
               for i in range(3))


def _faces(model, bounds_mm):
    found = []
    for body in member(model, "GetBodies2", 0, False) or []:
        for face in member(body, "GetFaces") or []:
            box = [float(v)*1000 for v in member(face, "GetBox")]
            if contained(box, bounds_mm):
                found.append((face, {"bounds_mm": box, "area_mm2": float(member(face, "GetArea"))*1e6}))
    return found


def _health(model):
    bodies = list(member(model, "GetBodies2", 0, False) or [])
    return {"solid_count": len(bodies), "body_checks": [int(member(b, "Check2")) for b in bodies],
            "volume_mm3": sum(float(member(b, "GetMassProperties", 1)[3])*1e9 for b in bodies)}


def translate_faces_in_box(model, bounds_mm, translation_mm, expected_face_count,
                           feature_name, dry_run=True):
    """按完整面包围盒选择并平移，要求明确面数；失败后删除本次特征并回读。

    仅支持单配置零件。直接编辑可影响邻接拓扑，调用者仍须检查导出和装配。
    dry_run 返回所选面的边界和面积；所有坐标为零件坐标，不是装配坐标。
    """
    validate_request(bounds_mm, translation_mm, expected_face_count)
    if int(member(model, "GetType")) != 1:
        raise ValueError("仅支持零件文档")
    if len(member(model, "GetConfigurationNames") or []) != 1:
        raise ValueError("仅支持单配置零件")
    if member(member(model, "SketchManager"), "ActiveSketch") is not None:
        raise ValueError("请先退出草图编辑")
    selected = _faces(model, bounds_mm)
    if len(selected) != expected_face_count:
        raise ValueError(f"面数不符: expected={expected_face_count}, actual={len(selected)}")
    before = _health(model)
    if not before["solid_count"] or any(before["body_checks"]):
        raise ValueError(f"修改前实体检查失败: {before}")
    report = {"success": True, "dry_run": dry_run, "faces_before": [r for _, r in selected],
              "translation_mm": list(translation_mm), "health_before": before,
              "saved": False, "review_required": True}
    if dry_run:
        return report
    if bool(member(model, "IsOpenedReadOnly")):
        raise ValueError("零件只读")
    if member(model, "FeatureByName", feature_name) is not None:
        raise ValueError("目标特征名称已存在，拒绝重复位移")
    import pythoncom
    from win32com.client import VARIANT
    member(model, "ClearSelection2", True)
    data = member(member(model, "SelectionManager"), "CreateSelectData")
    data.Mark = 1
    for i, (face, _) in enumerate(selected):
        if not member(face, "Select4", i != 0, data):
            member(model, "ClearSelection2", True)
            raise RuntimeError("面选择失败")
    created = None
    try:
        vector = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [v/1000 for v in translation_mm])
        empty = VARIANT(pythoncom.VT_EMPTY, None)
        created = member(member(model, "FeatureManager"), "InsertMoveFace3",
                         1, False, 0.0, 0.0, vector, empty, 0, 0.0)
        if created is None:
            raise RuntimeError("InsertMoveFace3 未创建特征")
        created.Name = feature_name
        if not member(model, "EditRebuild3") or int(member(created, "GetErrorCode")):
            raise RuntimeError("Move Face 重建失败")
        health = _health(model)
        region = [v+translation_mm[i % 3] for i, v in enumerate(bounds_mm)]
        moved = _faces(model, region)
        if len(moved) != expected_face_count or health["solid_count"] != before["solid_count"] or any(health["body_checks"]):
            raise RuntimeError("移动后面数或实体检查失败")
        report.update(feature_name=str(member(created, "Name")), feature_type=str(member(created, "GetTypeName2")),
                      faces_after=[r for _, r in moved], health_after=health,
                      translation_readback_m=list(member(member(created, "GetDefinition"), "TriadTranslationParameters")))
        if any(abs(a-b/1000) > 1e-8 for a,b in zip(report["translation_readback_m"], translation_mm)):
            raise RuntimeError("位移回读不符")
        return report
    except Exception as exc:
        rollback = False
        if created is not None:
            try:
                member(model, "ClearSelection2", True)
                if member(created, "Select2", False, 0) and member(member(model, "Extension"), "DeleteSelection2", 0):
                    member(model, "EditRebuild3")
                    restored = _health(model)
                    rollback = (restored["solid_count"] == before["solid_count"] and not any(restored["body_checks"])
                                and abs(restored["volume_mm3"]-before["volume_mm3"]) < 1e-4
                                and len(_faces(model, bounds_mm)) == expected_face_count)
            except Exception:
                pass
        return {"success": False, "error": str(exc), "rollback_verified": rollback, "saved": False}
    finally:
        member(model, "ClearSelection2", True)
        member(model, "GraphicsRedraw2")
