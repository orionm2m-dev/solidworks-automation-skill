"""Independent read-recovery checks. File fixtures only, no application dispatch."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast, hashlib, importlib.util, json, os, sys
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE)))
sys.dont_write_bytecode=True
sys.path.insert(0,str(RUNTIME))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
staged_comtypes=load('scripts.sw_cam_comtypes',STAGE/'scripts/sw_cam_comtypes.py')
import scripts
scripts.sw_cam_comtypes=staged_comtypes
c=load('independent_import_recovery',STAGE/'scripts/sw_cam_process_import_recovery.py')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def messages(active,n=0):
 return dict(subscribed=True,active=active,disconnected=not active,event_count=n,events=[dict(message_id=i)for i in range(n)],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
def operation(oid):
 return dict(native_id=oid,mill_operation_type=1,suppressed=False,toolpath_generated=True,toolpath_record_counts=[29],linked_feature_ids=[264],assigned_tool=dict(native_id=269,tool_type_raw=8,cut_diameter_native=.6,protrusion_native=20.))
class Node:
 def __init__(self,native_id=None,**members):self.native_id=native_id;self.members=members
def import_graph():
 tool=Node(7001,IsMillTool=True,ToolType=8,CutDiameter=.6,Protrusion=20.)
 feature=Node(8001,Suppressed=False,FeatureName='R25 imported feature',VolumeType=2,SubType=0)
 fsetup=Node(8101,IGetEnumFeatures=[feature],Axis=[0.,0.,1.],GetReferencePosition=[0.,0.,26.])
 op=Node(9001,OpernType=1,Suppressed=False,GetIsToolpathGenerated=True,IGetAllFeatures=[feature],IGetEnumToolpaths=[Node(RecordCount=29)],IGetTool=tool)
 machine=Node(MachType=1,IGetEnumSetups=[fsetup],IGetEnumOpSetups=[Node(9101,IGetEnumOperations=[op])])
 config=Node(SWConfigurationName='Default',ConfigurationName='CAM-R25')
 doc=Node(GetDocType=1,GetActiveConfigurationName='CAM-R25',GetActiveConfiguration=config,IGetMachine=machine)
 class Guard:
  def typed(self,raw,name):assert raw is not None;return raw
  def read(self,raw,name,*args):
   if name=='Count':return len(raw)
   if name=='Item':return raw[args[0]]
   if name=='GetCWObjectID':return args[0].native_id,True
   return raw.members[name]
 return SimpleNamespace(app=Node(IGetActiveDoc=doc),guard=Guard())
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8')
def pin(p):return dict(path=str(p),sha256=sha(p))
def empty():return dict(capture_complete=True,operation_count=0,operations=[],operation_counts=[0],features=[],feature_setups=[dict(feature_count=0)],sw_reference=dict(feature_tree=[],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.])]),all_solid_body_count=1)
@pytest.fixture
def packet(tmp_path):
 original=tmp_path/'original/part.sldprt';target=tmp_path/'isolated/part.sldprt';source=tmp_path/'oldmill/part.sldprt'
 for p in(original,target,source):p.parent.mkdir()
 original.write_bytes(b'R25 geometry');target.write_bytes(original.read_bytes());source.write_bytes(b'protected MILL')
 archive=tmp_path/'process.prtcam';archive.write_bytes(b'exported CAM');ap=dict(path=str(archive),sha256=sha(archive),bytes=archive.stat().st_size)
 eb=dict(capture_complete=True,operations=[operation(271)])
 ex=dict(scope=c.core.EXPORT_SCOPE,status='review_required',phase='finished',export_verified=True,readback_verified=True,source_unchanged=True,runtime_unchanged=True,before=eb,after=deepcopy(eb),messages=messages(False),output=ap,request=dict(expected_document_path=str(source),expected_source_sha256=sha(source)))
 ep=tmp_path/'export.json';write(ep,ex);_,epin=c.read_pin(str(ep),sha(ep));op=tmp_path/'old-import.json'
 q=dict(process_id=123,expected_process_create_time=456.,expected_document_path=str(target),expected_source_sha256=sha(target),original_document_path=str(original),original_source_sha256=sha(original),export_receipt_path=str(ep),export_receipt_sha256=sha(ep),receipt_path=str(op))
 marker=c.core.marker_path(q,ap['sha256']);mark=dict(scope=c.core.SCOPE,automatic_replay=False,receipt_path=str(op),copy_path=str(target),copy_sha256=sha(target),archive_sha256=ap['sha256']);write(marker,mark)
 old=dict(scope=c.core.SCOPE,status='uncertain',phase='finished',failed_phase='after',reason='Unsupported CAM interface',issue=dict(type='ValueError',hresult=None,locations=[dict(function='_interface_class')]),request=q,native_return_type='int',native_return_value=0,messages=messages(False),import_event_baseline=messages(True),after_diagnostic=dict(capture_complete=False,native_read_count=4,last_native_method='GetActiveConfiguration',state=dict(capture_complete=False,cam_configuration_name='Mill - Metric - 0')),before_diagnostic=dict(capture_complete=True),before_confirmation_diagnostic=dict(capture_complete=True),before=empty(),before_confirmation=empty(),post_import_document=dict(path=str(target),title=target.name,type=1,needs_save=False),export_receipt_pin=epin,archive_pin=ap,marker_path=str(marker),evidence_pins=[pin(p)for p in(target,original,source,ep,archive,Path(c.core.__file__))])
 for k in('dispatch_claimed','mutation_attempted','native_call_attempted','native_call_returned','vendor_default_import_rebuild_allowed'):old[k]=True
 for k in('native_dispatch_pending','Save_attempted','GTP_attempted','GOP_attempted','AFR_attempted','explicit_rebuild_attempted','TechDB_write_attempted','automatic_replay','model_saved'):old[k]=False
 write(op,old)
 v=dict(process_id=123,expected_process_create_time=456.,expected_document_path=str(target),expected_source_sha256=sha(target),expected_sw_configuration='Default',expected_cam_configuration='Mill - Metric - 0',import_receipt_path=str(op),import_receipt_sha256=sha(op),receipt_path=str(tmp_path/'recovery.json'),qualification_only=True,message_policy='vendor_default')
 return SimpleNamespace(v=v,old=old,op=op,marker=marker,mark=mark,target=target,original=original,source=source)
@pytest.mark.parametrize('fault',['pid','lifetime','target','sha','extra','nonzero','bool_return','pending','not_returned','save','phase','exception','event','cleanup','pin','marker','nonempty','different_before','cam','readcount','method','complete'])
def test_exact_consumed_local_failure_only(packet,fault):
 p=packet;v=deepcopy(p.v);o=deepcopy(p.old)
 if fault=='pid':v['process_id']=True
 elif fault=='lifetime':v['expected_process_create_time']+=1
 elif fault=='target':v['expected_document_path']=str(p.original)
 elif fault=='sha':v['expected_source_sha256']='f'*64
 elif fault=='extra':v['allow_replay']=True
 elif fault=='nonzero':o['native_return_value']=1
 elif fault=='bool_return':o['native_return_value']=False
 elif fault=='pending':o['native_dispatch_pending']=True
 elif fault=='not_returned':o['native_call_returned']=False
 elif fault=='save':o['Save_attempted']=True
 elif fault=='phase':o['failed_phase']='ImportCAMData'
 elif fault=='exception':o['issue']['type']='COMError'
 elif fault=='event':o['messages']=messages(False,1)
 elif fault=='cleanup':o['cleanup_error']={}
 elif fault=='pin':o['evidence_pins']=[x for x in o['evidence_pins']if x['path']!=str(p.source)]
 elif fault=='marker':m=deepcopy(p.mark);m['archive_sha256']='f'*64;write(p.marker,m)
 elif fault=='nonempty':
  for k in('before','before_confirmation'):o[k]['features']=[dict(native_id=1)]
 elif fault=='different_before':o['before_confirmation']['operation_counts']=[1]
 elif fault=='cam':v['expected_cam_configuration']='other'
 elif fault=='readcount':o['after_diagnostic']['native_read_count']=5
 elif fault=='method':o['after_diagnostic']['last_native_method']='IGetMachine'
 elif fault=='complete':o['after_diagnostic']['capture_complete']=True
 write(p.op,o);v['import_receipt_sha256']=sha(p.op)
 with pytest.raises((ValueError,KeyError)):c.validate(v)
 assert not Path(v['receipt_path']).exists()
def test_valid_authority_keeps_original_uncertain_and_marker(packet):
 p=packet;b=(p.op.read_bytes(),p.marker.read_bytes());d=c.validate(p.v)
 assert d['old']['status']=='uncertain'and d['archived_operations'][0]['native_id']==271
 assert b==(p.op.read_bytes(),p.marker.read_bytes())
@pytest.mark.parametrize('fault',['request','old_receipt','marker','output'])
def test_prepared_authority_burns_once_on_drift(packet,fault):
 p=packet;b=c.prepare(p.v,runtime_check=lambda:None);v=deepcopy(p.v)
 if fault=='request':v['process_id']+=1
 elif fault=='old_receipt':p.op.write_bytes(p.op.read_bytes()+b' ')
 elif fault=='marker':p.marker.write_bytes(p.marker.read_bytes()+b' ')
 else:write(v['receipt_path'],{})
 with pytest.raises(ValueError):c.consume(b,v,lambda:None)
 assert b.used is True
 with pytest.raises(ValueError):c.consume(b,p.v,lambda:None)
@pytest.mark.parametrize('fault',[None,'before_error','after_error','incomplete','inventory','body','cam','sw','count','cleanup','owner','event','file','runtime'])
def test_read_flow_and_fail_closed_cleanup(packet,fault):
 p=packet;calls=[];doc=deepcopy(p.old['post_import_document']);initial=(p.op.read_bytes(),p.marker.read_bytes());state={'runtime':False}
 def runtime_check():
  if state['runtime']:raise RuntimeError('runtime changed')
 class Context:
  def __init__(self,sw,clsid,tlb,v,d,r,persist,check):self.r=r;self.expected=deepcopy(doc);self.closed=False
  def start(self):calls.append('start')
  def capture(self,label,*,empty):
   assert empty is False;calls.append(label);self.r['phase']=label
   if fault==label+'_error':raise RuntimeError('bounded getter failed')
   s=globals()['empty']();s.update(operation_count=1,operations=[operation(9001)],cam_configuration_name=p.v['expected_cam_configuration'],associated_sw_configuration=p.v['expected_sw_configuration'])
   if fault=='incomplete':s['capture_complete']=False
   if fault=='inventory'and label=='after':s['operations'][0]['native_id']=9002
   if fault=='body':s['sw_reference']['solids'][0]['box_m'][3]=2.
   if fault=='cam':s['cam_configuration_name']='wrong'
   if fault=='sw':s['associated_sw_configuration']='wrong'
   if fault=='count':s['operations'].append(operation(9002))
   self.r[label]=deepcopy(s);return s
  def verify_owned(self):calls.append('verify_owned')
  def verify_files(self):calls.append('verify_files')
  def close(self):
   if self.closed:return
   self.closed=True;calls.append('close');self.r['messages']=messages(False,1 if fault=='event'else 0)
   if fault=='cleanup':raise RuntimeError('disconnect failed')
   if fault=='owner':doc['path']=str(p.original)
   if fault=='file':p.source.write_bytes(b'changed protected MILL')
   if fault=='runtime':state['runtime']=True
  def identity(self):return deepcopy(doc)
 r=c.run_read(object(),'registered','unused',runtime_check=runtime_check,_context_factory=Context,_preflight=lambda t:{},**p.v)
 assert calls.count('close')==1 and calls.count('before')==1 and calls.count('after')<=1
 assert initial==(p.op.read_bytes(),p.marker.read_bytes())
 assert json.loads(Path(p.v['receipt_path']).read_text(encoding='utf-8'))==r
 assert all(r[k]is False for k in('import_attempted','Save_attempted','GTP_attempted','GOP_attempted','explicit_rebuild_attempted','mutation_attempted','automatic_replay','model_saved','CAM_migration_verified','stock_parameters_exported','feature_association_verified','production_qualified'))
 assert r['import_receipt_status']=='uncertain'
 if fault is None:
  assert r['status']=='review_required'and all(r[k]is True for k in c.SUCCESS_FLAGS)
  row=r['archive_comparison']['ordered_observations'][0];assert row['historical_operation_native_id']==271 and row['observed_operation_native_id']==9001
  assert r['archive_comparison']['native_identity_mapping_verified']is False
 else:assert r['status']=='error'and all(r[k]is False for k in c.SUCCESS_FLAGS)
def test_mutators_rejected_before_base_dispatch(monkeypatch):
 calls=[];monkeypatch.setattr(c.ScopedCamDispatchGuard,'read',lambda *a,**k:calls.append('read'));monkeypatch.setattr(c.ScopedCamDispatchGuard,'typed',lambda *a,**k:calls.append('typed'));g=object.__new__(c.ReadGuard)
 for name in('ImportCAMData','Save3','GenerateToolpath','Rebuild','SetResponse','DeleteFeature','CreateMillFeature2'):
  with pytest.raises(ValueError):g.read(object(),name)
 with pytest.raises(ValueError):g.typed(object(),'ICWVisiNCParam')
 with pytest.raises(ValueError):g.dispatch_once(lambda:calls.append('MUTATION'))
 assert calls==[]
def test_full_import_inventory_through_actual_recovery_admission(monkeypatch):
 graph=import_graph();reads=[];types=[]
 def read(_,raw,name,*args):reads.append(name);return graph.guard.read(raw,name,*args)
 def typed(_,raw,name):types.append(name);return graph.guard.typed(raw,name)
 monkeypatch.setattr(c.ScopedCamDispatchGuard,'read',read);monkeypatch.setattr(c.ScopedCamDispatchGuard,'typed',typed)
 g=object.__new__(c.ReadGuard);d={};r=c.core.capture_import_inventory(graph.app,'unused',g,d,lambda d:None)
 assert r['capture_complete']is True and r['operations'][0]['native_id']==9001
 assert set(reads)<=c.READS and set(types)<=set(c.TYPES)
 assert 'ICWConfiguration'in types and 'SWConfigurationName'in reads and 'Count'in reads and 'Item'in reads
 assert set(types)<=set(staged_comtypes._INTERFACES)
def test_actual_public_typelib_whitelist_no_application():
 tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH')or os.environ.get('CAM_TYPELIB_PATH')
 if not tlb:pytest.skip('Set SWMCP_CAM_TYPELIB_PATH for installed public metadata check')
 abi=c.preflight(tlb);assert abi['interfaces_verified']==len(c.TYPES)==15 and abi['native_application_calls']==0
 assert set(c.TYPES)<=set(staged_comtypes._INTERFACES)
def test_no_mutation_call_in_recovery_source():
 tree=ast.parse((STAGE/'scripts/sw_cam_process_import_recovery.py').read_text(encoding='utf-8-sig'));bad={'run_import','ImportCAMData','Save','Save3','SaveAs','EditRebuild3','ForceRebuild3','GenerateToolpath','GenerateOperation','ExtractFeatures','SetResponse','SendMessage','PostMessage','dispatch_once'}
 for n in ast.walk(tree):
  if isinstance(n,ast.Call):
   if isinstance(n.func,ast.Attribute):assert n.func.attr not in bad
   if isinstance(n.func,ast.Name):assert n.func.id not in bad
