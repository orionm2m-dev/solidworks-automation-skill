"""Four explicit island sketches on an exclusive initialized-empty CAM copy.
Reuse the signed native sketch component, generic inventory and one checked Save.
No CAM feature/AddIsland/import/rebuild/GOP/GTP/tool/stock/parameter mutation.
"""
from copy import deepcopy
from pathlib import Path
import json,math,os,re
from scripts import sw_cam_explicit_island_sketch as component
from scripts import sw_cam_process_import as inventory
from scripts import sw_cam_process_import_recovery as read_scope
from scripts import sw_cam_current_saved_generation as engine

from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_current_pocket_saved_context import merge_pins
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import check_document_target

SCOPE='EXCLUSIVE_EMPTY_CAM_FOUR_ISLAND_SKETCH_BATCH_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
      'expected_sw_configuration','expected_cam_configuration','expected_setup_native_id',
      'expected_setup_axis_native','expected_setup_origin_native','copy_receipt_path','copy_receipt_sha256',
      'sketch_plan_path','sketch_plan_sha256','receipt_path','save_after_creation','qualification_only',
      'acknowledge_isolated_copy','acknowledge_four_sketches','message_policy'}
FLAGS=('readback_verified','CAD_body_fingerprint_unchanged','empty_CAM_unchanged','protected_files_unchanged','runtime_unchanged')
require=inventory.require
same_path=read_scope.same_path


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact four-sketch request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_setup_native_id'])is int and 0<v['expected_setup_native_id']<2**31,'Strict process/setup IDs required')
    t=v['expected_process_create_time'];require(type(t)in(int,float) and math.isfinite(t)and t>0,'Exact owned process lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute explicit path required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA256 required')
    require(Path(v['expected_document_path']).suffix.lower()=='.sldprt','Saved part copy required')
    for k in ('expected_sw_configuration','expected_cam_configuration'):require(type(v[k])is str and 0<len(v[k])<=1024 and '\x00'not in v[k],'Exact bounded configuration required')
    for k in ('expected_setup_axis_native','expected_setup_origin_native'):component.mixed.vector(v[k])
    require(abs(sum(x*x for x in v['expected_setup_axis_native'])-1)<1e-10,'Unit setup axis required')
    require(type(v['save_after_creation'])is bool and all(v[k]is True for k in ('qualification_only','acknowledge_isolated_copy','acknowledge_four_sketches')) and v['message_policy']=='vendor_default','Explicit bounded copy/sketch/Save policy required')
    return v


def pinned_json(path,sha):
    p=Path(path);require(p.is_absolute()and p.is_file()and not p.is_symlink()and p.suffix.lower()=='.json'and p.stat().st_size<=4*1024*1024,'Bounded pinned regular JSON required')
    raw=p.read_bytes();require(__import__('hashlib').sha256(raw).hexdigest()==sha,'Evidence bytes changed')
    data=json.loads(raw);require(type(data)is dict,'JSON object required');return data,inventory.file_pin(str(p),sha)


def pointer(value,path):
    require(type(path)is str and path.startswith('/')and len(path)<=512,'Explicit object JSON pointer required')
    for name in path[1:].split('/'):
        name=name.replace('~1','/').replace('~0','~');require(type(value)is dict and name in value,'Missing explicit geometry array');value=value[name]
    return value


def prepare(v):
    shape(v);copy,copy_pin=pinned_json(v['copy_receipt_path'],v['copy_receipt_sha256'])
    require(copy.get('scope')=='EXCLUSIVE_INITIALIZED_CAM_SKETCH_COPY_V1'and copy.get('exclusive_creation_verified')is True and copy.get('source_unchanged')is True,'Exclusive initialized copy evidence required')
    source,target=copy['source'],copy['target']
    require(same_path(target['path'],v['expected_document_path'])and target['sha256']==source['sha256']==v['expected_source_sha256'],'Exact copy/source bytes required')
    for item in (source,target):
        p=Path(item['path']);require(p.is_absolute()and p.is_file()and not p.is_symlink()and p.suffix.lower()=='.sldprt'and _file_hash(p)==item['sha256'],'Protected regular source/copy changed')
    require(not same_path(source['path'],target['path'])and not os.path.samefile(source['path'],target['path']),'Copy cannot alias protected source')
    plan,plan_pin=pinned_json(v['sketch_plan_path'],v['sketch_plan_sha256'])
    require(set(plan)=={'scope','geometry_contract_pin','loops_pointer','plane_z_mm','sketch_names','plane_names'}and plan['scope']=='FOUR_EXPLICIT_ISLAND_SKETCH_PLAN_V1','Exact explicit sketch plan required')
    gp=plan['geometry_contract_pin'];require(type(gp)is dict and set(gp)=={'path','sha256'},'Exact geometry contract pin required')
    contract,geometry_pin=pinned_json(gp['path'],gp['sha256'])
    specs=component.compile_loops(pointer(contract,plan['loops_pointer']),**{k:plan[k]for k in ('plane_z_mm','sketch_names','plane_names')})
    pins=[copy_pin,plan_pin,geometry_pin,inventory.file_pin(source['path'],source['sha256']),inventory.file_pin(target['path'],target['sha256'])]
    for module in (component,component.core,component.mixed,component.sketch,inventory,read_scope,engine,__import__(run_one_existing_save.__module__,fromlist=['x']),__import__(merge_pins.__module__,fromlist=['x'])):pins.append(inventory.file_pin(module.__file__,_file_hash(module.__file__)))
    pins.append(inventory.file_pin(__file__,_file_hash(__file__)));pins=merge_pins(pins,[])
    receipt=Path(v['receipt_path']);target_path=Path(v['expected_document_path'])
    marker=target_path.parent/('explicit_island_sketch_once_'+_digest(dict(scope=SCOPE,target=str(target_path.resolve()).casefold()))+'.json')
    for output in (receipt,marker):
        require(output.suffix.lower()=='.json'and output.parent.is_dir()and not output.exists()and not output.is_symlink(),'Fresh receipt and unused target marker required')
        require(all(not same_path(output,p['path'])for p in pins),'Output aliases protected input')
    require(not same_path(receipt,marker),'Distinct receipt and marker required')
    return dict(request=deepcopy(v),copy=copy,copy_pin=copy_pin,plan=plan,plan_pin=plan_pin,geometry_pin=geometry_pin,specs=specs,pins=pins,receipt=receipt,marker=marker,consumed=False)


def preflight(tlb):
    result=read_scope.preflight(tlb);cls=_interface_class('ICWApp',tlb)
    member=next(m for base in cls.__mro__ for m in getattr(base,'_methods_',[])if m.name=='SaveActiveDocument')
    require(member.idlflags[0]==12 and not member.paramflags,'Exact no-OUT SaveActiveDocument ABI required')
    result['SaveActiveDocument_public_ABI_verified']=True;return result


def verify_empty(state,v):
    require(state.get('capture_complete')is True and state['machine_type']==1,'Complete actual MILL inventory required')
    require(state['cam_configuration_name']==v['expected_cam_configuration']and state['associated_sw_configuration']==v['expected_sw_configuration'],'Exact CAD/CAM binding required')
    require(state['features']==[]and state['operations']==[]and all(type(state[k])is int and state[k]==0 for k in ('feature_count','operation_count','generated_operation_count','total_record_count','unique_tool_count')),'Only initialized empty CAM is admitted')
    require(len(state['feature_setups'])==1,'One empty feature setup required')
    row=state['feature_setups'][0]
    require(row['native_id']==v['expected_setup_native_id']and type(row['native_id'])is int and row['feature_ids']==[] and row['axis_native']==v['expected_setup_axis_native']and row['origin_native']==v['expected_setup_origin_native'],'Actual setup identity/frame differs')
    require(all(type(x['operation_count'])is int and x['operation_count']==0 for x in state['operation_setups']),'No operation rows allowed')
    return state


def without_save(value):
    out=deepcopy(value);out['cad'].pop('saved_file_sha256');out['cad'].pop('needs_save');return out


class Journal(engine.Journal):
    def marker_state(self):
        r=self.report;return dict(scope=SCOPE,target=r['request']['expected_document_path'],initial_source_sha256=r['source_before_sha256'],receipt_path=str(self.receipt),plan_pin=r['plan_pin'],actions=deepcopy(r['actions']),status=r['status'],phase=r['phase'],automatic_replay=False)
    def pending(self,name):
        allowed={'CreateSketch:'+str(i)for i in range(4)}|({'SaveActiveDocument'}if self.report['request']['save_after_creation']else set())
        require(name in allowed,'Outside declared sketch/explicit Save actions');self.report['mutation_attempted']=True
        return super().pending(name)


class Backend:
    def __init__(self,sw,clsid,tlb,data,report,persist,runtime_check):
        self.sw,self.clsid,self.tlb=sw,clsid,tlb;self.data=data;self.v=data['request'];self.report,self.persist,self.runtime_check=report,persist,runtime_check
        self.source=self.v['expected_source_sha256'];self.pins=deepcopy(data['pins']);self.expected=None;self.session=None;self.closed=False
    def files(self):
        for p in self.pins:require(_file_hash(p['path'])==p['sha256'],'Protected evidence/source changed')
    def identity(self):
        v=self.v;p=_process_identity(v['process_id']);require(p.get('alive')is True and p.get('process_id')==v['process_id']and p.get('create_time')==v['expected_process_create_time']and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact owned lifetime required')
        require(type(_member(self.sw,'GetProcessID'))is int and _member(self.sw,'GetProcessID')==v['process_id'],'Native PID differs')
        doc=raw_part_identity(self.sw);check_document_target(doc['path'],doc['title'],expected_path=v['expected_document_path'],required=True)
        require(type(doc['type'])is int and doc['type']==1 and type(doc['needs_save'])is bool,'Exact part identity required')
        config=_member(_member(_member(_member(self.sw,'ActiveDoc'),'ConfigurationManager'),'ActiveConfiguration'),'Name')
        require(config==v['expected_sw_configuration']and _file_hash(v['expected_document_path'])==self.source,'CAD config/source differs')
        return doc
    def events(self,active=True):
        self.report['messages']=self.session.summary();require(inventory.event_health(self.report['messages'],active=active)==0,'Any CAM event requires uncertain stop')
    def boundary(self):
        self.runtime_check();require(self.identity()==self.expected,'Owned document changed');self.events();self.files()
    def sketch_boundary(self):
        actual=self.identity();expected=deepcopy(self.expected);expected['needs_save']=actual['needs_save'];require(actual==expected,'Sketch changed document identity');self.expected=actual;self.boundary()
    def start(self):
        self.files();self.expected=self.identity();require(self.expected['needs_save']is False,'Fresh clean initialized copy required')
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded')
        self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb);self.save_app=_typed(self.app,'ICWApp',self.tlb)
        require(self.identity()==self.expected,'Bootstrap changed document');self.session=CamMessageSession(self.app,self.tlb);self.session.__enter__();self.boundary()
    def capture_inventory(self,label):
        self.boundary();diag={};self.report.setdefault('inventory_captures',[]).append(dict(label=label,diagnostic=diag));self.persist()
        with read_scope.ReadGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected,source_sha256=self.source,evidence_pins=self.pins,verify_evidence=self.files,verify_owned_process=lambda:require(self.identity()==self.expected,'Owned document changed'),check_events=self.events)as g:
            state=inventory.capture_import_inventory(self.app,self.tlb,g,diag,lambda _:self.persist())
        verify_empty(state,self.v);self.boundary();return state
    def capture(self,label,*,read_sketches=False):
        cam=self.capture_inventory(label);cad,model,refs=component.core._snapshot(self.sw,self.v['process_id'],self.v['expected_document_path'],self.data['specs'][0]);self.boundary()
        result=dict(inventory=cam,cad=cad)
        if read_sketches:
            rows=[]
            for spec in self.data['specs']:
                f=next((f for f in refs if str(f.Name)==spec['sketch_name']),None);require(f is not None and component.core.call(f,'GetTypeName2')=='ProfileFeature','Exact named sketch missing')
                native=component.core.call(f,'GetSpecificFeature2');observed=component.sketch._read_sketch(self.sw,native,spec);component.verify_readback(spec,observed);rows.append(dict(spec=deepcopy(spec),sketch_readback=observed))
                self.boundary()
            result['sketches']=rows
        return result
    def create_sketch(self,index,journal):
        out={};self.report['sketches'].append(out);self.persist()
        return component.create_one(self.sw,process_id=self.v['process_id'],document_path=self.v['expected_document_path'],source_sha256=self.source,expected_needs_save=self.expected['needs_save'],spec=self.data['specs'][index],check=self.sketch_boundary,claim=lambda:journal.pending('CreateSketch:'+str(index)),persist=self.persist,report=out)
    def save(self):
        self.boundary();self.report['Save_attempted']=True;self.persist();return _member(self.save_app,'SaveActiveDocument')
    def adopt_saved_source(self):
        new=_file_hash(self.v['expected_document_path']);self.report['saved_file_sha256_after_native_return']=new;self.persist()
        require(new!=self.source,'Explicit Save must advance source bytes')
        old=self.source;self.source=new;found=0
        for p in self.pins:
            if same_path(p['path'],self.v['expected_document_path']):require(p['sha256']==old,'Target preimage changed');p.update(inventory.file_pin(p['path'],new));found+=1
        require(found==1,'Exactly one mutable target pin required');self.expected=self.identity();require(self.expected['needs_save']is False,'Saved copy must be clean')
        self.report.update(model_saved=True,source_transition=dict(before_sha256=old,after_sha256=new,native_return_value=0));self.persist();self.boundary();return new
    def close(self):
        if self.closed:return
        self.closed=True
        if self.session is not None:
            try:self.session.__exit__(None,None,None)
            finally:self.events(False)

def verify_batch_snapshot(before,after,specs,created,source_sha256,*,saved):
    require(after['inventory']==before['inventory'],'Sketch/Save changed actual empty CAM inventory')
    cad=deepcopy(after['cad']);reference=before['cad']
    require(cad['saved_file_sha256']==source_sha256 and cad['needs_save']is(not saved),'Explicit current source/dirty state differs')
    cad['saved_file_sha256']=reference['saved_file_sha256'];cad['needs_save']=True
    component.verify_cad_delta(reference,cad,created)
    rows=after.get('sketches');require(type(rows)is list and len(rows)==4,'Four fresh final sketch readbacks required')
    for spec,row in zip(specs,rows):
        require(row['spec']==spec,'Ordered explicit sketch specification changed')
        component.verify_readback(spec,row['sketch_readback'])
    return dict(CAD_body_fingerprint_unchanged=True,empty_CAM_unchanged=True,four_signed_closed_profiles_verified=True,
        CAM_island_association_verified=False,physical_island_depth_verified=False,machining_qualified=False)


def save_comparison(snapshot,reference_solids):
    # Retain every raw capture separately. Only existing mass-property tolerance
    # and the two explicit Save fields are normalized for the checked Save.
    value=without_save(snapshot)
    require(component.core._same_bodies(reference_solids,value['cad']['solids']),'Save body fingerprint differs')
    value['cad']['solids']=deepcopy(reference_solids)
    value['sketches']=[row['spec']for row in snapshot['sketches']]
    return value


def run_backend(backend,journal,data):
    r=journal.report;created=[]
    try:
        backend.start();r['before_document']=deepcopy(backend.expected)
        r['phase']='before';r['before']=backend.capture('before');journal.persist()
        before=r['before'];require(before['cad']['needs_save']is False,'Initial sketch copy must be clean')
        names={x['name'].casefold()for x in before['cad']['features']}
        require(all(s[k].casefold()not in names for s in data['specs']for k in ('plane_name','sketch_name')),'All requested names must be new before the first mutation')
        backend.boundary();journal.claim()
        for i in range(4):
            name='CreateSketch:'+str(i);journal.action(name)
            observed=backend.create_sketch(i,journal)
            require(observed.get('native_readback_verified')is True and observed.get('status')=='sketch_observed','Individual sketch observation failed')
            journal.returned(name,None);r['actions'][name]['readback_verified']=True
            created.extend(deepcopy(observed['created_features']));r['created_features']=deepcopy(created);journal.persist()
            state=backend.capture_inventory('after_sketch_'+str(i))
            require(state==before['inventory'],'Sketch changed the protected empty CAM inventory');journal.persist()
        if data['request']['save_after_creation']:
            journal.action('SaveActiveDocument');r['native_save']={};r['save_snapshots']={}
            def capture(label):
                observed=backend.capture('save_'+label,read_sketches=True)
                r['save_snapshots'][label]=deepcopy(observed);journal.persist()
                r['definition_proof']=verify_batch_snapshot(before,observed,data['specs'],created,backend.source,saved=label=='after')
                return save_comparison(observed,before['cad']['solids'])
            def save():
                result=backend.save();journal.returned('SaveActiveDocument',result);return result
            run_one_existing_save(r['native_save'],capture=capture,verify=lambda _:None,guard=backend.boundary,
                claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=backend.adopt_saved_source)
            r['save_readback_verified']=True;r['actions']['SaveActiveDocument']['readback_verified']=True
            r['after']=deepcopy(r['save_snapshots']['after'])
        else:
            r['phase']='after_creation';r['after']=backend.capture('after_creation',read_sketches=True);journal.persist()
            r['definition_proof']=verify_batch_snapshot(before,r['after'],data['specs'],created,backend.source,saved=False)
        backend.boundary();backend.close();backend.runtime_check()
        r['after_cleanup_document']=backend.identity();require(r['after_cleanup_document']==backend.expected,'Document changed during cleanup')
        backend.events(False);backend.files()
        r.update(status='review_required',phase='finished',source_after_sha256=backend.source,current_pins=deepcopy(backend.pins),
            reason='FOUR_EXPLICIT_SIGNED_SKETCHES_OBSERVED_CAM_ISLAND_ASSOCIATION_NOT_CREATED',**{k:True for k in FLAGS})
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),reason=str(exc),**{k:False for k in FLAGS})
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',cleanup_error=_error(exc),**{k:False for k in FLAGS})
        r['phase']='finished'
        try:journal.persist()
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',receipt_write_error=_error(exc),**{k:False for k in FLAGS})
    return r


def new_report(data,abi):
    v=data['request']
    return dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',request=deepcopy(v),receipt_path=v['receipt_path'],
        marker_path=str(data['marker']),source_before_sha256=v['expected_source_sha256'],initial_pins=deepcopy(data['pins']),
        copy_pin=data['copy_pin'],plan_pin=data['plan_pin'],geometry_pin=data['geometry_pin'],specs=deepcopy(data['specs']),abi=abi,
        actions={},sketches=[],receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,
        native_call_returned=False,native_dispatch_pending=False,Save_attempted=False,save_attempted=False,model_saved=False,save_readback_verified=False,
        CAM_feature_creation_attempted=False,AddIsland_attempted=False,import_attempted=False,explicit_rebuild_attempted=False,
        GOP_attempted=False,GTP_attempted=False,tool_mutation_attempted=False,stock_edit_attempted=False,
        automatic_replay=False,automatic_rollback=False,reopen_persistence_verified=False,CAM_island_association_verified=False,
        physical_island_depth_verified=False,production_qualified=False,**{k:False for k in FLAGS})


def run_batch(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_backend=Backend):
    runtime_check();data=prepare(v)if prepared is None else prepared
    require(data['consumed']is False and data['request']==v,'Same unconsumed private preparation required');data['consumed']=True
    for pin in data['pins']:require(_file_hash(pin['path'])==pin['sha256'],'Prepared evidence changed')
    abi=preflight(tlb);data['pins']=merge_pins(data['pins'],[inventory.file_pin(str(tlb),_file_hash(tlb))])
    runtime_check();r=new_report(data,abi);journal=Journal(data['receipt'],data['marker'],r);journal.create()
    backend=_backend(sw,clsid,tlb,data,r,journal.persist,runtime_check)
    return run_backend(backend,journal,data)


def revoke(r,error):
    r.update(status='uncertain'if r['mutation_attempted']else'error',runtime_error=_error(error),**{k:False for k in FLAGS})
    _write_receipt(Path(r['receipt_path']),r);return r
