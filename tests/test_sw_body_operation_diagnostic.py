import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_body_operation_diagnostic as m

def row(i): return dict(check3=0,volume_m3=10. if i==0 else 1.,box_model_m=[i,0,0,i+1,1,1])

def test_match_bijection():
    assert m._match_rows([row(1),row(0)],[row(0),row(1)])==[1,0]

@pytest.mark.parametrize("bad",[[row(0)],[row(0),row(0)],[row(0),dict(row(1),check3=2)]])
def test_match_rejects_changes(bad):
    with pytest.raises(ValueError):m._match_rows(bad,[row(0),row(1)])

class Body:
    def __init__(self,index,temp=False):self.index=index;self.temp=temp
    def Copy(self): return Body(self.index,True)
    def IsTemporaryBody(self):return self.temp
    def ApplyTransform(self,t):return True
class Model:
    Visible=False
    def GetPathName(self):return self.path
    def GetModelViewCount(self):return 0
class SW:
    UserControl=True
    def GetProcessID(self):return 42
    def IsSame(self,a,b):return int(a is b)
    def GetMathUtility(self):return self
    def CreateTransform(self,data):return object()

@pytest.fixture
def world(tmp_path,monkeypatch):
    output=tmp_path/'out.sldprt';output.write_bytes(b'original')
    digest=m._file_hash(output)
    receipt=tmp_path/'failed.json'
    rows=[row(i) for i in range(5)]
    prior=dict(status='uncertain',phase='finished',mode='subtract_delta',
        failed_phase='InsertCombineFeature_SUBTRACT_DELTA_returned',
        output_path=str(output),copied_source_sha256=digest,
        before=dict(config=dict(process_id=42,expected_document_path=str(tmp_path/'anchor.sldprt')),frozen_files={}),
        open_donor=dict(title='donor'),inserted_bodies=dict(bodies=rows),body_before=dict(bodies=[rows[0]]))
    receipt.write_text(json.dumps(prior))
    model=Model();model.path=str(output)
    sw=SW();sw.ActiveDoc=model
    bodies=[Body(i) for i in range(5)]
    docs=[dict(path=str(output),title='out',type=1),dict(path=str(tmp_path/'anchor.sldprt'),title='anchor',type=1),dict(path='',title='donor',type=1)]
    def stats(obj):
        found=obj.bodies if isinstance(obj,m._TemporaryPart) else bodies
        return dict(bodies=[row(b.index) for b in found]),found
    monkeypatch.setattr(m,'_stats',stats)
    monkeypatch.setattr(m,'_documents',lambda obj:docs)
    monkeypatch.setattr(m,'_features',lambda obj:['Imported1'])
    monkeypatch.setattr(m,'_double_array',lambda data:data)
    args=dict(process_id=42,transfer_receipt_path=str(receipt),transfer_receipt_sha256=m._file_hash(receipt),receipt_path=str(tmp_path/'result.json'))
    return sw,args,bodies

def test_one_source_cut_success_no_control(world,monkeypatch):
    sw,args,bodies=world;calls=[]
    def op(a,b):
        assert a.temp and b.temp and a not in bodies and b not in bodies
        calls.append((a,b));return [Body(0,True)],0
    monkeypatch.setattr(m,'_operations_cut',op)
    result=m.diagnose_retained_subtraction(sw,**args)
    assert result['status']=='ok' and result['document_unchanged_verified']
    assert result['active_visible'] is False and result['active_model_view_count']==0
    assert len(calls)==1 and not result['document_mutation_attempted']
    with pytest.raises(ValueError):m.diagnose_retained_subtraction(sw,**args)

def test_failure_runs_one_control_with_fresh_copies(world,monkeypatch):
    sw,args,bodies=world;seen=[]
    def op(a,b):
        assert all(a is not x and b is not x for pair in seen for x in pair)
        seen.append((a,b));return ([],1040) if len(seen)==1 else ([Body(1,True)],0)
    monkeypatch.setattr(m,'_operations_cut',op)
    result=m.diagnose_retained_subtraction(sw,**args)
    assert result['status']=='ok' and len(seen)==2
    assert result['calls'][0]['error_name']=='PartialCoincidence'
    assert result['calls'][1]['returned'] and result['document_unchanged_verified']

def test_exception_does_not_retry(world,monkeypatch):
    sw,args,bodies=world
    def op(a,b):raise RuntimeError('transport')
    monkeypatch.setattr(m,'_operations_cut',op)
    result=m.diagnose_retained_subtraction(sw,**args)
    assert result['status']=='uncertain' and result['temporary_operations_attempted']==1
    assert result['calls'][0]['returned'] is False

def test_wrong_pid_no_copy(world,monkeypatch):
    sw,args,bodies=world;args['process_id']=43
    with pytest.raises(ValueError):m.diagnose_retained_subtraction(sw,**args)

def test_document_change_detected(world,monkeypatch):
    sw,args,bodies=world
    def op(a,b):bodies.pop();return [],4
    monkeypatch.setattr(m,'_operations_cut',op)
    result=m.diagnose_retained_subtraction(sw,**args)
    assert result['status']=='uncertain' and 'final_verification_issue' in result

def test_typed_operations_binding(monkeypatch):
    import pythoncom
    calls=[]
    class Ole:
        def InvokeTypes(self,*args):calls.append(args);return (None,1040)
    target=SimpleNamespace(_oleobj_=Ole());tool=SimpleNamespace(_oleobj_=object())
    assert m._operations_cut(target,tool)==([],1040)
    assert calls==[(110,0,pythoncom.DISPATCH_METHOD,(pythoncom.VT_VARIANT,0),
      ((pythoncom.VT_I4,1),(pythoncom.VT_DISPATCH,1),(pythoncom.VT_BYREF | pythoncom.VT_I4,2)),15902,tool._oleobj_,pythoncom.Missing)]


def test_operations_out_parameter_matches_installed_typelib():
    import pythoncom
    path=Path(r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb")
    if not path.is_file():pytest.skip("Installed SolidWorks typelib not present")
    lib=pythoncom.LoadTypeLib(str(path))
    descriptors=[]
    for i in range(lib.GetTypeInfoCount()):
        if lib.GetDocumentation(i)[0]=="IBody2":
            info=lib.GetTypeInfo(i)
            for j in range(info.GetTypeAttr()[6]):
                desc=info.GetFuncDesc(j)
                if desc[0]==110:descriptors.append(desc)
    assert len(descriptors)==1
    desc=descriptors[0]
    assert desc[2][1][0]==pythoncom.VT_DISPATCH
    assert desc[2][2][0]==(pythoncom.VT_PTR,pythoncom.VT_I4)
    assert desc[2][2][1]==2
    assert desc[8][0]==pythoncom.VT_VARIANT
