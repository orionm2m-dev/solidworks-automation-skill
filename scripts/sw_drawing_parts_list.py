"""装配图明细表（ISO 7573 风格）与零件序号：原生 BOM 表 + 自动零件序号，二者关联。

明细表用 SolidWorks 原生 BOM 表（IView.InsertBomTable4），列按规格重建：序号、数量、
零件号或自定义属性；表头可放在底部（明细表位于标题栏上方时按 ISO 7573 自下而上编号）。
手工行（电缆、端子等非模型材料）插在表尾并回读。零件序号用 IDrawingDoc.AutoBalloon5，
序号文字取 BOM 项目号，因此与表格一致。所有写操作支持 dry_run，不覆盖文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# swBomType_e / swBOMConfigurationAnchorType_e / swTableHeaderPosition_e / swTableColumnTypes_e。
BOM_TYPES = {'parts_only': 1, 'top_level': 2, 'indented': 3}
ANCHORS = {'top_left': 1, 'top_right': 2, 'bottom_left': 3, 'bottom_right': 4}
HEADER_TOP, HEADER_BOTTOM = 1, 2
COL_PART_NUMBER, COL_ITEM, COL_QUANTITY, COL_PROPERTY = 201, 202, 203, 204
INSERT_AFTER = 3
NUMBERING_DETAILED = 1
# swBalloonStyle_e / swBalloonFit_e / swBalloonLayoutType_e / swBalloonTextContent_e。
BALLOON_STYLES = {'circular': 1, 'underline': 10, 'box': 4, 'triangle': 2, 'hexagon': 3}
BALLOON_SIZES = {'tight': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5}
BALLOON_LAYOUTS = {'square': 1, 'circle': 2, 'top': 3, 'bottom': 4, 'right': 5, 'left': 6}
BALLOON_TEXT_ITEM = 1


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PartsListColumn(Strict):
    title: str = Field(min_length=1, max_length=40)
    source: Literal['item', 'quantity', 'part_number', 'property']
    property: str | None = Field(default=None, min_length=1, max_length=80)
    width_mm: float | None = Field(default=None, gt=2, le=300)

    @model_validator(mode='after')
    def _property(self):
        if (self.source == 'property') != bool(self.property):
            raise ValueError('property is required exactly when source="property"')
        return self


DEFAULT_COLUMNS = [
    PartsListColumn(title='Поз.', source='item', width_mm=10),
    PartsListColumn(title='Обозначение', source='property', property='PartNumber', width_mm=60),
    PartsListColumn(title='Наименование', source='property', property='Title', width_mm=70),
    PartsListColumn(title='Кол.', source='quantity', width_mm=10),
    PartsListColumn(title='Примечание', source='property', property='MPN', width_mm=35),
]


class PartsListSpec(Strict):
    sheet: str = Field(min_length=1, max_length=80)
    view: str | None = Field(default=None, max_length=80, description='Drawing view of the assembly; default: first model view on the sheet.')
    position_mm: tuple[float, float]
    anchor: Literal['top_left', 'top_right', 'bottom_left', 'bottom_right'] = 'bottom_right'
    bom_type: Literal['top_level', 'parts_only', 'indented'] = 'top_level'
    configuration: str = Field(default='', max_length=120)
    template_path: str | None = None
    columns: list[PartsListColumn] = Field(default_factory=lambda: [c.model_copy() for c in DEFAULT_COLUMNS], min_length=1, max_length=12)
    header_at_bottom: bool = True
    manual_rows: list[dict[str, str]] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def _check(self):
        titles = [c.title for c in self.columns]
        if len(set(titles)) != len(titles):
            raise ValueError('column titles must be unique')
        if sum(c.source == 'item' for c in self.columns) > 1 or sum(c.source == 'quantity' for c in self.columns) > 1:
            raise ValueError('at most one item and one quantity column')
        for row in self.manual_rows:
            unknown = set(row) - set(titles)
            if unknown:
                raise ValueError(f'manual row uses unknown columns {sorted(unknown)}; columns={titles}')
        if self.template_path is not None:
            p = Path(self.template_path)
            if not p.is_absolute() or p.suffix.casefold() != '.sldbomtbt':
                raise ValueError('template_path must be an absolute .sldbomtbt path')
        return self


def default_template():
    """已安装的 bom-standard.sldbomtbt（俄文界面优先）。"""
    from scripts.cad_installation import discover_installation
    root = Path(discover_installation('solidworks')['executable']).parent / 'lang'
    for lang in ('russian', 'english'):
        p = root / lang / 'bom-standard.sldbomtbt'
        if p.is_file():
            return str(p)
    raise FileNotFoundError(f'bom-standard.sldbomtbt not found under {root}')


def _m(value):
    return float(value) / 1000.0


def _views_on_sheet(draw):
    from scripts.sw_connect import get_com_member as get
    views = []
    v = get(draw, 'GetFirstView')  # 第一项是图纸本身
    v = get(v, 'GetNextView') if v is not None else None
    while v is not None:
        views.append(v)
        v = get(v, 'GetNextView')
    return views


def _find_view(draw, name):
    from scripts.sw_connect import get_com_member as get
    views = _views_on_sheet(draw)
    model_views = [v for v in views if get(v, 'ReferencedDocument') is not None]
    if name is None:
        if not model_views:
            raise ValueError('no model view on this sheet')
        return model_views[0]
    for v in views:
        if str(get(v, 'GetName2')) == name:
            return v
    raise ValueError(f'view {name!r} not found; views={[str(get(v, "GetName2")) for v in views]}')


def _table_of(bom):
    """BOM 表的 ITableAnnotation：优先取 BomFeature 的表注释，退回 BOM 对象本身。"""
    from scripts.sw_connect import get_com_member as get
    try:
        feature = get(bom, 'BomFeature')
        tables = list(get(feature, 'GetTableAnnotations') or [])
        if tables:
            return tables[0]
    except Exception:  # noqa: BLE001
        pass
    return bom


def _cell(tann, row, col):
    from scripts.sw_drawing_2d import _table_text
    return str(_table_text(tann, row, col) or '')


def _grid(tann):
    from scripts.sw_connect import get_com_member as get
    rows, cols = int(get(tann, 'RowCount')), int(get(tann, 'ColumnCount'))
    return [[_cell(tann, r, c) for c in range(cols)] for r in range(rows)]


def _header_row(grid, titles):
    for r, row in enumerate(grid):
        if [x.strip() for x in row] == titles:
            return r
    return None


def _shape_columns(tann, bom, columns):
    from scripts.sw_connect import get_com_member as get
    while int(get(tann, 'ColumnCount')) < len(columns):
        n = int(get(tann, 'ColumnCount'))
        if not tann.InsertColumn2(INSERT_AFTER, n - 1, f'C{n + 1}', 0):
            raise RuntimeError('InsertColumn2 failed')
    while int(get(tann, 'ColumnCount')) > len(columns):
        n = int(get(tann, 'ColumnCount'))
        if not tann.DeleteColumn(n - 1):
            raise RuntimeError('DeleteColumn failed')
    plan = []
    for i, col in enumerate(columns):
        code = {'item': COL_ITEM, 'quantity': COL_QUANTITY, 'part_number': COL_PART_NUMBER, 'property': COL_PROPERTY}[col.source]
        ok_type = bool(tann.SetColumnType(i, code))
        ok_prop = True
        if col.source == 'property':
            ok_prop = bool(bom.SetColumnCustomProperty(i, col.property))
        ok_title = bool(tann.SetColumnTitle(i, col.title))
        width = None
        if col.width_mm:
            width = float(tann.SetColumnWidth(i, _m(col.width_mm), 0)) * 1000
        plan.append({'index': i, 'title': col.title, 'source': col.source, 'property': col.property,
                     'type_set': ok_type, 'property_set': ok_prop, 'title_set': ok_title,
                     'width_mm': None if width is None else round(width, 2)})
    return plan


def _add_manual_rows(tann, spec, header_row):
    """在最后一个数据行之后插入手工行，按列标题填写；返回新行索引。"""
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_drawing_2d import _set_table_text
    titles = [c.title for c in spec.columns]
    added = []
    for row in spec.manual_rows:
        before = _grid(tann)
        data_rows = [r for r in range(len(before)) if r != header_row]
        anchor_row = max(data_rows) if data_rows else header_row
        if spec.header_at_bottom:
            anchor_row = min(data_rows) if data_rows else header_row
        if not tann.InsertRow(INSERT_AFTER if not spec.header_at_bottom else 2, anchor_row):  # 2 = Before
            raise RuntimeError('InsertRow failed')
        after = _grid(tann)
        new_rows = [r for r in range(len(after)) if not any(x.strip() for x in after[r])]
        if not new_rows:
            raise RuntimeError('inserted row not found')
        r_new = new_rows[0]
        for title, text in row.items():
            _set_table_text(tann, r_new, titles.index(title), str(text))
        added.append(r_new)
        header_row = _header_row(_grid(tann), titles)
        if header_row is None:
            raise RuntimeError('header row lost after inserting a manual row')
    return added


def insert_parts_list(sw, draw, spec, dry_run=True):
    """在指定图纸的装配体视图上插入原生明细表，并按规格整理列、表头与手工行。"""
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_drawing_2d import _activate_sheet, _byref_int, _sheet_names
    spec = spec if isinstance(spec, PartsListSpec) else PartsListSpec.model_validate(spec)
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    if spec.sheet not in _sheet_names(draw):
        raise ValueError(f'Unknown sheet {spec.sheet!r}; sheets={_sheet_names(draw)}')
    template = spec.template_path or default_template()
    if not Path(template).is_file():
        raise FileNotFoundError(template)
    _activate_sheet(draw, spec.sheet)
    view = _find_view(draw, spec.view)
    referenced = get(view, 'ReferencedDocument')
    if referenced is None or int(get(referenced, 'GetType')) != 2:
        raise ValueError(f'view {get(view, "GetName2")!r} does not show an assembly')
    plan = {'sheet': spec.sheet, 'view': str(get(view, 'GetName2')), 'assembly': str(get(referenced, 'GetPathName')),
            'template': template, 'bom_type': spec.bom_type, 'columns': [c.model_dump() for c in spec.columns],
            'header_at_bottom': spec.header_at_bottom, 'manual_rows': len(spec.manual_rows)}
    if dry_run:
        return {'status': 'ready', 'dry_run': True, **plan}
    bom = view.InsertBomTable4(False, _m(spec.position_mm[0]), _m(spec.position_mm[1]), ANCHORS[spec.anchor],
                               BOM_TYPES[spec.bom_type], spec.configuration, template, False, NUMBERING_DETAILED, False)
    if bom is None:
        raise RuntimeError('InsertBomTable4 failed')
    tann = _table_of(bom)
    columns = _shape_columns(tann, bom, spec.columns)
    if not tann.SetHeader(HEADER_BOTTOM if spec.header_at_bottom else HEADER_TOP, 1):
        raise RuntimeError('SetHeader failed')
    titles = [c.title for c in spec.columns]
    header_row = _header_row(_grid(tann), titles)
    if header_row is None:
        raise RuntimeError(f'header row not recognised after setup: {_grid(tann)[:3]}')
    manual = _add_manual_rows(tann, spec, header_row) if spec.manual_rows else []
    draw.ForceRebuild3(False)
    grid = _grid(tann)
    header_row = _header_row(grid, titles)
    err, warn = _byref_int(), _byref_int()
    if not draw.Save3(1, err, warn) and err.value:
        raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
    return {'status': 'inserted', **plan, 'column_setup': columns, 'header_row': header_row,
            'manual_row_indices': manual, 'cells': grid, 'manual_review_required': True}


class BalloonSpec(Strict):
    sheet: str = Field(min_length=1, max_length=80)
    view: str | None = Field(default=None, max_length=80)
    style: Literal['circular', 'underline', 'box', 'triangle', 'hexagon'] = 'circular'
    size: Literal['tight', '1', '2', '3', '4', '5'] = '2'
    layout: Literal['square', 'circle', 'top', 'bottom', 'right', 'left'] = 'square'
    ignore_multiple: bool = True
    leader_to_faces: bool = False


def insert_balloons(sw, draw, spec, dry_run=True):
    """对视图自动插入零件序号（文字 = BOM 项目号）；视图已有序号时拒绝，避免重复。"""
    from scripts.sw_connect import create_empty_dispatch_variant, get_com_member as get
    from scripts.sw_drawing_2d import _activate_sheet, _byref_int, _sheet_names
    spec = spec if isinstance(spec, BalloonSpec) else BalloonSpec.model_validate(spec)
    if int(get(draw, 'GetType')) != 3:
        raise ValueError('Active document must be a drawing (.SLDDRW)')
    if spec.sheet not in _sheet_names(draw):
        raise ValueError(f'Unknown sheet {spec.sheet!r}; sheets={_sheet_names(draw)}')
    _activate_sheet(draw, spec.sheet)
    view = _find_view(draw, spec.view)
    name = str(get(view, 'GetName2'))
    existing = _balloon_texts(view)
    plan = {'sheet': spec.sheet, 'view': name, 'existing_balloons': existing}
    if existing:
        raise ValueError(f'view {name!r} already has balloons {existing}; delete them first')
    if dry_run:
        return {'status': 'ready', 'dry_run': True, **plan}
    draw.ClearSelection2(True)
    ext = get(draw, 'Extension')
    if not ext.SelectByID2(name, 'DRAWINGVIEW', 0, 0, 0, False, 0, create_empty_dispatch_variant(), 0):
        raise RuntimeError(f'cannot select view {name!r}')
    opts = draw.CreateAutoBalloonOptions()
    opts.Layout = BALLOON_LAYOUTS[spec.layout]
    opts.Style = BALLOON_STYLES[spec.style]
    opts.Size = BALLOON_SIZES[spec.size]
    opts.UpperTextContent = BALLOON_TEXT_ITEM
    opts.IgnoreMultiple = bool(spec.ignore_multiple)
    opts.LeaderAttachmentToFaces = bool(spec.leader_to_faces)
    created = draw.AutoBalloon5(opts)
    draw.ClearSelection2(True)
    draw.ForceRebuild3(False)
    texts = _balloon_texts(view)
    if not texts:
        raise RuntimeError(f'AutoBalloon5 created no balloons on {name!r} (returned {type(created).__name__})')
    err, warn = _byref_int(), _byref_int()
    if not draw.Save3(1, err, warn) and err.value:
        raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
    return {'status': 'inserted', **plan, 'balloons': texts, 'count': len(texts), 'manual_review_required': True}


def _balloon_texts(view):
    from scripts.sw_connect import get_com_member as get
    texts = []
    note = get(view, 'GetFirstNote')
    while note is not None:
        try:
            if bool(get(note, 'IsBomBalloon')):
                texts.append(str(get(note, 'GetText') or ''))
        except Exception:  # noqa: BLE001
            pass
        note = get(note, 'GetNext')
    return texts
