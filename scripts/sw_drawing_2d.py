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


class ReplaceDimensionTextOp(TextMatch):
    """显示尺寸的文字：match 对比显示文字（<DIM> 代入数值）或数值本身（"149,95" 与 149.95 mm 相等）。"""
    new_text: str = Field(min_length=1, max_length=200)
    underline: bool = False  # 不按比例的尺寸（ГОСТ 2.307）：文字加下划线


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
    replace_dimension_text: list[ReplaceDimensionTextOp] = Field(default_factory=list, max_length=100)
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


def _view_dimensions(view):
    from scripts.sw_connect import get_com_member as get
    out = []
    try:
        dd = get(view, 'GetFirstDisplayDimension5')
    except Exception:  # noqa: BLE001
        return out
    while dd is not None:
        out.append(dd)
        dd = get(dd, 'GetNext5')
    return out


def _format_number(value):
    text = f'{value:.3f}'.rstrip('0').rstrip('.')
    return text.replace('.', ',')


def _dimension_record(dd, view_name):
    """显示尺寸：各部分文字、数值（mm）、替代值、显示文字、位置、图层。"""
    from scripts.sw_connect import get_com_member as get
    rec = {'view': view_name}
    for key, part in (('text', 0), ('prefix', 1), ('suffix', 2), ('above', 3), ('below', 4)):
        try:
            rec[key] = str(dd.GetText(part) or '')
        except Exception:  # noqa: BLE001
            pass
    value = None
    try:
        dim = dd.GetDimension2(0)
        rec['name'] = str(get(dim, 'FullName') or '')
        value = float(get(dim, 'SystemValue')) * 1000.0
        rec['value_mm'] = round(value, 4)
    except Exception as exc:  # noqa: BLE001
        rec['value_error'] = str(exc)
    try:
        if bool(dd.GetOverride()):
            rec['override_value'] = float(dd.GetOverrideValue())
    except Exception:  # noqa: BLE001
        pass
    shown = rec.get('override_value', value)
    number = _format_number(shown) if shown is not None else ''
    rec['display'] = ' '.join(x for x in (rec.get('prefix', ''), rec.get('text', '<DIM>').replace('<DIM>', number),
                                          rec.get('suffix', '')) if x).strip()
    try:
        ann = get(dd, 'GetAnnotation')
        pos = list(get(ann, 'GetPosition') or [])
        rec['position_mm'] = [_mm(pos[0]), _mm(pos[1])] if len(pos) >= 2 else None
        rec['layer'] = str(get(ann, 'Layer') or '')
    except Exception as exc:  # noqa: BLE001
        rec['position_error'] = str(exc)
    return rec


def dimension_matches(rec, op):
    """显示文字匹配，或 match 为数字时与数值相差 < 0.005 mm。"""
    shown = normalize_text(rec.get('display', ''))
    want = normalize_text(op.match)
    if (want in shown) if op.contains else (shown == want):
        return True
    try:
        number = float(op.match.replace(',', '.').strip())
    except ValueError:
        return False
    value = rec.get('override_value', rec.get('value_mm'))
    return value is not None and abs(float(value) - number) < 0.005


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
                rec.setdefault('dimensions', []).extend(_dimension_record(d, vname) for d in _view_dimensions(v))
                try:
                    counts = {}
                    for ann in list(get(v, 'GetAnnotations') or []):
                        kind = int(get(ann, 'GetType'))
                        counts[kind] = counts.get(kind, 0) + 1
                    vrec['annotation_types'] = {str(k): n for k, n in sorted(counts.items())}
                except Exception:  # noqa: BLE001
                    pass
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
                           'notes': len(s['notes']), 'dimensions': len(s.get('dimensions', [])),
                           'segment_types': s['segment_types'],
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
    plan = {'sheet': sheet_edit.sheet, 'notes_on_sheet': len(notes), 'replace_text': [], 'delete_notes': [], 'delete_in_box': [],
            'replace_dimension_text': []}
    problems = []
    if sheet_edit.replace_dimension_text:
        dims = [(d, _dimension_record(d, str(get(v, 'GetName2')))) for v in _views(draw) for d in _view_dimensions(v)]
        plan['dimensions_on_sheet'] = len(dims)
        for op in sheet_edit.replace_dimension_text:
            hits = [r for _d, r in dims if dimension_matches(r, op) and note_position_in_box(r.get('position_mm'), op)]
            plan['replace_dimension_text'].append({'match': op.match, 'box_mm': op.box_mm, 'found': len(hits),
                                                   'expected': op.expected_count, 'hits': hits[:10]})
            if len(hits) != op.expected_count:
                problems.append(f'replace_dimension_text {op.match!r}: found {len(hits)}, expected {op.expected_count}')
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


def _underline_dimension(dd):
    """尺寸文字加下划线：注释的局部文字格式 Underline=True（不用文档默认格式）。"""
    from scripts.sw_connect import get_com_member as get
    ann = get(dd, 'GetAnnotation')
    fmt = ann.GetTextFormat(0)
    fmt.Underline = True
    if not ann.SetTextFormat(0, False, fmt):
        raise RuntimeError('SetTextFormat(underline) failed')


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
        dim_replaced = []
        if se.replace_dimension_text:
            dims = [(d, _dimension_record(d, str(get(v, 'GetName2')))) for v in _views(draw) for d in _view_dimensions(v)]
            for op in se.replace_dimension_text:
                hits = [d for d, r in dims if dimension_matches(r, op) and note_position_in_box(r.get('position_mm'), op)]
                if len(hits) != op.expected_count:
                    raise RuntimeError(f'replace_dimension_text {op.match!r}: found {len(hits)}, expected {op.expected_count}')
                for d in hits:
                    # 整段文字替换 <DIM>：显示为 new_text，数值不再参与显示。
                    d.SetText(0, op.new_text)
                    for part in (1, 2):
                        d.SetText(part, '')
                    if op.underline:
                        _underline_dimension(d)
                after = [_dimension_record(d, '') for d in hits]
                bad = [a for a in after if a.get('display') != op.new_text and a.get('text') != op.new_text]
                if bad:
                    raise RuntimeError(f'replace_dimension_text {op.match!r}: readback {bad}')
                dim_replaced.append({'match': op.match, 'replaced': len(hits), 'new_text': op.new_text,
                                     'readback': [a.get('text') for a in after]})
        res['dimension_text_replaced'] = dim_replaced
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


def _safe_file_part(name):
    bad = '<>:"/\\|?*'
    out = ''.join('_' if c in bad or ord(c) < 32 else c for c in str(name)).strip(' .')
    return out or 'sheet'


def check_pdf_pages(pdf_path, sheets, tolerance_mm=0.5):
    """逐页核对 PDF 页面尺寸 = 图纸尺寸（100 % 比例），页数 = 图纸数；不修改文件。"""
    import pymupdf
    k = 72 / 25.4
    doc = pymupdf.open(str(pdf_path))
    try:
        pages = [(p.rect.width / k, p.rect.height / k) for p in doc]
    finally:
        doc.close()
    rows = []
    for i, sheet in enumerate(sheets):
        w, h = sheet['size_mm']
        if i >= len(pages):
            rows.append({'sheet': sheet['name'], 'sheet_size_mm': [w, h], 'page_size_mm': None, 'ok': False,
                         'problem': 'missing_page'})
            continue
        pw, ph = pages[i]
        delta = max(abs(pw - w), abs(ph - h))
        row = {'sheet': sheet['name'], 'page': i + 1, 'sheet_size_mm': [round(w, 2), round(h, 2)],
               'page_size_mm': [round(pw, 2), round(ph, 2)], 'delta_mm': round(delta, 2), 'ok': delta <= tolerance_mm}
        if not row['ok']:
            rotated = max(abs(pw - h), abs(ph - w)) <= tolerance_mm
            row['problem'] = 'rotated' if rotated else 'size'
        rows.append(row)
    extra = len(pages) - len(sheets)
    return {'pages': rows, 'page_count': len(pages), 'sheet_count': len(sheets),
            'extra_pages': max(extra, 0), 'tolerance_mm': tolerance_mm,
            'all_ok': extra == 0 and all(r['ok'] for r in rows)}


def export_release(sw, draw, *, pdf_path=None, dxf_dir=None, sheets=None, tolerance_mm=0.5, overwrite=False):
    """出图：全部（或指定）图纸 → 一个 PDF（逐页核对尺寸 = 图纸尺寸）+ 每张图纸一个 DXF。

    DXF 逐页导出：临时把 swDxfMultiSheetOption 设为仅当前页，finally 中恢复原设置和原活动页。
    已有输出文件在任何写入前拒绝（overwrite=False）。
    """
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import create_empty_dispatch_variant, get_com_member as get
    if not pdf_path and not dxf_dir:
        raise ValueError('pdf_path or dxf_dir required')
    all_names = _sheet_names(draw)
    names = list(sheets) if sheets else all_names
    unknown = [n for n in names if n not in all_names]
    if unknown or not names:
        raise ValueError(f'Unknown sheets {unknown}; sheets={all_names}')
    drawing_path = str(get(draw, 'GetPathName'))
    stem = Path(drawing_path).stem or 'drawing'
    planned = []
    if pdf_path:
        _absolute(pdf_path, {'.pdf'})
        planned.append(Path(pdf_path))
    dxf_paths = {}
    if dxf_dir:
        if not Path(dxf_dir).is_absolute():
            raise ValueError('dxf_dir must be absolute')
        for n in names:
            dxf_paths[n] = Path(dxf_dir) / f'{stem}_{_safe_file_part(n)}.dxf'
        if len({str(p).casefold() for p in dxf_paths.values()}) != len(dxf_paths):
            raise ValueError('Sheet names collide after file-name cleanup')
        planned.extend(dxf_paths.values())
    existing = [str(p) for p in planned if p.exists()]
    if existing and not overwrite:
        raise FileExistsError(f'Outputs exist: {existing}')

    original = str(get(get(draw, 'GetCurrentSheet'), 'GetName'))
    sheet_info = []
    old_dxf = None
    result = {'status': 'exported', 'drawing_path': drawing_path, 'sheet_names': names}
    try:
        for n in names:
            _activate_sheet(draw, n)
            props = list(get(get(draw, 'GetCurrentSheet'), 'GetProperties2') or [])
            if len(props) < 7:
                raise RuntimeError(f'Sheet size unavailable: {n}')
            sheet_info.append({'name': n, 'size_mm': [float(props[5]) * 1000, float(props[6]) * 1000],
                               'scale': [float(props[2]), float(props[3])]})
        result['sheets'] = [{'name': i['name'], 'size_mm': [round(x, 2) for x in i['size_mm']],
                             'sheet_scale': i['scale']} for i in sheet_info]
        if pdf_path:
            Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
            pdf = sw.GetExportFileData(1)
            pdf.SetSheets(3, VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, tuple(names)))  # swExportData_ExportSpecifiedSheets
            err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            if not draw.Extension.SaveAs(str(pdf_path), 0, 1, pdf, err, warn) or err.value:
                raise RuntimeError(f'PDF export failed: {err.value}')
            check = check_pdf_pages(pdf_path, sheet_info, tolerance_mm)
            result['pdf'] = {'path': str(pdf_path), **check}
        if dxf_dir:
            Path(dxf_dir).mkdir(parents=True, exist_ok=True)
            old_dxf = int(sw.GetUserPreferenceIntegerValue(253))  # swDxfMultiSheetOption
            sw.SetUserPreferenceIntegerValue(253, 0)  # swDxfActiveSheetOnly
            files = []
            for n in names:
                _activate_sheet(draw, n)
                target = dxf_paths[n]
                err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                # swSaveAsOptions_Copy：导出副本，活动文档仍指向原 SLDDRW。
                if not draw.Extension.SaveAs(str(target), 0, 2, create_empty_dispatch_variant(), err, warn) or err.value:
                    raise RuntimeError(f'DXF export failed for {n}: {err.value}, {warn.value}')
                if not target.is_file() or target.stat().st_size == 0:
                    raise RuntimeError(f'DXF export reported success but no file: {target}')
                files.append({'sheet': n, 'path': str(target), 'bytes': target.stat().st_size})
            result['dxf'] = files
    finally:
        if old_dxf is not None:
            sw.SetUserPreferenceIntegerValue(253, old_dxf)
        try:
            _activate_sheet(draw, original)
        except Exception:  # noqa: BLE001
            pass
    if pdf_path and not result['pdf']['all_ok']:
        result['status'] = 'size_mismatch'
    result['success'] = result['status'] == 'exported'
    result['manual_review_required'] = True
    return result


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
    target_path = str(get(draw, 'GetPathName') or '')
    # 工程图标题含当前页名，换页后会变；按文件名激活，未保存时退回标题。
    target_name = Path(target_path).name if target_path else str(get(draw, 'GetTitle'))
    before = _sheet_names(draw)

    def activate_target():
        _activate_doc(sw, target_name)
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
    active = get(sw, 'ActiveDoc')
    if target_path and (active is None or str(get(active, 'GetPathName') or '').casefold() != target_path.casefold()):
        raise RuntimeError(f'target drawing is not active after sheet copy: {target_path}')
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


# swDisplayMode_e：只开放能可靠回读的几种。
DISPLAY = {'wireframe': 0, 'hidden_visible': 1, 'hidden_removed': 2, 'shaded': 3}


class ModelViewOp(Strict):
    named_view: str = Field(default='*Front', min_length=1, max_length=80)
    center_mm: Point
    scale: float | None = Field(default=None, gt=0, le=100)  # None：使用图纸比例
    display: Literal['wireframe', 'hidden_visible', 'hidden_removed', 'shaded'] = 'hidden_removed'
    name: str | None = Field(default=None, min_length=1, max_length=80)


# 标准视图在 GetModelViewNames 开头的固定顺序（与界面语言无关）。
STANDARD_VIEWS = ['*Normal To', '*Front', '*Back', '*Left', '*Right', '*Top', '*Bottom', '*Isometric', '*Trimetric', '*Dimetric']


def resolve_named_view(requested, named):
    """按名称取视图；英文标准名在本地化界面下按标准顺序映射到本地名称。找不到返回 None。"""
    if requested in named:
        return requested
    keys = [k.casefold() for k in STANDARD_VIEWS]
    if requested.casefold() in keys:
        std = [n for n in named if n.startswith('*')][:len(STANDARD_VIEWS)]
        if len(std) == len(STANDARD_VIEWS):
            return std[keys.index(requested.casefold())]
    return None


def _byref_int():
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _open_model(sw, model_path):
    """静默打开（或取已打开的）零件/装配体，返回文档。"""
    from scripts.sw_connect import get_com_member as get
    kind = {'.sldprt': 1, '.sldasm': 2}[Path(model_path).suffix.lower()]
    for doc in list(get(sw, 'GetDocuments') or []):
        if str(get(doc, 'GetPathName') or '').casefold() == str(model_path).casefold():
            return doc
    try:
        r = sw.OpenDoc6(str(model_path), kind, 1, '', _byref_int(), _byref_int())
    except TypeError:
        r = sw.OpenDoc6(str(model_path), kind, 1, '', 0, 0)
    doc = r[0] if isinstance(r, tuple) else r
    if doc is None:
        raise RuntimeError(f'cannot open model {model_path}')
    return doc


def _activate_doc(sw, name):
    """ActivateDoc3：早绑定要整数，晚绑定要按引用 VARIANT；两种都试。"""
    try:
        return sw.ActivateDoc3(name, False, 0, _byref_int())
    except TypeError:
        return sw.ActivateDoc3(name, False, 0, 0)


def _activate_by_path(sw, path, title):
    _activate_doc(sw, Path(path).name if path else title)


def insert_model_views(sw, draw, model_path, sheet, views, dry_run=True):
    """把零件/装配体的命名视图放到现有工程图的指定页上（不改图框），按中心定位，可设比例与显示方式。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as get
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    _absolute(model_path, {'.sldprt', '.sldasm'})
    if not Path(model_path).is_file():
        raise FileNotFoundError(model_path)
    views = [v if isinstance(v, ModelViewOp) else ModelViewOp.model_validate(v) for v in views]
    if not views or len(views) > 16:
        raise ValueError('1..16 views required')
    if sheet not in _sheet_names(draw):
        raise ValueError(f'Unknown sheet {sheet!r}; sheets={_sheet_names(draw)}')
    draw_path = str(get(draw, 'GetPathName') or '')
    draw_title = str(get(draw, 'GetTitle'))
    model = _open_model(sw, model_path)
    named = [str(n) for n in (get(model, 'GetModelViewNames') or [])]
    _activate_by_path(sw, draw_path, draw_title)
    resolved = {v.named_view: resolve_named_view(v.named_view, named) for v in views}
    missing = [k for k, val in resolved.items() if val is None]
    plan = {'status': 'blocked' if missing else 'ready', 'model_path': str(model_path), 'sheet': sheet,
            'named_views': named, 'resolved': resolved, 'missing': missing, 'views': [v.model_dump() for v in views]}
    if missing or dry_run:
        return plan
    _activate_sheet(draw, sheet)
    sh = get(draw, 'GetCurrentSheet')
    props = list(get(sh, 'GetProperties2') or [])
    sheet_size = (_mm(props[5]), _mm(props[6])) if len(props) > 6 else None
    vec = lambda vals: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(vals))
    out = []
    for op in views:
        v = draw.CreateDrawViewFromModelView3(str(model_path), resolved[op.named_view], _m(op.center_mm[0]), _m(op.center_mm[1]), 0.0)
        if v is None:
            raise RuntimeError(f'CreateDrawViewFromModelView3 failed: {op.named_view}')
        if op.scale is not None:
            v.UseSheetScale = 0
            v.ScaleDecimal = float(op.scale)
        v.SetDisplayMode4(False, DISPLAY[op.display], False, True, True)
        if op.name:
            v.SetName2(op.name)
        draw.ForceRebuild3(False)
        draw.GraphicsRedraw2()
        box = list(get(v, 'GetOutline'))
        pos = list(get(v, 'Position'))
        pos[0] += _m(op.center_mm[0]) - (box[0] + box[2]) / 2
        pos[1] += _m(op.center_mm[1]) - (box[1] + box[3]) / 2
        v.Position = vec(pos)
        draw.ForceRebuild3(False)
        box = [_mm(x) for x in list(get(v, 'GetOutline'))]
        rec = {'name': str(get(v, 'GetName2')), 'named_view': op.named_view, 'outline_mm': box,
               'scale': round(float(get(v, 'ScaleDecimal')), 6), 'display_mode': int(get(v, 'GetDisplayMode2'))}
        if sheet_size and not (0 <= box[0] and box[2] <= sheet_size[0] and 0 <= box[1] and box[3] <= sheet_size[1]):
            rec['warning'] = f'view outline outside sheet {sheet_size}'
        out.append(rec)
    err, warn = _byref_int(), _byref_int()
    if not draw.Save3(1, err, warn) and err.value:
        raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
    return {'status': 'inserted', 'model_path': str(model_path), 'sheet': sheet, 'sheet_size_mm': sheet_size,
            'views': out, 'manual_review_required': True}


class RevisionRow(Strict):
    revision: str = Field(min_length=1, max_length=8)
    description: str = Field(default='', max_length=400)
    date: str = Field(default='', max_length=40)
    approved: str = Field(default='', max_length=80)


def _table_text(tann, row, col):
    """读表格单元格文字（带参数的属性 Text(row, col)）。"""
    t = getattr(tann, 'Text')
    return t(row, col) if callable(t) else t


def _set_table_text(tann, row, col, value):
    """写表格单元格：早绑定有 SetText；晚绑定用 DISPATCH_PROPERTYPUT 调用 Text(row, col)。"""
    setter = getattr(tann, 'SetText', None)
    if callable(setter):
        return setter(row, col, value)
    import pythoncom
    dispid = tann._oleobj_.GetIDsOfNames('Text')
    return tann._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, row, col, value)


def insert_revision_table(sw, draw, sheet, rows, *, position_mm=None, anchor='bottom_right', table_template=''):
    """在指定页插入原生修订表并按行填写；返回表的列标题与回读的单元格。"""
    from scripts.sw_connect import get_com_member as get
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    rows = [r if isinstance(r, RevisionRow) else RevisionRow.model_validate(r) for r in rows]
    if not rows:
        raise ValueError('at least one revision row required')
    if sheet not in _sheet_names(draw):
        raise ValueError(f'Unknown sheet {sheet!r}; sheets={_sheet_names(draw)}')
    _activate_sheet(draw, sheet)
    sh = get(draw, 'GetCurrentSheet')
    if get(sh, 'RevisionTable') is not None:
        raise ValueError(f'sheet {sheet!r} already has a revision table')
    # swBOMConfigurationAnchor_e：TopLeft=1, TopRight=2, BottomLeft=3, BottomRight=4。
    anchor_code = {'top_left': 1, 'top_right': 2, 'bottom_left': 3, 'bottom_right': 4}[anchor]
    use_anchor = position_mm is None
    x, y = (_m(position_mm[0]), _m(position_mm[1])) if position_mm else (0.0, 0.0)
    table = sh.InsertRevisionTable2(use_anchor, x, y, anchor_code, str(table_template or ''), 1, True)
    if table is None:
        raise RuntimeError('InsertRevisionTable2 failed')
    tann = table  # IRevisionTableAnnotation 继承 ITableAnnotation
    for r in rows:
        row_id = table.AddRevision(r.revision)
        if not row_id:
            raise RuntimeError(f'AddRevision failed: {r.revision}')
    ncols = int(get(tann, 'ColumnCount'))
    nrows = int(get(tann, 'RowCount'))
    cell = lambda r_, c_: str(_table_text(tann, r_, c_) or '')
    # 表头行：前几行中含“描述/日期”类列名的那一行（第一行常是表名）。
    keys = {'desc': ('desc', 'опис'), 'date': ('date', 'дат'), 'appr': ('approv', 'утв')}
    header_row, cols = None, {}
    for r_ in range(min(3, nrows)):
        found = {}
        for k, words in keys.items():
            for c_ in range(ncols):
                if any(w in cell(r_, c_).casefold() for w in words):
                    found[k] = c_
                    break
        if 'desc' in found:
            header_row, cols = r_, found
            break
    if header_row is None:
        raise RuntimeError(f'revision table header not recognised: {[[cell(r_, c_) for c_ in range(ncols)] for r_ in range(min(3, nrows))]}')
    data_rows = list(range(nrows - len(rows), nrows))
    for r, row in zip(rows, data_rows):
        for k, val in (('desc', r.description), ('date', r.date), ('appr', r.approved)):
            if k in cols and val:
                _set_table_text(tann, row, cols[k], val)
    headers = [cell(header_row, c_) for c_ in range(ncols)]
    draw.ForceRebuild3(False)
    readback = [[cell(r_, c_) for c_ in range(ncols)] for r_ in range(nrows)]
    err, warn = _byref_int(), _byref_int()
    if not draw.Save3(1, err, warn) and err.value:
        raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
    return {'status': 'inserted', 'sheet': sheet, 'headers': headers, 'cells': readback}
