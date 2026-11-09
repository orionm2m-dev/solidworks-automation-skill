"""
刚体变换的纯数学工具，不依赖 COM。

SolidWorks MathTransform.ArrayData 采用行向量约定：p' = p·R + t。
R 的第 i 行就是组件局部第 i 根坐标轴在装配体坐标系中的方向，
因此调用方只需给出局部 X/Y/Z 轴方向和原点位置即可，无需记忆矩阵排列。
"""
import math

AXIS_TOLERANCE = 1e-6


def _vector3(name, values):
    """
    @brief 校验并转换三维向量。
    @param name 参数名，用于错误信息。
    @param values 可迭代数值。
    @return 三元组 float。
    @raise ValueError 长度不是 3 或含非有限数。
    """
    vector = tuple(float(v) for v in values)
    if len(vector) != 3 or not all(math.isfinite(v) for v in vector):
        raise ValueError(f"{name} 必须是 3 个有限数")
    return vector


def _dot(a, b):
    """@brief 向量点积。"""
    return sum(p * q for p, q in zip(a, b))


def _cross(a, b):
    """@brief 向量叉积。"""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def build_rigid_transform_data(x_axis, y_axis, z_axis, origin_m, tolerance=AXIS_TOLERANCE):
    """
    @brief 由组件局部坐标轴方向和原点位置生成 MathTransform 数组。
    @param x_axis 组件局部 X 轴在装配体坐标系中的单位向量。
    @param y_axis 组件局部 Y 轴单位向量。
    @param z_axis 组件局部 Z 轴单位向量，必须等于 x_axis × y_axis。
    @param origin_m 组件原点在装配体坐标系中的位置，单位米。
    @param tolerance 单位长度、正交与右手系判定容差。
    @return 16 元组，可赋给 MathTransform.ArrayData。
    @raise ValueError 轴不是单位向量、互不正交或构成左手系（镜像）。
    """
    axes = [_vector3(name, axis) for name, axis in (("x_axis", x_axis), ("y_axis", y_axis), ("z_axis", z_axis))]
    for name, axis in zip(("x_axis", "y_axis", "z_axis"), axes):
        if abs(math.sqrt(_dot(axis, axis)) - 1.0) > tolerance:
            raise ValueError(f"{name} 不是单位向量")
    for (name_a, a), (name_b, b) in (
        (("x_axis", axes[0]), ("y_axis", axes[1])),
        (("y_axis", axes[1]), ("z_axis", axes[2])),
        (("x_axis", axes[0]), ("z_axis", axes[2])),
    ):
        if abs(_dot(a, b)) > tolerance:
            raise ValueError(f"{name_a} 与 {name_b} 不正交")
    if any(abs(c - z) > tolerance for c, z in zip(_cross(axes[0], axes[1]), axes[2])):
        raise ValueError("z_axis 必须等于 x_axis × y_axis（右手系，不允许镜像）")
    origin = _vector3("origin", origin_m)
    return (*axes[0], *axes[1], *axes[2], *origin, 1.0, 0.0, 0.0, 0.0)


def transform_matches(actual, expected, rotation_tolerance=1e-7, translation_tolerance_m=1e-7):
    """
    @brief 比较回读的 ArrayData 与目标是否一致（只比较旋转与平移）。
    @param actual 回读的 ArrayData。
    @param expected 目标 ArrayData。
    @return True 表示一致。
    """
    actual = tuple(float(v) for v in actual)
    expected = tuple(float(v) for v in expected)
    if len(actual) < 12 or len(expected) < 12:
        return False
    rotation_ok = all(abs(a - b) <= rotation_tolerance for a, b in zip(actual[:9], expected[:9]))
    translation_ok = all(abs(a - b) <= translation_tolerance_m for a, b in zip(actual[9:12], expected[9:12]))
    return rotation_ok and translation_ok
