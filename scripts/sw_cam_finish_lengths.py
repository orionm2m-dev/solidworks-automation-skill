"""Read three native length statistics from one saved generated Finish operation."""
from copy import deepcopy
from pathlib import Path
import json,math,re
from scripts import sw_cam_fresh_finish_recipe as saved
from scripts import sw_cam_fresh_finish_protected_read as protected
from scripts import sw_cam_pocket_finish_apply as finish
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_rough_firstcut import require
common,group=saved.common,saved.group
SCOPE='SAVED_FINISH_LENGTH_READ_V1'
PARAMS=protected.PARAMS
FIELDS=(('feed_length_native','ToolpathFeedLength',7),('rapid_length_native','ToolpathRapidLength',9),('total_length_native','ToolpathTotalLength',11))
MEMBERS={'GetDocType','MachType','IGetEnumOpSetups','IGetEnumOperations','GetCWObjectFromID','GetCWObjectID','Suppressed','OpernType','IGetAllFeatures','IGetTool','GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','Count','Item'}|{x[1] for x in FIELDS}
INTERFACES={'ICWOperation','ICWMillOperation','ICWBaseOpSetup','ICWDispatchCollection','ICWToolpath'}


def read_lengths(operation,*,read,record):
    result={}
    for key,member,_ in FIELDS:
        value=read(operation,member);record(key,value)
        require(type(value) in (int,float) and math.isfinite(value) and value>=0,'Finite nonnegative native length required')
        result[key]=value
    return result


def projected_inventory(state):
    keys=('setup_index','setup_native_id','operation_index','native_id','mill_operation_type','suppressed','toolpath_generated','linked_feature_ids','toolpath_record_counts')
    return dict(operation_setups=deepcopy(state['operation_setups']),operations=[dict({k:deepcopy(r[k]) for k in keys},tool_native_id=r['assigned_tool']['native_id'] if r['assigned_tool'] is not None else None) for r in state['operations']])


def inventory(doc,machine,*,read,typed):
    setups=[];operations=[]
    for si,raw in enumerate(_items(read(machine,'IGetEnumOpSetups'),typed,read,8)):
        setup=typed(raw,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        ops=_items(read(setup,'IGetEnumOperations'),typed,read,32);setups.append(dict(index=si,native_id=sid,operation_count=len(ops)))
        for oi,rawop in enumerate(ops):
            op=typed(rawop,'ICWOperation');mill=typed(rawop,'ICWMillOperation');tool=read(op,'IGetTool')
            features=_items(read(op,'IGetAllFeatures'),typed,read,4)
            paths=_items(read(op,'IGetEnumToolpaths'),typed,read,4)
            operations.append(dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=_object_id(doc,op,read),
                mill_operation_type=read(mill,'OpernType'),suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'),
                linked_feature_ids=[_object_id(doc,x,read) for x in features],
                toolpath_record_counts=[read(typed(x,'ICWToolpath'),'RecordCount') for x in paths],
                tool_native_id=_object_id(doc,tool,read) if tool is not None and bool(tool) else None))
    return dict(operation_setups=setups,operations=operations)


def authority(loaded,p):
    a=loaded['fresh_finish_result']
    require(a['native_id']==p['operation_native_id'] and a['feature_native_id']==p['feature_native_id'] and a['generated'] is True
        and type(a['record_counts']) is list and len(a['record_counts'])==1 and type(a['record_counts'][0]) is int and a['record_counts'][0]>0,'Exact saved generated Finish authority required')
    rows=[r for r in loaded['state']['operations'] if r['native_id']==a['native_id']]
    require(len(rows)==1 and rows[0]['mill_operation_type']==1 and rows[0]['linked_feature_ids']==[a['feature_native_id']]
        and rows[0]['suppressed'] is False and rows[0]['toolpath_generated'] is True and rows[0]['toolpath_record_counts']==a['record_counts'],'Saved target identity/counts differ')
    return a


def audit(typelib,generated_pin):
    from ctypes import POINTER,c_double
    from scripts.sw_cam_pocket_rough_apply import require_abi
    cls=finish.interface_class('ICWOperation',typelib,generated_pin);rows=[]
    for _,name,ident in FIELDS:
        found=[m for m in cls._methods_ if m.name=='_get_'+name]
        require(len(found)==1,'Exact readonly property required');require_abi(found[0],ident,(POINTER(c_double),),(10,))
        rows.append(dict(interface='ICWOperation',member=name,dispid=ident,property='get',return_type='DOUBLE'))
    return dict(abi_verified=True,native_calls=0,properties=rows,units_semantics_verified=False)


class ReadBatch(protected.ReadBatch):
    def read(self,obj,name,*args):
        try:
            require(name in MEMBERS,'Getter outside saved-length read scope')
            for value in args:require(type(value) in (str,int,float,bool) or id(value) in self._known_objects,'Argument outside retained graph')
            self.progress(name,False);value=self._observe_read(obj,'getter',lambda:_member(obj,name,*args));self.progress(name,True);return value
        except BaseException:self._invalid=True;raise
    def typed(self,obj,name):
        try:
            require(name in INTERFACES,'Interface outside saved-length read scope')
            cls=finish.interface_class(name,self.typelib_path,self.generated_pin)
            return self._observe_read(obj,'qi',lambda:obj.QueryInterface(cls))
        except BaseException:self._invalid=True;raise


def observe(batch,doc,machine,loaded,p,report,persist):
    report['phase']='inventory_before';report['inventory_before']=inventory(doc,machine,read=batch.read,typed=batch.typed);persist()
    require(group.exact(report['inventory_before'],projected_inventory(loaded['state'])),'Saved operation inventory differs')
    report['before'],op,_=protected.binding(doc,loaded['state'],p['operation_native_id'],p['feature_native_id'],read=batch.read,typed=batch.typed);persist()
    def record(key,value):
        row=dict(key=key,returned_type=type(value).__name__)
        if value is None or type(value) in (bool,int,float,str):row['value']=value
        else:row['unsupported_shape']=True
        report['scalar_observations'].append(row);persist()
    report['phase']='read_lengths';report['lengths']=read_lengths(op,read=batch.read,record=record);persist()
    report['phase']='inventory_after';report['after'],_,_=protected.binding(doc,loaded['state'],p['operation_native_id'],p['feature_native_id'],read=batch.read,typed=batch.typed)
    report['inventory_after']=inventory(doc,machine,read=batch.read,typed=batch.typed);persist()
    require(group.exact(report['before'],report['after']) and group.exact(report['inventory_before'],report['inventory_after']),'Readback inventory/binding changed')


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_saved_finish_lengths','Exact read-only length action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact parameters required')
    for k in ('process_id','operation_native_id','feature_native_id'):require(type(p[k]) is int and 0<p[k]<2**31,'Strict identity required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM registration required');return p


def scope_pins(loaded,runtime):
    # Completed writer and its field batch are validated offline, never called by
    # the native reader. Keep their proofs without consuming live guard slots.
    retired=[x for x in loaded['pins'] if Path(x['path']).name in ('sw_cam_fresh_finish_recipe.py','sw_cam_fresh_finish_field_batch.py')]
    require({Path(x['path']).name for x in retired}=={'sw_cam_fresh_finish_recipe.py','sw_cam_fresh_finish_field_batch.py'},'Expected completed-writer proof pins required')
    loaded['pins']=common._merge([x for x in loaded['pins'] if x not in retired],runtime)
    loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],retired)
    require(1<=len(loaded['pins'])<=64,'Bounded read-only closure required')
    return retired


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request)
    loaded=saved.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')});a=authority(loaded,p)
    retired=scope_pins(loaded,[common._pin(__file__),common._pin(protected.__file__),common._pin(finish.__file__)])
    for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb');audited=audit(tlb,loaded['generated_pin'])
    receipt=common._local_receipt(p['receipt_path']);require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh local receipt required')
    pins={common._key(x['path']) for name in ('pins','offline_export_proof_pins','bootstrap_export_pins') for x in loaded[name]}|{common._key(p['expected_document_path'])}
    require(common._key(receipt) not in pins,'Receipt must not overwrite source/evidence')
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),interface_audit=audited,authority=a,retired_offline_proof_pins=retired)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],operation_native_id=p['operation_native_id'],feature_native_id=p['feature_native_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],checkpoint_pin=loaded['parent_pin'],runtime_pins=loaded['pins'],retired_offline_proof_pins=retired,read_only=True,mutation_attempted=False,GTP_attempted=False,save_attempted=False,readback_verified=False,interface_audit=audited,scalar_observations=[],units_semantics_verified=False,full_circle_semantics_verified=False,geometry_acceptance_complete=False,production_qualified=False)
        persist=lambda:_write_receipt(receipt,report);_write_receipt(receipt,report,create=True)
        backend=group.NativeBackend(loaded,p,sw,reg['clsid'],tlb,report,persist)
        try:
            backend.start()
            with backend.ctx.guard() as g:
                active=g.read(backend.ctx.app,'IGetActiveDoc');doc=g.typed(active,'ICWDoc3');part=g.typed(active,'ICWPartDoc');machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
                require(g.read(doc,'GetDocType')==1 and g.read(machine,'MachType')==1,'Exact MILL document required')
            def retained():
                backend.events();require(_member(doc,'GetDocType')==1 and _member(machine,'MachType')==1,'Retained document changed');backend.events()
            def progress(name,returned):report.update(current_read=name,native_dispatch_pending=not returned)
            batch=ReadBatch(sw,tlb,generated_pin=loaded['generated_pin'],progress=progress,process_id=p['process_id'],expected_document=backend.ctx.identity(),source_sha256=p['expected_source_sha256'],evidence_pins=loaded['pins'],verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,check_events=backend.events,retained_objects=(doc,machine),verify_retained_binding=retained,max_native_calls=600)
            try:
                with batch:observe(batch,doc,machine,loaded,p,report,persist)
                batch.require_complete()
            finally:report['batch']=batch.summary();persist()
            backend.finish()
            for name in ('offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
            report.update(status='observed',phase='finished',readback_verified=True)
        except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,native_dispatch_pending=False)
        finally:protected.close_and_observe(backend,report,persist)
        return report


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','lengths','issue','native_called')}));return 0 if r.get('readback_verified') or r.get('status')=='validated_offline' else 1
if __name__=='__main__':raise SystemExit(main())
