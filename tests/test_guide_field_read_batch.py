from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,importlib.util,math,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('SOLIDWORKS_SKILL_ROOT',str(ROOT)))
spec=importlib.util.spec_from_file_location('guide_fields_test',ROOT/'scripts/sw_cam_guide_field_read_batch.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
TARGET={'operation_native_id':328,'feature_native_id':83,'operation_type':1}
CONFIG={'cam_configuration_name':'Mill','configuration_object_name':'Mill','associated_sw_configuration_name':'Default',
    'sw_configuration_name':'Default','names_consistent':True,'associated_sw_configuration_matches':True}


def test_fixed_field_selection():
    assert m.select_fields(TARGET)==m.config.FINISH_FIELDS
    assert m.select_fields(TARGET,['previous_allowance'])[0][0]=='previous_allowance'


@pytest.mark.parametrize('names',[[],['bad'],['previous_allowance','previous_allowance'],[{}],[True],('previous_allowance',)])
def test_reject_arbitrary_or_unbounded_getter_selection(names):
    with pytest.raises(ValueError):m.select_fields(TARGET,names)


def test_reject_bool_native_type():
    with pytest.raises(ValueError):m.select_fields(dict(TARGET,operation_type=True))


@pytest.mark.parametrize('value',[float('nan'),float('inf'),None,'x',object(),[1]*5])
def test_bad_scalar_rejected(value):
    with pytest.raises(ValueError):m.normalized(value)


def test_actual_batch_constructor_includes_progress_and_state(tmp_path):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'synthetic')
    pinfile=tmp_path/'module.py';pinfile.write_bytes(b'# synthetic')
    document={'path':str(source),'title':'part.SLDPRT','type':1,'needs_save':True}
    backend=SimpleNamespace(sw=object(),typelib_path='metadata.tlb',args={'process_id':52},
        loaded={'generated_pin':{'path':str(pinfile),'sha256':hashlib.sha256(pinfile.read_bytes()).hexdigest()},'pins':[{'path':str(pinfile),'sha256':hashlib.sha256(pinfile.read_bytes()).hexdigest()}]},
        ctx=SimpleNamespace(identity=lambda:document,args={'expected_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()},files=lambda:None,owned=lambda:None),events=lambda:None)
    state={};progress=lambda:None;batch=m.make_batch(backend,object(),progress,state,lambda:None)
    assert isinstance(batch,m.reader.ParameterReadBatch) and batch.progress is progress and batch.progress_state is state
    assert batch._budget==256 and not batch._active


def test_binding_callback_uses_fixed_names_without_nested_dispatch_guards(monkeypatch):
    class Config:
        ConfigurationName='Mill';SWConfigurationName='Default'
        def QueryInterface(self,cls):assert cls is Config;return self
    c=Config()
    doc=SimpleNamespace(GetActiveConfigurationName=lambda:'Mill',GetActiveConfiguration=lambda:c)
    sw=SimpleNamespace(ActiveDoc=SimpleNamespace(ConfigurationManager=SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name='Default'))))
    cb=m.guide.configuration_binding
    monkeypatch.setattr(cb,'_load_type_library',lambda path:SimpleNamespace(ICWConfiguration=Config))
    monkeypatch.setattr(cb,'_verify_generated_class',lambda cls,*args:cls)
    backend=SimpleNamespace(sw=sw,typelib_path='metadata.tlb',loaded={'generated_pin':{},'guide_parameters':{'configuration':CONFIG}},
        args={'expected_configuration':'Default'},events=lambda:None)
    stats={'binding_native_calls':0,'binding_checks':0,'binding_elapsed_seconds':0.}
    check=m.make_configuration_check(backend,doc,stats);check()
    assert stats['binding_checks']==1 and 4<stats['binding_native_calls']<16
    c.SWConfigurationName='wrong'
    with pytest.raises(ValueError):check()


class Batch:
    def __init__(self):self.queries=[];self.gets=[];self.complete=False
    def __enter__(self):return self
    def __exit__(self,*args):self.complete=not any(args)
    def require_complete(self):assert self.complete
    def summary(self):return {'completed':self.complete,'native_calls':len(self.gets)+len(self.queries)}
    def typed(self,raw,name):self.queries.append(name);return (raw,name)
    def read(self,obj,name,*args):
        self.gets.append((name,args))
        if name in ('IGetLeadin','IGetLeadout'):return name
        return (False,0.3) if name=='GetFirstDepthCut' else 0.1


def fake_read(monkeypatch,*,change_binding=False):
    backend=SimpleNamespace(doc=object(),loaded={'configuration_tool':{'native_id':273,'cut_diameter_native':2.0}})
    batch=Batch();monkeypatch.setattr(m,'make_batch',lambda *args:batch)
    monkeypatch.setattr(m,'make_configuration_check',lambda *args:lambda:None)
    calls=[]
    def binding(*args):
        calls.append(1)
        return {'id':2 if change_binding and len(calls)==2 else 1},'operation','feature'
    monkeypatch.setattr(m,'target_binding',binding)
    return backend,batch,calls


def test_fixed_values_cached_owners_and_before_after_identity(monkeypatch):
    backend,batch,calls=fake_read(monkeypatch)
    result=m.read_field_values(backend,TARGET,field_names=['first_depth','max_depth'])
    assert result['read_complete'] and result['field_values']['first_depth']==[False,0.3]
    assert result['field_values']['max_depth']==0.1 and calls==[1,1]
    assert len(batch.queries)==1 and len(batch.gets)==2 and result['elapsed_seconds']>=0


def test_changed_binding_stops_and_preserves_partial_diagnostic(monkeypatch):
    backend,batch,_=fake_read(monkeypatch,change_binding=True);diagnostic={}
    with pytest.raises(ValueError):m.read_field_values(backend,TARGET,field_names=['first_depth'],diagnostic=diagnostic)
    assert diagnostic['field_values']=={'first_depth':[False,0.3]} and not diagnostic['read_complete']
    assert 'read_batch'in diagnostic


def test_read_batch_cannot_dispatch():
    batch=object.__new__(m.FieldReadBatch)
    with pytest.raises(ValueError,match='cannot dispatch'):batch.dispatch_once(lambda:None,persist_pending=lambda:None)


def test_real_target_binding_body_uses_exact_existing_helper_contracts():
    class Collection:
        def __init__(self,rows):self.rows=rows;self.Count=len(rows)
        def Item(self,index):return self.rows[0]
    feature=SimpleNamespace(native_id=83)
    tool=SimpleNamespace(native_id=273,IsMillTool=True,ToolType=1,CutDiameter=2.0,Protrusion=7.0)
    operation=SimpleNamespace(native_id=328,OpernType=1,Suppressed=False,GetIsToolpathGenerated=lambda:False,
        IGetAllFeatures=lambda:Collection([feature]),IGetEnumToolpaths=lambda:Collection([]),IGetTool=lambda:tool)
    doc=SimpleNamespace(GetCWObjectID=lambda obj:(obj.native_id,True),
        GetCWObjectFromID=lambda kind,oid:(operation if kind==3 and oid==328 else feature,True))
    class Transport:
        def typed(self,obj,name):return obj
        def feature_dispatch(self,obj):return obj
        def read(self,obj,name,*args):return m._member(obj,name,*args)
    batch=Transport();wanted,_=m.read_generic_tool(operation,doc,batch.read,batch.typed)
    observed,raw,linked=m.target_binding(doc,TARGET,batch,wanted)
    assert observed['feature_ids']==[83] and raw is operation and linked is feature
    operation.OpernType=0
    with pytest.raises(ValueError):m.target_binding(doc,TARGET,batch,wanted)
