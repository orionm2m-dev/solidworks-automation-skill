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
INSERT_LAST = 4
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
        ok_type = _set_column_type(tann, i, code, col.property or '')
        ok_prop = True
        if col.source == 'property':
            bom.SetColumnCustomProperty(i, col.property)
            ok_prop = str(_call(bom, 'GetColumnCustomProperty', i) or '') == col.property
        ok_title = bool(tann.SetColumnTitle(i, col.title))
        width = None
        if col.width_mm:
            width = float(tann.SetColumnWidth(i, _m(col.width_mm), 0)) * 1000
        plan.append({'index': i, 'title': col.title, 'source': col.source, 'property': col.property,
                     'type_set': ok_type, 'property_set': ok_prop, 'title_set': ok_title,
                     'width_mm': None if width is None else round(width, 2)})
    return plan


def _new_row_index(before, after):
    """插入一行后的新行索引：前后网格第一处不同的位置（末尾追加时为原行数）。"""
    if len(after) != len(before) + 1:
        raise RuntimeError(f'row count {len(before)} -> {len(after)} after InsertRow')
    for i, row in enumerate(before):
        if after[i] != row:
            return i
    return len(before)


def _call(obj, name, *args):
    from scripts.sw_connect import get_com_member as get
    return get(obj, name, *args)


def _set_column_type(tann, index, code, prop):
    """设列类型并回读：SetColumnType3 → SetColumnType2 → SetColumnType，以 GetColumnType2 为准。"""
    def current():
        for name, args in (('GetColumnType2', (index, False)), ('GetColumnType', (index,))):
            try:
                return int(_call(tann, name, *args))
            except Exception:  # noqa: BLE001
                continue
        return None

    if current() == code and code != COL_PROPERTY:
        return True
    for name, args in (('SetColumnType3', (index, code, False, prop)), ('SetColumnType2', (index, code, False)),
                       ('SetColumnType', (index, code))):
        try:
            _call(tann, name, *args)
        except Exception:  # noqa: BLE001
            continue
        if current() == code:
            return True
    return False


def _add_manual_rows(tann, spec, header_row):
    """在表尾（逻辑最后一行之后）插入手工行，按列标题填写；返回新行索引。"""
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_drawing_2d import _set_table_text
    titles = [c.title for c in spec.columns]
    added = []
    for row in spec.manual_rows:
        before = _grid(tann)
        if not tann.InsertRow(INSERT_LAST, len(before) - 1):
            raise RuntimeError('InsertRow failed')
        r_new = _new_row_index(before, _grid(tann))
        # 新行会复制相邻行的文字（含表头），先按规格整行写入，未给出的列写空。
        for index, title in enumerate(titles):
            _set_table_text(tann, r_new, index, str(row.get(title, '')))
        added.append(r_new)
        if _header_row(_grid(tann), titles) is None:
            raise RuntimeError(f'header row lost after inserting a manual row: {_grid(tann)}')
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
    # 配置名为空时 BOM 没有任何行：默认取视图引用的配置。
    configuration = spec.configuration or str(get(view, 'ReferencedConfiguration') or '')
    bom = view.InsertBomTable4(False, _m(spec.position_mm[0]), _m(spec.position_mm[1]), ANCHORS[spec.anchor],
                               BOM_TYPES[spec.bom_type], configuration, template, False, NUMBERING_DETAILED, False)
    if bom is None:
        raise RuntimeError('InsertBomTable4 failed')
    tann = _table_of(bom)
    titles = [c.title for c in spec.columns]
    try:
        columns = _shape_columns(tann, bom, spec.columns)
        wanted = HEADER_BOTTOM if spec.header_at_bottom else HEADER_TOP
        tann.SetHeader(wanted, 1)
        header_style = int(_call(tann, 'GetHeaderStyle'))
        header_row = _header_row(_grid(tann), titles)
        if header_row is None:
            raise RuntimeError('header row not recognised after column setup')
        manual = _add_manual_rows(tann, spec, header_row) if spec.manual_rows else []
    except Exception as exc:  # noqa: BLE001 - the table exists but the drawing is not saved
        try:
            grid = _grid(tann)
        except Exception:  # noqa: BLE001
            grid = None
        raise RuntimeError(f'parts list setup failed after InsertBomTable4; the drawing is NOT saved, close it without '
                           f'saving or undo: {exc}; table={grid}') from exc
    draw.ForceRebuild3(False)
    grid = _grid(tann)
    header_row = _header_row(grid, titles)
    err, warn = _byref_int(), _byref_int()
    if not draw.Save3(1, err, warn) and err.value:
        raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
    problems = [f"column {c['title']}: type not set" for c in columns if not c['type_set']]
    problems += [f"column {c['title']}: property not set" for c in columns if not c['property_set']]
    if header_style != wanted:
        problems.append(f'header position {header_style}, wanted {wanted}')
    data_rows = [r for r in range(len(grid)) if r != header_row and r not in manual]
    if not data_rows:
        problems.append('no component rows in the BOM')
    return {'status': 'inserted' if not problems else 'inserted_with_problems', 'problems': problems,
            **plan, 'configuration': configuration, 'header_style': header_style, 'column_setup': columns, 'header_row': header_row,
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
    def step(label, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - name the failing COM member
            raise RuntimeError(f'{label}: {exc}') from exc

    draw.ClearSelection2(True)
    ext = get(draw, 'Extension')
    if not step('SelectByID2', lambda: ext.SelectByID2(name, 'DRAWINGVIEW', 0, 0, 0, False, 0, create_empty_dispatch_variant(), 0)):
        raise RuntimeError(f'cannot select view {name!r}')
    opts = step('CreateAutoBalloonOptions', lambda: get(draw, 'CreateAutoBalloonOptions'))
    if opts is None:
        raise RuntimeError('CreateAutoBalloonOptions returned nothing')
    for prop, value in (('Layout', BALLOON_LAYOUTS[spec.layout]), ('Style', BALLOON_STYLES[spec.style]),
                        ('Size', BALLOON_SIZES[spec.size]), ('UpperTextContent', BALLOON_TEXT_ITEM),
                        ('IgnoreMultiple', bool(spec.ignore_multiple)), ('LeaderAttachmentToFaces', bool(spec.leader_to_faces))):
        step(f'AutoBalloonOptions.{prop}', lambda prop=prop, value=value: _put(opts, prop, value))
    created = step('AutoBalloon5', lambda: draw.AutoBalloon5(opts))
    draw.ClearSelection2(True)
    draw.ForceRebuild3(False)
    texts = _balloon_texts(view)
    if not texts:
        raise RuntimeError(f'AutoBalloon5 created no balloons on {name!r} (returned {type(created).__name__})')
    err, warn = _byref_int(), _byref_int()
    if not draw.Save3(1, err, warn) and err.value:
        raise RuntimeError(f'Save failed: {err.value}, {warn.value}')
    return {'status': 'inserted', **plan, 'balloons': texts, 'count': len(texts), 'manual_review_required': True}


def _put(obj, name, value):
    """属性赋值：动态代理失败时直接 DISPATCH_PROPERTYPUT。"""
    try:
        setattr(obj, name, value)
        return
    except Exception:  # noqa: BLE001
        import pythoncom
        dispid = obj._oleobj_.GetIDsOfNames(name)
        obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, value)


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
