"""Bounded import tests use real ScopedCamDispatchGuard with fake application methods."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import hashlib,json,os,sys
import pytest
sys.dont_write_bytecode=True
K=Path(os.environ.get('SWMCP_RUNTIME_ROOT',os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1])) );S=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(K));import scripts;scripts.__path__.insert(0,str(S/'scripts'))
from scripts import sw_cam_process_import as c
from scripts import sw_cam_dispatch_guard as sg
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def messages(active=True,n=0):
 return dict(subscribed=True,active=active,disconnected=not active,event_count=n,events=[dict(message_id=i,response='default_unknown')for i in range(n)],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
def row(oid):
 return dict(native_id=oid,mill_operation_type=0,suppressed=False,toolpath_generated=True,toolpath_record_counts=[7],linked_feature_ids=[2],assigned_tool=dict(tool_type_raw=2,cut_diameter_native=8.,protrusion_native=25.))
@pytest.fixture
def packet(tmp_path,monkeypatch):
 # Native archive locality is tested separately; file/guard fixtures may live on a shared workspace.
 monkeypatch.setattr(c,"local_archive_path",lambda p: p.parent==tmp_path)
 original=tmp_path/'original/part.sldprt';copy=tmp_path/'isolated/copy.sldprt';cam=tmp_path/'cam.sldprt';archive=tmp_path/'process.prtcam';receipt=tmp_path/'export.json'
 original.parent.mkdir();copy.parent.mkdir();original.write_bytes(b'geometry');copy.write_bytes(original.read_bytes());cam.write_bytes(b'saved CAM');archive.write_bytes(b'exported process')
 state=dict(capture_complete=True,operations=[row(1)])
 ex=dict(scope=c.EXPORT_SCOPE,status='review_required',phase='finished',export_verified=True,readback_verified=True,runtime_unchanged=True,source_unchanged=True,native_call_returned=True,native_return_type='int',native_return_value=0,native_dispatch_pending=False,messages=messages(False),before=state,after=deepcopy(state),request=dict(expected_document_path=str(cam),expected_source_sha256=sha(cam)),source_before_sha256=sha(cam),source_after_sha256=sha(cam),output=dict(path=str(archive),sha256=sha(archive),bytes=archive.stat().st_size))
 receipt.write_text(json.dumps(ex),encoding='utf-8')
 v=dict(process_id=123,expected_process_create_time=456.,expected_document_path=str(copy),expected_source_sha256=sha(copy),original_document_path=str(original),original_source_sha256=sha(original),export_receipt_path=str(receipt),export_receipt_sha256=sha(receipt),receipt_path=str(tmp_path/'import.json'),qualification_only=True,message_policy='vendor_default',acknowledge_isolated_copy=True,allow_vendor_default_import_rebuild=True)
 return v,ex,original,copy,cam,archive,receipt

def test_actual_file_validation_derives_archive_and_copy_marker(packet):
 v,*_=packet;data=c.validate(v)
 assert data['archive'].suffix=='.prtcam'and data['copy']!=data['original']
 assert data['marker'].parent==data['copy'].parent and len(data['pins'])==6

@pytest.mark.parametrize('fault',['same_original','same_cam','changed_copy','changed_original','changed_archive','prior_marker','false_qualification','deny_vendor_effect','custom_policy','export_uncertain','export_bool','export_pending','export_changed_before','existing_receipt'])
def test_preflight_rejects_wrong_authority_or_nonisolated_target(packet,fault):
 v,ex,original,copy,cam,archive,receipt=packet
 if fault=='same_original':v['expected_document_path']=str(original)
 elif fault=='same_cam':v['expected_document_path']=str(cam);v['expected_source_sha256']=sha(cam);v['original_source_sha256']=sha(cam)
 elif fault=='changed_copy':copy.write_bytes(b'changed')
 elif fault=='changed_original':original.write_bytes(b'changed')
 elif fault=='changed_archive':archive.write_bytes(b'changed')
 elif fault=='prior_marker':c.marker_path(v,sha(archive)).write_text('{}',encoding='utf-8')
 elif fault=='false_qualification':v['qualification_only']=False
 elif fault=='deny_vendor_effect':v['allow_vendor_default_import_rebuild']=False
 elif fault=='custom_policy':v['message_policy']='answer_no'
 elif fault=='export_uncertain':ex['status']='uncertain'
 elif fault=='export_bool':ex['native_return_value']=False
 elif fault=='export_pending':ex['native_dispatch_pending']=True
 elif fault=='export_changed_before':ex['after']['operations'][0]['native_id']=9
 elif fault=='existing_receipt':Path(v['receipt_path']).write_text('{}',encoding='utf-8')
 if fault.startswith('export_'):
  receipt.write_text(json.dumps(ex),encoding='utf-8');v['export_receipt_sha256']=sha(receipt)
 with pytest.raises(ValueError):c.validate(v)

@pytest.mark.parametrize('fault',[None,'exception','return_bool','return_nonzero','pre_event','import_event','post_event','post_inventory','CAD_change','count_change','source_change','runtime_after'])
def test_actual_scoped_dispatch_one_import_fresh_postread_and_no_save(packet,monkeypatch,fault):
 v,ex,original,copy,cam,archive,receipt=packet;events={'n':0,'active':True};doc=dict(type=1,title='copy.sldprt',path=str(copy),needs_save=False);calls=[];guards=[];ctxs=[]
 app=object();sw=object()
 def native_member(obj,name,*args):
  assert obj is app and name=='ImportCAMData'and args==(str(archive),0,False)
  calls.append(name);events['n']=1 if fault=='import_event'else 0;doc['needs_save']=True
  if fault=='source_change':original.write_bytes(b'changed')
  if fault=='exception':raise RuntimeError('Native import failed')
  return False if fault=='return_bool'else 1 if fault=='return_nonzero'else 0
 monkeypatch.setattr(c,'_member',native_member)
 monkeypatch.setattr(sg,'_member',lambda obj,name,*args:123 if name=='GetProcessID'else object()if name=='ActiveDoc'else pytest.fail(name))
 monkeypatch.setattr(sg,'raw_part_identity',lambda sw:deepcopy(doc));monkeypatch.setattr(sg,'_typed',lambda obj,name,tlb:obj)
 body=dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.])
 def inventory(app,tlb,guard,diagnostic,progress):
  guard._fast()
  if fault=='post_event':events['n']+=1
  guard._fast()
  if fault=='post_inventory':raise RuntimeError('Native feature capture failed')
  diagnostic['capture_complete']=True;rows=[row(101)]
  if fault=='count_change':rows.append(row(102))
  return dict(operation_count=len(rows),features=[dict(native_id=2)],operations=rows)
 monkeypatch.setattr(c,'capture_import_inventory',inventory)
 def empty_snapshot(*args,**kw):
  assert kw['required_machine_type']is None;kw['check']();kw['diagnostic']['capture_complete']=True
  return dict(operation_counts=[],feature_setups=[],current_machine={'machine_type':0},material_raw=None),{}
 monkeypatch.setattr(c,'capture_empty_snapshot',empty_snapshot)
 monkeypatch.setattr(c,'cad_features',lambda model:([],None))
 def bodies(model):
  b=deepcopy(body)
  if doc['needs_save']and fault=='CAD_change':b['box_m'][-1]=2.
  return [b]
 monkeypatch.setattr(c,'cad_bodies',bodies)
 class Context:
  capture=c.ImportContext.capture;adopt_post_import_baseline=c.ImportContext.adopt_post_import_baseline
  check_events=c.ImportContext.check_events
  def __init__(self,sw,clsid,tlb,v,data,r,persist,runtime):
   self.sw,self.clsid,self.tlb=sw,clsid,tlb;self.v,self.data,self.r=v,data,r;self.persist=persist;self.app=app;self.expected=deepcopy(doc);self.baseline=0;self.closed=False
   self.session=SimpleNamespace(summary=lambda:messages(events['active'],events['n']));ctxs.append(self)
  def identity(self):return deepcopy(doc)
  def verify_files(self):
   for p in self.data['pins']:c.require(sha(p['path'])==p['sha256'],'Protected file changed')
  def verify_owned(self):c.require(doc==self.expected,'Identity changed');self.check_events()
  def start(self):
   if fault=='pre_event':events['n']=1
   self.check_events()
  def guard(self):
   g=sg.ScopedCamDispatchGuard(sw,'dummy',process_id=123,expected_document=self.expected,source_sha256=v['expected_source_sha256'],evidence_pins=self.data['pins'],verify_evidence=self.verify_files,verify_owned_process=self.verify_owned,check_events=self.check_events);guards.append(g);return g
  def close(self):
   if self.closed:return
   self.closed=True;events['active']=False;self.r['messages']=self.session.summary();c.event_health(self.r['messages'],active=False)
 def runtime():
  if fault=='runtime_after'and ctxs and ctxs[0].closed:raise ValueError('Runtime drift')
 result=c.run_import(sw,'registered','dummy',runtime_check=runtime,_context_factory=Context,_preflight=lambda tlb:{},**v)
 assert calls==([]if fault=='pre_event'else['ImportCAMData'])
 assert all(result[k]is False for k in('Save_attempted','GTP_attempted','GOP_attempted','AFR_attempted','explicit_rebuild_attempted','TechDB_write_attempted','model_saved','automatic_replay','CAM_migration_verified','production_qualified'))
 assert json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))==result
 assert all(not g._active for g in guards)
 if fault is None:
  assert len(guards)==4 and [g._claimed for g in guards]==[False,False,True,False]
  assert result['readback_verified']is True and result['import_event_baseline']['event_count']==0 and result['messages']['event_count']==0
  assert result['archive_comparison']['native_identity_mapping_verified']is False
  assert copy.read_bytes()==original.read_bytes()==b'geometry'and cam.read_bytes()==b'saved CAM'
 else:
  assert result['readback_verified']is False
  if fault!='pre_event':assert result['status']=='uncertain'and Path(result['marker_path']).exists()
  if fault not in('pre_event','exception'):assert result['native_call_returned']is True
  if fault in('import_event','post_event','post_inventory','CAD_change','count_change','source_change','runtime_after'):assert result['native_return_value']==0
  if fault in('post_event','import_event'):assert result['messages']['event_count']==1
  if fault=='import_event':assert 'after'in result
 if fault!='pre_event':
  later=dict(v,receipt_path=str(Path(v['receipt_path']).with_name('second.json')))
  with pytest.raises(ValueError):c.validate(later)

def test_compare_archive_does_not_assume_old_ids_or_cached_paths():
 a=row(1);b=row(99);b['toolpath_record_counts']=[];b['toolpath_generated']=False
 out=c.compare_archive([a],[b]);assert out['definition_count_matches']is True and out['ordered_observations'][0]['ordered_descriptor_match']is True
 assert out['ordered_observations'][0]['cached_count_match']is False and out['native_identity_mapping_verified']is False



@pytest.mark.parametrize('fault',['request','bundle','source','pin_metadata','marker'])
def test_prepared_same_call_rejects_drift_before_any_application_access(packet,fault):
 v,ex,original,copy,cam,archive,receipt=packet;bundle=c.prepare(v,runtime_check=lambda:None)
 if fault=='request':v['process_id']=456
 elif fault=='bundle':bundle.data['archived_operations'][0]['native_id']=999
 elif fault=='source':original.write_bytes(b'changed')
 elif fault=='pin_metadata':
  st=archive.stat();os.utime(archive,ns=(st.st_atime_ns,st.st_mtime_ns+1000000))
 elif fault=='marker':bundle.data['marker'].write_text('{}',encoding='utf-8')
 with pytest.raises(ValueError):c._consume(bundle,v,lambda:None)
 assert bundle.used is True
 with pytest.raises(ValueError):c._consume(bundle,v,lambda:None)

def test_preparation_parses_export_once_then_consumes_without_json_revalidation(packet,monkeypatch):
 v,*_=packet;calls=[];real=c.validate
 def validated(value):calls.append(1);return real(value)
 bundle=c.prepare(v,runtime_check=lambda:None,_validate=validated)
 data=c._consume(bundle,v,lambda:None)
 assert calls==[1]and data['export_pin']['sha256']==v['export_receipt_sha256']
 with pytest.raises(ValueError):c._consume(bundle,v,lambda:None)


def test_native_archive_locality_rejects_unc_before_file_access():
 from pathlib import PureWindowsPath
 class UNC:
  drive='\\\\host\\share'
  def resolve(self):raise AssertionError('UNC path should short circuit')
 assert c.local_archive_path(UNC())is False

def test_native_archive_locality_requires_local_resolution():
 class Local:
  drive='X:'
  def resolve(self):return str(Path('ordinary-local-archive.prtcam'))
 assert c.local_archive_path(Local())is True
 class MappedUNC(Local):
  def resolve(self):return '\\\\host\\share\\archive.prtcam'
 assert c.local_archive_path(MappedUNC())is False
