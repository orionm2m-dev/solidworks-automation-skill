from copy import deepcopy
import ast
from pathlib import Path
import pytest
from scripts import sw_cam_local_optimization_cl as m
from scripts import sw_cam_local_operation_cl as old
from scripts import sw_cam_local_serial_optimization as main
from optimization_fixture import fixture

def test_export_native_body_unchanged():
    def tree(path):return ast.dump(next(n for n in ast.parse(Path(path).read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='export_current_cl'),include_attributes=False)
    assert tree(m.__file__)==tree(old.__file__)

def test_marker_ignores_pid_recipe_output(monkeypatch,tmp_path):
    monkeypatch.setattr(main.common,'local_evidence_root',lambda:tmp_path)
    a=dict(expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,process_id=123,recipe_sha256='b'*64,receipt_path='old')
    b=dict(a,process_id=456,recipe_sha256='c'*64,receipt_path='new')
    assert main.marker_path(a)==main.marker_path(b)

def stream_fixture(monkeypatch):
    baseline,snap,targets,plan=fixture()
    rows=[dict(operation_native_id=o['native_id'],toolpath_record_counts=o['toolpath_record_counts'])for o in snap['binding']['operations']if o['toolpath_generated']]
    a=dict(declared_units=['MM'],commands=[],signatures=list(range(14)))
    b=dict(declared_units=['MM'],commands=[],signatures=list(range(18)),cutcom_records=[],motions=[dict(block=i,cutcom_state=dict(status='not_declared'))for i in range(14,18)])
    monkeypatch.setattr(m.review,'block_signature',lambda p,i:p['signatures'][i])
    return a,b,rows[:14],rows,targets,snap

def test_pure_protected14_identity(monkeypatch):
    args=stream_fixture(monkeypatch)
    assert m.verify_streams(*args)['protected_count']==14

@pytest.mark.parametrize('damage',['CUTCOM','protected','alias','unit','count','motion'])
def test_rejected_stream_drift(monkeypatch,damage):
    a,b,old,rows,t,s=stream_fixture(monkeypatch)
    if damage=='CUTCOM':b['cutcom_records']=[dict(block=14)]
    elif damage=='protected':b['signatures'][0]=999
    elif damage=='alias':b['signatures'][14]=b['signatures'][0]
    elif damage=='unit':b['declared_units']=['INCH']
    elif damage=='count':rows[-1]['toolpath_record_counts']=[666]
    else:b['motions']=b['motions'][1:]
    with pytest.raises(ValueError):m.verify_streams(a,b,old,rows,t,s)
