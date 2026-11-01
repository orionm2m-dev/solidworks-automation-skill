"""Read missing finish restrictions on a saved CAM route without edits or generation."""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_saved_wall_configuration as saved
from scripts import sw_cam_finish_diagnostics as details
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_rough_firstcut import require
common,group=saved.common,saved.group
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','checkpoint_receipt_path','checkpoint_receipt_sha256','receipt_path','module_sha256'}
TARGETS=(144,248)
BIND_MEMBERS={'GetDocType','MachType','GetCWObjectFromID','GetCWObjectID','Suppressed','GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','IGetAllFeatures','IGetTool','Count','Item','OpernType'}
BIND_INTERFACES={'ICWOperation','ICWMillOperation','ICWFeature','ICWDoc3','ICWTool','ICWDispatchCollection','ICWToolpath'}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_finish_diagnostics','Exact read-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact diagnostic fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Owned PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Strict digest required')
    require(p['module_sha256']==_file_hash(__file__),'Diagnostic module changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact registered CAM CLSID required')
    return p


class ReadBatch(ScopedCamReadBatch):
    def __init__(self,*args,generated_pin,progress,**kwargs):
        self.generated_pin=generated_pin;self.progress=progress
        super().__init__(*args,**kwargs)
    def read(self,obj,name,*args):
        try:
            require(name in BIND_MEMBERS|set(details.ALLOWED_MEMBERS),'Getter outside finish diagnostic allowlist')
            for arg in args:require(type(arg) in (str,int,float,bool) or id(arg) in self._known_objects,'Argument outside retained graph')
            self.progress(name,False)
            value=self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
            self.progress(name,True,value)
            return value
        except BaseException:self._invalid=True;raise
    def typed(self,obj,name):
        try:
            require(name in BIND_INTERFACES|set(details.IIDS),'Interface outside diagnostic allowlist')
            from scripts.sw_cam_comtypes import _load_type_library,_INTERFACES
            from scripts.sw_cam_face_interfaces import _verify_generated_class
            cls=getattr(_load_type_library(self.typelib_path),name)
            cls=_verify_generated_class(cls,details.IIDS.get(name) or _INTERFACES[name],self.generated_pin)
            self.progress('QueryInterface.'+name,False)
            value=self._observe_read(obj,'qi',lambda:obj.QueryInterface(cls))
            self.progress('QueryInterface.'+name,True)
            return value
        except BaseException:self._invalid=True;raise


def binding(doc,reference,*,read,typed):
    rows={};handles={}
    for oid in TARGETS:
        expected=next(x for x in reference['operations'] if x['native_id']==oid)
        found=read(doc,'GetCWObjectFromID',3,oid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact operation lookup required')
        op=typed(found[0],'ICWOperation');mill=typed(found[0],'ICWMillOperation')
        features=_items(read(op,'IGetAllFeatures'),typed,read,4)
        feature_ids=[_object_id(doc,x,read) for x in features]
        streams=_items(read(op,'IGetEnumToolpaths'),typed,read,2)
        counts=[read(typed(x,'ICWToolpath'),'RecordCount') for x in streams]
        tool=read(op,'IGetTool')
        row=dict(native_id=_object_id(doc,op,read),suppressed=read(op,'Suppressed'),generated=read(op,'GetIsToolpathGenerated'),feature_ids=feature_ids,tool_id=_object_id(doc,tool,read),record_counts=counts,mill_type=read(mill,'OpernType'))
        wanted=dict(native_id=oid,suppressed=expected['suppressed'],generated=expected['toolpath_generated'],feature_ids=expected['linked_feature_ids'],tool_id=expected['assigned_tool']['native_id'],record_counts=expected['toolpath_record_counts'],mill_type=expected['mill_operation_type'])
        require(group.exact(row,wanted) and len(features)==1,'Actual selected operation differs from saved reference')
        rows[str(oid)]=row;handles[oid]=(op,features[0])
    return rows,handles


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request)
    loaded=saved.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    loaded['pins']=common._merge(loaded['pins'],[common._pin(__file__),common._pin(details.__file__)])
    require(len(loaded['pins'])<=64,'Bounded runtime closure required')
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb')
    # Generated interface source was qualified previously and must remain byte-identical.
    common._check([loaded['generated_pin']]);audit=details.audit(tlb,loaded['generated_pin'])
    receipt=common._local_receipt(p['receipt_path']);require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh local receipt required')
    if validate_only:return dict(status='validated_offline',native_called=False,interface_audit=audit)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope='SAVED_FINISH_DIAGNOSTIC_READ_V1',status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],checkpoint_pin=loaded['parent_pin'],runtime_pins=loaded['pins'],read_only=True,mutation_attempted=False,GTP_attempted=False,save_attempted=False,readback_verified=False,interface_audit=audit)
        persist=lambda:_write_receipt(receipt,report)
        _write_receipt(receipt,report,create=True)
        backend=group.NativeBackend(loaded,p,sw,reg['clsid'],tlb,report,persist)
        try:
            backend.start()
            with backend.ctx.guard() as g:
                active=g.read(backend.ctx.app,'IGetActiveDoc');doc=g.typed(active,'ICWDoc3');part=g.typed(active,'ICWPartDoc');machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
                require(g.read(doc,'GetDocType')==1 and g.read(machine,'MachType')==1,'Exact MILL part required')
            def retained():
                backend.events();require(_member(doc,'GetDocType')==1 and _member(machine,'MachType')==1,'Retained document changed');backend.events()
            def progress(name,returned,value=None):
                report.update(current_read=name,native_dispatch_pending=not returned)
                if returned and (value is None or type(value) in (bool,int,float,str) or type(value) in (list,tuple) and all(v is None or type(v) in (bool,int,float,str) for v in value)):
                    report.setdefault('scalar_observations',[]).append(dict(phase=report['phase'],member=name,value=value))
                persist()
            batch=ReadBatch(sw,tlb,generated_pin=loaded['generated_pin'],progress=progress,process_id=p['process_id'],expected_document=backend.ctx.identity(),source_sha256=p['expected_source_sha256'],evidence_pins=loaded['pins'],verify_evidence=backend.ctx.files,verify_owned_process=backend.ctx.owned,check_events=backend.events,retained_objects=(doc,machine),verify_retained_binding=retained,max_native_calls=750)
            try:
                with batch:
                    report['phase']='binding_before';report['before'],handles=binding(doc,loaded['state'],read=batch.read,typed=batch.typed);persist();report['operations']={}
                    for oid in TARGETS:
                        report['phase']='read_'+str(oid);op,feature=handles[oid];fid=report['before'][str(oid)]['feature_ids'][0]
                        report['operations'][str(oid)]=details.read_finish_diagnostics(op,feature,doc,read=batch.read,typed=batch.typed);persist()
                    report['phase']='binding_after';report['after'],_=binding(doc,loaded['state'],read=batch.read,typed=batch.typed)
                    require(group.exact(report['before'],report['after']),'Selected route binding changed')
                batch.require_complete()
            finally:report['batch']=batch.summary();persist()
            backend.finish();report.update(status='observed',phase='finished',readback_verified=True)
        except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,native_dispatch_pending=False)
        finally:
            try:backend.close()
            except Exception as exc:report.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
            persist()
        return report


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False));return 0 if r.get('readback_verified') or r.get('status')=='validated_offline' else 1

if __name__=='__main__':raise SystemExit(main())
