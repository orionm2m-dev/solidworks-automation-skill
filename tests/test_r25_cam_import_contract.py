"""Independent import boundary checks. No application, runtime writes, or COM dispatch."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast, hashlib, importlib.util, json, os, sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE)))
sys.dont_write_bytecode=True
sys.path.insert(0,str(RUNTIME))
spec=importlib.util.spec_from_file_location('independent_r25_import',STAGE/'scripts/sw_cam_process_import.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
from scripts import sw_cam_dispatch_guard as sg

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def messages(active,n=0):
 return dict(subscribed=True,active=active,disconnected=not active,event_count=n,events=[dict(message_id=i,message='native prompt',response='default_unknown')for i in range(n)],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
def operation(oid):
 return dict(native_id=oid,mill_operation_type=1,suppressed=False,toolpath_generated=True,toolpath_record_counts=[29],linked_feature_ids=[264],assigned_tool=dict(native_id=269,tool_type_raw=8,cut_diameter_native=.6,protrusion_native=20.))
@pytest.fixture
def packet(tmp_path,monkeypatch):
 original=tmp_path/'R25-original/part.sldprt';target=tmp_path/'exclusive-R25/target.sldprt';source=tmp_path/'old-MILL/source.sldprt'
 for p in [original,target,source]:p.parent.mkdir()
 original.write_bytes(b'R25 new geometry, no CAM');target.write_bytes(original.read_bytes());source.write_bytes(b'protected old MILL c483 provenance')
 archive=tmp_path/'process.prtcam';archive.write_bytes(b'verified archive')
 # Synthetic files may live on a shared workspace. Only this fixture's archive locality
 # is substituted; independent real locality tests are owned by the implementation suite.
 real_locality=c.local_archive_path
 monkeypatch.setattr(c,'local_archive_path',lambda candidate:True if Path(candidate).resolve()==archive.resolve() else real_locality(candidate))
 before=dict(capture_complete=True,operations=[operation(271)])
 export=dict(scope=c.EXPORT_SCOPE,status='review_required',phase='finished',export_verified=True,readback_verified=True,runtime_unchanged=True,source_unchanged=True,native_call_returned=True,native_return_type='int',native_return_value=0,native_dispatch_pending=False,messages=messages(False),before=before,after=deepcopy(before),request=dict(expected_document_path=str(source),expected_source_sha256=sha(source)),source_before_sha256=sha(source),source_after_sha256=sha(source),output=dict(path=str(archive),sha256=sha(archive),bytes=archive.stat().st_size))
 ep=tmp_path/'export.json';ep.write_text(json.dumps(export),encoding='utf-8')
 v=dict(process_id=123,expected_process_create_time=456.,expected_document_path=str(target),expected_source_sha256=sha(target),original_document_path=str(original),original_source_sha256=sha(original),export_receipt_path=str(ep),export_receipt_sha256=sha(ep),receipt_path=str(tmp_path/'import.json'),qualification_only=True,message_policy='vendor_default',acknowledge_isolated_copy=True,allow_vendor_default_import_rebuild=True)
 return SimpleNamespace(v=v,original=original,target=target,source=source,archive=archive,export=export,export_path=ep)

@pytest.mark.parametrize('fault',['original_alias','old_CAM_target','hardlink_original','different_bytes','same_directory','no_vendor_rebuild_admission','non_default_policy','bool_pid','changed_export_source'])
def test_preflight_rejects_before_any_app_access(packet,monkeypatch,fault):
 p=packet;v=deepcopy(p.v)
 if fault=='original_alias':v['expected_document_path']=str(p.original)
 elif fault=='old_CAM_target':v['expected_document_path']=str(p.source)
 elif fault=='hardlink_original':
  # The shared WSL filesystem cannot create hardlinks via Win32. Exercise the
  # exact samefile API result instead; local-fixture run01 also tested a real link.
  actual_samefile=os.path.samefile;pair={p.target.resolve(),p.original.resolve()}
  monkeypatch.setattr(os.path,'samefile',lambda left,right:True if {Path(left).resolve(),Path(right).resolve()}==pair else actual_samefile(left,right))
 elif fault=='different_bytes':p.target.write_bytes(b'other geometry')
 elif fault=='same_directory':
  other=p.original.parent/'other.sldprt';other.write_bytes(p.original.read_bytes());v['expected_document_path']=str(other)
 elif fault=='no_vendor_rebuild_admission':v['allow_vendor_default_import_rebuild']=False
 elif fault=='non_default_policy':v['message_policy']='answer_no'
 elif fault=='bool_pid':v['process_id']=True
 elif fault=='changed_export_source':p.source.write_bytes(b'changed original CAM')
 with pytest.raises(ValueError):c.validate(v)
 assert not Path(v['receipt_path']).exists()

def test_target_consumption_survives_archive_and_source_sha_changes(packet):
 p=packet;old=c.marker_path(p.v,sha(p.archive));v=deepcopy(p.v);v['expected_source_sha256']='f'*64
 assert c.marker_path(v,'a'*64)==old
 old.write_text('{}',encoding='utf-8')
 p.archive.write_bytes(b'new independently exported archive');p.export['output'].update(sha256=sha(p.archive),bytes=p.archive.stat().st_size)
 p.export_path.write_text(json.dumps(p.export),encoding='utf-8');p.v['export_receipt_sha256']=sha(p.export_path)
 with pytest.raises(ValueError):c.validate(p.v)

@pytest.mark.parametrize('fault',['request','source_metadata','target_bytes','receipt_occupied'])
def test_prepared_authority_burns_on_drift_and_cannot_be_reused(packet,fault):
 p=packet;bundle=c.prepare(p.v,runtime_check=lambda:None);v=deepcopy(p.v)
 if fault=='request':v['process_id']+=1
 elif fault=='source_metadata':
  st=p.source.stat();os.utime(p.source,ns=(st.st_atime_ns,st.st_mtime_ns+1000000))
 elif fault=='target_bytes':p.target.write_bytes(b'mutated copy')
 else:Path(v['receipt_path']).write_text('{}',encoding='utf-8')
 with pytest.raises(ValueError):c._consume(bundle,v,lambda:None)
 assert bundle.used is True
 with pytest.raises(ValueError):c._consume(bundle,p.v,lambda:None)

@pytest.mark.parametrize('fault',[None,'import_prompt','native_exception','bool_hresult','nonzero_hresult','after_capture_error','cleanup_error','source_changed','preexisting_operation','preexisting_feature','preempty_change','owner_changed_after_cleanup'])
def test_one_dispatch_and_fail_closed_terminal_flags(packet,monkeypatch,fault):
 p=packet;v=p.v;state={'events':0,'active':True,'closed':False,'empty_calls':0};calls=[];guards=[]
 doc=dict(path=str(p.target),title=p.target.name,type=1,needs_save=False);app=object();sw=object()
 body=dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.])
 def member(obj,name,*args):
  assert obj is app and name=='ImportCAMData' and args==(str(p.archive),0,False)
  assert Path(v['receipt_path']).exists() and c.marker_path(v,sha(p.archive)).exists()
  pending=json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'));assert pending['native_dispatch_pending'] is True
  calls.append(name);doc['needs_save']=True
  if fault=='import_prompt':state['events']=1
  if fault=='source_changed':p.source.write_bytes(b'mutated old MILL')
  if fault=='native_exception':raise RuntimeError('native import uncertain')
  return False if fault=='bool_hresult' else 17 if fault=='nonzero_hresult' else 0
 monkeypatch.setattr(c,'_member',member)
 monkeypatch.setattr(sg,'_member',lambda obj,name,*a:123 if name=='GetProcessID' else object() if name=='ActiveDoc' else pytest.fail(name))
 monkeypatch.setattr(sg,'raw_part_identity',lambda sw:deepcopy(doc));monkeypatch.setattr(sg,'_typed',lambda raw,name,tlb:raw)
 def empty(*args,**kw):
  kw['check']();kw['diagnostic']['capture_complete']=True;state['empty_calls']+=1
  machine={'machine_type':0,'name':str(state['empty_calls']) if fault=='preempty_change' else 'empty'}
  return dict(operation_counts=[1 if fault=='preexisting_operation' else 0],feature_setups=[dict(feature_count=1 if fault=='preexisting_feature' else 0)],current_machine=machine),{}
 monkeypatch.setattr(c,'capture_empty_snapshot',empty)
 monkeypatch.setattr(c,'cad_features',lambda model:([],None));monkeypatch.setattr(c,'cad_bodies',lambda model:[deepcopy(body)])
 def after(app,tlb,guard,diagnostic,progress):
  guard._fast()
  if fault=='after_capture_error':raise RuntimeError('incomplete imported inventory')
  diagnostic['capture_complete']=True
  op=operation(9001);op['linked_feature_ids']=[8001];op['assigned_tool']['native_id']=7001;op['toolpath_record_counts']=[];op['toolpath_generated']=False
  return dict(operation_count=1,features=[dict(native_id=8001)],operations=[op],capture_complete=True)
 monkeypatch.setattr(c,'capture_import_inventory',after)
 class Context(c.ImportContext):
  def __init__(self,*args):
   super().__init__(*args);self.app=app;self.expected=deepcopy(doc);self.session=SimpleNamespace(summary=lambda:messages(state['active'],state['events']))
  def identity(self):return deepcopy(doc)
  def start(self):self.verify_files();self.check_events()
  def guard(self):
   g=super().guard();guards.append(g);return g
  def close(self):
   if self.closed:return
   self.closed=True;state['closed']=True;state['active']=False;self.r['messages']=self.session.summary()
   if fault=='cleanup_error':raise RuntimeError('disconnect error')
   if fault=='owner_changed_after_cleanup':doc['path']=str(p.original)
   c.event_health(self.r['messages'],active=False)
 result=c.run_import(sw,'registered','unused',runtime_check=lambda:None,_context_factory=Context,_preflight=lambda tlb:{},**v)
 pre=fault in ['preexisting_operation','preexisting_feature','preempty_change']
 assert calls==([] if pre else ['ImportCAMData'])
 assert all(not g._active for g in guards) and state['closed']
 assert all(result[k] is False for k in ['Save_attempted','GTP_attempted','GOP_attempted','AFR_attempted','explicit_rebuild_attempted','TechDB_write_attempted','model_saved','automatic_replay','CAM_migration_verified','production_qualified','stock_parameters_exported','feature_association_verified'])
 assert result['vendor_default_import_rebuild_allowed'] is True and result['vendor_default_internal_effects_qualified'] is False
 assert json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))==result
 if fault is None:
  assert result['status']=='review_required' and result['import_observed'] is True and result['readback_verified'] is True
  row=result['archive_comparison']['ordered_observations'][0];assert row['historical_operation_native_id']==271 and row['observed_operation_native_id']==9001
  assert result['archive_comparison']['native_identity_mapping_verified'] is False and row['cached_count_match'] is False
  assert p.target.read_bytes()==p.original.read_bytes() and p.source.read_bytes()==b'protected old MILL c483 provenance'
 else:
  assert result['status']==('error' if pre else 'uncertain') and result['import_observed'] is False and result['readback_verified'] is False
 if fault=='import_prompt':assert result['messages']['event_count']==1 and result['after']['operations'][0]['native_id']==9001
 if not pre:
  again=dict(v,receipt_path=str(Path(v['receipt_path']).with_name('another_receipt.json')))
  with pytest.raises(ValueError):c.validate(again)

@pytest.mark.parametrize('fault',['pid','creation','executable','path','document_type'])
def test_context_identity_rejects_wrong_owner_or_document(packet,monkeypatch,fault):
 p=packet;v=p.v;doc=dict(path=str(p.target),title=p.target.name,type=1,needs_save=False)
 identity=dict(alive=True,process_id=123,create_time=456.,executable=str(p.target.parent/'SLDWORKS.exe'))
 if fault=='pid':identity['process_id']=999
 elif fault=='creation':identity['create_time']+=1
 elif fault=='executable':identity['executable']=str(p.target.parent/'other.exe')
 elif fault=='path':doc['path']=str(p.original)
 else:doc['type']=2
 monkeypatch.setattr(c,'_process_identity',lambda pid:identity);monkeypatch.setattr(c,'_member',lambda *a:123);monkeypatch.setattr(c,'document_snapshot',lambda sw:doc)
 ctx=c.ImportContext(object(),'registered','unused',v,{}, {},lambda:None,lambda:None)
 with pytest.raises((ValueError,RuntimeError)):ctx.identity()

def test_no_explicit_save_generation_rebuild_UI_or_response_dispatch():
 tree=ast.parse((STAGE/'scripts/sw_cam_process_import.py').read_text(encoding='utf-8-sig'))
 forbidden={'Save','Save3','SaveAs','SaveAs3','EditRebuild3','ForceRebuild3','GenerateToolpath','GenerateOperation','ExtractFeatures','SetResponse','SendMessage','PostMessage','Rebuild','GTP','GOP','AFR'}
 dispatched=[]
 for node in ast.walk(tree):
  if isinstance(node,ast.Call):
   if isinstance(node.func,ast.Attribute):assert node.func.attr not in forbidden
   if isinstance(node.func,ast.Name) and node.func.id in ['_member','read'] and len(node.args)>1 and isinstance(node.args[1],ast.Constant):
    member=node.args[1].value;assert member not in forbidden;dispatched.append(member)
 assert dispatched.count('ImportCAMData')==1


class Node:
 def __init__(self,native_id=None,**members):self.native_id=native_id;self.members=members

def import_graph():
 tool=Node(7001,IsMillTool=True,ToolType=8,CutDiameter=.6,Protrusion=20.)
 feature=Node(8001,Suppressed=False,FeatureName='Imported current R25 target',VolumeType=2,SubType=0)
 fsetup=Node(8101,IGetEnumFeatures=[feature],Axis=[0.,0.,1.],GetReferencePosition=[0.,0.,26.])
 path=Node(RecordCount=29)
 op=Node(9001,OpernType=1,Suppressed=False,GetIsToolpathGenerated=True,IGetAllFeatures=[feature],IGetEnumToolpaths=[path],IGetTool=tool)
 osetup=Node(9101,IGetEnumOperations=[op])
 machine=Node(MachType=1,IGetEnumSetups=[fsetup],IGetEnumOpSetups=[osetup])
 config=Node(SWConfigurationName='Default',ConfigurationName='CAM-R25')
 doc=Node(GetDocType=1,GetActiveConfigurationName='CAM-R25',GetActiveConfiguration=config,IGetMachine=machine)
 app=Node(IGetActiveDoc=doc)
 reads=[]
 class Guard:
  def typed(self,raw,name):assert raw is not None;return raw
  def read(self,raw,name,*args):
   reads.append(name)
   if name=='Count':return len(raw)
   if name=='Item':return raw[args[0]]
   if name=='GetCWObjectID':return args[0].native_id,True
   value=raw.members[name]
   if isinstance(value,Exception):raise value
   return value
 return SimpleNamespace(app=app,doc=doc,config=config,machine=machine,feature=feature,fsetup=fsetup,path=path,op=op,osetup=osetup,tool=tool,guard=Guard(),reads=reads)

def test_generic_inventory_observes_new_IDs_and_truthful_limits():
 g=import_graph();diagnostic={};observations=[]
 result=c.capture_import_inventory(g.app,'unused',g.guard,diagnostic,lambda d:observations.append(deepcopy(d)))
 assert diagnostic['capture_complete'] is True and result['capture_complete'] is True
 assert result['operations'][0]['native_id']==9001 and result['features'][0]['native_id']==8001
 assert result['operations'][0]['assigned_tool']['native_id']==7001 and result['operations'][0]['all_linked_features_observed'] is True
 assert result['operation_count']==1 and result['feature_count']==1 and result['total_record_count']==29
 assert result['feature_association_verified'] is False and result['units_verified'] is False
 assert diagnostic['native_read_count']==len(g.reads)<4096 and observations
 assert not set(g.reads)&{'GetEnumRecords','IGetEnumRecords','IGetProfile','ImportCAMData','Rebuild','SetResponse','Save','Save3','GenerateToolpath'}

@pytest.mark.parametrize('fault',['nine_setups','sixtyfive_features','thirtythree_operations','thirtythree_paths','record_overflow','aggregate_record_overflow','duplicate_feature','duplicate_link','null_tool','nonmill_tool','bad_diameter','bad_axis','config_mismatch','nonbool_generated','getter_error','bool_doctype'])
def test_generic_inventory_bounded_fail_closed_and_keeps_partial_rows(fault):
 g=import_graph();diagnostic={}
 if fault=='nine_setups':g.machine.members['IGetEnumSetups']=[g.fsetup]*9
 elif fault=='sixtyfive_features':g.fsetup.members['IGetEnumFeatures']=[g.feature]*65
 elif fault=='thirtythree_operations':g.osetup.members['IGetEnumOperations']=[g.op]*33
 elif fault=='thirtythree_paths':g.op.members['IGetEnumToolpaths']=[g.path]*33
 elif fault=='record_overflow':g.path.members['RecordCount']=100001
 elif fault=='aggregate_record_overflow':g.op.members['IGetEnumToolpaths']=[Node(RecordCount=60000),Node(RecordCount=60000)]
 elif fault=='duplicate_feature':g.fsetup.members['IGetEnumFeatures']=[g.feature,g.feature]
 elif fault=='duplicate_link':g.op.members['IGetAllFeatures']=[g.feature,g.feature]
 elif fault=='null_tool':g.op.members['IGetTool']=None
 elif fault=='nonmill_tool':g.tool.members['IsMillTool']=False
 elif fault=='bad_diameter':g.tool.members['CutDiameter']=float('nan')
 elif fault=='bad_axis':g.fsetup.members['Axis']=[0.,0.,float('inf')]
 elif fault=='config_mismatch':g.config.members['ConfigurationName']='different'
 elif fault=='nonbool_generated':g.op.members['GetIsToolpathGenerated']=1
 elif fault=='getter_error':g.op.members['IGetTool']=RuntimeError('native getter failed once')
 elif fault=='bool_doctype':g.doc.members['GetDocType']=True
 with pytest.raises((ValueError,RuntimeError,AssertionError)):
  c.capture_import_inventory(g.app,'unused',g.guard,diagnostic,lambda d:None)
 assert diagnostic['capture_complete'] is False and diagnostic['state']['capture_complete'] is False
 assert diagnostic['native_read_count']<=4096
 if fault in ['getter_error','bad_diameter','nonmill_tool','null_tool']:
  assert diagnostic['state']['operations'][0]['native_id']==9001
  assert diagnostic['state']['operations'][0]['toolpath_record_counts']==[29]
  assert g.reads.count('IGetTool')==1

def test_unresolved_imported_feature_link_is_observed_without_association_claim():
 g=import_graph();g.op.members['IGetAllFeatures']=[Node(9999)]
 result=c.capture_import_inventory(g.app,'unused',g.guard,{},lambda d:None)
 assert result['operations'][0]['linked_feature_ids']==[9999]
 assert result['operations'][0]['all_linked_features_observed'] is False
 assert result['feature_association_verified'] is False
