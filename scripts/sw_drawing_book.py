"""多页原生工程图，所有页共享一个文档编号与受保护的源模型。"""
from pathlib import Path
import json
from pydantic import Field, model_validator
from scripts.sw_drawing_layout import Strict,DrawingLayout,create_layout


class BookSheet(Strict):
    name: str = Field(min_length=1,max_length=80)
    layout: DrawingLayout


class DrawingBook(Strict):
    output_path: str
    sheets: list[BookSheet] = Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def check_sheets(self):
        """拒绝重复页名及不一致的输出目标。"""
        if len({s.name.casefold() for s in self.sheets})!=len(self.sheets):raise ValueError('Duplicate sheet name')
        if any(s.layout.output_path!=self.output_path for s in self.sheets):raise ValueError('All sheets must share the book output path')
        return self


def create_book(sw,source,book,dry_run=True):
    """逐页建立真实视图与尺寸，最后导出全部页；不能覆盖已有文件。"""
    from scripts.sw_connect import get_com_member as get
    from scripts.sw_operation_guard import check_document_target
    from scripts.sw_export import export_to_dxf
    import pythoncom
    from win32com.client import VARIANT
    output=Path(book.output_path)
    for ext in ['.SLDDRW','.pdf','.dxf','.audit.json']:
        if output.with_suffix(ext).exists():raise FileExistsError(output.with_suffix(ext))
    for sheet in book.sheets:create_layout(sw,source,sheet.layout,dry_run=True)
    if dry_run:return {'status':'ready','sheet_names':[s.name for s in book.sheets]}
    draw=None;results=[]
    for sheet in book.sheets:
        spec=sheet.layout.model_copy(update={'export_pdf':False,'export_dxf':False})
        result=create_layout(sw,source,spec,dry_run=False,_drawing=draw,_sheet_name=sheet.name)
        draw=get(sw,'ActiveDoc');results.append({'sheet_name':sheet.name,**result})
    check_document_target(get(draw,'GetPathName'),get(draw,'GetTitle'),expected_path=book.output_path,required=True)
    names=list(get(draw,'GetSheetNames'))
    if names!=[s.name for s in book.sheets]:raise RuntimeError('Saved sheet names mismatch')
    pdf=sw.GetExportFileData(1)
    pdf.SetSheets(1,VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,tuple(names)))
    error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0);warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    if not draw.Extension.SaveAs(str(output.with_suffix('.pdf')),0,1,pdf,error,warning) or error.value:raise RuntimeError(f'PDF export failed {error.value}')
    old=sw.GetUserPreferenceIntegerValue(253)
    try:
        sw.SetUserPreferenceIntegerValue(253,2)
        if not export_to_dxf(draw,str(output.with_suffix('.dxf'))):raise RuntimeError('DXF export failed')
    finally:sw.SetUserPreferenceIntegerValue(253,old)
    result={'status':'created','drawing_path':book.output_path,'source_path':get(source,'GetPathName'),
            'sheets':results,'sheet_count':len(names),'sheet_names':names,'manual_review_required':True,
            'document':{'path':get(draw,'GetPathName'),'title':get(draw,'GetTitle'),'type':get(draw,'GetType')}}
    output.with_suffix('.audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
