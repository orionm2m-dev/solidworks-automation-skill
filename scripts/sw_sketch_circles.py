"""读取和调整现有二维草图圆半径；不重建草图实体或自动保存。"""
from __future__ import annotations

import math
import hashlib
import json

from .sw_connect import get_com_member as member


def match_circles(circles, centers_mm, expected_radius_mm, tolerance_mm=0.001):
    """按圆心和旧半径严格匹配；歧义、重复请求或缺失圆均拒绝。"""
    if not centers_mm or expected_radius_mm <= 0 or not math.isfinite(expected_radius_mm):
        raise ValueError("圆心和旧半径无效")
    indices = []
    for center in centers_mm:
        if len(center) != 2 or not all(math.isfinite(v) for v in center):
            raise ValueError("圆心必须是两个有限毫米坐标")
        found = [i for i,c in enumerate(circles)
                 if math.dist(center, c["center_mm"][:2]) <= tolerance_mm
                 and abs(c["radius_mm"]-expected_radius_mm) <= tolerance_mm]
        if len(found) != 1 or found[0] in indices:
            raise ValueError(f"圆匹配不唯一或缺失: {center}, matches={found}")
        indices.append(found[0])
    return indices


def _read(model, sketch_name):
    feature = member(model, "FeatureByName", sketch_name)
    if feature is None or str(member(feature, "GetTypeName2")) != "ProfileFeature":
        raise ValueError("找不到二维草图")
    sketch = member(feature, "GetSpecificFeature2")
    if member(sketch, "Is3D"):
        raise ValueError("不支持三维草图")
    # GetArcs2 一次返回每条圆弧的 16 个值，避免遍历大型 DXF 的全部 COM 段。
    arcs=list(member(sketch,"GetArcs2") or [])
    arc_count=int(member(sketch,"GetArcCount"))
    if len(arcs) != 16*arc_count:
        raise ValueError("圆弧数组长度不符")
    circles=[]
    for offset in range(0,len(arcs),16):
        row=arcs[offset:offset+16];start,end,center=row[6:9],row[9:12],row[12:15]
        if math.dist(start,end) > 1e-9:
            continue
        circles.append({"center_mm":[float(v)*1000 for v in center],
                        "radius_mm":math.dist(start,center)*1000})
    lines=list(member(sketch,"GetLines2",0) or [])
    return {"sketch_name":sketch_name,"circles":circles,"arc_count":arc_count,
            "lines_sha256":hashlib.sha256(json.dumps(lines).encode()).hexdigest(),
            "line_data_length":len(lines),
            "has_dimensions":member(feature,"GetFirstDisplayDimension") is not None,
            "relation_count":int(member(member(sketch,"RelationManager"),"GetRelationsCount",0))},feature,None


def _health(model):
    bodies=list(member(model,"GetBodies2",0,False) or [])
    return {"solid_count":len(bodies), "body_checks":[int(member(b,"Check2")) for b in bodies],
            "volume_mm3":sum(float(member(b,"GetMassProperties",1)[3])*1e9 for b in bodies)}


def _apply(model, feature, refs, radii_mm):
    member(model,"ClearSelection2",True)
    if not member(feature,"Select2",False,0):
        raise RuntimeError("无法选择草图")
    member(model,"EditSketch")
    manager=member(model,"SketchManager")
    active=member(manager,"ActiveSketch")
    if active is None or active._oleobj_ != member(feature,"GetSpecificFeature2")._oleobj_:
        raise RuntimeError("未进入目标草图")
    try:
        for item,radius in zip(refs,radii_mm):
            ref=item.get("reference")
            if ref is None:
                from .sw_connect import create_empty_dispatch_variant
                transform=list(member(member(member(active,"ModelToSketchTransform"),"Inverse"),"ArrayData"))
                c=[v/1000 for v in item["center_mm"]];r=item["radius_mm"]/1000
                for angle in (0,math.pi/2,math.pi,3*math.pi/2):
                    q=[c[0]+r*math.cos(angle),c[1]+r*math.sin(angle),c[2]]
                    point=[transform[12]*sum(q[j]*transform[j*3+i] for j in range(3))+transform[9+i] for i in range(3)]
                    member(model,"ClearSelection2",True)
                    ok=member(member(model,"Extension"),"SelectByID2","","SKETCHSEGMENT",
                              *point,False,0,create_empty_dispatch_variant(),0)
                    if not ok:continue
                    candidate=member(member(model,"SelectionManager"),"GetSelectedObject6",1,-1)
                    if candidate is None or int(member(candidate,"GetType")) != 1 or not member(candidate,"IsCircle"):
                        continue
                    owner=member(candidate,"GetSketch")
                    if owner._oleobj_ != active._oleobj_:continue
                    cp=member(candidate,"GetCenterPoint2")
                    xyz=[float(member(cp,n))*1000 for n in ("X","Y","Z")]
                    if math.dist(xyz,item["center_mm"]) > .001 or abs(float(member(candidate,"GetRadius"))*1000-item["radius_mm"]) > .001:
                        continue
                    if member(candidate,"ConstructionGeometry"):
                        raise ValueError("不支持构造圆")
                    ref=candidate;item["reference"]=ref;break
                if ref is None:raise RuntimeError("无法唯一选择目标完整圆")
            if not member(ref,"SetRadius",radius/1000):
                raise RuntimeError("SetRadius 返回失败")
    finally:
        member(manager,"InsertSketch",True)


def resize_sketch_circles(model, sketch_name, centers_mm, expected_radius_mm,
                          radius_mm, dry_run=True):
    """仅调整严格匹配的完整圆，保留圆心、圆实体与其他草图段。

    仅支持单配置无关系、无尺寸的二维草图。可用于投影图形或孔轮廓；不自动保存。
    失败时用原半径尝试恢复并验证；rollback_verified=false 要求立即停止。
    """
    if not math.isfinite(radius_mm) or radius_mm <= 0:
        raise ValueError("新半径必须为正有限数")
    if int(member(model,"GetType")) != 1 or len(member(model,"GetConfigurationNames") or []) != 1:
        raise ValueError("仅支持单配置零件")
    if member(member(model,"SketchManager"),"ActiveSketch") is not None:
        raise ValueError("请先退出草图编辑")
    before,feature,refs=_read(model,sketch_name)
    indices=match_circles(before["circles"],centers_mm,expected_radius_mm)
    health_before=_health(model)
    report={"success":True,"dry_run":dry_run,"before":before,"selected_indices":indices,
            "radius_mm":radius_mm,"health_before":health_before,"saved":False,"review_required":True}
    if dry_run:
        return report
    if before["has_dimensions"] or before["relation_count"]:
        raise ValueError("草图存在尺寸或关系，请使用尺寸编辑")
    if bool(member(model,"IsOpenedReadOnly")) or any(health_before["body_checks"]):
        raise ValueError("文档只读或实体检查失败")
    selected=[dict(before["circles"][i]) for i in indices]
    try:
        _apply(model,feature,selected,[radius_mm]*len(selected))
        rebuilt=bool(member(model,"EditRebuild3"))
        after,_,_=_read(model,sketch_name)
        match_circles(after["circles"],centers_mm,radius_mm)
        health=_health(model)
        if not rebuilt or any(health["body_checks"]) or health["solid_count"] != health_before["solid_count"]:
            raise RuntimeError("重建或实体检查失败")
        if before["lines_sha256"] != after["lines_sha256"] or before["arc_count"] != after["arc_count"]:
            raise RuntimeError("其他直线或圆弧数变化")
        expected=[dict(c) for c in before["circles"]]
        for i in indices: expected[i]["radius_mm"]=radius_mm
        for a,b in zip(expected,after["circles"]):
            if math.dist(a["center_mm"],b["center_mm"]) > .001 or abs(a["radius_mm"]-b["radius_mm"]) > .001:
                raise RuntimeError("其他圆或圆心发生变化")
        report.update(after=after,health_after=health,entities_preserved=True)
        return report
    except Exception as exc:
        rollback=False
        try:
            _apply(model,feature,selected,[before["circles"][i]["radius_mm"] for i in indices])
            member(model,"EditRebuild3")
            restored,_,_=_read(model,sketch_name)
            match_circles(restored["circles"],centers_mm,expected_radius_mm)
            health=_health(model)
            rollback=(not any(health["body_checks"]) and health["solid_count"]==health_before["solid_count"]
                      and abs(health["volume_mm3"]-health_before["volume_mm3"]) < 1e-4)
        except Exception:
            pass
        return {"success":False,"error":str(exc),"rollback_verified":rollback,"saved":False}
    finally:
        member(model,"ClearSelection2",True)
        member(model,"GraphicsRedraw2")
