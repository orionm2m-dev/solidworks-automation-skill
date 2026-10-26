"""精确签名圆角的离线回归：真实辅助函数、单次构建、无保存。"""
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_guarded_fillet as guarded


class Line:
    _dispobj_=object()
    def __init__(self, start, end): self.start=start;self.end=end;self.LineParams=list(start)+[1.,0.,0.]
    def __call__(self,*args):raise AssertionError('COM default member must not be invoked')
    def IsLine(self):return True
    def IsCircle(self):return False
    def GetLength3(self,a,b):assert (a,b)==(0.,1.);return math.dist(self.start,self.end)


class Edge:
    def __init__(self,start,end):self.start=list(start);self.end=list(end);self.model=None;self.selectable=True
    def GetCurveParams2(self):return self.start+self.end+[0.,1.,999.,123.]
    def GetCurve(self):return Line(self.start,self.end)
    def GetCurveParams3(self):return N(StartPoint=self.start,EndPoint=self.end,UMinValue=0.,UMaxValue=1.)
    def GetTwoAdjacentFaces2(self):return []
    def Select4(self,append,data):
        if self.selectable:self.model.selected.append(self)
        return self.selectable


@pytest.fixture
def model_graph(tmp_path,monkeypatch):
    path=tmp_path/'working.sldprt';path.write_bytes(b'saved source')
    edges=[Edge((0,0,0),(.01,0,0)),Edge((0,.002,0),(.01,.002,0))]
    state=dict(volume=1e-6,null=False,radius_factor=1.,calls=[],invalid=False)
    model=N(selected=[],dirty=False,features=[N(Name='Base',GetTypeName2=lambda:'Imported')])
    for edge in edges:edge.model=model
    body=N(GetEdges=lambda:edges,Check3=N(Count=0),GetMassProperties=lambda d:[0.,0.,0.,state['volume']]+[0.]*8,
        GetBodyBox=lambda:[0.,0.,0.,.01,.01,.01])
    model.GetBodies2=lambda kind,visible:[body] if kind==0 else []
    model.GetPathName=lambda:str(path);model.GetType=lambda:1;model.GetSaveFlag=lambda:model.dirty
    model.ClearSelection2=lambda all:model.selected.clear()
    model.SelectionManager=N(GetSelectedObjectCount2=lambda mark:len(model.selected),
        GetSelectedObject6=lambda index,mark:model.selected[index-1])
    def first():
        for i,f in enumerate(model.features):f.GetNextFeature=lambda i=i:model.features[i+1] if i+1<len(model.features) else None
        return model.features[0]
    model.FirstFeature=first
    def create(options,radius,r1,r2):
        state['calls'].append((options,radius,r1,r2));assert options==194
        intent=json.loads((tmp_path/'operation.json').read_text())
        assert intent['native_call_attempted'] and not intent['native_call_returned']
        model.dirty=True
        if state['null']:return None
        feature=N(Name='ExactFillet',GetTypeName2=lambda:'Fillet',
            GetDefinition=lambda:N(DefaultRadius=radius*state['radius_factor'],Type=0,IsMultipleRadius=False))
        model.features.append(feature)
        if state['invalid']:body.Check3.Count=1
        return feature
    model.FeatureManager=N(FeatureFillet=create)
    model.ForceRebuild3=lambda top:True
    model.Save3=Mock(side_effect=AssertionError('must not save'))
    sw=N(GetProcessID=lambda:81,ActiveDoc=model,IsSame=lambda left,right:1 if left is right else 0)
    import scripts.sw_connect as connect
    monkeypatch.setattr(connect,'create_empty_dispatch_variant',lambda:object())
    args=dict(process_id=81,expected_document_path=str(path),radius_mm=.2,
        edge_signatures=[guarded.inspect_edge(edges[0])['signature']],expected_edge_count=1,dry_run=True)
    def prepare(**changes):return guarded.configure_fillet(sw,**(args|changes))
    def apply(prepared=None,**changes):
        prepared=prepared or prepare();assert prepared['status']=='ok',prepared
        return prepare(**(dict(dry_run=False,expected_selection_sha256=prepared['selection_sha256'],
            receipt_path=str(tmp_path/'operation.json'))|changes))
    return N(**locals())


def test_line_signature_uses_documented_curve_length_and_native_trim_endpoints():
    edge=Edge((.01,.002,0),(0,.002,0));result=guarded.inspect_edge(edge)
    assert result['errors']==[] and result['box_basis']=='exact_line_endpoints'
    assert result['signature']['length_mm']==10.
    assert result['signature']['endpoints_mm']==[[0.,2.,0.],[10.,2.,0.]]
    assert result['signature']['box_mm']==[0.,2.,0.,10.,2.,0.]


def test_circle_signature_reports_supporting_circle_not_trimmed_arc():
    edge=Edge((.001,0,0),(0,.001,0))
    curve=N(IsLine=lambda:False,IsCircle=lambda:True,CircleParams=[0.,0.,0.,0.,0.,1.,.001],
        GetLength3=lambda a,b:math.pi*.001/2.,Evaluate2=lambda p,d:[.001/math.sqrt(2),.001/math.sqrt(2),0.])
    edge.GetCurve=lambda:curve
    result=guarded.inspect_edge(edge)
    assert result['signature']['curve_type']=='circle'
    assert result['box_basis']=='supporting_circle_not_trimmed_arc'
    assert result['signature']['box_mm']==[-1.,-1.,0.,1.,1.,0.]


def test_prepare_is_readonly_and_stable_across_edge_order_and_new_wrappers(model_graph):
    p=model_graph;first=p.prepare();p.edges.reverse()
    second=p.prepare()
    assert first['selection_sha256']==second['selection_sha256'] and p.state['calls']==[]
    assert p.model.selected==[] and not p.model.dirty and not (p.tmp_path/'operation.json').exists()


def test_exact_apply_one_native_call_radius_readback_no_save(model_graph):
    p=model_graph;result=p.apply()
    assert result['status']=='review_required' and result['radius_verified'] and result['feature_tree_verified'],result
    assert result['valid_single_solid'] and result['actual_radius_mm']==.2
    assert p.state['calls']==[(194,.0002,0,0)] and not result['model_saved']
    p.model.Save3.assert_not_called();assert p.path.read_bytes()==b'saved source'


@pytest.mark.parametrize('change',['unselected_geometry','selected_geometry','file','feature_tree','radius','dirty'])
def test_state_guard_rejects_changed_shape_file_radius_or_history(model_graph,change):
    p=model_graph;prepared=p.prepare();kw={}
    if change=='unselected_geometry':p.edges[1].end[0]+=.001
    elif change=='selected_geometry':p.edges[0].end[0]+=.001
    elif change=='file':p.path.write_bytes(b'changed saved file')
    elif change=='feature_tree':p.model.features.append(N(Name='Another',GetTypeName2=lambda:'Cut'))
    elif change=='radius':kw['radius_mm']=.3
    else:p.model.dirty=True
    result=p.apply(prepared,**kw)
    assert result['status']=='error' and not result['mutation_attempted'] and not p.state['calls']


def test_ambiguous_duplicate_geometry_stops_before_selection(model_graph):
    p=model_graph;p.edges.append(Edge(p.edges[0].start,p.edges[0].end))
    result=p.prepare()
    assert result['status']=='error' and not p.state['calls'] and p.model.selected==[]


def test_duplicate_requested_signatures_stop(model_graph):
    p=model_graph;result=p.prepare(edge_signatures=p.args['edge_signatures']*2,expected_edge_count=2)
    assert result['status']=='error' and not p.state['calls']


@pytest.mark.parametrize('mode',['null','wrong_radius','invalid_solid'])
def test_failed_native_result_keeps_receipt_and_reads_state_without_replay(model_graph,mode):
    p=model_graph
    if mode=='null':p.state['null']=True
    elif mode=='wrong_radius':p.state['radius_factor']=.5
    else:p.state['invalid']=True
    result=p.apply()
    assert result['status']=='uncertain' and len(p.state['calls'])==1
    assert result['native_call_attempted'] and result['native_call_returned']
    assert 'failure_readback' in result or 'failure_readback_issue' in result
    p.model.Save3.assert_not_called()


def test_selection_failure_prevents_native_fillet(model_graph):
    p=model_graph;p.edges[0].selectable=False;result=p.apply()
    assert result['status']=='error' and not p.state['calls']


def test_existing_operation_receipt_blocks_before_selection(model_graph):
    p=model_graph;receipt=p.tmp_path/'operation.json';receipt.write_bytes(b'keep original attempt')
    result=p.apply();assert result['status']=='error' and not p.state['calls']
    assert receipt.read_bytes()==b'keep original attempt'


def test_dirty_prepare_blocks_before_mutation(model_graph):
    p=model_graph;p.model.dirty=True
    assert p.prepare()['status']=='error' and p.state['calls']==[]

def test_local_inspection_only_reads_detailed_geometry_for_selected_region(model_graph):
    p=model_graph
    p.edges[1].GetCurve=lambda:(_ for _ in ()).throw(AssertionError('unselected detailed geometry'))
    result=guarded.inspect_local_edges(p.model,[-1,-.1,-.1,11,.1,.1])
    assert result['matched_count']==1
    assert result['edges'][0]['signature']==p.args['edge_signatures'][0]

def test_fast_trim_excludes_non_geometric_curve_tags(model_graph):
    p=model_graph;a=p.prepare()
    p.edges[1].GetCurveParams2=lambda:p.edges[1].start+p.edges[1].end+[0.,1.,12345.,54321.]
    assert p.prepare()['selection_sha256']==a['selection_sha256']
