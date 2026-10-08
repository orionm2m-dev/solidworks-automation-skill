"""受约束的原生工程图布局：视图、剖视、投影参考尺寸与审计。"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class ViewSpec(Strict):
    id: str
    named_view: str = '*Front'
    center_mm: tuple[float, float]
    scale: float = Field(default=1, gt=0, le=20)
    parent: str | None = None
    section_line_mm: tuple[tuple[float,float,float],tuple[float,float,float]] | None = None
    section_label: str = 'A'
    minimum_hatched_faces: int = Field(default=0,ge=0)
    crop_mm: list[tuple[float,float,float]] | None = None

class NoteSpec(Strict):
    text: str = Field(min_length=1)
    position_mm: tuple[float,float]
    height_mm: float = Field(default=2.5,gt=0,le=15)
    bold: bool = False

class DimensionSpec(Strict):
    view: str
    kind: Literal['horizontal','vertical','aligned']
    points_mm: tuple[tuple[float,float,float],tuple[float,float,float]]
    offset_mm: tuple[float,float]
    expected_mm: float = Field(gt=0)
    tolerance_mm: float = Field(default=0.02,gt=0,le=0.1)
    prefix: str = ''

class LineSpec(Strict):
    points_mm: tuple[tuple[float,float],tuple[float,float]]
    construction: bool = False

class DrawingLayout(Strict):
    output_path: str
    template_path: str | None = None
    size_mm: tuple[float,float] = (420,297)
    views: list[ViewSpec] = Field(default_factory=list,max_length=16)
    notes: list[NoteSpec] = Field(default_factory=list,max_length=100)
    dimensions: list[DimensionSpec] = Field(default_factory=list,max_length=100)
    lines: list[LineSpec] = Field(default_factory=list,max_length=300)
    export_pdf: bool = True
    export_dxf: bool = True

    @model_validator(mode='after')
    def validate_layout(self):
        """在修改文档前验证引用、图幅和输出路径。"""
        from scripts.sw_operation_guard import absolute_document_path
        if not absolute_document_path(self.output_path) or Path(self.output_path).suffix.lower() != '.slddrw':
            raise ValueError('output_path must be absolute .SLDDRW')
        if not all(50 <= v <= 2000 for v in self.size_mm):
            raise ValueError('Unsupported sheet size')
        seen = set()
        for v in self.views:
            if v.id in seen or (v.parent and v.parent not in seen):
                raise ValueError('Duplicate view or missing preceding parent')
            if bool(v.parent) != bool(v.section_line_mm):
                raise ValueError('Sections require parent and cutting line')
            if v.minimum_hatched_faces and not v.parent:
                raise ValueError('Hatch validation requires a section view')
            if v.crop_mm and len(v.crop_mm) != 4:
                raise ValueError('Crop requires four model-coordinate corners')
            seen.add(v.id)
        for d in self.dimensions:
            if d.view not in seen:
                raise ValueError('Unknown dimension view')
        return self


def load_layout(path):
    """读取严格的布局文件，不接受任意代码。"""
    return DrawingLayout.model_validate_json(Path(path).read_text(encoding='utf-8-sig'))


def transform_point(values, matrix):
    """按 SOLIDWORKS MathTransform 的行向量、缩放及平移约定投影点。"""
    xyz=list(values); m=list(matrix)
    if len(xyz)!=3 or len(m)!=16: raise ValueError('Expected 3D point and 16-value transform')
    return [m[12]*sum(xyz[i]*m[3*i+j] for i in range(3))+m[9+j] for j in range(3)]


def require_section_hatches(view, minimum, view_id):
    """要求实际剖切填充；拒绝只有剖视名称而没有剖切几何的失败结果。"""
    from scripts.sw_connect import get_com_member as get
    count = int(get(view, 'GetFaceHatchCount'))
    if count < minimum:
        raise RuntimeError(f'Section {view_id} has {count} hatched faces, requires {minimum}')
    return count


def create_layout(sw, source, spec, dry_run=True, *, _drawing=None, _sheet_name=None):
    """创建独立图纸；参考尺寸保留原生尺寸实体，明确为快照而非模型关联。"""
    from scripts.sw_connect import get_com_member as get, new_document, create_empty_dispatch_variant
    from scripts.sw_operation_guard import check_document_target
    from scripts.sw_export import export_to_dxf
    import pythoncom
    from win32com.client import VARIANT
    source_path = str(get(source,'GetPathName'))
    source_title = str(get(source,'GetTitle'))
    if int(get(source,'GetType')) not in (1,2) or not source_path:
        raise ValueError('A saved part or assembly is required')
    targets = [Path(spec.output_path)]
    if spec.export_pdf: targets.append(Path(spec.output_path).with_suffix('.pdf'))
    if spec.export_dxf: targets.append(Path(spec.output_path).with_suffix('.dxf'))
    if _drawing is None and any(p.exists() for p in targets):
        raise FileExistsError('Refusing to replace an existing drawing or export')
    named_views = list(get(source,'GetModelViewNames') or [])
    for view in spec.views:
        if not view.parent and view.named_view not in named_views:
            raise ValueError(f'Unknown model view {view.named_view}; available={named_views}')
    if dry_run:
        return {'status':'ready','source_path':source_path,'named_views':named_views,
                'layout':spec.model_dump(),'manual_review_required':True}
    targets[0].parent.mkdir(parents=True,exist_ok=True)
    draw = _drawing if _drawing is not None else new_document(sw,'drawing',spec.template_path)
    if _drawing is not None:
        check_document_target(get(draw,'GetPathName'),get(draw,'GetTitle'),expected_path=spec.output_path,required=True)
        if not draw.NewSheet3(_sheet_name,12,13,1.,1.,True,'',spec.size_mm[0]/1000,spec.size_mm[1]/1000,''):
            raise RuntimeError('NewSheet3 failed')
    title = str(get(draw,'GetTitle'))
    null = create_empty_dispatch_variant()
    vec = lambda values: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,tuple(values))
    def guard():
        active=get(sw,'ActiveDoc')
        check_document_target(get(active,'GetPathName'),get(active,'GetTitle'),
            expected_path=spec.output_path if get(draw,'GetPathName') else None,
            expected_title=None if get(draw,'GetPathName') else title,required=True)
    def save():
        guard()
        errors=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        warnings=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        if not draw.Extension.SaveAs(spec.output_path,0,1,null,errors,warnings) or errors.value:
            raise RuntimeError(f'Drawing save failed: {errors.value}, {warnings.value}')
    active = get(sw, 'ActiveDoc')
    if get(active, 'GetTitle') != title:
        raise RuntimeError(f'New drawing is not active: created={title!r}, active={get(active, "GetTitle")!r}')
    if _sheet_name and not get(draw,'GetPathName'): save()
    sheet=get(draw,'GetCurrentSheet')
    if _sheet_name:
        sheet.SetName(_sheet_name)
    sheet_name=str(get(sheet,'GetName'))
    guard()
    if not draw.SetupSheet5(sheet_name,12,13,1.,1.,True,'',spec.size_mm[0]/1000,spec.size_mm[1]/1000,'',True):
        raise RuntimeError('SetupSheet5 failed')
    # 清除模板图框，避免与调用者布局重叠。
    template=get(sheet,'GetTemplateName')
    if template:
        sheet.SetTemplateName('')
        draw.ReloadTemplate(False)
    for text_pref in (10,23,24,25,26):
        fmt=draw.Extension.GetUserPreferenceTextFormat(text_pref,0)
        fmt.CharHeight=.003;fmt.Italic=False;fmt.Bold=False;fmt.TypeFaceName='Arial'
        draw.Extension.SetUserPreferenceTextFormat(text_pref,0,fmt)
    draw.SetUserPreferenceToggle(6,False)
    draw.Extension.SetUserPreferenceInteger(47,0,0)
    draw.Extension.SetUserPreferenceInteger(24,0,2)
    save()
    result={'status':'created','source_path':source_path,'drawing_path':spec.output_path,
            'views':[],'dimensions':[],'notes':[], 'manual_review_required':True,
            'dimension_attachment':'projected_model_coordinate_snapshot'}
    views={}
    def transform(values, matrix):
        return transform_point(values,get(matrix,'ArrayData'))
    def project(v, xyz, sketch=False):
        arr=transform([x/1000 for x in xyz],get(v,'ModelToViewTransform')); arr[2]=0
        if sketch: arr=transform(arr,get(get(v,'GetSketch'),'ModelToSketchTransform'))
        return arr
    def center(v, xy):
        draw.ForceRebuild3(False)
        box=list(get(v,'GetOutline')); pos=list(get(v,'Position'))
        pos[0]+=xy[0]/1000-(box[0]+box[2])/2
        pos[1]+=xy[1]/1000-(box[1]+box[3])/2
        v.Position=vec(pos)
        draw.ForceRebuild3(False)
    for vs in spec.views:
        guard(); draw.ClearSelection2(True)
        if vs.parent:
            parent=views[vs.parent]
            draw.ActivateView(get(parent,'GetName2'))
            a,b=[project(parent,p,True) for p in vs.section_line_mm]
            sm=get(draw,'SketchManager'); sm.AddToDB=True
            try: line=sm.CreateLine(*a,*b)
            finally: sm.AddToDB=False
            if line is None or not line.Select4(False,null):
                raise RuntimeError('Cannot select native section cutting line')
            v=draw.CreateSectionViewAt5(vs.center_mm[0]/1000,vs.center_mm[1]/1000,0.,vs.section_label,1,null,0.)
            if v is None or get(v,'GetSection') is None:
                raise RuntimeError('Native section creation failed')
            sec=get(v,'GetSection'); sec.SetPartialSection(False); sec.SetDisplayOnlySurfaceCut(False); sec.SetAutoHatch(True)
            fmt=get(sec,'GetTextFormat'); fmt.CharHeight=.0025; fmt.Italic=False; fmt.TypeFaceName='Arial'
            sec.SetTextFormat(False,fmt)
            v.UseParentScale=False
        else:
            v=draw.CreateDrawViewFromModelView3(source_path,vs.named_view,vs.center_mm[0]/1000,vs.center_mm[1]/1000,0.)
            if v is None: raise RuntimeError('Native model view creation failed')
        v.UseSheetScale=0; v.ScaleDecimal=vs.scale
        v.SetDisplayMode4(False,2,False,True,True)
        if vs.crop_mm:
            draw.ClearSelection2(True); draw.ActivateView(get(v,'GetName2'))
            points=[project(v,p,True) for p in vs.crop_mm]
            sm=get(draw,'SketchManager'); sm.AddToDB=True
            try: lines=[sm.CreateLine(*points[i],*points[(i+1)%4]) for i in range(4)]
            finally: sm.AddToDB=False
            draw.ClearSelection2(True)
            for i,line in enumerate(lines):
                if line is None or not line.Select4(i!=0,null): raise RuntimeError('Crop selection failed')
            if v.Crop2(False,False,5)!=1 or not get(v,'IsCropped'): raise RuntimeError('Native view crop failed')
        center(v,vs.center_mm)
        actual_source=str(get(v,'GetReferencedModelName'))
        check_document_target(actual_source,source_title,expected_path=source_path,required=True)
        if abs(float(get(v,'ScaleDecimal'))-vs.scale)>1e-8: raise RuntimeError('View scale mismatch')
        hatch_count=require_section_hatches(v,vs.minimum_hatched_faces,vs.id) if vs.parent else 0
        views[vs.id]=v
        result['views'].append({'id':vs.id,'name':get(v,'GetName2'),'source':actual_source,
            'scale':get(v,'ScaleDecimal'),'outline_m':list(get(v,'GetOutline')),
            'native_section':get(v,'GetSection') is not None,'hatched_face_count':hatch_count,'cropped':bool(get(v,'IsCropped')),
            'model_to_view':list(get(get(v,'ModelToViewTransform'),'ArrayData'))})
    old_prompt = bool(sw.GetUserPreferenceToggle(10))
    sw.SetUserPreferenceToggle(10, False)
    try:
        for ds in spec.dimensions:
            guard(); v=views[ds.view]; draw.ClearSelection2(True); draw.ActivateView(get(v,'GetName2'))
            sm=get(draw,'SketchManager'); sm.AddToDB=True
            try: points=[sm.CreatePoint(*project(v,p,True)) for p in ds.points_mm]
            finally: sm.AddToDB=False
            draw.ClearSelection2(True)
            for i,p in enumerate(points):
                if p is None or not p.Select4(i!=0,null): raise RuntimeError('Dimension point selection failed')
            a,b=[project(v,p) for p in ds.points_mm]
            at=[(a[i]+b[i])/2+ds.offset_mm[i]/1000 for i in range(2)]
            fn={'horizontal':'AddHorizontalDimension2','vertical':'AddVerticalDimension2','aligned':'AddDimension2'}[ds.kind]
            dd=getattr(draw,fn)(at[0],at[1],0.)
            if dd is None: raise RuntimeError('Native dimension creation failed')
            dimension=dd.GetDimension2(0)
            actual=float(get(dimension,'SystemValue'))*1000
            if abs(actual-ds.expected_mm)>ds.tolerance_mm:
                raise RuntimeError(f'Dimension value {actual} differs from expected {ds.expected_mm}')
            dd.SetPrecision2(2,2,2,2)
            ann=get(dd,'GetAnnotation'); fmt=ann.GetTextFormat(0)
            fmt.CharHeight=.0025; fmt.TypeFaceName='Arial'; fmt.Italic=False
            ann.SetTextFormat(0,False,fmt)
            if ds.prefix: dd.SetText(1,ds.prefix)
            result['dimensions'].append({'view':ds.view,'kind':ds.kind,'native_name':get(dimension,'FullName'),
                'actual_mm':actual,'expected_mm':ds.expected_mm,'model_points_mm':ds.points_mm,
                'associative_to_model':False})
    finally:
        sw.SetUserPreferenceToggle(10, old_prompt)
    draw.ClearSelection2(True); draw.ActivateView(''); draw.EditTemplate()
    sm=get(draw,'SketchManager'); sm.AddToDB=True
    try:
        for ls in spec.lines:
            a,b=ls.points_mm
            line=sm.CreateLine(a[0]/1000,a[1]/1000,0,b[0]/1000,b[1]/1000,0)
            if line is None: raise RuntimeError('Sheet line creation failed')
            line.ConstructionGeometry=ls.construction; line.Color=0
    finally: sm.AddToDB=False
    draw.EditSheet()
    for ns in spec.notes:
        guard(); draw.ClearSelection2(True); draw.ActivateView('')
        note=draw.InsertNote(ns.text)
        if note is None: raise RuntimeError('Note creation failed')
        ann=get(note,'GetAnnotation')
        fmt=ann.GetTextFormat(0); fmt.CharHeight=ns.height_mm/1000; fmt.TypeFaceName='Arial'; fmt.Bold=ns.bold; fmt.Italic=False
        ann.SetTextFormat(0,False,fmt)
        ann.SetPosition(ns.position_mm[0]/1000,ns.position_mm[1]/1000,0.)
        result['notes'].append({'text':str(get(note,'GetText')),'position_m':list(get(ann,'GetPosition'))})
    draw.ClearSelection2(True); draw.ActivateView(''); draw.ForceRebuild3(False); draw.ViewZoomtofit2()
    save()
    if spec.export_pdf:
        pdf_data=sw.GetExportFileData(1)
        errors=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        warnings=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        if not draw.Extension.SaveAs(str(targets[0].with_suffix('.pdf')),0,1,pdf_data,errors,warnings) or errors.value:
            raise RuntimeError(f'PDF export failed: {errors.value}')
    if spec.export_dxf and not export_to_dxf(draw,str(targets[0].with_suffix('.dxf'))): raise RuntimeError('DXF export failed')
    guard()
    result['document']={'path':get(draw,'GetPathName'),'title':get(draw,'GetTitle'),'type':get(draw,'GetType')}
    Path(spec.output_path).with_suffix('.audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def cancel_dimension_prompt(process_id, *, gui=None, processes=None):
    """验证尺寸输入窗体特有控件后取消；不触碰其他提示。"""
    if not isinstance(process_id,int) or process_id <= 0: raise ValueError('Explicit process ID required')
    if gui is None:
        import win32gui as gui
    if processes is None:
        import win32process as processes
    dismissed=[]
    def visit(handle,_):
        if processes.GetWindowThreadProcessId(handle)[1] != process_id: return True
        if not gui.IsWindowVisible(handle) or gui.GetClassName(handle) != '#32770': return True
        if gui.GetWindowText(handle) not in {'Modify','Изменить','修改'}: return True
        ids=set()
        gui.EnumChildWindows(handle,lambda child,_: ids.add(gui.GetDlgCtrlID(child)) or True,None)
        if not {1111,2222,5555,44168}.issubset(ids): return True
        if processes.GetWindowThreadProcessId(handle)[1] != process_id: return True
        gui.PostMessage(handle,0x10,0,0)
        dismissed.append(handle)
        return True
    gui.EnumWindows(visit,None)
    return {'status':'posted' if dismissed else 'no_matching_prompt','process_id':process_id,'dismissed':dismissed}


def inspect_sections(drawing):
    """读取当前图纸剖视的剖切定义、排除列表和填充数量。"""
    from scripts.sw_connect import get_com_member as get
    if int(get(drawing,'GetType'))!=3: raise ValueError('Drawing required')
    rows=[];v=get(drawing,'GetFirstView')
    while v is not None:
        sec=get(v,'GetSection')
        if sec is not None:
            excluded=list(get(sec,'GetExcludedComponents') or [])
            row={'name':get(v,'GetName2'),'source':get(v,'GetReferencedModelName'),
                 'excluded_components':[str(get(c,'Name2')) for c in excluded],
                 'auto_hatch':get(sec,'GetAutoHatch'),'partial':get(sec,'GetPartialSection'),
                 'surface_only':get(sec,'GetDisplayOnlySurfaceCut'),
                 'line_info':list(get(sec,'GetLineInfo') or []),
                 'exclude_fasteners':get(sec,'ExcludeFasteners'),
                 'exclude_slice_bodies':get(sec,'ExcludeSliceSectionBodies'),
                 'section_depth':get(sec,'SectionDepth'),'lightweight':bool(get(v,'IsLightweight')),
                 'visible_components':[str(get(c,'Name2')) for c in (get(v,'GetVisibleComponents') or [])]}
            for name in ['GetFaceHatchCount','GetFaceHatchesCount']:
                try:row[name]=get(v,name)
                except Exception:pass
            rows.append(row)
        v=get(v,'GetNextView')
    errors=[];f=get(drawing,'FirstFeature')
    while f is not None:
        try:
            code=get(f,'GetErrorCode')
            if code: errors.append({'name':get(f,'Name'),'type':get(f,'GetTypeName2'),'code':code})
        except Exception:pass
        sub=get(f,'GetFirstSubFeature')
        while sub is not None:
            code=get(sub,'GetErrorCode')
            if code: errors.append({'name':get(sub,'Name'),'type':get(sub,'GetTypeName2'),'code':code})
            sub=get(sub,'GetNextSubFeature')
        f=get(f,'GetNextFeature')
    return {'status':'inspected','sections':rows,'feature_errors':errors,'read_only':True}
