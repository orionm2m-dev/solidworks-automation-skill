"""Read TURN toolcrib candidates without resolving broken operation tool links.

This is RAM diagnosis, including after a known CAM Save error. It grants no
persistence, tool assignment, generation, physical-tool or production authority.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_bore_definitions as prior
from scripts import sw_cam_operation_profile as profile
from scripts import sw_cam_read_batch_guard as batches
from scripts import sw_cam_mill_inventory as collection_support
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=prior.common
SCOPE='TURN_TOOLCRIB_RAM_DIAGNOSTIC_V1'
MAX_TOOLS=32
PARAMS={'process_id','expected_document_path','expected_source_sha256','parent_receipt_path','parent_receipt_sha256','save_error_path','save_error_sha256','receipt_path','module_sha256'}
GETTERS=frozenset({'IGetToolcrib','GetAllTools','Count','Item','GetCWObjectID','ToolType','GetToolInfoString','InsertType','IGetTurnToolHolder','GetHolderType','GetHolderId','Thickness','IncludedAngle','NoseRadius','InscribedCircle','BoringBarDiameter','ShankLength','LeadAngle','BackClearAngle','FrontClearAngle','ZInsertOffset','XInsertOffset','Protrusion','HolderShape'})
INTERFACES=frozenset({'ICWMachine','ICWToolcrib4','ICWDispatchCollection','ICWTool','ICWTurnTool','ICWTurnToolHolder'})
BORING_FIELDS=('BoringBarDiameter','ShankLength','LeadAngle','BackClearAngle','FrontClearAngle','ZInsertOffset','XInsertOffset','Protrusion','HolderShape')


def read_tools(machine,doc,*,read,typed,items,rows,publish):
    crib=typed(read(machine,'IGetToolcrib'),'ICWToolcrib4')
    handles=items(read(crib,'GetAllTools'),MAX_TOOLS)
    require(len(handles)<=MAX_TOOLS,'Toolcrib exceeds bounded diagnostic scope')
    seen=set()
    for raw in handles:
        row={'complete':False};rows.append(row)
        tool=typed(raw,'ICWTool');ident=_object_id(doc,tool,read)
        require(ident not in seen,'Duplicate native tool ID');seen.add(ident)
        row.update(native_id=ident,tool_type_raw=profile._integer(read(tool,'ToolType')),info_raw=profile._text(read(tool,'GetToolInfoString')))
        if row['tool_type_raw']!=15:
            row.update(complete=True,candidate=False,reason='not_turn_tool');publish();continue
        turn=typed(raw,'ICWTurnTool');row['turn_tool_type_raw']=profile._integer(read(turn,'ToolType'))
        if row['turn_tool_type_raw']!=1:
            row.update(complete=True,candidate=False,reason='not_insert_holder_no_subtype_probe');publish();continue
        row['insert_type_raw']=profile._integer(read(turn,'InsertType'))
        raw_holder=read(turn,'IGetTurnToolHolder')
        row['holder_present']=raw_holder is not None and bool(raw_holder)
        if not row['holder_present']:
            row.update(complete=True,candidate=False,reason='holder_absent');publish();continue
        holder=typed(raw_holder,'ICWTurnToolHolder')
        row['holder_type_raw']=profile._integer(read(holder,'GetHolderType'))
        row['holder_id_raw']=profile._integer(read(holder,'GetHolderId'))
        row['candidate']=row['insert_type_raw']==1 and row['holder_type_raw']==2
        if row['candidate']:
            row['insert_dimensions_native']={name:profile._number(read(turn,name)) for name in ('Thickness','IncludedAngle','NoseRadius','InscribedCircle')}
            row['holder_dimensions_native']={name:(profile._integer(read(holder,name)) if name=='HolderShape' else profile._number(read(holder,name))) for name in BORING_FIELDS}
            row['reason']='diamond_boring_bar_requires_physical_and_geometric_qualification'
        else:row['reason']='not_diamond_boring_bar'
        row['complete']=True;publish()
    return crib,sorted(seen)


class ToolReadBatch(batches.ScopedCamReadBatch):
    def read(self,obj,name,*args):
        require(name in GETTERS,'Getter outside read-only toolcrib scope')
        for value in args:require(type(value) is int or id(value) in self._known_objects,'Argument outside retained graph')
        return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
    def typed(self,obj,name):
        require(name in INTERFACES,'Interface outside toolcrib scope')
        return self._observe_read(obj,'qi',lambda:_typed(obj,name,self.typelib_path))


def audit(typelib,generated_pin):
    from ctypes import POINTER,c_int,c_double
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _load_type_library,_INTERFACES
    from scripts.sw_cam_face_interfaces import _verify_generated_class
    from scripts.sw_cam_pocket_rough_apply import require_abi
    lib=_load_type_library(typelib);rows=[]
    for interface,member,ident,args,flags in (
        ('ICWToolcrib4','GetAllTools',13,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWTurnTool','IGetTurnToolHolder',1,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWTurnToolHolder','GetHolderType',3,(POINTER(c_int),),(10,)),
        ('ICWTurnToolHolder','GetHolderId',4,(POINTER(c_int),),(10,))):
        cls=_verify_generated_class(getattr(lib,interface),_INTERFACES[interface],generated_pin)
        found=[m for m in cls._methods_ if m.name==member];require(len(found)==1,'Unique typed getter required')
        require_abi(found[0],ident,args,flags);rows.append(dict(interface=interface,member=member,dispid=ident))
    specs=[('ICWTurnTool',name,ident,c_double) for name,ident in [('IncludedAngle',7),('InscribedCircle',8),('NoseRadius',9),('Thickness',10)]]
    specs += [('ICWTurnToolHolder',name,ident,c_double) for name,ident in [('ShankLength',13),('LeadAngle',14),('BackClearAngle',15),('FrontClearAngle',16),('ZInsertOffset',17),('XInsertOffset',18),('Protrusion',19),('BoringBarDiameter',29)]]
    specs += [('ICWTurnToolHolder','HolderShape',11,c_int)]
    for interface,member,ident,scalar in specs:
        cls=_verify_generated_class(getattr(lib,interface),_INTERFACES[interface],generated_pin)
        found=[m for m in cls._methods_ if m.name=='_get_'+member];require(len(found)==1,'Unique typed property getter required')
        require_abi(found[0],ident,(POINTER(scalar),),(10,));rows.append(dict(interface=interface,member=member,dispid=ident))
    return dict(abi_verified=True,native_called=False,methods=rows)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_turn_toolcrib_candidates','Exact read-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader bytes changed');return p


def prepare(p):
    parent,ppin=read_pin(p['parent_receipt_path'],p['parent_receipt_sha256'])
    require(parent['scope']==prior.SCOPE and parent['phase']=='finished','Terminal definition observation required')
    require(parent['process_id']==p['process_id'] and common._key(parent['source_path'])==common._key(p['expected_document_path']),'Same owned source required')
    # The raw successful Save receipt is only an observed RAM reference here.
    # Its known Save error explicitly prevents using the completed-save loader.
    state=parent['final_state'];require(state['saved_file_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path']),'Exact current disk bytes required for diagnostic binding')
    require(parent['new_operations'] and all(parent['actions']['InsertOperation_'+str(x['turn_operation_type'])]['readback_verified'] is True for x in parent['new_operations']),'Verified inserted RAM identities required')
    err,epin=read_pin(p['save_error_path'],p['save_error_sha256'])
    require(type(err) is dict and err.get('pid')==p['process_id'] and err.get('COM_called') is False and err.get('window_commands_sent') is False and type(err.get('dialogs')) is list and any('SOLIDWORKS CAM' in str(x.get('title','')) for x in err['dialogs']),'Same-process captured read-only CAM dialog evidence required')
    common._check(parent['runtime_and_evidence_pins'])
    cat=read_pin(parent['catalogue_pin']['path'],parent['catalogue_pin']['sha256'])[0]
    q=cat['request'];generated=common._pin(q['generated_path']);require(generated['sha256']==q['generated_sha256'],'Generated binding changed')
    reg=prior.catalogue.jobs._validate_registration(q);a=audit(q['typelib_path'],generated)
    pins=common._merge(parent['runtime_and_evidence_pins'],[ppin,epin]+[common._pin(x.__file__) for x in (prior,profile,batches,collection_support)]+[common._pin(__file__)])
    require(len(pins)<=64,'Bounded evidence closure required')
    out=common._local_receipt(p['receipt_path']);require(out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh existing-parent receipt required')
    require(common._key(out) not in {common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])},'Receipt aliases source/evidence')
    return dict(parent=parent,reference=state,catalogue=cat,pins=pins,typelib_path=q['typelib_path'],generated_pin=generated,registration=reg,abi=a,output=out)


class NativeBackend(prior.NativeBackend):
    def read(self,obj,name,*args):
        value=super().read(obj,name,*args)
        if name=='IGetMachine':self.machine=value
        return value
    def tools(self):
        doc=self.native['doc'];machine=self.machine;expected=self.identity()
        def binding():require(_object_id(doc,self.native['feature'],lambda o,n,*a:_member(o,n,*a))==self.p['feature_native_id'],'Retained feature identity changed')
        with ToolReadBatch(self.sw,self.typelib,process_id=self.p['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=self.plan['pins'],verify_evidence=lambda:common._check(self.plan['pins']),verify_owned_process=self.owned,check_events=self.event_check,retained_objects=(doc,machine,self.native['feature']),max_native_calls=1500,verify_retained_binding=binding) as b:
            def items(raw,limit):return _items(raw,b.typed,b.read,limit)
            _,ids=read_tools(b.typed(machine,'ICWMachine'),doc,read=b.read,typed=b.typed,items=items,rows=self.report['tools'],publish=self.persist)
        self.report['read_batch']=b.summary();return ids


def run_backend(backend,plan,r,persist):
    try:
        backend.start();r['phase']='before';r['before']=backend.capture('before');persist()
        require(r['before']==plan['reference'],'Current RAM definition/reference differs')
        r['phase']='toolcrib';r['tool_ids']=backend.tools();persist()
        r['phase']='after';r['after']=backend.capture('after');persist()
        require(r['after']==r['before'],'Read changed observed source/operation metadata')
        backend.finish();r.update(status='observed',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='error',cleanup_error=_error(exc),readback_verified=False)
        persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),abi=plan['abi'],persistence_qualified=False)
    from scripts.sw_connect import connect_solidworks
    bp=dict(p,feature_native_id=plan['parent']['request']['feature_native_id'])
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,persistence_qualified=False,tool_assignment_authorized=False,physical_tool_qualified=False,production_qualified=False,readback_verified=False,tools=[],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],runtime_and_evidence_pins=plan['pins'],limitations=['RAM diagnosis after known CAM Save error; HRESULT0 is not persistence proof','No operation IGetTool lookup; no assign/create/insert/generation/save','Candidate means diamond insert and boring-bar holder only; no access/stock/depth qualification','Existing path protection is counts/flags and route metadata, not CL byte hashes'])
        _write_receipt(plan['output'],r,create=True)
        persist=lambda:_write_receipt(plan['output'],r)
        return run_backend(NativeBackend(sw,bp,plan,r,persist),plan,r,persist)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps(result,ensure_ascii=False,indent=2))




