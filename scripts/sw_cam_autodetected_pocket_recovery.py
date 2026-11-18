"""Read a consumed pocket definition with an explicitly reviewed Attribute suffix.

No feature creation, operation generation, save, association or island-geometry call.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_autodetected_pocket as creator
from scripts import sw_cam_process_import as shared
from scripts.sw_cam_process_import_recovery import ReadGuard as InventoryReadGuard, READS, TYPES
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
require=shared.require
SCOPE='MILL_AUTODETECTED_POCKET_READ_RECOVERY_V1'
FLAGS=creator.FLAGS
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
      'expected_sw_configuration','expected_cam_configuration','creator_receipt_path','creator_receipt_sha256',
      'expected_feature_native_id','expected_attribute_suffix','receipt_path','qualification_only','message_policy'}

def suffix_shape(value):
    require(type(value)is list and 1<=len(value)<=32,'Explicit bounded observed Attribute suffix required')
    for row in value:
        require(type(row)is dict and set(row)=={'name','type'} and row['type']=='Attribute'
                and type(row['name'])is str and 0<len(row['name'])<=1024,'Exact named Attribute row required')
    require(len({x['name'].casefold() for x in value})==len(value),'Unique Attribute names required')

def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact read-only recovery request required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit qualification/default events required')
    for key in ('process_id','expected_feature_native_id'):
        require(type(v[key])is int and 0<v[key]<2**31,'Strict native identity required')
    require(type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
    for k in ('expected_sw_configuration','expected_cam_configuration'):
        require(type(v[k])is str and 0<len(v[k])<=1024,'Exact configuration required')
    suffix_shape(v['expected_attribute_suffix'])

def reconcile_raw(raw,expected_attribute_suffix):
    """Pure historical comparison; does not claim current files or current native state."""
    suffix_shape(expected_attribute_suffix);q=raw['request'];creator.shape(q)
    require(raw.get('scope')==creator.SCOPE and raw.get('status')=='uncertain' and raw.get('phase')=='finished'
            and raw.get('failed_phase')=='after' and raw.get('reason')=='Unrequested inventory/CAD delta','Exact known post-create comparison failure required')
    issue=raw.get('issue',{});require(issue.get('type')=='ValueError' and issue.get('hresult')is None
        and any(x.get('function')=='verify_delta' for x in issue.get('locations',[])),'Known pure delta failure required')
    for k in ('dispatch_claimed','native_call_attempted','native_call_returned','native_return_nonnull','auto_detect_islands_requested'):
        require(raw.get(k)is True,'Missing completed creation fact '+k)
    for k in ('native_dispatch_pending','Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','Import_attempted','model_saved','island_geometry_getter_attempted','automatic_replay'):
        require(raw.get(k)is False,'Unexpected previous action '+k)
    require(all(raw.get(k)is False for k in FLAGS),'Original uncertain flags must remain false')
    require(not any(k in raw for k in ('cleanup_error','runtime_error','receipt_write_error')),'Unresolved old cleanup/runtime failure')
    require(shared.event_health(raw['messages'],active=False)==0,'Prior CAM events prohibit this continuation')
    for label in ('before','before_confirmation','after'):
        require(raw[label+'_diagnostic'].get('capture_complete')is True and raw[label].get('capture_complete')is True,'Complete original captures required')
    require(creator.same_inventory(raw['before'],raw['before_confirmation']),'Original before captures differ')
    before,after=raw['before'],raw['after'];oldtree=before['sw_reference']['feature_tree'];newtree=after['sw_reference']['feature_tree']
    require(newtree==oldtree+expected_attribute_suffix,'Only exact reviewed appended Attribute suffix allowed')
    require(not ({x['name'].casefold()for x in oldtree}&{x['name'].casefold()for x in expected_attribute_suffix}),'Attribute name aliases original tree')
    normalized=deepcopy(after);normalized['sw_reference']['feature_tree']=deepcopy(oldtree)
    header=raw['feature_header'];require(type(header['native_id'])is int and header['native_id']==raw['new_feature_native_id'] and header['taper_angle_native']==0.0,'Exact returned feature/header required')
    proof=creator.verify_delta(before,normalized,header,q)
    return dict(definition_proof=proof,attribute_suffix=deepcopy(expected_attribute_suffix),header=deepcopy(header),expected_inventory=deepcopy(after))

def _authority_files(raw,creator_pin,expected_attribute_suffix,*,verify_files):
    d=reconcile_raw(raw,expected_attribute_suffix);q=raw['request']
    marker=Path(q['expected_document_path']).parent/('pocket_definition_'+_digest(dict(scope=creator.SCOPE,target=creator.canonical(q['expected_document_path']),sketch=q['sketch_spec']['sketch_name']))+'.json')
    require(creator.same_path(str(marker),raw['marker_path']),'Exact consumed marker path required')
    mark,mp=read_pin(str(marker),_file_hash(marker));require(mark==dict(scope=creator.SCOPE,request_digest=_digest(q),receipt_path=raw['receipt_path'],source_sha256=q['expected_source_sha256'],automatic_replay=False),'Exact consumed creation marker required')
    require(creator.same_path(creator_pin['path'],raw['receipt_path']),'Exact original native receipt path required')
    pins=deepcopy(raw['evidence_pins']);require(type(pins)is list and 1<=len(pins)<=32,'Bounded original evidence pins required')
    needed=[(q[a],q[b])for a,b in [('expected_document_path','expected_source_sha256'),('original_document_path','original_source_sha256'),('native_geometry_path','native_geometry_sha256'),('setup_receipt_path','setup_receipt_sha256'),('setup_save_receipt_path','setup_save_receipt_sha256'),('sketch_receipt_path','sketch_receipt_sha256')]]
    if creator.saved_caps(q):
        needed.extend((q[n+'_receipt_path'],q[n+'_receipt_sha256']) for n in ('caps','caps_geometry','caps_save','caps_inventory','caps_export'))
    needed.append((creator.__file__,_file_hash(creator.__file__)))
    for path,sha in needed:require(any(creator.same_path(p['path'],path)and p['sha256']==sha for p in pins),'Missing original source/evidence pin')
    if verify_files:
        for p in pins:shared.file_pin(p['path'],p['sha256'])
    sketch,kp=read_pin(q['sketch_receipt_path'],q['sketch_receipt_sha256'])
    caps_data=None
    if creator.saved_caps(q):
        caps_data=creator.validate_saved_caps(q,creator._input(q['sketch_spec']),sketch,[])
        checks=raw.get('saved_caps_sketch_checks',[])
        require(len(checks)>=1 and checks[0].get('readback_verified') is True,'Actual inline saved circle authority required')
        initial=checks[0]['before'];confirmed=checks[0]['after']
        require(creator.same_saved_sketch_capture(initial,confirmed) and initial['circle_readback']==raw['circle_readback'], 'Initial saved circle pair differs')
        snapshot=initial['snapshot']
        require(snapshot['features']==raw['before']['sw_reference']['feature_tree'] and
                creator._same_bodies(snapshot['solids'],raw['before']['sw_reference']['solids']) and
                snapshot['needs_save'] is False and snapshot['saved_file_sha256']==q['expected_source_sha256'],
                'Current saved circle/CAD initial binding differs')
        transition=raw['post_create_document_observation']
        require(transition['before']==raw['document_before'] and transition['before']['needs_save'] is False and
                type(transition['after']['needs_save']) is bool and
                transition['after']==dict(transition['before'],needs_save=transition['after']['needs_save']),
                'Exact observed post-Create dirty-only transition required')
    else:
        require(sketch.get('status')=='ok'and sketch.get('native_readback_verified')is True and sketch.get('saved')is False,'Verified original circle receipt required')
        require(sketch['after']['features']==raw['before']['sw_reference']['feature_tree'] and sketch['sketch_readback']==raw['circle_readback'],'Original analytic sketch/tree binding differs')
        require(sketch['after']['pid']==q['process_id'] and creator.same_path(sketch['after']['path'],q['expected_document_path']) and sketch['after']['saved_file_sha256']==q['expected_source_sha256'] and sketch['after']['needs_save']is True,'Exact unsaved sketch identity required')
    d.update(old=raw,creator_pin=creator_pin,marker_pin=mp,pins=pins+[creator_pin,mp],sketch=sketch,spec=creator._input(q['sketch_spec']),caps_data=caps_data)
    return d

def validate_authority(path,sha,expected_attribute_suffix):
    raw,rp=read_pin(path,sha)
    return _authority_files(raw,rp,expected_attribute_suffix,verify_files=True)

def bind_request(d,v):
    q=d['old']['request']
    for k in ('process_id','expected_process_create_time','expected_source_sha256','expected_sw_configuration','expected_cam_configuration'):
        require(type(v[k])is type(q[k])and v[k]==q[k],'Historical request binding differs '+k)
    require(creator.same_path(v['expected_document_path'],q['expected_document_path']) and v['expected_feature_native_id']==d['header']['native_id'],'Exact current target/feature required')

def prepare(v):
    shape(v);d=validate_authority(v['creator_receipt_path'],v['creator_receipt_sha256'],v['expected_attribute_suffix']);bind_request(d,v)
    receipt=Path(v['receipt_path']);require(receipt.suffix.lower()=='.json' and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh read receipt required')
    require(not any(creator.same_path(str(receipt),p['path'])for p in d['pins']),'Output aliases protected input')
    d['pins'].append(shared.file_pin(__file__,_file_hash(__file__)));d.update(request=deepcopy(v),receipt=receipt,consumed=False)
    return d

def verify_observation(data,state,header):
    require(creator.same_inventory(state,data['expected_inventory']),'Current inventory/CAD differs from exact consumed after-state')
    require(header==data['header'],'Current feature header differs from consumed creation')
    normalized=deepcopy(state);normalized['sw_reference']['feature_tree']=deepcopy(data['old']['before']['sw_reference']['feature_tree'])
    return creator.verify_delta(data['old']['before'],normalized,header,data['old']['request'])

class ReadGuard(InventoryReadGuard):
    def read(self,obj,name,*args):
        require(name in READS|{'GetOwner','IGetIslandCount','Depth','IGetTaperAngle','FeatureByName','GetTypeName2','GetSpecificFeature2','IsSuppressed'},'Only inventory/header/sketch getters permitted')
        # The inherited gate covers inventory only; retain its native boundary implementation.
        from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
        return ScopedCamDispatchGuard.read(self,obj,name,*args)

class ReadContext(creator.Context):
    def __init__(self,sw,clsid,tlb,v,data,r,persist,runtime_check):
        expected=deepcopy(data)
        if creator.saved_caps(data['old']['request']):
            expected['caps_data']['baseline']['feature_tree']+=deepcopy(data['attribute_suffix'])
            expected['initial_dirty']=post_create_document(data['old'])['needs_save']
        else:expected['sketch']['after']['features']+=deepcopy(data['attribute_suffix'])
        q=deepcopy(data['old']['request']);q['receipt_path']=v['receipt_path']
        super().__init__(sw,clsid,tlb,q,expected,r,persist,runtime_check)
    def guard(self):
        return ReadGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected,
            source_sha256=self.v['expected_source_sha256'],evidence_pins=self.data['pins'],verify_evidence=self.verify_files,
            verify_owned_process=self.verify_owned,check_events=self.check_events)
    def create(self,*args,**kwargs):raise ValueError('Creation is consumed; read-only continuation')
    def adopt_post_import_baseline(self):raise ValueError('No import or event baseline adoption')
    def read_header(self,label):
        self.r['phase']=label;self.persist()
        with self.guard()as g:
            doc=g.typed(g.read(self.app,'IGetActiveDoc'),'ICWDoc3')
            machine=g.typed(g.read(g.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            setups=shared._items(g.read(machine,'IGetEnumSetups'),g.typed,g.read,8)
            require(len(setups)==1 and _object_id(doc,setups[0],g.read)==self.v['owner_setup_native_id'],'One exact owner required')
            rows=shared._items(g.read(g.typed(setups[0],'ICWBaseSetup'),'IGetEnumFeatures'),g.typed,g.read,64)
            require(len(rows)==1,'One current feature required');raw=rows[0]
            base=g.typed(raw,'ICWFeature');mill=g.typed(raw,'ICWMillFeature');fid=_object_id(doc,base,g.read)
            require(fid==self.data['header']['native_id'],'Exact selected created ID required')
            h=dict(native_id=fid,owner_setup_native_id=_object_id(doc,g.read(base,'GetOwner'),g.read),suppressed=g.read(base,'Suppressed'),axis_native=creator._vector(g.read(base,'Axis')))
            self.r[label]=h;self.persist()
            for name,key in [('VolumeType','volume_type'),('IGetIslandCount','island_count')]:
                value=g.read(mill,name);require(type(value)is int,'Strict native integer '+name);h[key]=value;self.persist()
            for name,key in [('Depth','depth_native'),('IGetTaperAngle','taper_angle_native')]:h[key]=creator.number(g.read(mill,name))
            g._boundary()
        self.r[label]=deepcopy(h);self.persist();return h

def preflight(tlb):
    from ctypes import HRESULT,POINTER
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class
    abi=creator.preflight(tlb)
    cls=_interface_class('ICWBaseSetup',tlb)
    require(str(cls._iid_).upper()=='{FB4CC0DA-2AA4-11D6-A99F-00062999E55F}','Exact public base-setup owner required')
    methods=[m for c in cls.__mro__ for m in c.__dict__.get('_methods_',[])if m.name=='IGetEnumFeatures']
    require(len(methods)==1,'Unique public feature enumeration required');m=methods[0]
    require(m.restype is HRESULT and m.idlflags[0]==1 and m.argtypes==(POINTER(POINTER(IDispatch)),)
            and tuple(x[0]for x in m.paramflags)==(10,),'Exact base-setup feature enumeration ABI required')
    return dict(abi,feature_enumeration_owner='ICWBaseSetup',feature_enumeration_method='IGetEnumFeatures',feature_enumeration_dispid=1)

def run_read(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_context_factory=ReadContext):
    d=prepared if prepared is not None else prepare(v)
    require(d.get('consumed')is False and d['request']==v,'Unused exact same-call preparation required');d['consumed']=True
    for p in d['pins']:shared.file_pin(p['path'],p['sha256'])
    abi=preflight(tlb)
    r=dict(scope=SCOPE,status='running',phase='prepared',request=deepcopy(v),receipt_path=str(d['receipt']),
        creator_receipt_pin=d['creator_pin'],consumed_creation_marker_pin=d['marker_pin'],original_creator_status='uncertain',
        original_creator_flags={k:False for k in FLAGS},evidence_pins=deepcopy(d['pins']),abi=abi,
        exact_observed_attribute_suffix=deepcopy(d['attribute_suffix']),attribute_payload_verified=False,
        definition_only=True,geometry_unqualified=True,island_geometry_verified=False,physical_depth_verified=False,
        feature_association_verified=False,machining_eligible=False,production_qualified=False,
        mutation_attempted=False,Create_attempted=False,Save_attempted=False,GOP_attempted=False,GTP_attempted=False,
        AFR_attempted=False,Import_attempted=False,explicit_rebuild_attempted=False,automatic_replay=False,model_saved=False,
        source_before_sha256=v['expected_source_sha256'],**{k:False for k in FLAGS})
    def persist():_write_receipt(d['receipt'],r)
    _write_receipt(d['receipt'],r,create=True);ctx=None
    try:
        runtime_check();ctx=_context_factory(sw,clsid,tlb,v,d,r,persist,runtime_check);ctx.start()
        require(ctx.expected==post_create_document(d['old']),'Exact consumed current document identity required')
        before=ctx.capture_basic('before');hb=ctx.read_header('feature_header_before');verify_observation(d,before,hb)
        after=ctx.capture_basic('after');ha=ctx.read_header('feature_header_after');r['definition_proof']=verify_observation(d,after,ha)
        require(creator.same_inventory(before,after)and hb==ha,'Fresh observation changed')
        ctx.verify_sketch();ctx.verify_owned();ctx.verify_files();ctx.close();runtime_check()
        r['after_cleanup_document']=ctx.identity();require(r['after_cleanup_document']==ctx.expected,'Document changed during cleanup')
        require(shared.event_health(r['messages'],active=False)==0,'Any event rejects recovery acceptance')
        for p in d['pins']:shared.file_pin(p['path'],p['sha256'])
        final_source=_file_hash(v['expected_document_path']);require(final_source==v['expected_source_sha256'],'Source changed at final boundary')
        r.update(status='definition_only',phase='finished',source_after_sha256=final_source,
                 reason='CONSUMED_CREATION_READ_RECOVERED_EXACT_ATTRIBUTE_SUFFIX_ASSOCIATION_UNQUALIFIED',**{k:True for k in FLAGS})
    except Exception as error:
        r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),**{k:False for k in FLAGS})
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:r.update(status='error',cleanup_error=_error(error),**{k:False for k in FLAGS})
        r['phase']='finished';persist()
    return r

def revoke(r,error):
    r.update(status='error',runtime_error=_error(error),**{k:False for k in FLAGS});_write_receipt(Path(r['receipt_path']),r);return r

def verify_recovery_receipt(path,sha):
    """Validate durable read evidence. Caller must verify current source/immutable pins.

This intentionally permits a later explicitly proved Save transition; it never claims
that the old mutable target bytes still exist.
"""
    r,rp=read_pin(path,sha);require(r.get('scope')==SCOPE and r.get('status')=='definition_only'and r.get('phase')=='finished'
        and all(r.get(k)is True for k in FLAGS),'Successful complete read-only recovery required')
    require(not any(k in r for k in ('issue','cleanup_error','runtime_error'))and shared.event_health(r['messages'],active=False)==0,'Clean recovered read required')
    for key in ('mutation_attempted','Create_attempted','Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','Import_attempted','explicit_rebuild_attempted','automatic_replay','model_saved','feature_association_verified','attribute_payload_verified','production_qualified','island_geometry_verified','physical_depth_verified','machining_eligible'):
        require(r.get(key)is False,'Unexpected recovery claim/action '+key)
    v=r['request'];shape(v);raw,cp=read_pin(v['creator_receipt_path'],v['creator_receipt_sha256']);d=_authority_files(raw,cp,v['expected_attribute_suffix'],verify_files=False);bind_request(d,v)
    require(r['creator_receipt_pin']==cp and r['consumed_creation_marker_pin']==d['marker_pin']and r['original_creator_status']=='uncertain'and r['original_creator_flags']=={k:False for k in FLAGS},'Original uncertain authority must remain unchanged')
    require(r['document_before']==r['after_cleanup_document']==post_create_document(raw),'Exact recovered dirty document boundary required')
    require(r['exact_observed_attribute_suffix']==d['attribute_suffix']and r['source_before_sha256']==r['source_after_sha256']==v['expected_source_sha256']==raw['request']['expected_source_sha256'],'Exact recovered source/suffix required')
    for k in ('before','after'):verify_observation(d,r[k],r['feature_header_'+k])
    require(creator.same_inventory(r['before'],r['after'])and r['feature_header_before']==r['feature_header_after'],'Recovered observations differ')
    require(type(r.get('evidence_pins'))is list and 1<=len(r['evidence_pins'])<=40,'Bounded recovery evidence pins required')
    for pin in d['pins']+[dict(path=__file__,sha256=_file_hash(__file__))]:
        require(any(creator.same_path(pin['path'],p['path'])and pin['sha256']==p['sha256'] for p in r['evidence_pins']),'Missing recovery evidence pin')
    require(r.get('definition_proof')==verify_observation(d,r['after'],r['feature_header_after']),'Exact recovered definition proof required')
    d.update(receipt=r,receipt_pin=rp,pins=deepcopy(r['evidence_pins']));return d


def post_create_document(raw):
    return raw['post_create_document_observation']['after'] if creator.saved_caps(raw['request']) else raw['document_before']
