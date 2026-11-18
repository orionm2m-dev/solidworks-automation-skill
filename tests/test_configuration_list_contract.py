"""Independent bounded configuration-name observation; no application/native calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast,hashlib,importlib.util,json,os,sys
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE)))
sys.dont_write_bytecode=True;sys.path.insert(0,str(RUNTIME))
spec=importlib.util.spec_from_file_location('independent_configuration_list',STAGE/'scripts/sw_cam_process_configuration_list.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
class Node:
 def __init__(self,**members):self.members=members

def graph(n=2):
 configs=[Node(ConfigurationName='active'if i==0 else 'other'+str(i),SWConfigurationName='Default')for i in range(n)]
 collection=Node(Count=n,Item=lambda i:configs[i])
 machine=Node(MachType=1,IGetEnumSetups=[],IGetEnumOpSetups=[])
 doc=Node(GetDocType=1,GetActiveConfigurationName='active',GetAllConfigurations=collection,IGetMachine=machine)
 app=Node(IGetActiveDoc=doc);calls=[];observed=[]
 def read(raw,name,*args):
  calls.append(('read',name,args))
  if isinstance(raw,list):return len(raw)if name=='Count'else raw[args[0]]
  value=raw.members[name]
  if isinstance(value,Exception):raise value
  return value(*args)if callable(value)else value
 def typed(raw,name):
  calls.append(('typed',name));assert raw is not None,'null interface';return raw
 def metadata(raw):calls.append(('metadata',));return dict(guid=c.COLLECTION_IID,typekind=4,name='ICWDispatchCollection')
 def progress(row):observed.append(deepcopy(row))
 return SimpleNamespace(app=app,doc=doc,machine=machine,collection=collection,configs=configs,read=read,typed=typed,metadata=metadata,progress=progress,calls=calls,observed=observed)

def capture(g):return c.capture_configurations(g.app,read=g.read,typed=g.typed,metadata=g.metadata,progress=g.progress)
@pytest.mark.parametrize('count',[1,2,16])
def test_exact_bounded_zero_based_names_and_mapping_only(count):
 g=graph(count);r=capture(g)
 assert r['capture_complete']is True and r['configuration_count']==count
 assert r['additional_configurations_observed']is(count>1)
 assert r['inactive_contents_observed']is False and r['activation_attempted']is False
 assert [(x['name'],x['sw_configuration_name'])for x in r['configurations']]==[('active'if i==0 else 'other'+str(i),'Default')for i in range(count)]
 assert [x[2]for x in g.calls if x[:2]==('read','Item')]==[(i,)for i in range(count)]
 assert g.calls.index(('metadata',))<g.calls.index(('typed','ICWDispatchCollection'))
 assert r['active_feature_count']==r['active_operation_count']==0
 assert not {'ActivateConfiguration','AddNewConfiguration','ImportCAMData','Save','Save3','GetCWObjectFromID'}&{x[1]for x in g.calls if len(x)>1}
@pytest.mark.parametrize('fault',['null','wrong_guid','metadata_exception','zero','overflow','bool_count','duplicate','active_missing','null_item','name_not_string','empty_sw','count_drift','active_drift','getter_failure','active_feature','active_operation'])
def test_no_fallback_and_partial_observation_on_invalid_list(fault):
 g=graph()
 if fault=='null':g.doc.members['GetAllConfigurations']=None
 elif fault=='wrong_guid':g.metadata=lambda raw:dict(guid='{00000000-0000-0000-0000-000000000000}')
 elif fault=='metadata_exception':
  def metadata(raw):raise ValueError('public type-info unavailable')
  g.metadata=metadata
 elif fault=='zero':g.collection.members['Count']=0
 elif fault=='overflow':g.collection.members['Count']=17
 elif fault=='bool_count':g.collection.members['Count']=True
 elif fault=='duplicate':g.configs[1].members['ConfigurationName']='active'
 elif fault=='active_missing':g.configs[0].members['ConfigurationName']='not-active'
 elif fault=='null_item':g.configs[1]=None
 elif fault=='name_not_string':g.configs[1].members['ConfigurationName']=23
 elif fault=='empty_sw':g.configs[1].members['SWConfigurationName']=''
 elif fault=='count_drift':
  vals=iter([2,3]);g.collection.members['Count']=lambda:next(vals)
 elif fault=='active_drift':
  vals=iter(['active','other1']);g.doc.members['GetActiveConfigurationName']=lambda:next(vals)
 elif fault=='getter_failure':g.configs[1].members['ConfigurationName']=RuntimeError('getter failed once')
 elif fault=='active_feature':g.machine.members['IGetEnumSetups']=[Node(IGetEnumFeatures=[Node()])]
 elif fault=='active_operation':g.machine.members['IGetEnumOpSetups']=[Node(IGetEnumOperations=[Node()])]
 with pytest.raises((ValueError,RuntimeError,AssertionError)):capture(g)
 assert g.observed[-1]['capture_complete']is False
 if fault in('null','wrong_guid','metadata_exception'):assert not any(x==('typed','ICWDispatchCollection')for x in g.calls)
 if fault in('zero','overflow','bool_count'):assert not any(x[:2]==('read','Item')for x in g.calls)
 if fault in('null_item','name_not_string','empty_sw','getter_failure'):
  assert len(g.observed[-1]['configurations'])==1
  assert sum(x[:2]==('read','Item')and x[2]==(1,)for x in g.calls)==1
 assert not any(len(x)>1 and x[1]in('ActivateConfiguration','ImportCAMData','Save3')for x in g.calls)

def test_actual_readguard_covers_graph_and_rejects_mutators(monkeypatch):
 g=graph();monkeypatch.setattr(c.ScopedCamDispatchGuard,'read',lambda _,obj,name,*args:g.read(obj,name,*args));guard=object.__new__(c.ReadGuard)
 r=c.capture_configurations(g.app,read=guard.read,typed=g.typed,metadata=g.metadata,progress=g.progress)
 assert r['capture_complete']is True
 before=len(g.calls)
 for method in('ActivateConfiguration','AddCopyConfiguration','DeleteConfiguration','SetComment','ImportCAMData','Save3','Rebuild'):
  with pytest.raises(ValueError):guard.read(object(),method)
 with pytest.raises(ValueError):guard.dispatch_once(lambda:pytest.fail('mutation'))
 assert len(g.calls)==before

def messages(n=0):return dict(subscribed=True,active=False,disconnected=True,event_count=n,events=[{}for _ in range(n)],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
@pytest.mark.parametrize('fault',[None,'before_error','after_drift','mapping','cleanup','owner','events','file','runtime'])
def test_terminal_success_requires_clean_stable_read_only_context(tmp_path,fault):
 target=tmp_path/'copy.sldprt';target.write_bytes(b'R25 unchanged');sha=hashlib.sha256(target.read_bytes()).hexdigest();out=tmp_path/'read.json';doc=dict(path=str(target),title=target.name,type=1,needs_save=False);calls=[];state={'runtime':False}
 v=dict(expected_document_path=str(target),expected_source_sha256=sha,expected_cam_configuration='active',expected_sw_configuration='Default')
 d=dict(pins=[dict(path=str(target),sha256=sha)],receipt=out,import_pin={},marker_pin={},empty_read_pin={})
 def runtime():
  if state['runtime']:raise RuntimeError('runtime changed')
 class Context:
  def __init__(self,sw,clsid,tlb,v,d,r,persist,check):self.r=r;self.expected=deepcopy(doc);self.closed=False
  def start(self):calls.append('start')
  def capture(self,label):
   calls.append(label);self.r['phase']=label
   if fault=='before_error'and label=='before':raise RuntimeError('one failed getter')
   row=capture(graph())
   if fault=='after_drift'and label=='after':row['configurations'][1]['name']='changed'
   if fault=='mapping':row['configurations'][0]['sw_configuration_name']='wrong'
   self.r[label]=row;return row
  def verify_owned(self):pass
  def verify_files(self):assert hashlib.sha256(target.read_bytes()).hexdigest()==sha
  def close(self):
   if self.closed:return
   self.closed=True;calls.append('close');self.r['messages']=messages(1 if fault=='events'else 0)
   if fault=='cleanup':raise RuntimeError('disconnect failed')
   if fault=='owner':doc['path']='changed'
   if fault=='file':target.write_bytes(b'changed')
   if fault=='runtime':state['runtime']=True
  def identity(self):return deepcopy(doc)
 r=c.run_read(object(),'registered','unused',runtime_check=runtime,_validate=lambda v:d,_preflight=lambda p:{},_context_factory=Context,**v)
 assert calls.count('close')==1 and calls.count('before')==1 and calls.count('after')<=1
 assert json.loads(out.read_text(encoding='utf-8'))==r
 assert all(r[x]is False for x in('mutation_attempted','activation_attempted','import_attempted','Save_attempted','GTP_attempted','explicit_rebuild_attempted','model_saved','inactive_contents_observed'))
 flags=('readback_verified','protected_files_unchanged','runtime_unchanged')
 if fault is None:assert r['status']=='review_required'and all(r[x]is True for x in flags)
 else:assert r['status']=='error'and all(r[x]is False for x in flags)

def test_no_activation_save_import_generation_calls_in_source():
 t=ast.parse((STAGE/'scripts/sw_cam_process_configuration_list.py').read_text(encoding='utf-8-sig'));bad={'ActivateConfiguration','DeleteConfiguration','AddNewConfiguration','AddCopyConfiguration','ImportCAMData','Save','Save3','SetComment','GenerateToolpath','dispatch_once'}
 for n in ast.walk(t):
  if isinstance(n,ast.Call):
   if isinstance(n.func,ast.Attribute):assert n.func.attr not in bad
   if isinstance(n.func,ast.Name):assert n.func.id not in bad
 assert not bad&c.EXTRA


@pytest.mark.parametrize('raw',[0,17,True])
def test_raw_count_diagnostic_saved_before_first_count_rejection(raw):
 g=graph();g.collection.members['Count']=raw
 with pytest.raises(ValueError):capture(g)
 last=g.observed[-1]
 assert last['capture_complete']is False
 assert type(last['configuration_count_native'])is type(raw)and last['configuration_count_native']==raw
 assert last['configuration_count_native_type']==type(raw).__name__
 assert 'configuration_count'not in last and last['configurations']==[]
 assert not any(x[:2]==('read','Item')for x in g.calls)
 assert sum(x[:2]==('read','GetAllConfigurations')for x in g.calls)==1

@pytest.mark.parametrize('raw',[0,3,True])
def test_raw_repeated_count_diagnostic_saved_before_rejection(raw):
 g=graph();counts=iter([2,raw]);g.collection.members['Count']=lambda:next(counts)
 with pytest.raises(ValueError):capture(g)
 last=g.observed[-1]
 assert last['capture_complete']is False and last['configuration_count_native']==2
 assert type(last['configuration_count_after_native'])is type(raw)and last['configuration_count_after_native']==raw
 assert last['configuration_count_after_native_type']==type(raw).__name__
 assert [x['name']for x in last['configurations']]==['active','other1']
 assert sum(x[:2]==('read','Count')for x in g.calls)==2
 assert not any(x[:2]==('read','IGetMachine')for x in g.calls)

def test_metadata_getters_admitted_by_actual_readguard_without_bypass(monkeypatch):
 calls=[];token=object()
 def base_read(_,raw,name,*args):calls.append((raw,name,args));return token
 monkeypatch.setattr(c.ScopedCamDispatchGuard,'read',base_read)
 guard=object.__new__(c.ReadGuard);raw=object()
 for name,args in [('GetTypeInfo',(0,)),('GetTypeAttr',()),('GetDocumentation',(-1,))]:
  assert guard.read(raw,name,*args)is token
 assert [x[1]for x in calls]==['GetTypeInfo','GetTypeAttr','GetDocumentation']
 with pytest.raises(ValueError):guard.read(raw,'ActivateConfiguration','other')
 assert len(calls)==3
