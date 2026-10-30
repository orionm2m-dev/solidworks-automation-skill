"""Synthetic compact compound-strategy tests; no CAD connections."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast
import hashlib
import json
import os
import pytest
from scripts import sw_cam_mill_compound_strategy as m

def calls_fixture():
    header = dict(native_id=64,volume_type=11,subtype_raw=0,shape_raw=2,suppressed=False,
        name='Compound1',axis_native=[0.,0.,-1.],depth_native=13.7,
        bounds_native=[-9999000.,-9999000.,13.7],start_native=[0.,0.,26.])
    owner=SimpleNamespace(id=69)
    raw=SimpleNamespace(id=64,VolumeType=11,SubType=0,Shape=2,Suppressed=False,FeatureName='Compound1',
        Axis=[0.,0.,-1.],Depth=13.7,GetBoundParams=lambda:header['bounds_native'],
        GetStartPosition=lambda:header['start_native'],GetOwner=lambda:owner,
        GetNumOfSteps=lambda:3,Attribute=7,GetAttribute=lambda:('Observed strategy',7),
        IGetActiveAttribute=lambda:'Observed strategy',IGetAllAttributes=lambda:['Mill A','Mill B'],
        IGetAllAttributes2=lambda:('Compound A','Compound B'))
    doc=SimpleNamespace(GetCWObjectFromID=lambda kind,ident:(raw,True),GetCWObjectID=lambda ob:(ob.id,True))
    log=[];bounds=[]
    def read(ob,name,*args):
        log.append(name)
        value=getattr(ob,name)
        return value(*args) if callable(value) else value
    def typed(ob,name):
        log.append('QI:'+name)
        if ob is None:raise ValueError('null')
        return ob
    state=dict(features=[dict(setup_native_id=69,geometry=deepcopy(header))])
    args=dict(state=state,native={'doc':doc},read=read,typed=typed,diagnostic={},
        feature_id=64,owner_id=69,step_count=3,expected_header=header,boundary=lambda:bounds.append(1))
    return SimpleNamespace(raw=raw,owner=owner,doc=doc,header=header,log=log,bounds=bounds,args=args)

def test_direct_typed_catalogues_and_context_preserved():
    f=calls_fixture();before=deepcopy(f.args['state']);m.read_compound_strategy(**f.args)
    out=f.args['diagnostic']['compound_strategy']
    assert out['attribute_id']==7 and out['number_of_steps']==3
    assert out['mill_attributes']['values']==['Mill A','Mill B']
    assert out['multi_step_attributes']['observed_representation']=='tuple'
    assert out['metadata_read_complete'] and not out['step_dimensions_read']
    assert out['index_base_verified'] is False
    assert f.args['state']==before and len(f.bounds)==2
    assert {'QI:ICWFeature','QI:ICWMillFeature','QI:ICWMultiStepFeature'} <= set(f.log)
    assert not set(f.log)&{'SetStrategy','ISetActiveAttribute','GenerateOpPlan','GetTypeAtStep','GetCylParams','GetConeParams'}

@pytest.mark.parametrize('value',[None,'','A;B',[],(),['A','A']])
def test_catalogues_preserve_representation_without_parsing(value):
    out=m.catalogue_observation(value)
    assert out['observed_representation']==type(value).__name__ and out['native_vartype'] is None
    assert out['native_vartype_verified'] is False
    assert out['values']==(list(value) if type(value) in (tuple,list) else value)

@pytest.mark.parametrize('value',[True,7,{},['A',None],[['A']],['x']*129,'x'*4097,['x'*4097]])
def test_unsafe_catalogue_shape_rejected(value):
    with pytest.raises(ValueError):m.catalogue_observation(value)

@pytest.mark.parametrize('mode',['lookup_false','wrong_id','wrong_owner','wrong_header','wrong_count',
    'bool_count','bad_attribute','bad_pair','mismatched_id','bad_catalogue','bad_qi','changed_pair','changed_count'])
def test_direct_faults_stop_before_complete(mode):
    f=calls_fixture()
    if mode=='lookup_false':f.doc.GetCWObjectFromID=lambda *a:(f.raw,False)
    if mode=='wrong_id':f.raw.id=65
    if mode=='wrong_owner':f.owner.id=70
    if mode=='wrong_header':f.raw.Depth=10
    if mode=='wrong_count':f.raw.GetNumOfSteps=lambda:4
    if mode=='bool_count':f.raw.GetNumOfSteps=lambda:True
    if mode=='bad_attribute':f.raw.Attribute=True
    if mode=='bad_pair':f.raw.GetAttribute=lambda:('A',)
    if mode=='mismatched_id':f.raw.GetAttribute=lambda:('A',8)
    if mode=='bad_catalogue':f.raw.IGetAllAttributes2=lambda:[['A']]
    if mode=='bad_qi':
        old=f.args['typed']
        def fail(ob,name):
            if name=='ICWMultiStepFeature':raise ValueError('QI failed')
            return old(ob,name)
        f.args['typed']=fail
    if mode=='changed_pair':
        values=iter([('Observed strategy',7),('changed',7)]);f.raw.GetAttribute=lambda:next(values)
    if mode=='changed_count':
        values=iter([3,4]);f.raw.GetNumOfSteps=lambda:next(values)
    with pytest.raises(ValueError):m.read_compound_strategy(**f.args)
    assert f.args['diagnostic'].get('compound_strategy',{}).get('metadata_read_complete') is not True

def test_null_bstr_and_distinct_active_name_preserved():
    f=calls_fixture();f.raw.GetAttribute=lambda:(None,7);f.raw.IGetActiveAttribute=lambda:'other observed name'
    m.read_compound_strategy(**f.args)
    out=f.args['diagnostic']['compound_strategy']
    assert out['attribute_name'] is None and out['active_attribute_name']=='other observed name'

@pytest.mark.parametrize('feature,owner,count',[(True,69,3),(64,True,3),(64,69,True),(2**32,69,3),(64,69,65)])
def test_scope_requires_bounded_strict_values(feature,owner,count):
    f=calls_fixture()
    with pytest.raises(ValueError):m.validate_compound_scope(SimpleNamespace(state=f.args['state']),feature,owner,count)

class FakeSession:
    last=None
    def __init__(self,*args):
        self.active=False;self.closed=False;self.event=False;self.close_error=False;FakeSession.last=self
    def __enter__(self):self.active=True;return self
    def __exit__(self,*args):self.active=False;self.closed=True
    def summary(self):
        return dict(subscribed=True,active=self.active,disconnected=self.closed,event_count=int(self.event),
                    disconnect_errors=['fail'] if self.close_error else [])

def run_fake(tmp_path,monkeypatch,mode='ok',capture_mode='full_plan'):
    import scripts.sw_cam_events as events
    f=calls_fixture()
    doc=dict(path=str(tmp_path/'Qualification'/'model.SLDPRT'),title='model.SLDPRT',type=1,needs_save=False)
    state=dict(document=doc,features=deepcopy(f.args['state']['features']) + [dict(setup_native_id=69,geometry=dict(native_id=100+i,volume_type=2,shape_raw=2,suppressed=False)) for i in range(17)], sw_reference=dict(solids=[],feature_tree=[]))
    anchor=SimpleNamespace(state=state,check_files=lambda:None,summary=lambda:{'saved':True})
    def verify(observed):
        if observed!=state:raise ValueError('neighbor changed')
        return True
    anchor.verify=verify
    monkeypatch.setattr(m,'load_saved_plan_tools_evidence',lambda *a,**k:anchor)
    monkeypatch.setattr(m,'validate_inventory_request',lambda **k:None)
    monkeypatch.setattr(m,'_member',lambda *a:16516)
    monkeypatch.setattr(m,'raw_part_identity',lambda *a:deepcopy(doc))
    monkeypatch.setattr(m,'_file_hash',lambda *a:'a'*64)
    monkeypatch.setattr(m,'_bootstrap',lambda *a:'app')
    monkeypatch.setattr(events,'CamMessageSession',FakeSession)
    snapshots=[]
    def capture(*args,**kw):
        kw['check']();snapshots.append(1);out=deepcopy(state)
        if capture_mode == 'full_plan':
            assert kw['operation_details_reader'].func is m.read_compound_strategy
        else:
            out = dict(document=deepcopy(doc),capture_scope='selected_compound_only',
                       features=deepcopy(f.args['state']['features']))
        details=dict(metadata_read_complete=True,attribute_id=7,step_dimensions_read=False)
        kw['diagnostic']['operation_details']={'compound_strategy':details}
        if mode=='changed_catalogue' and len(snapshots)==2:details['attribute_id']=8
        if mode=='neighbor' and len(snapshots)==2:out['features'][0]['geometry']['depth_native']=9
        if mode=='event':FakeSession.last.event=True
        if mode=='cleanup':FakeSession.last.close_error=True
        if mode=='dirty':out['document']['needs_save']=True
        if mode=='failure':raise RuntimeError('native read failed')
        if mode=='file':monkeypatch.setattr(m,'_file_hash',lambda *a:'b'*64)
        if mode=='missing':details['metadata_read_complete']=False
        return out,{}
    monkeypatch.setattr(m,'capture_selected_plan',capture)
    if capture_mode == 'target_only':
        monkeypatch.setattr(m,'capture_compound_target',lambda *a,**kw:capture(*a,**kw)[0])
        def forbidden(*a,**kw):
            raise AssertionError('Full inventory must not be compared in target-only mode')
        monkeypatch.setattr(m,'_same_inventory',forbidden)
        monkeypatch.setattr(m,'capture_selected_plan',forbidden)
    if mode=='write_failure':
        original=m._write_receipt
        def fail(path,value,*args,**kwargs):
            if value.get('readback_verified'):raise OSError('disk full')
            return original(path,value,*args,**kwargs)
        monkeypatch.setattr(m,'_write_receipt',fail)
    out=m.inspect_saved_compound_strategy('sw','clsid','tlb',
        process_id=16516,expected_document_path=doc['path'],expected_source_sha256='a'*64,
        saved_plan_receipt_path=str(tmp_path/'saved.json'),saved_plan_receipt_sha256='b'*64,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        expected_compound_feature_native_id=64,expected_compound_owner_setup_native_id=69,
        expected_compound_step_count=3,qualification_only=True,acknowledge_disposable_copy=True,
        receipt_path=str(tmp_path/'out.json'),strategy_capture_mode=capture_mode)
    return out,snapshots

def test_two_captures_and_clean_cleanup(tmp_path,monkeypatch):
    out,calls=run_fake(tmp_path,monkeypatch)
    assert len(calls)==2 and out['readback_verified'] and out['catalogues_read_complete'], out
    assert FakeSession.last.closed and out['status']=='review_required'
    for key in ('strategy_assignment_attempted','GOP_attempted','GTP_attempted','save_attempted',
                'model_saved','step_dimensions_read','index_base_verified','full_inventory_verified',
                'production_qualified','mutation_attempted'):
        assert out[key] is False

@pytest.mark.parametrize('mode',['changed_catalogue','neighbor','event','cleanup','dirty','failure','file','missing','write_failure'])
def test_wrapper_failures_never_complete(tmp_path,monkeypatch,mode):
    out,_=run_fake(tmp_path,monkeypatch,mode)
    assert out['status']=='error' and out['readback_verified'] is False and out['catalogues_read_complete'] is False
    assert FakeSession.last.closed

def test_backend_has_no_native_mutations_or_indexed_reads():
    path=Path(m.__file__);tree=ast.parse(path.read_text(encoding='utf-8'))
    forbidden={'SetStrategy','ISetActiveAttribute','SetDefaultStrategyFromTechDB','GenerateOpPlan',
               'GenerateToolPath','SaveActiveDocument','GetTypeAtStep','GetCylParams','GetConeParams','GetTorusParams'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):assert node.func.id!='setattr'
        if isinstance(node,ast.Constant) and isinstance(node.value,str):assert node.value not in forbidden

def test_installed_or_staged_schema_has_explicit_compound_scope():
    root=Path(os.environ.get('SW_SKILL_TEST_ROOT',Path(__file__).resolve().parents[1]))
    tree=ast.parse((root/'mcp-server'/'server.py').read_text(encoding='utf-8'))
    match=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SolidWorksCamSavedCompoundStrategyInput']
    assert len(match)==1
    fields={n.target.id for n in match[0].body if isinstance(n,ast.AnnAssign)}
    assert fields=={'expected_compound_feature_native_id','expected_compound_owner_setup_native_id','expected_compound_step_count','strategy_capture_mode','compound_observation'}
    assert match[0].bases[0].id=='SolidWorksCamSavedMillPlanToolsInput'

def test_target_only_capture_avoids_plan_enumeration(monkeypatch):
    f=calls_fixture()
    f.doc.GetDocType=lambda:1
    app=SimpleNamespace(IGetActiveDoc=lambda:f.doc)
    import scripts.sw_cam_generation as g
    monkeypatch.setattr(g,'_typed',lambda raw,name,path:raw)
    diag={}
    result=m.capture_compound_target(app,'unused',identity=lambda:{'path':'p','type':1,'needs_save':False},
        check=lambda:None,diagnostic=diag,feature_id=64,owner_id=69,step_count=3,expected_header=f.header)
    assert result['capture_scope']=='selected_compound_only'
    assert len(result['features'])==1
    assert diag['capture_complete'] and diag['full_plan_reread'] is False
    assert diag['native_read_count']<80

def test_target_only_rejects_changed_header(monkeypatch):
    f=calls_fixture();f.doc.GetDocType=lambda:1;f.raw.Depth=8
    import scripts.sw_cam_generation as g
    monkeypatch.setattr(g,'_typed',lambda raw,name,path:raw)
    with pytest.raises(ValueError):
        m.capture_compound_target(SimpleNamespace(IGetActiveDoc=lambda:f.doc),'unused',
          identity=lambda:{'path':'p'},check=lambda:None,diagnostic={},
          feature_id=64,owner_id=69,step_count=3,expected_header=f.header)


def test_target_only_complete_wrapper(tmp_path,monkeypatch):
    out,calls=run_fake(tmp_path,monkeypatch,capture_mode='target_only')
    assert out['readback_verified'] and out['catalogues_read_complete'], out
    assert len(calls)==2 and out['full_plan_reread'] is False
    assert out['before']['capture_scope']=='selected_compound_only'
    assert FakeSession.last.closed and not out['mutation_attempted']

@pytest.mark.parametrize('mode',['changed_catalogue','neighbor','event','cleanup','failure','file','missing','write_failure'])
def test_target_only_complete_wrapper_failures(tmp_path,monkeypatch,mode):
    out,_=run_fake(tmp_path,monkeypatch,mode,capture_mode='target_only')
    assert out['status']=='error' and out['readback_verified'] is False
    assert out['catalogues_read_complete'] is False and FakeSession.last.closed
