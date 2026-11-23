"""二维工程图：DWG/DXF 导入为原生工程图，读取页内注释与草图实体，按严格规格编辑并导出全部页 PDF。

用于电气原理图、安装图、明细表一类不依赖三维模型的图纸。所有写操作先 dry_run 解析匹配数量，
匹配数与 expected_count 不符时在修改文档前中止；不覆盖已有输出。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Point = tuple[float, float]

# swLineWeights_e / swLineStyles_e / swTextJustification_e。
WEIGHTS = {'normal': 0, 'thin': 1, 'thick': 2, 'thick2': 3, 'thick3': 4, 'thick4': 5}
STYLES = {'continuous': 0, 'hidden': 1, 'phantom': 2, 'chain': 3, 'center': 4}
JUSTIFY = {'left': 1, 'center': 2, 'right': 3}
DRAWING_EXTS = {'.dwg', '.dxf'}
PICTURE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


def _absolute(value, suffixes):
    from scripts.sw_operation_guard import absolute_document_path
    if not absolute_document_path(value) or Path(value).suffix.lower() not in suffixes:
        raise ValueError(f'absolute path with suffix {sorted(suffixes)} required: {value}')
    return value


class Pen(Strict):
    weight: Literal['normal', 'thin', 'thick', 'thick2', 'thick3', 'thick4'] | None = None
    style: Literal['continuous', 'hidden', 'phantom', 'chain', 'center'] | None = None
    color_rgb: tuple[int, int, int] | None = None

    @field_validator('color_rgb')
    @classmethod
    def color_range(cls, value):
        if value is not None and not all(0 <= c <= 255 for c in value):
            raise ValueError('color_rgb components must be 0..255')
        return value


class LineOp(Pen):
    points_mm: tuple[Point, Point]


class PolylineOp(Pen):
    points_mm: list[Point] = Field(min_length=2, max_length=200)
    closed: bool = False


class CircleOp(Pen):
    center_mm: Point
    radius_mm: float = Field(gt=0, le=500)


class ArcOp(Pen):
    center_mm: Point
    start_mm: Point
    end_mm: Point
    counterclockwise: bool = True

    @model_validator(mode='after')
    def same_radius(self):
        r1 = math.dist(self.center_mm, self.start_mm)
        r2 = math.dist(self.center_mm, self.end_mm)
        if r1 <= 0 or abs(r1 - r2) > 0.01:
            raise ValueError('arc start and end must lie on one circle around center')
        return self


class NoteOp(Strict):
    text: str = Field(min_length=1, max_length=2000)
    position_mm: Point
    height_mm: float = Field(default=2.5, gt=0, le=20)
    angle_deg: float = Field(default=0, ge=-360, le=360)
    font: str | None = Field(default=None, min_length=1, max_length=64)
    bold: bool = False
    italic: bool = False
    width_factor: float | None = Field(default=None, gt=0, le=5)
    line_spacing_mm: float | None = Field(default=None, gt=0, le=20)
    justify: Literal['left', 'center', 'right'] = 'left'


class TextMatch(Strict):
    match: str = Field(min_length=1, max_length=2000)
    contains: bool = False
    expected_count: int = Field(default=1, ge=1, le=500)
    # 只在此框内（注释插入点，图纸毫米坐标 x1, y1, x2, y2）匹配；同一张图纸上有多个图框时必用。
    box_mm: tuple[float, float, float, float] | None = None

    @model_validator(mode='after')
    def ordered_box(self):
        if self.box_mm is not None:
            x1, y1, x2, y2 = self.box_mm
            if not (x1 < x2 and y1 < y2):
                raise ValueError('box_mm must be x1 < x2 and y1 < y2')
        return self


class ReplaceTextOp(TextMatch):
    new_text: str = Field(min_length=1, max_length=2000)


class DeleteInBoxOp(Strict):
    box_mm: tuple[float, float, float, float]
    notes: bool = True
    segments: bool = True
    max_count: int = Field(default=200, ge=1, le=5000)

    @model_validator(mode='after')
    def ordered(self):
        x1, y1, x2, y2 = self.box_mm
        if not (x1 < x2 and y1 < y2):
            raise ValueError('box_mm must be x1 < x2 and y1 < y2')
        return self


class PictureOp(Strict):
    path: str
    origin_mm: Point
    width_mm: float = Field(gt=0, le=2000)
    height_mm: float | None = Field(default=None, gt=0, le=2000)

    @field_validator('path')
    @classmethod
    def picture_path(cls, value):
        return _absolute(value, PICTURE_EXTS)


class SheetEdit(Strict):
    sheet: str = Field(min_length=1, max_length=80)
    create_size_mm: tuple[float, float] | None = None
    rename_to: str | None = Field(default=None, min_length=1, max_length=80)
    explode_blocks: bool = False
    delete_in_box: list[DeleteInBoxOp] = Field(default_factory=list, max_length=50)
    delete_notes: list[TextMatch] = Field(default_factory=list, max_length=200)
    replace_text: list[ReplaceTextOp] = Field(default_factory=list, max_length=500)
    lines: list[LineOp] = Field(default_factory=list, max_length=3000)
    polylines: list[PolylineOp] = Field(default_factory=list, max_length=500)
    circles: list[CircleOp] = Field(default_factory=list, max_length=1000)
    arcs: list[ArcOp] = Field(default_factory=list, max_length=1000)
    notes: list[NoteOp] = Field(default_factory=list, max_length=1500)
    pictures: list[PictureOp] = Field(default_factory=list, max_length=10)

    @field_validator('create_size_mm')
    @classmethod
    def sheet_size(cls, value):
        if value is not None and not all(50 <= v <= 2000 for v in value):
            raise ValueError('Unsupported sheet size')
        return value


class DrawingEdit2D(Strict):
    save_as: str | None = None
    pdf_path: str | None = None
    overwrite_pdf: bool = False
    sheets: list[SheetEdit] = Field(min_length=1, max_length=20)

    @field_validator('save_as')
    @classmethod
    def save_path(cls, value):
        return value if value is None else _absolute(value, {'.slddrw'})

    @field_validator('pdf_path')
    @classmethod
    def pdf(cls, value):
        return value if value is None else _absolute(value, {'.pdf'})

    @model_validator(mode='after')
    def unique_sheets(self):
        names = [s.sheet.casefold() for s in self.sheets]
        if len(set(names)) != len(names):
            raise ValueError('Duplicate sheet entry')
        return self


def load_edit(path):
    """读取严格编辑规格，不接受任意代码。"""
    return DrawingEdit2D.model_validate_json(Path(path).read_text(encoding='utf-8-sig'))


# ---------- 纯函数（无 COM，可单测） ----------

def normalize_text(value):
    """统一换行与首尾空白，便于与导入文字比较。"""
    return '\n'.join(line.strip() for line in str(value).replace('\r\n', '\n').replace('\r', '\n').split('\n')).strip()


def text_matches(text, op):
    """精确或包含匹配；比较前统一换行与空白。"""
    have, want = normalize_text(text), normalize_text(op.match)
    return want in have if op.contains else have == want


def note_position_in_box(position_mm, op):
    """注释插入点在操作的 box_mm 内；未给 box_mm 时总为真。"""
    if op.box_mm is None:
        return True
    return bool(position_mm) and inside_box([tuple(position_mm)], op.box_mm)


def inside_box(points_mm, box_mm, tol=1e-6):
    """全部点在框内（含边界）才算在框内。"""
    x1, y1, x2, y2 = box_mm
    return all(x1 - tol <= x <= x2 + tol and y1 - tol <= y <= y2 + tol for x, y in points_mm)


def rgb_to_ref(rgb):
    """RGB → Windows COLORREF（0x00BBGGRR）。"""
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


def polyline_segments(op):
    pts = list(op.points_mm)
    if op.closed:
        pts.append(pts[0])
    return list(zip(pts[:-1], pts[1:]))


# ---------- COM ----------

def _m(value):
    return float(value) / 1000.0


def _mm(value):
    return round(float(value) * 1000.0, 3)


def _sheet_names(draw):
    from scripts.sw_connect import get_com_member as get
    return [str(n) for n in (get(draw, 'GetSheetNames') or [])]


def _activate_sheet(draw, name):
    from scripts.sw_connect import get_com_member as get
    if name not in _sheet_names(draw):
        raise ValueError(f'Unknown sheet {name!r}; sheets={_sheet_names(draw)}')
    if str(get(get(draw, 'GetCurrentSheet'), 'GetName')) != name:
        if not draw.ActivateSheet(name):
            raise RuntimeError(f'ActivateSheet failed: {name}')
    draw.EditSheet()
    draw.ClearSelection2(True)


def _views(draw):
    """当前页的图纸视图（第一个）及其后的工程视图。"""
    from scripts.sw_connect import get_com_member as get
    out = []
    v = get(draw, 'GetFirstView')
    while v is not None:
        out.append(v)
        v = get(v, 'GetNextView')
    return out


def _view_notes(view):
    from scripts.sw_connect import get_com_member as get
    notes = []
    n = get(view, 'GetFirstNote')
    while n is not None:
        notes.append(n)
        n = get(n, 'GetNext')
    return notes


def _note_record(note, view_name):
    from scripts.sw_connect import get_com_member as get
    ann = get(note, 'GetAnnotation')
    rec = {'view': view_name, 'text': str(get(note, 'GetText') or '')}
    try:
        pos = list(get(ann, 'GetPosition') or [])
        rec['position_mm'] = [_mm(pos[0]), _mm(pos[1])] if len(pos) >= 2 else None
    except Exception as exc:  # noqa: BLE001
        rec['position_error'] = str(exc)
    try:
        ext = list(get(note, 'GetExtent') or [])
        if len(ext) >= 5:
            rec['extent_mm'] = [_mm(ext[0]), _mm(ext[1]), _mm(ext[3]), _mm(ext[4])]
    except Exception:  # noqa: BLE001
        pass
    try:
        rec['angle_deg'] = round(math.degrees(float(get(note, 'Angle'))), 3)
    except Exception:  # noqa: BLE001
        pass
    try:
        fmt = ann.GetTextFormat(0)
        rec['height_mm'] = _mm(fmt.CharHeight)
        rec['font'] = str(fmt.TypeFaceName)
        rec['italic'] = bool(fmt.Italic)
        rec['bold'] = bool(fmt.Bold)
        rec['width_factor'] = round(float(fmt.WidthFactor), 5)
        rec['line_spacing_mm'] = _mm(fmt.LineSpacing)
    except Exception:  # noqa: BLE001
        pass
    try:
        rec['layer'] = str(get(ann, 'Layer') or '')
    except Exception:  # noqa: BLE001
        pass
    return rec


def _point_mm(p):
    from scripts.sw_connect import get_com_member as get
    return (_mm(get(p, 'X')), _mm(get(p, 'Y')))


def _segment_record(seg):
    """线段与圆弧给出坐标；其余类型只给类型码。"""
    from scripts.sw_connect import get_com_member as get
    kind = int(get(seg, 'GetType'))
    rec = {'type': {0: 'line', 1: 'arc', 2: 'ellipse', 3: 'spline', 4: 'text', 5: 'parabola'}.get(kind, str(kind))}
    try:
        if kind == 0:
            rec['points_mm'] = [_point_mm(get(seg, 'GetStartPoint2')), _point_mm(get(seg, 'GetEndPoint2'))]
        elif kind == 1:
            c = _point_mm(get(seg, 'GetCenterPoint2'))
            r = _mm(get(seg, 'GetRadius'))
            rec.update(center_mm=c, radius_mm=r,
                       points_mm=[(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
    except Exception as exc:  # noqa: BLE001
        rec['error'] = str(exc)
    for name in ('Layer', 'Width', 'Style', 'Color', 'ConstructionGeometry'):
        try:
            rec[name.lower()] = get(seg, name)
        except Exception:  # noqa: BLE001
            pass
    return rec


def _sheet_segments(view):
    from scripts.sw_connect import get_com_member as get
    sketch = get(view, 'GetSketch')
    if sketch is None:
        return []
    return list(get(sketch, 'GetSketchSegments') or [])


def _block_definitions(draw):
    from scripts.sw_connect import get_com_member as get
    sm = get(draw, 'SketchManager')
    out = []
    for d in list(get(sm, 'GetSketchBlockDefinitions') or []):
        rec = {'name': '', 'instances': 0, 'notes': []}
        try:
            rec['name'] = str(get(d, 'Name') or get(d, 'FileName') or '')
        except Exception:  # noqa: BLE001
            pass
        try:
            rec['instances'] = len(list(get(d, 'GetInstances') or []))
        except Exception:  # noqa: BLE001
            pass
        try:
            rec['notes'] = [str(get(n, 'GetText') or '') for n in list(get(d, 'GetNotes') or [])]
        except Exception:  # noqa: BLE001
            pass
        out.append((d, rec))
    return out


def inspect_2d(draw, output_path, sheet=None, max_segments_per_sheet=20000):
    """只读：每页尺寸、视图、注释（文字、位置、范围、角度、字高、字体）、草图实体与块。"""
    from scripts.sw_connect import get_com_member as get
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    out = Path(output_path)
    if out.suffix.lower() != '.json':
        raise ValueError('output_path must be .json')
    current = str(get(get(draw, 'GetCurrentSheet'), 'GetName'))
    names = _sheet_names(draw)
    targets = [sheet] if sheet else names
    report = {'status': 'inspected', 'read_only': True, 'document': str(get(draw, 'GetPathName')),
              'sheet_names': names, 'sheets': []}
    try:
        for name in targets:
            _activate_sheet(draw, name)
            sh = get(draw, 'GetCurrentSheet')
            props = list(get(sh, 'GetProperties2') or [])
            rec = {'name': name, 'size_mm': [_mm(props[5]), _mm(props[6])] if len(props) > 6 else None,
                   'views': [], 'notes': [], 'segments': [], 'segment_types': {}}
            for i, v in enumerate(_views(draw)):
                vname = str(get(v, 'GetName2'))
                vrec = {'name': vname, 'sheet_view': i == 0}
                try:
                    vrec['outline_mm'] = [_mm(x) for x in list(get(v, 'GetOutline') or [])]
                    vrec['scale'] = float(get(v, 'ScaleDecimal'))
                except Exception:  # noqa: BLE001
                    pass
                rec['views'].append(vrec)
                rec['notes'].extend(_note_record(n, vname) for n in _view_notes(v))
                segs = _sheet_segments(v)
                vrec['segment_count'] = len(segs)
                for seg in segs[:max_segments_per_sheet]:
                    s = _segment_record(seg)
                    s['view'] = vname
                    rec['segments'].append(s)
                    rec['segment_types'][s['type']] = rec['segment_types'].get(s['type'], 0) + 1
                if len(segs) > max_segments_per_sheet:
                    rec['segments_truncated'] = len(segs) - max_segments_per_sheet
            report['sheets'].append(rec)
        report['blocks'] = [rec for _, rec in _block_definitions(draw)]
    finally:
        if current in names:
            draw.ActivateSheet(current)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    summary = {'status': 'inspected', 'output_path': str(out), 'sheet_names': names,
               'blocks': len(report['blocks']),
               'sheets': [{'name': s['name'], 'size_mm': s['size_mm'], 'views': len(s['views']),
                           'notes': len(s['notes']), 'segment_types': s['segment_types'],
                           'segments_truncated': s.get('segments_truncated', 0)} for s in report['sheets']]}
    return summary


def import_dwg(sw, source_path, output_path, *, import_method=None, dry_run=True):
    """DWG/DXF → 新的原生工程图并保存为 SLDDRW；源文件只读，不覆盖输出。"""
    import pythoncom
    from win32com.client import VARIANT, dynamic
    from scripts.sw_connect import get_com_member as get, create_empty_dispatch_variant
    src = Path(source_path)
    _absolute(str(src), DRAWING_EXTS)
    _absolute(str(output_path), {'.slddrw'})
    out = Path(output_path)
    if not src.is_file():
        raise FileNotFoundError(src)
    if out.exists():
        raise FileExistsError(out)
    data = sw.GetImportFileData(str(src))
    if data is None:
        raise RuntimeError(f'GetImportFileData returned nothing for {src}')
    options = {}
    for name in ('ImportMethod', 'LengthUnit', 'SheetName', 'ImportDimensions', 'ImportHatch', 'AddSketchConstraints'):
        try:
            options[name] = get(data, name, '')
        except Exception as exc:  # noqa: BLE001
            options[name] = f'error: {exc}'
    if dry_run:
        return {'status': 'ready', 'source_path': str(src), 'output_path': str(out),
                'default_import_options': options, 'import_method_requested': import_method}
    if import_method is not None:
        data.SetImportMethod('', int(import_method))
        options['ImportMethod_after_set'] = get(data, 'ImportMethod', '')
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        model = sw.LoadFile4(str(src), '', data, errors)
    except TypeError:
        dyn = dynamic.DumbDispatch(sw._oleobj_, 'SldWorks.Application')
        model = dyn.LoadFile4(str(src), '', data, errors)
    if model is None:
        raise RuntimeError(f'LoadFile4 failed: error={errors.value}, options={options}')
    doc_type = int(get(model, 'GetType'))
    result = {'status': 'imported', 'source_path': str(src), 'load_error': errors.value,
              'import_options': options, 'document_type': doc_type, 'title': str(get(model, 'GetTitle'))}
    if doc_type != 3:
        result['status'] = 'not_a_drawing'
        return result
    out.parent.mkdir(parents=True, exist_ok=True)
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    if not model.Extension.SaveAs(str(out), 0, 1, create_empty_dispatch_variant(), err, warn) or err.value:
        raise RuntimeError(f'SaveAs failed: {err.value}, {warn.value}')
    result.update(drawing_path=str(get(model, 'GetPathName')), save_warnings=warn.value,
                  sheet_names=_sheet_names(model))
    return result


def _apply_pen(seg, pen):
    from scripts.sw_connect import get_com_member as get
    applied = {}
    if pen.weight is not None:
        seg.Width = WEIGHTS[pen.weight]
        applied['width'] = get(seg, 'Width')
    if pen.style is not None:
        seg.Style = STYLES[pen.style]
        applied['style'] = get(seg, 'Style')
    if pen.color_rgb is not None:
        seg.Color = rgb_to_ref(pen.color_rgb)
        applied['color'] = get(seg, 'Color')
    return applied


def _resolve(draw, sheet_edit):
    """解析匹配：各注释操作的命中、框内实体；不修改文档。"""
    from scripts.sw_connect import get_com_member as get
    _activate_sheet(draw, sheet_edit.sheet)
    notes = []
    for v in _views(draw):
        notes.extend(_view_notes(v))
    texts = [str(get(n, 'GetText') or '') for n in notes]
    positions = [_note_position(n) for n in notes]
    plan = {'sheet': sheet_edit.sheet, 'notes_on_sheet': len(notes), 'replace_text': [], 'delete_notes': [], 'delete_in_box': []}
    problems = []
    for kind, ops in (('replace_text', sheet_edit.replace_text), ('delete_notes', sheet_edit.delete_notes)):
        for op in ops:
            hits = [i for i, t in enumerate(texts) if text_matches(t, op) and note_position_in_box(positions[i], op)]
            plan[kind].append({'match': op.match, 'box_mm': op.box_mm, 'found': len(hits), 'expected': op.expected_count,
                               'positions_mm': [positions[i] for i in hits][:20]})
            if len(hits) != op.expected_count:
                problems.append(f'{kind} {op.match!r}: found {len(hits)}, expected {op.expected_count}')
    sheet_view = _views(draw)[0]
    segs = _sheet_segments(sheet_view)
    for op in sheet_edit.delete_in_box:
        n_hits = [n for n in notes if _note_in_box(n, op.box_mm)] if op.notes else []
        s_hits = [s for s in segs if _segment_in_box(s, op.box_mm)] if op.segments else []
        plan['delete_in_box'].append({'box_mm': op.box_mm, 'notes': len(n_hits), 'segments': len(s_hits)})
        if len(n_hits) + len(s_hits) > op.max_count:
            problems.append(f'delete_in_box {op.box_mm}: {len(n_hits) + len(s_hits)} > max_count {op.max_count}')
    return notes, texts, segs, plan, problems


def _note_position(note):
    from scripts.sw_connect import get_com_member as get
    try:
        pos = list(get(get(note, 'GetAnnotation'), 'GetPosition') or [])
        return [_mm(pos[0]), _mm(pos[1])] if len(pos) >= 2 else None
    except Exception:  # noqa: BLE001
        return None


def _note_in_box(note, box):
    from scripts.sw_connect import get_com_member as get
    try:
        ext = list(get(note, 'GetExtent') or [])
        pts = [(_mm(ext[0]), _mm(ext[1])), (_mm(ext[3]), _mm(ext[4]))]
    except Exception:  # noqa: BLE001
        pos = list(get(get(note, 'GetAnnotation'), 'GetPosition'))
        pts = [(_mm(pos[0]), _mm(pos[1]))]
    return inside_box(pts, box)


def _segment_in_box(seg, box):
    rec = _segment_record(seg)
    return bool(rec.get('points_mm')) and inside_box(rec['points_mm'], box)


def edit_2d(sw, draw, spec, dry_run=True):
    """按规格编辑当前工程图各页；dry_run 只解析匹配，不符即中止。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as get, create_empty_dispatch_variant
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    if spec.pdf_path and Path(spec.pdf_path).exists() and not spec.overwrite_pdf:
        raise FileExistsError(spec.pdf_path)
    current_path = str(get(draw, 'GetPathName') or '')
    if spec.save_as and Path(spec.save_as).exists() and Path(spec.save_as).resolve() != Path(current_path or '.').resolve():
        raise FileExistsError(spec.save_as)
    if not spec.save_as and not current_path:
        raise ValueError('Unsaved drawing requires save_as')
    names = _sheet_names(draw)
    plans, problems = [], []
    for se in spec.sheets:
        if se.create_size_mm is not None:
            if se.sheet in names:
                problems.append(f'sheet {se.sheet!r} already exists')
            plans.append({'sheet': se.sheet, 'create_size_mm': se.create_size_mm})
            continue
        if se.sheet not in names:
            problems.append(f'unknown sheet {se.sheet!r}; sheets={names}')
            continue
        *_, plan, sheet_problems = _resolve(draw, se)
        plans.append(plan)
        problems.extend(sheet_problems)
    if problems or dry_run:
        return {'status': 'blocked' if problems else 'ready', 'problems': problems, 'plans': plans,
                'sheet_names': names, 'document': current_path}
    null = create_empty_dispatch_variant()
    results = []
    for se in spec.sheets:
        res = {'sheet': se.sheet}
        if se.create_size_mm is not None:
            w, h = se.create_size_mm
            if not draw.NewSheet3(se.sheet, 12, 13, 1., 1., True, '', w / 1000, h / 1000, ''):
                raise RuntimeError(f'NewSheet3 failed: {se.sheet}')
            res['created'] = True
        _activate_sheet(draw, se.sheet)
        sm = get(draw, 'SketchManager')
        if se.explode_blocks:
            exploded = 0
            for d, _rec in _block_definitions(draw):
                for inst in list(get(d, 'GetInstances') or []):
                    if sm.ExplodeSketchBlockInstance(inst):
                        exploded += 1
            res['exploded_blocks'] = exploded
        notes, texts, segs, _plan, again = _resolve(draw, se)
        if again:
            raise RuntimeError(f'Matches changed before edit: {again}')
        # 删除：框内实体与匹配注释一次选中后删除。
        draw.ClearSelection2(True)
        selected = 0
        targets = set()
        for op in se.delete_in_box:
            if op.notes:
                targets.update(i for i, n in enumerate(notes) if _note_in_box(n, op.box_mm))
            if op.segments:
                for s in segs:
                    if _segment_in_box(s, op.box_mm) and s.Select4(True, null):
                        selected += 1
        for op in se.delete_notes:
            targets.update(i for i, t in enumerate(texts)
                           if text_matches(t, op) and note_position_in_box(_note_position(notes[i]), op))
        selected_segments = selected
        selected_notes = 0
        for i in sorted(targets):
            ann = get(notes[i], 'GetAnnotation')
            # Select3 с пустым SelectData у надписей листа возвращает False; Select2(append, mark) работает.
            if ann.Select2(True, 0):
                selected_notes += 1
        if selected_notes != len(targets):
            draw.ClearSelection2(True)
            raise RuntimeError(f'delete: selected {selected_notes} of {len(targets)} notes; nothing changed')
        selected = selected_segments + selected_notes
        if selected:
            draw.EditDelete()
        res['deleted'] = selected
        # 改字：删除后重新取注释，避免失效引用。
        replaced = []
        if se.replace_text:
            notes2 = []
            for v in _views(draw):
                notes2.extend(_view_notes(v))
            for op in se.replace_text:
                hits = [n for n in notes2 if text_matches(str(get(n, 'GetText') or ''), op)
                        and note_position_in_box(_note_position(n), op)]
                if len(hits) != op.expected_count:
                    raise RuntimeError(f'replace {op.match!r}: found {len(hits)} after deletes, expected {op.expected_count}')
                ok = [bool(n.SetText(op.new_text)) for n in hits]
                replaced.append({'match': op.match, 'replaced': sum(ok), 'new_text': op.new_text})
        res['replaced'] = replaced
        # 绘制：图纸草图（非图框模板），不吸附。
        draw.ClearSelection2(True)
        draw.EditSheet()
        sm.AddToDB = True
        pens = []
        try:
            def line(a, b, pen):
                seg = sm.CreateLine(_m(a[0]), _m(a[1]), 0, _m(b[0]), _m(b[1]), 0)
                if seg is None:
                    raise RuntimeError(f'CreateLine failed {a}->{b}')
                pens.append(_apply_pen(seg, pen))
            for op in se.lines:
                line(*op.points_mm, op)
            for op in se.polylines:
                for a, b in polyline_segments(op):
                    line(a, b, op)
            for op in se.circles:
                seg = sm.CreateCircleByRadius(_m(op.center_mm[0]), _m(op.center_mm[1]), 0, _m(op.radius_mm))
                if seg is None:
                    raise RuntimeError(f'CreateCircleByRadius failed {op.center_mm}')
                pens.append(_apply_pen(seg, op))
            for op in se.arcs:
                c, s, e = op.center_mm, op.start_mm, op.end_mm
                seg = sm.CreateArc(_m(c[0]), _m(c[1]), 0, _m(s[0]), _m(s[1]), 0, _m(e[0]), _m(e[1]), 0,
                                   1 if op.counterclockwise else -1)
                if seg is None:
                    raise RuntimeError(f'CreateArc failed {op.center_mm}')
                pens.append(_apply_pen(seg, op))
        finally:
            sm.AddToDB = False
        res['geometry_created'] = len(pens)
        res['pen_readback_sample'] = [p for p in pens if p][:5]
        added = []
        for op in se.notes:
            draw.ClearSelection2(True)
            draw.ActivateView('')
            note = draw.InsertNote(op.text)
            if note is None:
                raise RuntimeError(f'InsertNote failed: {op.text[:40]!r}')
            ann = get(note, 'GetAnnotation')
            fmt = ann.GetTextFormat(0)
            fmt.CharHeight = _m(op.height_mm)
            fmt.Bold = op.bold
            fmt.Italic = op.italic
            if op.font:
                fmt.TypeFaceName = op.font
            if op.width_factor is not None:
                fmt.WidthFactor = op.width_factor
            if op.line_spacing_mm is not None:
                fmt.LineSpacing = _m(op.line_spacing_mm)
            ann.SetTextFormat(0, False, fmt)
            note.SetTextJustification(JUSTIFY[op.justify])
            if op.angle_deg:
                note.Angle = math.radians(op.angle_deg)
            ann.SetPosition(_m(op.position_mm[0]), _m(op.position_mm[1]), 0.)
            added.append(_note_record(note, ''))
        res['notes_added'] = len(added)
        res['notes_sample'] = added[:5]
        pics = []
        for op in se.pictures:
            pic = sm.InsertSketchPicture(op.path)
            if pic is None:
                raise RuntimeError(f'InsertSketchPicture failed: {op.path}')
            w = _m(op.width_mm)
            h = _m(op.height_mm) if op.height_mm else None
            if h is None:
                cur = pic.GetSize()
                cw, ch = (float(cur[0]), float(cur[1])) if cur else (w, w)
                h = w * ch / cw if cw else w
            pic.SetSize(w, h, op.height_mm is None)
            pic.SetOrigin(_m(op.origin_mm[0]), _m(op.origin_mm[1]))
            pics.append({'path': op.path, 'size_mm': [_mm(x) for x in (pic.GetSize() or [])][:2]})
        res['pictures'] = pics
        if se.rename_to:
            get(draw, 'GetCurrentSheet').SetName(se.rename_to)
            res['renamed_to'] = se.rename_to
        results.append(res)
    draw.ClearSelection2(True)
    draw.ForceRebuild3(False)
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    target = spec.save_as or current_path
    if not draw.Extension.SaveAs(target, 0, 1, null, err, warn) or err.value:
        raise RuntimeError(f'Drawing save failed: {err.value}, {warn.value}')
    final_names = _sheet_names(draw)
    out = {'status': 'edited', 'drawing_path': str(get(draw, 'GetPathName')), 'sheet_names': final_names,
           'sheets': results, 'manual_review_required': True}
    if spec.pdf_path:
        pdf = sw.GetExportFileData(1)
        pdf.SetSheets(3, VARIANT(  # swExportData_ExportSpecifiedSheets
        pythoncom.VT_ARRAY | pythoncom.VT_BSTR, tuple(final_names)))
        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if not draw.Extension.SaveAs(spec.pdf_path, 0, 1, pdf, err, warn) or err.value:
            raise RuntimeError(f'PDF export failed: {err.value}')
        out['pdf_path'] = spec.pdf_path
    return out


def export_pdf_all(sw, draw, pdf_path, overwrite=False):
    """全部页导出为一个 PDF。"""
    import pythoncom
    from win32com.client import VARIANT
    _absolute(pdf_path, {'.pdf'})
    if Path(pdf_path).exists() and not overwrite:
        raise FileExistsError(pdf_path)
    names = _sheet_names(draw)
    pdf = sw.GetExportFileData(1)
    pdf.SetSheets(3, VARIANT(  # swExportData_ExportSpecifiedSheets
        pythoncom.VT_ARRAY | pythoncom.VT_BSTR, tuple(names)))
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    if not draw.Extension.SaveAs(pdf_path, 0, 1, pdf, err, warn) or err.value:
        raise RuntimeError(f'PDF export failed: {err.value}')
    return {'status': 'exported', 'pdf_path': pdf_path, 'sheet_names': names}


class PdfFrame(Strict):
    box_mm: tuple[float, float, float, float]
    label: str | None = Field(default=None, max_length=80)
    # 页面尺寸（宽, 高，毫米）；给出时图框按比例缩放居中放入该页面（如 A2 图框打印到 A3），矢量不变。
    page_size_mm: tuple[float, float] | None = None

    @model_validator(mode='after')
    def ordered(self):
        x1, y1, x2, y2 = self.box_mm
        if not (x1 < x2 and y1 < y2):
            raise ValueError('box_mm must be x1 < x2 and y1 < y2')
        return self


def export_pdf_frames(sw, draw, sheet, frames, pdf_path, overwrite=False):
    """一张图纸上并排的多个图框 → 多页 PDF，每页按图框裁切（矢量不变，页面尺寸=图框尺寸）。"""
    import os
    import tempfile
    import pythoncom
    import pymupdf
    from win32com.client import VARIANT
    _absolute(pdf_path, {'.pdf'})
    if Path(pdf_path).exists() and not overwrite:
        raise FileExistsError(pdf_path)
    frames = [f if isinstance(f, PdfFrame) else PdfFrame.model_validate(f) for f in frames]
    if not frames:
        raise ValueError('frames required')
    if sheet not in _sheet_names(draw):
        raise ValueError(f'Unknown sheet {sheet!r}; sheets={_sheet_names(draw)}')
    tmp = Path(tempfile.mkdtemp(prefix='sw2d_')) / 'sheet.pdf'
    try:
        pdf = sw.GetExportFileData(1)
        pdf.SetSheets(3, VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, (sheet,)))  # swExportData_ExportSpecifiedSheets
        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if not draw.Extension.SaveAs(str(tmp), 0, 1, pdf, err, warn) or err.value:
            raise RuntimeError(f'PDF export failed: {err.value}')
        src = pymupdf.open(str(tmp))
        out = pymupdf.open()
        k = 72 / 25.4
        page_w_mm = src[0].rect.width / k
        pages = []
        sheet_h = src[0].rect.height
        for f in frames:
            x1, y1, x2, y2 = f.box_mm
            pw, ph = f.page_size_mm or (x2 - x1, y2 - y1)
            page = out.new_page(width=pw * k, height=ph * k)
            # clip 用 PyMuPDF 页面坐标（原点左上）；图纸毫米坐标原点左下。
            clip = pymupdf.Rect(x1 * k, sheet_h - y2 * k, x2 * k, sheet_h - y1 * k)
            page.show_pdf_page(page.rect, src, 0, clip=clip, keep_proportion=True)
            scale = min(pw / (x2 - x1), ph / (y2 - y1))
            pages.append({'label': f.label, 'box_mm': list(f.box_mm), 'size_mm': [round(pw, 1), round(ph, 1)],
                          'scale': round(scale, 4)})
        Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        out.save(pdf_path)
        return {'status': 'exported', 'pdf_path': pdf_path, 'sheet': sheet,
                'sheet_pdf_width_mm': round(page_w_mm, 1), 'pages': pages}
    finally:
        try:
            os.remove(tmp)
            os.rmdir(tmp.parent)
        except OSError:
            pass


def export_dwg(draw, dwg_path, overwrite=False):
    """当前工程图另存为 DWG（原 SLDDRW 不变）。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import create_empty_dispatch_variant
    _absolute(dwg_path, {'.dwg', '.dxf'})
    if Path(dwg_path).exists() and not overwrite:
        raise FileExistsError(dwg_path)
    Path(dwg_path).parent.mkdir(parents=True, exist_ok=True)
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    # swSaveAsOptions_Copy：导出副本，活动文档仍指向原 SLDDRW。
    if not draw.Extension.SaveAs(dwg_path, 0, 2, create_empty_dispatch_variant(), err, warn) or err.value:
        raise RuntimeError(f'DWG export failed: {err.value}, {warn.value}')
    if not Path(dwg_path).is_file():
        raise RuntimeError(f'DWG export reported success but no file: {dwg_path}')
    return {'status': 'exported', 'dwg_path': dwg_path, 'bytes': Path(dwg_path).stat().st_size,
            'warnings': warn.value}



def _set_properties(draw, properties):
    """文档级自定义属性（图框 $PRP 链接读取这些值）；返回写入结果码。"""
    if not properties:
        return {}
    cpm = draw.Extension.CustomPropertyManager('')
    out = {}
    for name, value in properties.items():
        # swCustomInfoText=30, swCustomPropertyReplaceValue=2；0 表示已添加或已改值。
        out[name] = int(cpm.Add3(str(name), 30, str(value), 2))
    return out


def new_drawing_from_template(sw, template_path, save_as, *, sheet_name=None, properties=None):
    """由工程图模板新建无三维模型的工程图并保存；不覆盖已有文件。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as get, create_empty_dispatch_variant
    _absolute(template_path, {'.drwdot'})
    _absolute(save_as, {'.slddrw'})
    if not Path(template_path).is_file():
        raise FileNotFoundError(template_path)
    if Path(save_as).exists():
        raise FileExistsError(save_as)
    draw = sw.NewDocument(str(template_path), 0, 0, 0)
    if draw is None or int(get(draw, 'GetType')) != 3:
        raise RuntimeError(f'NewDocument did not create a drawing from {template_path}')
    if sheet_name:
        get(draw, 'GetCurrentSheet').SetName(sheet_name)
    written = _set_properties(draw, properties)
    draw.ForceRebuild3(False)
    Path(save_as).parent.mkdir(parents=True, exist_ok=True)
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    if not draw.Extension.SaveAs(str(save_as), 0, 1, create_empty_dispatch_variant(), err, warn) or err.value:
        raise RuntimeError(f'SaveAs failed: {err.value}, {warn.value}')
    sheet = get(draw, 'GetCurrentSheet')
    props = list(get(sheet, 'GetProperties2') or [])
    return {'status': 'created', 'drawing_path': str(get(draw, 'GetPathName')), 'template_path': str(template_path),
            'sheet_names': _sheet_names(draw), 'sheet_size_mm': [_mm(props[5]), _mm(props[6])] if len(props) > 6 else None,
            'sheet_format': str(get(sheet, 'GetTemplateName') or ''), 'properties_written': written}


def add_sheet_from_template(sw, draw, template_path, name, *, properties=None, save=True):
    """从 .DRWDOT 模板复制第一页到当前工程图末尾并改名：页面尺寸与带属性链接的图框完全随模板。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as get, create_empty_dispatch_variant
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    _absolute(template_path, {'.drwdot'})
    if not Path(template_path).is_file():
        raise FileNotFoundError(template_path)
    if name in _sheet_names(draw):
        raise ValueError(f'sheet {name!r} already exists')
    target_title = str(get(draw, 'GetTitle'))
    before = _sheet_names(draw)

    def activate_target():
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        sw.ActivateDoc3(target_title, False, 0, errors)
    src = sw.NewDocument(str(template_path), 0, 0, 0)
    if src is None or int(get(src, 'GetType')) != 3:
        raise RuntimeError(f'NewDocument did not create a drawing from {template_path}')
    src_title = str(get(src, 'GetTitle'))
    try:
        src_sheet = _sheet_names(src)[0]
        if not src.Extension.SelectByID2(src_sheet, 'SHEET', 0, 0, 0, False, 0, create_empty_dispatch_variant(), 0):
            raise RuntimeError('cannot select template sheet')
        src.EditCopy()
        activate_target()
        # swInsertOption_AtEnd=1, swRenameOption_Yes=2（同名自动改名，随后改为目标名）。
        if not draw.PasteSheet(1, 2):
            raise RuntimeError('PasteSheet failed')
    finally:
        sw.CloseDoc(src_title)
        activate_target()
    added = [n for n in _sheet_names(draw) if n not in before]
    if len(added) != 1:
        raise RuntimeError(f'expected one pasted sheet, got {added}')
    draw.ActivateSheet(added[0])
    sheet = get(draw, 'GetCurrentSheet')
    sheet.SetName(name)
    written = _set_properties(draw, properties)
    draw.ForceRebuild3(False)
    props = list(get(sheet, 'GetProperties2') or [])
    out = {'status': 'added', 'sheet': str(get(sheet, 'GetName')), 'sheet_names': _sheet_names(draw),
           'sheet_size_mm': [_mm(props[5]), _mm(props[6])] if len(props) > 6 else None,
           'template_path': str(template_path), 'properties_written': written}
    if save:
        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if not draw.Save3(1, err, warn) and err.value:
            raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
        out['saved'] = True
    return out


def add_sheet(draw, name, width_mm, height_mm, *, sheet_format_path=None, scale=(1, 1), first_angle=True,
              properties=None, save=True):
    """在当前工程图中加一页（可带 .slddrt 图纸格式），可选写文档属性并保存。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as get, create_empty_dispatch_variant
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    if not (50 <= width_mm <= 2000 and 50 <= height_mm <= 2000):
        raise ValueError('Unsupported sheet size')
    if name in _sheet_names(draw):
        raise ValueError(f'sheet {name!r} already exists')
    fmt = ''
    if sheet_format_path:
        _absolute(sheet_format_path, {'.slddrt'})
        if not Path(sheet_format_path).is_file():
            raise FileNotFoundError(sheet_format_path)
        fmt = str(sheet_format_path)
    # swDwgPapersUserDefined=12；有格式文件时 swDwgTemplateCustom=13，否则 swDwgTemplateNone=12。
    template_kind = 13 if fmt else 12
    if not draw.NewSheet3(name, 12, template_kind, float(scale[0]), float(scale[1]), bool(first_angle), fmt,
                          width_mm / 1000, height_mm / 1000, ''):
        raise RuntimeError(f'NewSheet3 failed: {name}')
    written = _set_properties(draw, properties)
    draw.ForceRebuild3(False)
    sheet = get(draw, 'GetCurrentSheet')
    props = list(get(sheet, 'GetProperties2') or [])
    out = {'status': 'added', 'sheet': str(get(sheet, 'GetName')), 'sheet_names': _sheet_names(draw),
           'sheet_size_mm': [_mm(props[5]), _mm(props[6])] if len(props) > 6 else None,
           'sheet_format': str(get(sheet, 'GetTemplateName') or ''), 'properties_written': written}
    if save:
        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if not draw.Save3(1, err, warn) and err.value:
            raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
        out['saved'] = True
    return out
