"""Observe saved Finish depth, lead and compensation choices without changing them."""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_fresh_finish_insert as saved
from scripts import sw_cam_finish_diagnostics as details
from scripts import sw_cam_pocket_finish_apply as finish
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_rough_firstcut import require
common,group=saved.common,saved.group
SCOPE='SAVED_FRESH_FINISH_PROTECTED_READ_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','checkpoint_receipt_path','checkpoint_receipt_sha256','operation_native_id','feature_native_id','receipt_path','module_sha256'}
SCALARS=(('gouge_check','ICWFinishMillOp3','GougeCheck','bool'),('single_depth','ICWFinishMillOp3','GetIsSingleCutDepth','bool'),('depth_process','ICWFinishMillOp','DepthProcessOpt','long'),('rest_method','ICWFinishMillOp3','ContourMillRestMachMethod','long'),('add_tool_radius','ICWFinishMillOp3','GetToolRadiusLeadInLeadOut','bool'))
INTERFACES={'ICWOperation','ICWMillOperation','ICWFinishMillOp','ICWFinishMillOp3','ICWNCParam','ICWLeadInOut','ICWDispatchCollection','ICWToolpath'}
MEMBERS={x[2] for x in SCALARS}|{'GetDocType','MachType','GetCWObjectFromID','GetCWObjectID','Suppressed','OpernType','IGetAllFeatures','IGetTool','GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','Count','Item','IGetLeadin','IGetLeadout','LeadType','IGetNCParam','GetTlpComp','GetCNCComp'}


def read_protected(operation,feature,*,read,typed,record):
    """Persist each returned scalar before shape checks; do not assume enum values."""
    owners={name:typed(operation,name) for name in ('ICWFinishMillOp','ICWFinishMillOp3','ICWMillOperation')}
    result={}
    def scalar(key,owner,member,kind):
        value=read(owner,member)
        record(key,value)
        return details._scalar(value,kind)
    for key,name,member,kind in SCALARS:result[key]=scalar(key,owners[name],member,kind)
    result['lead_types']=[]
    for side,member in (('in','IGetLeadin'),('out','IGetLeadout')):
        owner=typed(read(owners['ICWFinishMillOp'],member,feature),'ICWLeadInOut')
        result['lead_types'].append(scalar('lead_type_'+side,owner,'LeadType','long'))
    owner=typed(read(owners['ICWMillOperation'],'IGetNCParam'),'ICWNCParam')
    result['compensation']=[scalar('compensation_'+name,owner,name,'long') for name in ('GetTlpComp','GetCNCComp')]
    return result


def prior_expectation_comparison(value):
    expected={'gouge_check':True,'single_depth':False,'rest_method':0,'lead_types':[1,1]}
    return {'expected_from_previous_guard':expected,'differences':{k:{'expected':v,'observed':value[k]} for k,v in expected.items() if type(value[k]) is not type(v) or value[k]!=v},'enum_semantics_decoded':False,'manufacturing_acceptance':False}


def audit(typelib,generated_pin):
    from ctypes import POINTER,c_int
    from comtypes.automation import IDispatch
    from scripts.sw_cam_pocket_rough_apply import require_abi
    result=details.audit(typelib,generated_pin)
    rows=[]
    for name,member,ident,args,flags in [('ICWLeadInOut','_get_LeadType',1,(POINTER(c_int),),(10,)),('ICWFinishMillOp','IGetLeadin',28,(POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10)),('ICWFinishMillOp','IGetLeadout',29,(POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10))]:
        cls=finish.interface_class(name,typelib,generated_pin);found=[x for x in cls._methods_ if x.name==member]
        require(len(found)==1,'Exact getter declaration required');require_abi(found[0],ident,args,flags);rows.append({'interface':name,'member':member,'dispid':ident})
    result['additional_getters']=rows;return result


class ReadBatch(ScopedCamReadBatch):
    def __init__(self,*args,generated_pin,progress,**kwargs):
        self.generated_pin=generated_pin;self.progress=progress;super().__init__(*args,**kwargs)
    def read(self,obj,name,*args):
        try:
            require(name in MEMBERS,'Getter outside protected read scope')
            for value in args:require(type(value) in (str,int,float,bool) or id(value) in self._known_objects,'Argument outside retained graph')
            self.progress(name,False)
            value=self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
            self.progress(name,True);return value
        except BaseException:self._invalid=True;raise
    def typed(self,obj,name):
        try:
            require(name in INTERFACES,'Interface outside protected read scope')
            cls=finish.interface_class(name,self.typelib_path,self.generated_pin)
            return self._observe_read(obj,'qi',lambda:obj.QueryInterface(cls))
        except BaseException:self._invalid=True;raise


def binding(doc,reference,oid,fid,*,read,typed):
    expected=next(x for x in reference['operations'] if x['native_id']==oid)
    found=read(doc,'GetCWObjectFromID',3,oid)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact saved target required')
    op=typed(found[0],'ICWOperation');mill=typed(found[0],'ICWMillOperation')
    features=_items(read(op,'IGetAllFeatures'),typed,read,2)
    feature_ids=[_object_id(doc,x,read) for x in features]
    streams=_items(read(op,'IGetEnumToolpaths'),typed,read,1)
    row=dict(native_id=_object_id(doc,op,read),suppressed=read(op,'Suppressed'),generated=read(op,'GetIsToolpathGenerated'),feature_ids=feature_ids,tool_id=_object_id(doc,read(op,'IGetTool'),read),record_counts=[read(typed(x,'ICWToolpath'),'RecordCount') for x in streams],mill_type=read(mill,'OpernType'))
    wanted=dict(native_id=oid,suppressed=expected['suppressed'],generated=expected['toolpath_generated'],feature_ids=[fid],tool_id=expected['assigned_tool']['native_id'],record_counts=expected['toolpath_record_counts'],mill_type=expected['mill_operation_type'])
    require(group.exact(row,wanted) and len(features)==1,'Selected operation differs from saved reference')
    return row,op,features[0]


def close_and_observe(backend,report,persist):
    """Always disconnect and record the actual session summary, including failures."""
    try:backend.close()
    except Exception as exc:report.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
    finally:
        session=getattr(backend,'session',None)
        report['cleanup']={'attempted':True,'session_active':getattr(backend,'session_active',None),'messages':session.summary() if session is not None else None}
        if session is not None:
            report['messages']=deepcopy(report['cleanup']['messages'])
            try:backend.events(False)
            except Exception as exc:report.update(status='error',cleanup_observation_issue=_error(exc),readback_verified=False)
        persist()


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_fresh_finish_protected','Exact read-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact diagnostic parameters required')
    for k in ('process_id','operation_native_id','feature_native_id'):require(type(p[k]) is int and 0<p[k]<2**31,'Strict identity required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM registration required');return p


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request)
    loaded=saved.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    authority=loaded['fresh_finish_definition'];require(authority['native_id']==p['operation_native_id'] and authority['feature_native_id']==p['feature_native_id'],'Saved fresh definition binding differs')
    runtime=[common._pin(__file__),common._pin(details.__file__),common._pin(finish.__file__)]
    retired=[x for x in loaded['pins'] if Path(x['path']).name=='sw_cam_finish_runtime_compatibility.py' or x==loaded.get('runtime_compatibility_pin')]
    loaded['pins']=common._merge([x for x in loaded['pins'] if x not in retired],runtime)
    loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],retired)
    require(len(loaded['pins'])<=64,'Bounded runtime closure required')
    for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb');audited=audit(tlb,loaded['generated_pin'])
    receipt=common._local_receipt(p['receipt_path']);require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh local receipt required')
    protected={common._key(x['path']) for name in ('pins','offline_export_proof_pins','bootstrap_export_pins') for x in loaded[name]}|{common._key(p['expected_document_path'])}
    require(common._key(receipt) not in protected,'Receipt must not overwrite source/evidence')
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),interface_audit=audited)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],operation_native_id=p['operation_native_id'],feature_native_id=p['feature_native_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],checkpoint_pin=loaded['parent_pin'],runtime_pins=loaded['pins'],read_only=True,mutation_attempted=False,GTP_attempted=False,save_attempted=False,readback_verified=False,interface_audit=audited,scalar_observations=[])
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
            def record(key,value):
                row={'key':key,'returned_type':type(value).__name__}
                if value is None or type(value) in (bool,int,float,str):row['value']=value
                else:row['unserializable_type']=True
                report['scalar_observations'].append(row);persist()
            batch=ReadBatch(sw,tlb,generated_pin=loaded['generated_pin'],progress=progress,process_id=p['process_id'],expected_document=backend.ctx.identity(),source_sha256=p['expected_source_sha256'],evidence_pins=loaded['pins'],verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,check_events=backend.events,retained_objects=(doc,machine),verify_retained_binding=retained,max_native_calls=120)
            try:
                with batch:
                    report['phase']='binding_before';row,op,feature=binding(doc,loaded['state'],p['operation_native_id'],p['feature_native_id'],read=batch.read,typed=batch.typed);report['before']=row;persist()
                    report['phase']='read_protected';report['protected']=read_protected(op,feature,read=batch.read,typed=batch.typed,record=record);persist()
                    report['phase']='binding_after';report['after'],_,_=binding(doc,loaded['state'],p['operation_native_id'],p['feature_native_id'],read=batch.read,typed=batch.typed)
                    require(group.exact(report['before'],report['after']),'Selected binding changed')
                batch.require_complete()
            finally:report['batch']=batch.summary();persist()
            backend.finish();report['comparison']=prior_expectation_comparison(report['protected']);report.update(status='observed',phase='finished',readback_verified=True)
        except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,native_dispatch_pending=False)
        finally:close_and_observe(backend,report,persist)
        return report


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','protected','comparison','issue','native_called')}));return 0 if r.get('readback_verified') or r.get('status')=='validated_offline' else 1

if __name__=='__main__':raise SystemExit(main())
