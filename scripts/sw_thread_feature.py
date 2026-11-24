"""
原生“螺纹”特征（Insert > Features > Thread）与圆形边查找。

SolidWorks API：IFeatureManager.CreateDefinition(swFmSweepThread=87) 返回 IThreadFeatureData，
设置 Edge/Type/Size/ThreadMethod/EndCondition 等属性后由 IFeatureManager.CreateFeature 生成特征。
长度单位为米。导入几何体上 ICurve.IsCircle/CircleParams 可靠，本模块据此按圆心与半径定位起始边。
"""
import math

try:
    from .sw_connect import safe_get_com_member
except ImportError:
    from sw_connect import safe_get_com_member

SW_FM_SWEEP_THREAD = 87
SW_THREAD_METHOD = {"cut": 0, "extrude": 1}
SW_THREAD_END_CONDITION = {"blind": 0, "revolutions": 1, "up_to_selection": 2}
THREAD_TYPES = ("Metric Die", "Metric Tap", "Inch Die", "Inch Tap", "SP4xx Bottle", "SP4xx Bottle Lite")


def _call(obj, name, *args):
    """@brief 先标记为方法再调用，避免 pywin32 动态代理把方法当属性读取。"""
    flag = getattr(type(obj), "_FlagAsMethod", None)
    if flag is not None:
        flag(obj, name)
    return getattr(obj, name)(*args)


def _read_mm(obj, name):
    """@brief 读取以米为单位的数值属性并换算为毫米；属性不可读时返回 None。"""
    try:
        return round(float(getattr(obj, name)) * 1000.0, 6)
    except Exception:
        return None


def _created_size(feature, data):
    """@brief 读取已生成特征的规格名：优先取特征定义，取不到时取传入的数据对象。"""
    try:
        definition = _call(feature, "GetDefinition")
        if definition is not None:
            return str(safe_get_com_member(definition, "Size"))
    except Exception:
        pass
    return str(safe_get_com_member(data, "Size"))


def _numbers(values, count, label):
    values = tuple(float(v) for v in (values or ()))
    if len(values) < count or any(not math.isfinite(v) for v in values[:count]):
        raise ValueError(f"{label}: 需要 {count} 个有限数")
    return values[:count]


def iter_circular_edges(model):
    """
    @brief 遍历零件全部实体的边，产出圆形边及其参数。
    @param model 零件 IModelDoc2（IPartDoc）。
    @return 生成器，产出 dict：edge, center_m(3), axis(3), radius_m, body_index。
    """
    bodies = _call(model, "GetBodies2", 0, True) or []
    for body_index, body in enumerate(bodies):
        for edge in _call(body, "GetEdges") or []:
            curve = _call(edge, "GetCurve")
            if curve is None or not bool(_call(curve, "IsCircle")):
                continue
            params = _numbers(safe_get_com_member(curve, "CircleParams"), 7, "CircleParams")
            yield {
                "edge": edge,
                "body_index": body_index,
                "center_m": params[0:3],
                "axis": params[3:6],
                "radius_m": params[6],
            }


def list_circular_edges(model, radius_m=None, radius_tolerance_m=5e-5, limit=500):
    """
    @brief 只读列出圆形边（圆心、轴向、半径，单位毫米）。
    @param radius_m 可选半径过滤，米。
    @return dict：matched 为匹配总数，rows 为前 limit 行。
    """
    rows, matched = [], 0
    for item in iter_circular_edges(model):
        if radius_m is not None and abs(item["radius_m"] - radius_m) > radius_tolerance_m:
            continue
        matched += 1
        if len(rows) < limit:
            rows.append({
                "body_index": item["body_index"],
                "center_mm": [round(v * 1000.0, 4) for v in item["center_m"]],
                "axis": [round(v, 6) for v in item["axis"]],
                "diameter_mm": round(item["radius_m"] * 2000.0, 4),
            })
    return {"matched": matched, "rows": rows}


def find_circular_edge(model, center_m, radius_m, tolerance_m=5e-5):
    """
    @brief 按圆心与半径找到唯一圆形边。
    @raise RuntimeError 没有匹配或匹配多于一个。
    """
    center = _numbers(center_m, 3, "center")
    hits = [
        item for item in iter_circular_edges(model)
        if abs(item["radius_m"] - radius_m) <= tolerance_m
        and all(abs(a - b) <= tolerance_m for a, b in zip(item["center_m"], center))
    ]
    if len(hits) != 1:
        raise RuntimeError(f"圆形边应唯一：圆心 {[round(v * 1000, 3) for v in center]} mm、半径 {radius_m * 1000:.3f} mm 匹配 {len(hits)} 条")
    return hits[0]


def body_volume_m3(model):
    """@brief 全部实体体积之和（IBody2.GetMassProperties 第 4 项），米³。"""
    total = 0.0
    for body in _call(model, "GetBodies2", 0, True) or []:
        props = _numbers(_call(body, "GetMassProperties", 1.0), 4, "GetMassProperties")
        total += props[3]
    return total


def count_faces(model):
    """@brief 全部实体的面数。"""
    return sum(len(_call(body, "GetFaces") or []) for body in (_call(model, "GetBodies2", 0, True) or []))


def add_thread_feature(model, edge, *, thread_type, size, method="cut", end_condition="blind", depth_m=None,
                       revolutions=None, reverse_direction=False, right_handed=True, trim_start_face=True,
                       trim_end_face=True, offset_m=0.0, start_angle_deg=0.0, feature_name=None,
                       pitch_m=None, diameter_m=None):
    """
    @brief 在圆形边上创建原生螺纹特征并回读体积与面数变化。
    @param model 零件 IModelDoc2。
    @param edge 起始圆形边（IEdge）。
    @param thread_type 螺纹库名称，例如 "Metric Die"（外螺纹）或 "Metric Tap"（内螺纹）。
    @param size 库中的规格名，例如 "M10x1.5"；库中没有该规格时报错，不回落到其他规格。
    @param method "cut" 或 "extrude"。
    @param end_condition "blind"（需 depth_m）或 "revolutions"（需 revolutions）。
    @param pitch_m 可选：覆盖库规格的螺距，米（库中没有的螺距，如每英寸 36 牙）。
    @param diameter_m 可选：覆盖库规格的螺纹直径，米。
    @return dict：feature_name、size、pitch_mm、diameter_mm、volume_before/after_m3、face_count_before/after。
    @raise ValueError 参数无效或库中没有该规格。
    @raise RuntimeError 特征未创建（附 GetCreateFeatureErrors 信息）。
    """
    if method not in SW_THREAD_METHOD:
        raise ValueError("method 必须是 cut 或 extrude")
    for label, value in (("pitch_m", pitch_m), ("diameter_m", diameter_m)):
        if value is not None and not (math.isfinite(float(value)) and float(value) > 0):
            raise ValueError(f"{label} 必须是正的有限数")
    if end_condition not in ("blind", "revolutions"):
        raise ValueError("end_condition 必须是 blind 或 revolutions")
    if end_condition == "blind" and not (depth_m and depth_m > 0):
        raise ValueError("blind 需要正的 depth_m")
    if end_condition == "revolutions" and not (revolutions and revolutions > 0):
        raise ValueError("revolutions 需要正的圈数")
    volume_before = body_volume_m3(model)
    faces_before = count_faces(model)
    feature_manager = safe_get_com_member(model, "FeatureManager")
    data = _call(feature_manager, "CreateDefinition", SW_FM_SWEEP_THREAD)
    if data is None:
        raise RuntimeError("CreateDefinition(swFmSweepThread) 返回空")
    _call(data, "InitializeThreadData")
    data.Edge = edge
    data.Type = str(thread_type)
    data.Size = str(size)
    applied_size = str(safe_get_com_member(data, "Size"))
    if applied_size != str(size):
        raise ValueError(f"螺纹库 {thread_type} 中没有规格 {size}（库回落到 {applied_size}）")
    if diameter_m is not None:
        data.DiameterOverride = True
        data.Diameter = float(diameter_m)
    if pitch_m is not None:
        data.PitchOverride = True
        data.Pitch = float(pitch_m)
    data.ThreadMethod = SW_THREAD_METHOD[method]
    data.EndCondition = SW_THREAD_END_CONDITION[end_condition]
    if end_condition == "blind":
        data.BlindDepth = float(depth_m)
    else:
        data.Revolutions = float(revolutions)
    data.ReverseDirection = bool(reverse_direction)
    data.RightHanded = bool(right_handed)
    data.TrimStartFace = bool(trim_start_face)
    data.TrimEndFace = bool(trim_end_face)
    data.Offset = bool(offset_m)
    if offset_m:
        data.OffsetDistance = float(offset_m)
    data.ThreadStartAngle = math.radians(float(start_angle_deg))
    feature = _call(feature_manager, "CreateFeature", data)
    if feature is None:
        detail = ""
        try:
            detail = f"; 错误: {_call(feature_manager, 'GetCreateFeatureErrors', None, None)}"
        except Exception:
            pass
        raise RuntimeError(f"螺纹特征未创建（{thread_type} {size}）{detail}")
    created_size = _created_size(feature, data)
    if created_size != str(size):
        # SOLIDWORKS 2026 实测：库中没有该规格时赋值 Size 不报错，生成特征时才回落到库的第一个规格。
        # 错误特征必须删除并核对几何已复原，否则模型里会留下规格不符的螺纹。
        wrong = str(safe_get_com_member(feature, "Name"))
        if not _call(feature, "Select2", False, 0):
            raise RuntimeError(f"螺纹库 {thread_type} 中没有规格 {size}（生成时回落到 {created_size}），错误特征 {wrong} 无法选中，仍留在模型中")
        _call(model, "EditDelete")
        _call(model, "ForceRebuild3", False)
        volume_now = body_volume_m3(model)
        if count_faces(model) != faces_before or abs(volume_now - volume_before) > 1e-9 * max(abs(volume_before), 1e-12):
            raise RuntimeError(f"螺纹库 {thread_type} 中没有规格 {size}（生成时回落到 {created_size}），错误特征 {wrong} 未能删除")
        raise ValueError(f"螺纹库 {thread_type} 中没有规格 {size}（生成时回落到 {created_size}，特征已删除）")
    if feature_name:
        feature.Name = str(feature_name)
    _call(model, "ForceRebuild3", False)
    return {
        "feature_name": str(safe_get_com_member(feature, "Name")),
        "type": str(safe_get_com_member(data, "Type")),
        "size": str(safe_get_com_member(data, "Size")),
        "pitch_mm": _read_mm(data, "Pitch"),
        "diameter_mm": _read_mm(data, "Diameter"),
        "volume_before_m3": volume_before,
        "volume_after_m3": body_volume_m3(model),
        "face_count_before": faces_before,
        "face_count_after": count_faces(model),
    }
