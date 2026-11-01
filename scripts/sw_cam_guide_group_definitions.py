"""Bounded four-definition shallow-guide insertion; no SetTool, GTP or Save.

The native owner must supply a pinned current R122 authority, guarded context,
CAM session, full local catalogue comparison and exact per-operation readers.
The dispatcher connects only to the explicitly owned existing session. It never
selects another target, retries, saves, or infers TechDB default IDs.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_guide_group_reader as guide
from scripts import sw_cam_fresh_finish_rebind as rebind
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_grouped_face_recipe import exact
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_guide_group_reader import SCOPE as READ_SCOPE, ORDER
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam import _member

SCOPE='SHALLOW_GUIDE_DEFINITION_GROUP_V1'
ROWS=(('guide82_rough',82,0),('guide82_finish',82,1),('guide83_rough',83,0),('guide83_finish',83,1))


def compile_definition_plan(observed,choices):
    require(type(observed) is dict and observed.get('scope')==rebind.SCOPE and observed.get('session_rebind_verified') is True and observed.get('status')=='observed'
        and observed.get('phase')=='finished' and observed.get('readback_verified') is True
        and observed.get('group_baseline_read_complete') is True,'Completed current guide observation required')
    require(observed.get('read_only') is True and observed.get('mutation_attempted') is False
        and observed.get('save_attempted') is False and observed.get('GTP_attempted') is False,'Read-only observation required')
    require(not any(k in observed for k in ('issue','cleanup_issue','failed_phase','receipt_write_error')),'Uncertain observation rejected')
    require(exact(observed['before'],observed['after']) and exact(observed['configuration_before'],observed['configuration_after']),'Protected baseline/configuration changed')
    require(observed['configuration_before']['sw_configuration_name']==observed['request']['expected_configuration'],'Actual SW configuration required')
    baseline=observed['after'];require(tuple(v['native_id'] for v in baseline['operations'])==ORDER,'Exact saved nine-operation order required')
    require(type(choices) is dict and set(choices)=={r[0] for r in ROWS},'Four explicit catalogue choices required')
    out=[]
    for label,fid,kind in ROWS:
        choice=choices[label];require(type(choice) is dict and set(choice)=={'name','default_operation_id'},'Exact name/ID choice required')
        name,default=choice['name'],choice['default_operation_id']
        require(type(name) is str and 0<len(name)<=1000 and '\x00' not in name and type(default) is int and 0<default<2**31,'Strict actual default name/ID required')
        guides=[g for g in observed['guides'] if g['feature_native_id']==fid]
        require(len(guides)==1 and exact(guides[0]['header'],baseline['features'][str(fid)]),'Unique unchanged guide header required')
        catalogs=[c for c in guides[0]['defaults_catalogue'] if type(c['operation_type']) is int and c['operation_type']==kind]
        require(len(catalogs)==1,'Unique exact native operation catalogue required')
        matches=[v for v in catalogs[0]['entries'] if v['name']==name and type(v['default_operation_id']) is int and v['default_operation_id']==default]
        require(len(matches)==1,'Selected default absent or ambiguous; no inferred defaults')
        require(not any(fid in v['linked_feature_ids'] for v in baseline['operations']),'Guide already planned; no replay')
        out.append(dict(key=label,feature_native_id=fid,operation_type=kind,default_operation_name=name,
            default_operation_id=default,feature_owner_setup_native_id=69,operation_setup_native_id=93,
            anchor_native_id=320 if not out else None,anchor_result_key=out[-1]['key'] if out else None))
    return dict(schema_version=1,scope=SCOPE,rows=out,baseline=deepcopy(baseline),
        configuration=deepcopy(observed['configuration_after']),source_request=deepcopy(observed['request']),
        maximum_insert_calls=4,SetTool_allowed=False,GTP_allowed=False,Save_allowed=False,
        native_execution_ready=False,reason='A separately guarded writer must freshly verify this baseline before mutation.')


def verify_one_addition(before,after,row,new_id,anchor_id):
    require(type(new_id) is int and new_id>0 and type(anchor_id) is int and anchor_id>0,'Actual positive native IDs required')
    require(type(row['operation_type']) is int and row['operation_type'] in (0,1),'Rough0 or Finish1 required')
    old=before['operations'];now=after['operations']
    require(old and old[-1]['native_id']==anchor_id and new_id not in {v['native_id'] for v in old},'Append after exact current last operation only')
    require(len(now)==len(old)+1 and exact(now[:-1],old),'Exactly one appended operation; old metadata must remain identical')
    target=now[-1];anchor=old[-1]
    require(target['native_id']==new_id and target['setup_native_id']==anchor['setup_native_id']==row['operation_setup_native_id']
        and target['setup_index']==anchor['setup_index'] and target['operation_index']==anchor['operation_index']+1
        and type(target['mill_operation_type']) is int and target['mill_operation_type']==row['operation_type']
        and target['linked_feature_ids']==[row['feature_native_id']] and target['suppressed'] is False
        and target['toolpath_generated'] is False and target['toolpath_record_counts']==[],'Exact ungenerated requested definition required')
    require(target['assigned_tool'].get('native_read_complete') is True,'New definition tool reference must be actually readable')
    protected=deepcopy(after);protected['operations'].pop()
    setup=protected['operation_setups'][anchor['setup_index']]
    require(type(setup['operation_count']) is int and setup['operation_count']>0,'Strict target setup count required')
    setup['operation_count']-=1
    require(exact(protected,before),'Protected feature/setup fields changed')
    return deepcopy(target)


def insert_selected_once(ctx,doc,row,anchor_id,expected_header,pending):
    """Reuse the proven guarded InsertOperation pattern; never call without journal pending.

    Returns the real COM pointer. The caller must durably record its actual ID,
    read route/defaults/NC, verify_one_addition, and stop before the next row on
    every exception. A returned pointer does not prove NC readiness.
    """
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _is_comtypes_pointer
    require(callable(pending),'Durable pending callback required')
    require(type(row['operation_type']) is int and row['operation_type'] in (0,1),'Only explicit rough/finish definition insertion supported')
    with ctx.guard() as g:
        found=g.read(doc,'GetCWObjectFromID',1,row['feature_native_id'])
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact selected feature required')
        feature=g.typed(found[0],'ICWMillFeature')
        header,_=read_header(feature,doc,g.read,g.typed,row['feature_owner_setup_native_id'])
        require(exact(header,expected_header),'Selected feature header changed')
        found=g.read(doc,'GetCWObjectFromID',3,anchor_id)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact current anchor required')
        anchor=g.read(found[0],'QueryInterface',IDispatch)
        require(_object_id(doc,anchor,g.read)==anchor_id,'Anchor dispatch identity changed')
        default=g.read(feature,'GetTdbIdForDefaultOperation',row['operation_type'],row['default_operation_name'])
        require(type(default) is int and default==row['default_operation_id'],'Current native default changed')
        result=g.dispatch_once(lambda:_member(feature,'InsertOperation',row['operation_type'],default,anchor),persist_pending=pending)
    require(_is_comtypes_pointer(result) and bool(result),'Nonnull typed native operation pointer required')
    return result


common=guide.common
group=guide.group
PARAMS={'process_id','expected_document_path','expected_source_sha256','expected_configuration','addin_clsid',
    'checkpoint_receipt_path','checkpoint_receipt_sha256','session_rebind_receipt_path','session_rebind_receipt_sha256',
    'choices','module_sha256','receipt_path','acknowledge_definition_only_group'}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='insert_shallow_guide_definitions','Exact definition-only group action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact group parameters required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict owned PID required')
    require(p['acknowledge_definition_only_group'] is True,'Explicit definition-only group acknowledgement required')
    require(type(p['expected_configuration']) is str and 0<len(p['expected_configuration'])<=256 and '\x00' not in p['expected_configuration'],'Exact active configuration required')
    for name,value in p.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if name.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute paths required')
    require(type(p['choices']) is dict and set(p['choices'])=={v[0] for v in ROWS},'Exactly four selected default choices required')
    for choice in p['choices'].values():
        require(type(choice) is dict and set(choice)=={'name','default_operation_id'},'Exact catalogue name/ID selection required')
        require(type(choice['name']) is str and 0<len(choice['name'])<=1000 and '\x00' not in choice['name'] and type(choice['default_operation_id']) is int and 0<choice['default_operation_id']<2**31,'Strict bounded catalogue selection required')
    require(p['module_sha256']==_file_hash(__file__),'Exact writer module required')
    return deepcopy(p)


def read_current_binding(doc, *,read,typed):
    require(read(doc,'GetDocType')==1,'Current CAM part required')
    machine=typed(read(typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    require(read(machine,'MachType')==1,'Current MILL machine required')
    out=dict(features={},operation_setups=[],operations=[]);handles={}
    for si,raw_setup in enumerate(_items(read(machine,'IGetEnumOpSetups'),typed,read,3)):
        setup=typed(raw_setup,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        operations=_items(read(setup,'IGetEnumOperations'),typed,read,13)
        out['operation_setups'].append(dict(index=si,native_id=sid,operation_count=len(operations)))
        for oi,raw in enumerate(operations):
            op=typed(raw,'ICWOperation');oid=_object_id(doc,op,read)
            require(oid not in handles,'Duplicate operation native ID');handles[oid]=raw
            mill=typed(raw,'ICWMillOperation');tool,_=read_generic_tool(raw,doc,read,typed)
            out['operations'].append(dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=oid,
                mill_operation_type=read(mill,'OpernType'),base_operation_type=read(op,'OpernType'),
                suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'),
                linked_feature_ids=[_object_id(doc,v,read) for v in _items(read(op,'IGetAllFeatures'),typed,read,4)],
                toolpath_record_counts=[read(typed(v,'ICWToolpath'),'RecordCount') for v in _items(read(op,'IGetEnumToolpaths'),typed,read,4)],assigned_tool=tool))
    require(9<=len(out['operations'])<=13,'Only baseline nine plus at most four definitions allowed')
    for fid in (82,83):
        found=read(doc,'GetCWObjectFromID',1,fid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact guide lookup required')
        header,_=read_header(found[0],doc,read,typed,69);require(header['native_id']==fid,'Guide ID changed')
        out['features'][str(fid)]=header
    return out,handles


def read_own_nc(raw,*,read,typed):
    owner=read(typed(raw,'ICWMillOperation'),'IGetNCParam')
    base=typed(owner,'ICWNCParam');extension=typed(owner,'ICWNCParam2')
    return dict(read_complete=True,spindle_speed_native=guide.start.nc.scalar('double',read(base,'GetSpndlSpeed')),
        xy_feed_native=guide.start.nc.scalar('double',read(extension,'XYFeed')),
        physical_units_qualified=False,cutting_conditions_qualified=False,full_parameters_read=False)


class NativeBackend(guide.NativeBackend):
    def capture_binding(self,label,new_id=None):
        self.boundary()
        with self.ctx.guard() as g:doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3')
        configuration=self.configuration(doc)
        require(exact(configuration,self.report['plan']['configuration']),'Protected CAM/SW configuration changed')
        def binding():
            require(exact(self.configuration(doc),configuration),'Configuration changed during readback')
        batch=guide.GroupReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),source_sha256=self.args['expected_source_sha256'],
            evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,
            check_events=self.events,retained_objects=(doc,),verify_retained_binding=binding,max_native_calls=1200)
        diagnostic=dict(label=label,new_operation_native_id=new_id);self.report.setdefault('captures',[]).append(diagnostic);self.persist()
        try:
            with batch:
                value,handles=read_current_binding(doc,read=batch.read,typed=batch.typed)
                diagnostic['binding']=deepcopy(value);self.persist()
                nc=None
                if new_id is not None:
                    require(new_id in handles,'Returned new ID absent from route')
                    diagnostic['nc_stage']='IGetNCParam_and_two_scalar_getters';self.persist()
                    nc=read_own_nc(handles[new_id],read=batch.read,typed=batch.typed)
                    diagnostic['nc']=deepcopy(nc);self.persist()
            batch.require_complete();self.doc=doc
            require(exact(self.configuration(doc),configuration),'Configuration changed after readback')
            return value,nc
        finally:diagnostic['batch']=batch.summary();self.persist()

    def insert(self,row,anchor_id,pending,returned):
        self.boundary()
        require(exact(self.configuration(self.doc),self.report['plan']['configuration']),'Configuration changed before insertion')
        raw=insert_selected_once(self.ctx,self.doc,row,anchor_id,self.report['plan']['baseline']['features'][str(row['feature_native_id'])],pending)
        returned(raw)
        self.refresh_dirty()
        with self.ctx.guard() as g:oid=_object_id(self.doc,raw,g.read)
        require(type(oid) is int and 0<oid<2**31,'Actual returned positive operation ID required')
        forbidden={v['native_id'] for v in self.loaded['state']['operations']+self.loaded['state']['operation_setups']+self.loaded['state']['feature_setups']}
        forbidden|={v['geometry']['native_id'] for v in self.loaded['state']['features']}
        forbidden|={v['assigned_tool']['native_id'] for v in self.loaded['state']['operations']}
        require(oid not in forbidden,'New operation cross-kind ID collision')
        return oid


class DefinitionJournal(group.GroupJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),
            status=r['status'],phase=r['phase'],actions=deepcopy(r['actions']),actual_new_ids=deepcopy(r.get('actual_new_ids',[])),
            native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


def run_backend(backend,journal):
    require(not journal.created and not journal.claimed,'Group engine cannot be reentered; preserve original evidence')
    r=journal.report;r.update(status='error',phase='preflight',actions={},actual_new_ids=[],mutation_attempted=False,
        native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,readback_verified=False,
        model_saved=False,save_attempted=False,GTP_attempted=False,tool_assignment_attempted=False,
        parameter_setter_attempted=False,automatic_retry=False,automatic_rollback=False,production_qualified=False,
        full_parameter_readback=False,toolpath_bytes_compared=False,local_tool_catalogue_compared=False)
    try:
        journal.create();backend.start()
        before,_=backend.capture_binding('before')
        require(exact(before,r['plan']['baseline']),'Fresh baseline differs from completed group read')
        r['before']=deepcopy(before);journal.persist()
        current=before;anchor=320
        for row in r['plan']['rows']:
            label=row['key'];entry=journal.entry(label)
            def returned(raw):
                require(entry['attempted'] is True and entry.get('native_dispatch_pending') is True and entry['returned'] is False,'Native return without exactly one durable pending attempt')
                entry.update(returned=True,status='returned',native_dispatch_pending=False,returned_interface_pointer=True,native_return_type=type(raw).__name__)
                r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist()
            oid=backend.insert(row,anchor,lambda:journal.pending(label),returned)
            entry['actual_native_id']=oid;r['actual_new_ids'].append(oid);journal.persist()
            after,nc=backend.capture_binding('after_'+label,new_id=oid)
            result=verify_one_addition(current,after,row,oid,anchor)
            require(type(nc) is dict and nc.get('read_complete') is True,'Own NC getter readback required before another insertion')
            journal.verified(label,dict(operation=result,nc=nc));current=after;anchor=oid
        require(len(r['actual_new_ids'])==4 and len(set(r['actual_new_ids']))==4,'Exactly four unique returned native operation IDs required')
        backend.finish();r.update(status='observed',phase='finished',readback_verified=True,after=deepcopy(current),
            reason='FOUR_DEFINITIONS_AND_MINIMAL_OWN_NC_ONLY_NO_CONFIGURATION_GTP_OR_SAVE')
        journal.persist()
    except Exception as exc:
        r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
        try:journal.persist()
        except Exception as extra:r['receipt_write_error']=_error(extra)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',cleanup_issue=_error(exc),readback_verified=False)
        try:journal.persist()
        except Exception as extra:r['receipt_write_error']=_error(extra)
    return r


def audit_insert(typelib,generated):
    from ctypes import HRESULT,POINTER,c_int,c_double
    from comtypes.automation import IDispatch
    contracts=[('ICWMillFeature','InsertOperation',44,(c_int,c_int,POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,1,1,10)),
        ('ICWMillOperation','IGetNCParam',7,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWNCParam','GetSpndlSpeed',7,(POINTER(c_double),),(10,)),
        ('ICWNCParam2','_get_XYFeed',23,(POINTER(c_double),),(10,))]
    rows=[]
    for owner,name,dispid,args,flags in contracts:
        cls=guide.start.interface_class(owner,typelib,generated);methods=[v for v in cls._methods_ if v.name==name]
        require(len(methods)==1,'Unique exact method ABI required')
        m=methods[0];require(m.restype is HRESULT and int(m.idlflags[0])==dispid and m.argtypes==args and tuple(v[0] for v in m.paramflags)==flags,'Exact insertion/NC ABI differs: '+owner+'.'+name)
        rows.append(dict(interface=owner,name=name,dispid=dispid,iid=str(cls._iid_)))
    return rows


def prepare_request(request):
    p=validate_request(request)
    loaded=rebind.load_verified_rebind(p['session_rebind_receipt_path'],p['session_rebind_receipt_sha256'],p)
    observed,pin=read_pin(p['session_rebind_receipt_path'],p['session_rebind_receipt_sha256'])
    plan=compile_definition_plan(observed,p['choices'])
    # No start-point, full rough parameter or catalogue reader is called by this writer.
    retired_names={'sw_cam_rough_entry_parameters.py','sw_cam_chamfer_catalogue_preflight.py','sw_cam_read_progress_journal.py'}
    retired=[v for v in loaded['pins'] if Path(v['path']).name in retired_names]
    loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],retired)
    loaded['pins']=common._merge([v for v in loaded['pins'] if v not in retired],[common._pin(__file__)])
    registration=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    abi=audit_insert(typelib,loaded['generated_pin']);loaded['pins']=common._merge(loaded['pins'],[common._pin(typelib)])
    require(len(loaded['pins'])<=64,'Bounded live native dependency closure required')
    for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
    receipt=common._local_receipt(p['receipt_path'])
    marker=common.local_evidence_root()/('guide_definitions_'+_digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha256=p['expected_source_sha256']))+'.json')
    keys={common._key(v['path']) for name in ('pins','offline_export_proof_pins','bootstrap_export_pins') for v in loaded[name]}|{common._key(p['expected_document_path'])}
    for path in (receipt,marker):require(not path.exists() and not path.is_symlink() and common._key(path) not in keys,'Fresh nonaliased group output/marker required')
    require(common._key(receipt)!=common._key(marker),'Separate group journal and receipt required')
    return p,loaded,plan,registration,typelib,abi,receipt,marker


def dispatch_request(request,*,validate_only=False):
    p,loaded,plan,registration,typelib,abi,receipt,marker=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,plan=plan,interface_audit=abi,live_pin_count=len(loaded['pins']),marker_path=str(marker))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,plan=plan,source_path=p['expected_document_path'],
            source_sha256=p['expected_source_sha256'],recipe_sha256=_digest(plan),module_pin=common._pin(__file__),
            rebind_pin=loaded['session_rebind_receipt_pin'],ownership=loaded['ownership'],live_pins=loaded['pins'],interface_audit=abi)
        journal=DefinitionJournal(report,receipt,marker)
        backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        run_backend(backend,journal)
        try:
            for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
        except Exception as exc:report.update(status='uncertain' if report.get('mutation_attempted') else 'error',issue=_error(exc),readback_verified=False)
        journal.persist();return report
