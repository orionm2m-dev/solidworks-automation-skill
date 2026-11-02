from cam_mixed_test_support import ROOT, SCRIPTS, evidence_file, evidence_json, server_nodes, synthetic_specs, synthetic_context
import ast
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

STAGE=SCRIPTS
from scripts import sw_cam_mixed_arc_diagnostic as m

class Curve:
    def GetEndParams(self,low,high,closed,periodic):
        low.value=0.;high.value=6.283185307179586;closed.value=True;periodic.value=True
        return True
    def GetClosestPointOn(self,*point):return [*point,1.25]
    def Evaluate2(self,u,n):return [u,0.,0.]


def test_raw_closed_periodic_underlying_curve_is_preserved():
    got=m.raw_end_params(Curve(),call=lambda obj,name,*args:getattr(obj,name)(*args))
    assert got['closed'] is True and got['periodic'] is True
    assert got['returned'] is True and got['high']>got['low']
    assert got['closed_type']=='bool'


def failed():
    return dict(scope=m.parent.SCOPE,module_pin=m.common._pin(m.parent.__file__),status='uncertain',phase='finished',
        cleanup_session_active=False,new_feature_ids=[],actions={'CreateSketch:0':dict(status='pending',attempted=True,
        returned=False,readback_verified=False,native_dispatch_pending=True)},
        **{k:False for k in ('save_attempted','model_saved','readback_verified','continuation_ready','GOP_attempted','GTP_attempted',
                            'SetTool_attempted','operation_creation_attempted','tool_creation_attempted')},
        issue=dict(type='ValueError',locations=[dict(file='sw_cam_mixed_profile.py',function='curve_interval',line=150)]),
        sketch_creations=[dict(sketch_edit_exited=True)],
        profile_specs=[dict(sketch_name='RootRestProfile1',plane_name='RootRestPlane1')])


def test_exact_partial_failure_accepted_without_normalization():
    r=failed();before=deepcopy(r);assert m.failed_contract(r) is r;assert r==before

@pytest.mark.parametrize('key',['save_attempted','GTP_attempted','GOP_attempted','SetTool_attempted','model_saved','continuation_ready'])
def test_later_action_rejected(key):
    r=failed();r[key]=True
    with pytest.raises(ValueError):m.failed_contract(r)

@pytest.mark.parametrize('field,value',[('new_feature_ids',[340]),('cleanup_session_active',True),('status','success')])
def test_wrong_partial_boundary_rejected(field,value):
    r=failed();r[field]=value
    with pytest.raises(ValueError):m.failed_contract(r)


def test_wrong_error_location_rejected():
    r=failed();r['issue']['locations'][0]['line']=151
    with pytest.raises(ValueError):m.failed_contract(r)


def test_existing_sketch_must_be_closed():
    r=failed();r['sketch_creations'][0]['sketch_edit_exited']=False
    with pytest.raises(ValueError):m.failed_contract(r)


def test_raw_reader_records_direction_without_interpreting_it(monkeypatch):
    curve=Curve()
    class Segment:
        ConstructionGeometry=False
        def __init__(self,kind):self.kind=kind
        def GetType(self):return self.kind
        def GetStartPoint2(self):return [0.,0.,0.]
        def GetEndPoint2(self):return [1.,0.,0.]
        def GetLength(self):return 1.
        def IsCircle(self):return 0
        def GetRotationDir(self):return -1
        def GetNormalVector(self):return [0.,0.,1.]
        def GetCenterPoint2(self):return [0.5,0.,0.]
        def GetRadius(self):return .5
        def GetCurve(self):return curve
    transform=SimpleNamespace(ArrayData=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.],Inverse=lambda:None)
    sketch=SimpleNamespace(Is3D=lambda:False,GetSketchSegments=lambda:[Segment(1)]+[Segment(0)for _ in range(12)],ModelToSketchTransform=transform)
    sw=SimpleNamespace(GetMathUtility=lambda:None)
    monkeypatch.setattr(m.core,'call',lambda obj,name,*args:getattr(obj,name)(*args))
    monkeypatch.setattr(m.core,'_typed_segment',lambda seg,kind:seg)
    monkeypatch.setattr(m.core,'_point_values',lambda p:p)
    monkeypatch.setattr(m.core,'_point',lambda mu,p,t:p)
    monkeypatch.setattr(m.core,'_rigid_transform',lambda t:None)
    report={};writes=[]
    rows=m.read_rows(sw,sketch,check=lambda:None,persist=lambda:writes.append(deepcopy(report)),report=report)
    assert len(rows)==13 and rows[0]['rotation_direction_raw']==-1
    assert rows[0]['underlying_curve_end_params_raw']['closed'] is True
    assert len(rows[0]['underlying_curve_samples_raw'])==5
    assert any('underlying_curve_end_params_raw'in v['native_entities'][0] and 'underlying_curve_samples_raw'not in v['native_entities'][0] for v in writes)
    assert not any('mid_model_m'in row for row in rows)


def test_read_only_calls_have_no_creation_or_save():
    text=Path(m.__file__).read_text('utf-8-sig');tree=ast.parse(text)
    blocked={'InsertSketch','Create3PointArc','CreateLine','ClearSelection2','Select2','SaveActiveDocument',
             'CreateMillFeature2','GenerateToolpath','GenerateOpPlan','SetTool','CloseDoc','OpenDoc6'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            if isinstance(node.func,ast.Attribute):assert node.func.attr not in blocked
            if isinstance(node.func,ast.Attribute)and node.func.attr=='call' and len(node.args)>1 and isinstance(node.args[1],ast.Constant):
                assert node.args[1].value not in blocked

@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,'1'])
def test_nonfinite_native_values_rejected(value):
    with pytest.raises(ValueError):m.finite(value)

def test_wrapper_is_bounded_and_read_only():
    tree=ast.parse((ROOT/'mcp-server/server.py').read_text('utf-8-sig'))
    found=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='solidworks_cam_read_existing_mixed_arc')
    text=ast.unparse(found)
    assert "'readOnlyHint': True"in text
    assert 'desktop_guard=True'in text
    assert 'Explicit owned process connection required'in text
    assert '_cam_mixed_arc_diagnostic_sealed_payload'in text


def test_sealed_wrapper_checks_digest_and_implementation(tmp_path):
    import hashlib,json
    tree=ast.parse((ROOT/'mcp-server/server.py').read_text('utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_cam_mixed_arc_diagnostic_sealed_payload')
    ns={'SCRIPTS_DIR':str(STAGE)};exec(compile(ast.Module(body=[node],type_ignores=[]),'<sealed-wrapper>','exec'),ns)
    payload=dict(action='read_existing_mixed_arc',params=dict(process_id=123,module_sha256=m.parent._file_hash(m.__file__),receipt_path=str(tmp_path/'out.json')))
    path=tmp_path/'request.json';path.write_text(json.dumps(payload));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    check=ns[node.name];assert check(str(path),digest,123)==payload
    with pytest.raises(ValueError):check(str(path),'0'*64,123)
    with pytest.raises(ValueError):check(str(path),digest,124)
    payload['params']['module_sha256']='0'*64;path.write_text(json.dumps(payload));digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):check(str(path),digest,123)

