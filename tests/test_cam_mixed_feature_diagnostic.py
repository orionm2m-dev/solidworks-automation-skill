from cam_mixed_test_support import ROOT, SCRIPTS, evidence_file, evidence_json, server_nodes, synthetic_specs, synthetic_context
from copy import deepcopy
import ast,inspect,json,os,sys,types
from pathlib import Path
from types import SimpleNamespace
import pytest
R=ROOT;S=SCRIPTS
from scripts import sw_cam_mixed_feature_diagnostic as m


def partial():
    return dict(scope=m.previous.SCOPE,module_pin=m.common._pin(m.previous.__file__),status='uncertain',phase='finished',cleanup_session_active=False,new_feature_ids=[339],
        actions={'CreatePocket:0':dict(status='pending',attempted=True,returned=False,readback_verified=False,native_dispatch_pending=True)},
        **{k:False for k in ('save_attempted','model_saved','readback_verified','continuation_ready','GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted')},
        issue={'type':'ValueError','locations':[{'file':'sw_cam_signed_mixed_profile.py','function':'match_rows','line':164}]},
        adopted_first_sketch={'read_only':True,'recreated':False},current_document={'needs_save':True},created_cad_features=[],before={'binding':{}},initial_context={'guide_parameters':{'expected_parameters':{'binding':{}}}})


def test_exact_uncertain_first_feature_contract_remains_uncertain():
    r=partial();assert m.failed_contract(r,339)is r;assert r['status']=='uncertain'

@pytest.mark.parametrize('key',['save_attempted','model_saved','GTP_attempted','GOP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted'])
def test_later_mutation_rejected(key):
    r=partial();r[key]=True
    with pytest.raises(ValueError):m.failed_contract(r,339)

@pytest.mark.parametrize('fault',['id','action','error','adoption','dirty','baseline'])
def test_other_boundary_rejected(fault):
    r=partial()
    if fault=='id':r['new_feature_ids']=[340]
    if fault=='action':r['actions']['CreateSketch:1']={}
    if fault=='error':r['issue']['locations'][0]['line']=165
    if fault=='adoption':r['adopted_first_sketch']['recreated']=True
    if fault=='dirty':r['current_document']['needs_save']=False
    if fault=='baseline':r['before']['binding']['x']=1
    with pytest.raises(ValueError):m.failed_contract(r,339)


def test_actual_constructor_and_read_only_callable_graph():
    loaded={'deep_targets':[],'guide_parameters':{'document':{'path':'part','type':1,'title':'part','needs_save':True}}}
    b=m.NativeBackend(loaded,{},None,'x','tlb',{},lambda:None)
    assert isinstance(b.capture,types.ModuleType)
    for name in ('save','create_pocket','create_sketch','adopt_first_sketch','capture_snapshot','assign','generate','set_nc','set_field'):
        with pytest.raises(ValueError):getattr(b,name)()
    tree=ast.parse(inspect.getsource(m.run_backend))
    for n in ast.walk(tree):
        if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend':assert callable(getattr(b,n.func.attr))


@pytest.mark.parametrize('returned_id',[339,340])
def test_partial_native_contour_is_persisted_before_error(monkeypatch,returned_id):
    raw=SimpleNamespace(IGetIslandCount=lambda:0)
    doc=SimpleNamespace(GetCWObjectFromID=lambda *a:(raw,True))
    app=SimpleNamespace(IGetActiveDoc=lambda:doc)
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def typed(self,obj,name):return obj
        def read(self,obj,name,*a):return getattr(obj,name)(*a)
    report={};writes=[]
    b=SimpleNamespace(boundary=lambda:None,ctx=SimpleNamespace(guard=Guard,app=app),report=report,persist=lambda:writes.append(deepcopy(report)))
    monkeypatch.setattr(m.previous,'read_header',lambda *a:({'native_id':returned_id},raw))
    def broken(owner,method,*,diagnostic,**kwargs):
        diagnostic['state'].update(status='reading',chains=[{'curves':[{'curve_type':1,'start_native':[1,2,3]}]}])
        raise ValueError('native getter failed')
    monkeypatch.setattr(m.previous.inventory,'read_segment_chains',broken)
    with pytest.raises(ValueError):m.NativeBackend.raw_feature(b,339)
    if returned_id!=339:
        assert writes[-1]['raw_feature']['header']['native_id']==returned_id
        assert writes[-1]['raw_feature']['contours']=={}
        return
    assert writes[-1]['raw_feature']['contours']['top']['chains'][0]['curves'][0]['start_native']==[1,2,3]
    assert writes[-1]['raw_contour_diagnostics']['top']['state']==writes[-1]['raw_feature']['contours']['top']


def test_raw_data_precedes_domain_checks_and_no_matching():
    text=inspect.getsource(m.run_backend)
    assert text.index('backend.raw_feature')<text.index('previous.verify_headers')
    assert text.index("report['after_cad']")<text.index("previous.verify_cad(report['before_cad']")
    assert 'verify_pocket'not in text and 'match_rows'not in text and 'capture_snapshot'not in text


def test_actual_narrow_binding_path_reads_no_parameter_groups(monkeypatch):
    import importlib
    engine=importlib.import_module(m.previous.NativeBackend.capture_snapshot.__module__)
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def typed(self,obj,name):return obj
        def read(self,obj,name,*args):return getattr(obj,name)(*args)
    class Batch(Guard):
        def require_complete(self):pass
        def summary(self):return {'complete':True}
    loaded={'deep_targets':[],'guide_parameters':{'document':{'path':'part','type':1,'title':'part','needs_save':True}}}
    b=m.NativeBackend(loaded,{},None,'x','tlb',{},lambda:None)
    b.boundary=lambda:None;b.ctx=SimpleNamespace(guard=Guard,app=SimpleNamespace(IGetActiveDoc=lambda:object()))
    b.batch=lambda *a,**k:Batch()
    seen=[]
    def binding(*a,**k):seen.append(1);return {'operations':[]},{}
    def forbidden(*a,**k):raise AssertionError('Full parameter read must not run')
    monkeypatch.setattr(engine,'read_current_binding',binding)
    monkeypatch.setattr(engine.reader,'read_parameters',forbidden)
    monkeypatch.setattr(engine.fields,'read_parameter_groups',forbidden)
    assert b.capture_binding('narrow')=={'operations':[]}
    assert len(seen)==2 and b.report['captures'][0]['parameters']==[]
    with pytest.raises(ValueError):b.capture_snapshot('forbidden',full=True)
