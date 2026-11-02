"""Portable workflow, guard, constructor and saved-context regressions."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os,sys,json,ast,inspect,types
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
ROOT=add_runtime()
m=required_module("sw_cam_serial_flat_tool")
from test_pocket_rough_exports import make_loaded
TARGET=required_test_module("test_serial_flat_profile").TARGET
IDENTITY=dict(ToolIdentifier='Serial test .8',ToolVendor='Vendor',ToolDescription='Conservative step envelope')

@pytest.fixture
def batch(tmp_path,monkeypatch):
    loaded,source=make_loaded(tmp_path)
    loaded['generated_face_operation_id']=267
    loaded['long_cut_registration']={'clsid':'fixture'}
    loaded['state']['operations'][6]['toolpath_record_counts']=[31196]
    loaded['generated_pocket']['record_counts']=[31196]
    evidence=tmp_path/'manufacturer.json';evidence.write_text('{}')
    recipe=dict(target=deepcopy(TARGET),identity=deepcopy(IDENTITY),
        profile_basis=m.geometry.BASIS,accepted_identity_aliases=[],source_pins=[m.common._pin(evidence)])
    holder=dict(file_path=str(tmp_path/'holder.mh'),pins=[])
    before=m.existing.factory.rough.cl.validate_catalogue_authority(loaded)
    before.append(dict(native_id=273,tool_type_raw=1,CutDiameter=2.,Protrusion=26.,StnNo=19.))
    loaded['long_cut_initial_catalogue']=deepcopy(before)
    loaded['serial_flat_catalogue']=deepcopy(before)
    loaded['registration']={'clsid':'fixture'}
    loaded['long_cut_requested_diameter']=2.
    loaded['fresh_finish_result']=dict(generated=True,tool_native_id=273)
    loaded['deep_loaded']={'guide_parameters':{'expected_parameters':{'binding':{'ops':'protected17'},'parameters':['protected8']},'document':{}},'generated':{}}
    loaded['neck_tool_candidate']=dict(native_id=273,full_tool={'protected':'oldD2'})
    loaded['neck_tool_checkpoint']=dict(protected='original273')
    control=SimpleNamespace(created=0,saved=0,props=[],closed=0,fail=None,drift=None)
    class Backend:
        def __init__(self):
            self.new_id=None;self.values={k:0 if type(v) is not str else 'unconfigured' for k,v in dict(TARGET,**IDENTITY).items()}
            self.current_state=deepcopy(loaded['state'])
        def start(self):pass
        def close(self):control.closed+=1
        def boundary(self):pass
        def finish(self):
            journal.report['protected_fourteen_cl_verified']=True
            journal.report['saved_cl']={'test':'fourteen complete streams'}
            journal.report['saved_cl_comparison']={'all14':True}
            journal.report['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
        def refresh_dirty(self):pass
        def snapshot(self,label):
            out=dict(route=m.prior.expected_route(loaded),tools=self.catalogue(),guide_snapshot=deepcopy(loaded['deep_loaded']['guide_parameters']['expected_parameters']))
            if control.drift:control.drift(label,out)
            return out
        def catalogue(self):
            out=deepcopy(before)
            if self.new_id is not None:out.append(dict(native_id=self.new_id,tool_type_raw=1,CutDiameter=2.,Protrusion=22.,StnNo=20.))
            return out
        def duplicate_candidates(self,recipe):return []
        def create(self,pending,returned):
            pending();control.created+=1
            if control.fail=='create':raise RuntimeError('unknown factory outcome')
            self.new_id=500;returned(object());return self.new_id
        def created_classification(self):return dict(MillToolType=1,MillToolSubType=3,EndRadius=0.)
        def field(self,name):return self.values[name]
        def property(self,name,value,pending):
            pending();control.props.append(name)
            if control.fail==name:raise RuntimeError('injected field failure')
            self.values[name]=value;return None
        def attach_holder(self,path,pending):
            pending()
            if control.fail=='holder':raise ValueError('holder alias')
            return 0
        def candidate(self,label):
            return dict(full_tool={'values':deepcopy(self.values),'tool_native_id':500},identity=deepcopy(IDENTITY))
        def save(self):
            control.saved+=1
            if control.fail=='save':return False
            return 0
        def saved_hash(self,report):
            source.write_bytes(b'Synthetic saved new neck tool, no native execution')
            digest=m.common._pin(source)['sha256']
            journal.report['source_transition']=dict(document=deepcopy(loaded['state']['document']),source_before_sha256=journal.report['initial_source_sha256'],source_after_sha256=digest,strict_save_return=0)
            self.current_state['saved_file_sha256']=digest
            return digest
    def verify(observed,recipe,holder_recipe):
        full=observed['full_tool']
        assert {k:full['values'][k] for k in TARGET}==TARGET
        if control.fail=='profile':raise ValueError('native profile does not implement the proposal')
        return dict(profile_verified=True,conservative_envelope_only=True,production_qualified=False)
    monkeypatch.setattr(m,'verify_candidate',verify)
    monkeypatch.setattr(m.reuse,'require_new_exact_cutter',lambda *a,**kw:{'verified':'test_double'})
    report=dict(scope=m.SCOPE,source_path=str(source),initial_source_sha256=m.common._pin(source)['sha256'],
        initial_catalogue=deepcopy(before),actions={},mutation_attempted=False,phase='prepared',status='error')
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'once.json')
    return SimpleNamespace(loaded=loaded,recipe=recipe,holder=holder,backend=Backend(),journal=journal,control=control,source=source,root=tmp_path)

def run(b):return m.run_backend(b.backend,b.journal,b.loaded,b.recipe,b.holder)
def test_one_tool_one_save_and_protected_route(batch):
 r=run(batch)
 assert r['readback_verified']is True,r.get('issue')
 assert batch.control.created==batch.control.saved==batch.control.closed==1
 assert batch.control.props==[v for v in m.FIELD_ORDER if v!='MillToolShankType']
 assert [v['property']for v in r['field_readbacks']]==list(m.FIELD_ORDER)
 assert r['assignment_attempted']is r['GTP_attempted']is r['GOP_attempted']is False
 assert r['initial_observation']['route']==r['final_observation']['route']
@pytest.mark.parametrize('fail',['create','holder','ShankLength','profile','save'])
def test_unknown_outcome_never_replayed(batch,fail):
 batch.control.fail=fail;r=run(batch)
 assert r['readback_verified']is False and r['status']=='uncertain'
 assert batch.control.created==1 and batch.control.closed==1
 assert batch.control.saved==(1 if fail=='save'else 0)
 with pytest.raises(ValueError,match='Fresh exact attempt'):run(batch)
 assert batch.control.created==1
@pytest.mark.parametrize('change',['route','old_tool','guide'])
def test_protected_change_prevents_save(batch,change):
 def drift(label,out):
  if label!='configured':return
  if change=='route':out['route']['operation_counts'][0]+=1
  elif change=='old_tool':out['tools'][0]['Protrusion']=999.
  else:out['guide_snapshot']['parameters'].append('unrequested')
 batch.control.drift=drift;r=run(batch)
 assert r['status']=='uncertain'and batch.control.saved==0

def test_duplicate_policy_prevents_creation(batch,monkeypatch):
 def reject(*a,**k):raise ValueError('duplicate')
 monkeypatch.setattr(m.reuse,'require_new_exact_cutter',reject)
 assert run(batch)['status']=='error'
 assert batch.control.created==batch.control.saved==0

def test_real_constructor_has_no_method_shadowing(batch):
 b=m.NativeBackend(batch.loaded,{},None,'clsid','typelib',{},lambda:None)
 assert isinstance(b.capture,types.ModuleType)
 names={n.func.attr for n in ast.walk(ast.parse(inspect.getsource(m.run_backend)))if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='backend'}
 assert names and all(callable(getattr(b,n))for n in names)
 assert b.guide_reader is None
 for name,value in vars(b).items():assert not(callable(getattr(type(b),name,None))and not callable(value)),name

def test_real_shared_reader_does_not_own_second_session(batch,monkeypatch):
 b=m.NativeBackend(batch.loaded,{},None,'clsid','typelib',{},lambda:None)
 token=object();context=object()
 def start(self):self.ctx=context;self.session=token;self.session_active=True
 monkeypatch.setattr(m.existing.factory.NativeBackend,'start',start)
 monkeypatch.setattr(m.deep,'ParameterBackend',lambda *a:SimpleNamespace())
 b.start()
 assert b.guide_reader.ctx is context and b.guide_reader.session is token
 assert b.guide_reader.session_active is True
 assert m.NativeBackend.close is m.existing.NativeBackend.close

@pytest.mark.parametrize('count,accepted',[(1,True),(64,True),(65,False)])
def test_actual_guard_constructor_bound(tmp_path,count,accepted):
 source=tmp_path/'part.SLDPRT';source.write_bytes(b'offline')
 pins=[]
 for i in range(count):
  p=tmp_path/('evidence'+str(i)+'.txt');p.write_text(str(i));pins.append(m.common._pin(p))
 loaded=dict(state=dict(document=dict(type=1,path=str(source),needs_save=False)),pins=pins)
 p=dict(process_id=1,expected_document_path=str(source),expected_source_sha256=m.prior._file_hash(source))
 if not accepted:
  with pytest.raises(ValueError,match='bounded'):m.guard_constructor_preflight(p,loaded,'not opened')
 else:
  proof=m.guard_constructor_preflight(p,loaded,'not opened')
  assert proof['native_calls']==0 and proof['entered']is False and proof['live_pin_count']==count

def test_explicit_context_provider_required_before_files():
 with pytest.raises(ValueError,match='trusted'):m.prepare(dict(action='create_serial_flat_tool',params={}))

def test_marker_bound_to_source_not_receipt_or_pid(tmp_path,monkeypatch):
 monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
 assert m.marker_path(str(tmp_path/'part.SLDPRT'),'a'*64)==m.marker_path(str(tmp_path/'part.SLDPRT'),'a'*64)
 assert m.marker_path(str(tmp_path/'part.SLDPRT'),'a'*64)!=m.marker_path(str(tmp_path/'part.SLDPRT'),'b'*64)

def terminal(batch,monkeypatch):
 batch.loaded['source_sha256']=m.prior._file_hash(batch.source)
 r=run(batch);r['recipe']=deepcopy(batch.recipe);r['holder_recipe']=deepcopy(batch.holder)
 r['phase_proofs_verified']=True;r['loaded_context_pin']={'path':'saved context reference','sha256':'a'*64}
 batch.loaded['deep_loaded']['generated']['saved_cl']={'original':'14'}
 monkeypatch.setattr(m.deep.cl,'verify_all',lambda a,b:{'all14':True})
 r['checkpoint']=m.make_checkpoint(r,batch.loaded);r['checkpoint_digest']=m.prior._digest(r['checkpoint'])
 return r

def test_complete_terminal_contract_and_compact_checkpoint(batch,monkeypatch):
 r=terminal(batch,monkeypatch)
 assert m.validate_terminal(r,batch.loaded)==batch.loaded
 assert 'context'not in r['checkpoint']
 assert r['checkpoint']['initial_context_pin']==r['loaded_context_pin']

@pytest.mark.parametrize('damage',['save_bool','pending','field','catalogue','cl','checkpoint','messages','profile_id','scope','save_pending','transition','full_state','action_inventory','property_return','proof'])
def test_terminal_semantics_reject_incomplete_or_changed_evidence(batch,monkeypatch,damage):
 r=terminal(batch,monkeypatch)
 if damage=='save_bool':r['actions']['SaveActiveDocument']['native_return_value']=False
 elif damage=='pending':r['actions']['AddNewTool3']['pending']=True
 elif damage=='field':r['field_readbacks'][0]['actual']=99.
 elif damage=='catalogue':r['initial_catalogue'][0]['native_id']=999
 elif damage=='cl':r['saved_cl_comparison']={'all14':False}
 elif damage=='checkpoint':r['checkpoint']['new_tool_native_id']=999
 elif damage=='messages':r['messages']['active']=True
 elif damage=='profile_id':r['final_candidate']['full_tool']['tool_native_id']=999
 elif damage=='scope':r['assignment_attempted']=True
 elif damage=='save_pending':r['save_stage']['save_pending']=True
 elif damage=='transition':r['source_transition']['source_before_sha256']='b'*64
 elif damage=='full_state':r['final_state']['operation_count']=999
 elif damage=='action_inventory':del r['actions']['property:OverallLen']
 elif damage=='property_return':r['actions']['property:OverallLen']['native_return_value']=0
 elif damage=='proof':r['candidate_qualification']['profile_verified']=False
 with pytest.raises(ValueError):m.validate_terminal(r,batch.loaded)

@pytest.fixture
def prepared(batch,monkeypatch):
 b=batch;tmp=b.root;source=b.source
 b.loaded['holder_recipe']=deepcopy(b.holder)
 b.loaded['generated_pin']={'fixture':'metadata audit stubbed only in prepare fixture'}
 backup=tmp/'backup.SLDPRT';backup.write_bytes(source.read_bytes())
 context=tmp/'context_authority.json';context.write_text('{}')
 recipepath=tmp/'recipe.json';recipepath.write_text(json.dumps(b.recipe))
 modulepin=m.common._pin(m.__file__)
 clsid='{00000000-0000-0000-0000-000000000001}'
 state=b.loaded['state'];state['document'].update(type=1,needs_save=False)
 state['operations']=[dict(native_id=100+i)for i in range(17)]
 b.loaded['deep_loaded']['guide_parameters']['expected_parameters']=dict(binding=dict(operations=deepcopy(state['operations'])),parameters=[{}for _ in range(8)])
 b.loaded.update(source_sha256=m.prior._file_hash(source),native_feature_inventory_verified=True,
  parent_pin=m.common._pin(context),pins=[modulepin],offline_export_proof_pins=[],bootstrap_export_pins=[])
 p=dict(process_id=1,expected_document_path=str(source),expected_source_sha256=m.prior._file_hash(source),
  expected_configuration='Default',addin_clsid=clsid,module_sha256=modulepin['sha256'],qualification_only=True,
  acknowledge_disposable_copy=True,message_policy='vendor_default',receipt_path=str(tmp/'tool_result.json'),
  saved_cl_path=str(tmp/'new_cl'/'saved.cl'),context_receipt_path=str(context),context_receipt_sha256=m.prior._file_hash(context),
  recipe_path=str(recipepath),recipe_sha256=m.prior._file_hash(recipepath),source_backup_path=str(backup),source_backup_sha256=m.prior._file_hash(backup))
 monkeypatch.setattr(m.deep.cl,'contract',lambda binding:None)
 monkeypatch.setattr(m.existing.factory,'audit_interfaces',lambda *a:dict(all_resolved=True,native_calls=0))
 monkeypatch.setattr(m.common,'_local_receipt',lambda p:None)
 monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp)
 def provider(p):return dict(loaded=deepcopy(b.loaded),registration=dict(clsid=clsid),typelib='not opened',interface_audit={'fixture':True},provider_pin=modulepin)
 return SimpleNamespace(request=dict(action='create_serial_flat_tool',params=p),provider=provider,batch=b)

def test_prepare_uses_real_guard_and_fresh_not_existing_cl_directory(prepared):
 v=m.prepare(prepared.request,context_provider=prepared.provider)
 assert v[1]['native_guard_preflight']['constructor_verified']is True
 assert not Path(v[0]['saved_cl_path']).parent.exists()
 assert v[1]['serial_flat_catalogue']==prepared.batch.loaded['serial_flat_catalogue']

@pytest.mark.parametrize('damage',['wrong_parent','missing_inventory','wrong_source','dirty','wrong_backup','same_backup','receipt_exists','cl_exists','marker_exists','sixtyfive_pins'])
def test_prepare_blocks_incomplete_authority_or_replay(prepared,damage):
 p=prepared.request['params'];b=prepared.batch
 if damage=='wrong_parent':b.loaded['parent_pin']['sha256']='a'*64
 elif damage=='missing_inventory':b.loaded['native_feature_inventory_verified']=False
 elif damage=='wrong_source':b.loaded['source_sha256']='a'*64
 elif damage=='dirty':b.loaded['state']['document']['needs_save']=True
 elif damage=='wrong_backup':Path(p['source_backup_path']).write_bytes(b'changed')
 elif damage=='same_backup':p['source_backup_path']=p['expected_document_path']
 elif damage=='receipt_exists':Path(p['receipt_path']).write_text('{}')
 elif damage=='cl_exists':Path(p['saved_cl_path']).parent.mkdir()
 elif damage=='marker_exists':m.marker_path(p['expected_document_path'],p['expected_source_sha256']).write_text('{}')
 elif damage=='sixtyfive_pins':
  b.loaded['pins']=[]
  for i in range(65):
   q=b.root/('pin'+str(i));q.write_text(str(i));b.loaded['pins'].append(m.common._pin(q))
 with pytest.raises(ValueError):m.prepare(prepared.request,context_provider=prepared.provider)
 assert b.control.created==b.control.saved==0

def test_compact_saved_loader_updates_current_digest_and_reference_chain(batch,monkeypatch):
 r=terminal(batch,monkeypatch);root=batch.root
 parent=root/'parent.json';parent.write_text('{}');oldmark=root/'oldmark.json';oldmark.write_text('{}')
 initial=deepcopy(batch.loaded);initial.update(parent_pin=m.common._pin(parent),group_marker_pin=m.common._pin(oldmark),
  pins=[m.common._pin(parent)],offline_export_proof_pins=[],bootstrap_export_pins=[])
 context=root/'context.json';context.write_text(json.dumps(initial));r['loaded_context_pin']=m.common._pin(context)
 r['checkpoint']=m.make_checkpoint(r,initial);r['checkpoint_digest']=m.prior._digest(r['checkpoint'])
 r.update(process_id=1,module_pin=m.common._pin(m.__file__),profile_module_pin=m.common._pin(m.geometry.__file__),
  live_pins=[m.common._pin(m.__file__),m.common._pin(m.geometry.__file__)],offline_proof_pins=[],bootstrap_export_pins=[])
 marker=root/'completed.json';marker.write_text(json.dumps(dict(scope=m.SCOPE,readback_verified=True,
  saved_source_sha256=r['saved_source_sha256'],actions=r['actions'])))
 r['marker_pin']=m.common._pin(marker)
 receipt=root/'completed_receipt.json';receipt.write_text(json.dumps(r))
 current=m.load_completed(str(receipt),m.prior._file_hash(receipt),process_id=1,
  expected_document_path=str(batch.source),expected_source_sha256=r['saved_source_sha256'])
 assert current['serial_flat_tool_native_id']==500
 assert current['source_sha256']==r['saved_source_sha256']
 assert current['parent_pin']==m.common._pin(receipt)
 assert current['current_context_sha256']==m.prior._digest(m.group.current_projection(current))
 assert current['deep_loaded']['generated']['saved_cl']==r['saved_cl']
 assert current['deep_loaded']['guide_parameters']['expected_parameters']==r['final_observation']['guide_snapshot']
