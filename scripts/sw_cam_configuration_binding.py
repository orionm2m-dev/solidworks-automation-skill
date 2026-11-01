"""Bounded CAM/SOLIDWORKS configuration binding and TURN NC observation.

Only typed, fixed getters. No document activation, tool lookup, Save or mutation.
CAM configuration names belong to a separate namespace; SWConfigurationName is
its documented mapping to the owning SOLIDWORKS configuration.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import json, math, re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_executable_launch import _process_identity, _same_path
from scripts.sw_operation_guard import check_document_target, solidworks_operation_lock
from scripts.sw_cam_comtypes import _load_type_library, _INTERFACES
from scripts.sw_cam_face_interfaces import _verify_generated_class
from scripts.sw_cam_pocket_rough_apply import require_abi
from scripts.sw_cam_rough_firstcut import require

SCOPE='TURN_CONFIGURATION_BINDING_READ_V1'
CAM_CLASS='{CCAC6208-0E19-6455-2022-2026CEB541FA}'
EXTRA_INTERFACES={'ICWConfiguration':'{F74643C0-2AE2-4446-BE21-8C43F7881882}',
                  'ICWTurnNCParam':'{908023A2-B845-4C64-A395-5EF667E7DE68}'}
INTERFACES=frozenset({'ICWApp4','ICWDoc3','ICWPartDoc','ICWMachine','ICWBaseSetup',
    'ICWBaseOpSetup','ICWDispatchCollection','ICWOperation','ICWTurnOperation',
    'ICWTurnWorkpiece','ICWToolpath'})|frozenset(EXTRA_INTERFACES)
GETTERS=frozenset({'IGetActiveDoc','GetDocType','GetActiveConfigurationName',
    'GetActiveConfiguration','ConfigurationName','SWConfigurationName','IGetMachine',
    'MachType','IGetEnumSetups','IGetEnumFeatures','IGetEnumOpSetups',
    'IGetEnumOperations','Count','Item','GetCWObjectID','OpernType','Suppressed',
    'IGetAllFeatures','GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount',
    'IGetWorkpiece','GetTurnWorkpieceType','IGetTurnNCParam','GetSpndlSpeed','GetFeedRateIPM'})
# Fixed imported dependency closure; unrelated MCP server modules are not part of this reader.
RUNTIME_MODULES=('scripts.cad_installation', 'scripts.sw_cam', 'scripts.sw_cam_chamfer_approach_correction', 'scripts.sw_cam_chamfer_catalogue_preflight', 'scripts.sw_cam_chamfer_clearance_read', 'scripts.sw_cam_chamfer_defaults', 'scripts.sw_cam_chamfer_exports', 'scripts.sw_cam_chamfer_generate', 'scripts.sw_cam_chamfer_insert_defaults', 'scripts.sw_cam_chamfer_nc_planes', 'scripts.sw_cam_chamfer_receipt', 'scripts.sw_cam_chamfer_saved_parent', 'scripts.sw_cam_checkpoint_exports', 'scripts.sw_cam_checkpoint_reconfigure', 'scripts.sw_cam_circle_lifecycle_evidence', 'scripts.sw_cam_cl_inventory', 'scripts.sw_cam_complete_sandvik_observation', 'scripts.sw_cam_completed_gtp_save', 'scripts.sw_cam_completed_gtp_wip', 'scripts.sw_cam_completed_holder_cas', 'scripts.sw_cam_completed_sandvik_assignment', 'scripts.sw_cam_completed_sandvik_evidence', 'scripts.sw_cam_completed_sandvik_save', 'scripts.sw_cam_completed_sandvik_saved', 'scripts.sw_cam_compound_plan_delta', 'scripts.sw_cam_compound_plan_evidence', 'scripts.sw_cam_comtypes', 'scripts.sw_cam_defined_rough_levels', 'scripts.sw_cam_dispatch_guard', 'scripts.sw_cam_document_unit_scope', 'scripts.sw_cam_empty_mill_stock_export', 'scripts.sw_cam_events', 'scripts.sw_cam_existing_sandvik', 'scripts.sw_cam_existing_sandvik_evidence', 'scripts.sw_cam_face_interfaces', 'scripts.sw_cam_feature_sketch', 'scripts.sw_cam_finish_lead_observation', 'scripts.sw_cam_finish_observation', 'scripts.sw_cam_finish_read_batch', 'scripts.sw_cam_finish_recipe', 'scripts.sw_cam_generated_plan_cl', 'scripts.sw_cam_generation', 'scripts.sw_cam_grouped_face_recipe', 'scripts.sw_cam_holder_mode_query', 'scripts.sw_cam_holder_observation', 'scripts.sw_cam_holder_shape_cas', 'scripts.sw_cam_lifecycle', 'scripts.sw_cam_mill_afr_delta', 'scripts.sw_cam_mill_append_delta', 'scripts.sw_cam_mill_circle_geometry', 'scripts.sw_cam_mill_compound_strategy', 'scripts.sw_cam_mill_feature_context', 'scripts.sw_cam_mill_feature_process', 'scripts.sw_cam_mill_geometry', 'scripts.sw_cam_mill_inventory', 'scripts.sw_cam_mill_inventory_geometry', 'scripts.sw_cam_mill_inventory_recovery_evidence', 'scripts.sw_cam_mill_levels', 'scripts.sw_cam_mill_lifecycle', 'scripts.sw_cam_mill_profile_headers', 'scripts.sw_cam_mill_profile_indexed', 'scripts.sw_cam_mill_qualification', 'scripts.sw_cam_mill_rough_boundary', 'scripts.sw_cam_mill_route_context', 'scripts.sw_cam_mill_saved_plan_rebind', 'scripts.sw_cam_mill_saved_plan_tools', 'scripts.sw_cam_mill_selected_plan_context', 'scripts.sw_cam_mill_selected_plan_evidence', 'scripts.sw_cam_mill_selected_tool_details', 'scripts.sw_cam_mill_stock', 'scripts.sw_cam_mill_stock_export_evidence', 'scripts.sw_cam_mill_tool_geometry', 'scripts.sw_cam_mill_toolpath', 'scripts.sw_cam_mill_units_geometry', 'scripts.sw_cam_mill_units_qualification', 'scripts.sw_cam_noncutting_continuation', 'scripts.sw_cam_operation_profile', 'scripts.sw_cam_pocket_pair_read', 'scripts.sw_cam_pocket_rough_apply', 'scripts.sw_cam_profile_sketch', 'scripts.sw_cam_qualification_context', 'scripts.sw_cam_raw_mill_face_feature', 'scripts.sw_cam_raw_mill_face_move', 'scripts.sw_cam_raw_mill_face_operation', 'scripts.sw_cam_read_batch_guard', 'scripts.sw_cam_read_progress_journal', 'scripts.sw_cam_rough_entry_parameters', 'scripts.sw_cam_rough_firstcut', 'scripts.sw_cam_rough_startpoint_read', 'scripts.sw_cam_route_batch_qualified_capture', 'scripts.sw_cam_route_checkpoint', 'scripts.sw_cam_route_entry_continuation', 'scripts.sw_cam_route_entry_evidence', 'scripts.sw_cam_route_manifest', 'scripts.sw_cam_route_read_batch', 'scripts.sw_cam_sandvik_gtp_evidence', 'scripts.sw_cam_sandvik_mt', 'scripts.sw_cam_sandvik_phase1', 'scripts.sw_cam_sandvik_save', 'scripts.sw_cam_shared_cutter_config', 'scripts.sw_cam_shared_cutter_evidence', 'scripts.sw_cam_shared_cutter_geometry', 'scripts.sw_cam_shared_holder_geometry', 'scripts.sw_cam_simulation', 'scripts.sw_cam_stock_mesh_compare', 'scripts.sw_cam_straight_cutter_geometry', 'scripts.sw_cam_taper_interfaces', 'scripts.sw_cam_taper_profile', 'scripts.sw_cam_taper_resume_evidence', 'scripts.sw_cam_taper_tool_candidate', 'scripts.sw_cam_taper_tool_resume', 'scripts.sw_cam_thread', 'scripts.sw_cam_turn_feature', 'scripts.sw_cam_turn_feature_attribute', 'scripts.sw_cam_turn_tool', 'scripts.sw_cam_ud14_probe_core', 'scripts.sw_cam_ud14_qualification', 'scripts.sw_cam_ud14_save', 'scripts.sw_cam_ud14_specimen', 'scripts.sw_cam_upper_cone_feature', 'scripts.sw_cam_upper_cone_save', 'scripts.sw_connect', 'scripts.sw_executable_launch', 'scripts.sw_export', 'scripts.sw_macro_guard', 'scripts.sw_operation_guard', 'scripts.sw_preflight', 'scripts.sw_session')

PARAMS={'process_id','expected_process_create_time','expected_document_path',
    'expected_source_sha256','expected_sw_configuration','reference_receipt_path',
    'reference_receipt_sha256','typelib_path','typelib_sha256','generated_path',
    'generated_sha256','runtime_pins','nc_operation_ids','receipt_path','module_sha256'}


def key(path): return str(Path(path).resolve()).casefold()
def integer(value):
    require(type(value) is int and 0<=value<2**32,'Strict nonnegative native integer required');return value

def text(value):
    require(type(value) is str and 0<len(value)<=1024,'Nonempty bounded native BSTR required');return value

def boolean(value):
    require(type(value) is bool,'Strict native Boolean required');return value

def number(value):
    require(type(value) in (int,float) and math.isfinite(value),'Finite native number required');return value


def check_pins(pins):
    for pin in pins:
        require(set(pin)=={'path','sha256'} and Path(pin['path']).is_file() and not Path(pin['path']).is_symlink(),'Exact existing file pin required')
        require(_file_hash(pin['path'])==pin['sha256'],'Pinned file changed: '+pin['path'])


def abi(typelib_path,generated_pin):
    from ctypes import POINTER,c_double
    from comtypes import BSTR
    from comtypes.automation import IDispatch
    lib=_load_type_library(typelib_path);classes={};rows=[]
    specs=(('ICWDoc3','GetActiveConfigurationName',21,(POINTER(BSTR),),(10,)),
        ('ICWDoc3','GetActiveConfiguration',27,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWConfiguration','_get_ConfigurationName',3,(POINTER(BSTR),),(10,)),
        ('ICWConfiguration','_get_SWConfigurationName',4,(POINTER(BSTR),),(10,)),
        ('ICWTurnOperation','IGetTurnNCParam',4,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWTurnNCParam','GetSpndlSpeed',1,(POINTER(c_double),),(10,)),
        ('ICWTurnNCParam','GetFeedRateIPM',3,(POINTER(c_double),),(10,)))
    for interface,member,dispid,args,flags in specs:
        cls=_verify_generated_class(getattr(lib,interface),EXTRA_INTERFACES.get(interface,_INTERFACES.get(interface)),generated_pin)
        methods=[m for m in cls._methods_ if m.name==member]
        require(len(methods)==1,'Unique exact getter required: '+member)
        require_abi(methods[0],dispid,args,flags);classes[interface]=cls
        rows.append(dict(interface=interface,member=member,dispid=dispid))
    return classes,dict(verified=True,native_called=False,methods=rows)


def config_binding(doc,sw_configuration,*,read,typed):
    cam_name=text(read(doc,'GetActiveConfigurationName'))
    config=typed(read(doc,'GetActiveConfiguration'),'ICWConfiguration')
    own_name=text(read(config,'ConfigurationName'))
    sw_name=text(read(config,'SWConfigurationName'))
    row=dict(cam_configuration_name=cam_name,configuration_object_name=own_name,
             associated_sw_configuration_name=sw_name,sw_configuration_name=sw_configuration,
             names_consistent=cam_name==own_name,associated_sw_configuration_matches=sw_name==sw_configuration)
    return row


def require_binding(binding):
    require(binding['names_consistent'],'CAM configuration object/name mismatch')
    require(binding['associated_sw_configuration_matches'],'Associated SOLIDWORKS configuration mismatch')


def read_inventory(doc,machine,*,read,typed):
    def items(raw,limit):
        c=typed(raw,'ICWDispatchCollection');n=integer(read(c,'Count'))
        require(n<=limit,'Native collection exceeds bounded scope')
        return [read(c,'Item',i) for i in range(n)]
    counts=[];feature_ids=[]
    for si,raw in enumerate(items(read(machine,'IGetEnumSetups'),8)):
        setup=typed(raw,'ICWBaseSetup');features=items(read(setup,'IGetEnumFeatures'),64-sum(counts))
        counts.append(len(features));feature_ids.append(dict(setup_index=si,native_ids=[_object_id(doc,f,read) for f in features]))
    setups=items(read(machine,'IGetEnumOpSetups'),8);inventory=[];operations=[];handles={}
    for si,raw in enumerate(setups):
        setup=typed(raw,'ICWBaseOpSetup')
        for oi,rawop in enumerate(items(read(setup,'IGetEnumOperations'),32-len(operations))):
            op=typed(rawop,'ICWOperation');turn=typed(rawop,'ICWTurnOperation');ident=_object_id(doc,op,read)
            require(ident not in handles,'Duplicate operation ID');handles[ident]=turn
            kind=integer(read(turn,'OpernType'));generated=boolean(read(op,'GetIsToolpathGenerated'));records=[]
            if generated:
                for rawpath in items(read(op,'IGetEnumToolpaths'),16):
                    records.append(integer(read(typed(rawpath,'ICWToolpath'),'RecordCount')))
            inventory.append(dict(setup_index=si,operation_index=oi,turn_operation_type=kind,toolpath_generated=generated,toolpath_record_counts=records))
            links=items(read(op,'IGetAllFeatures'),4)
            operations.append(dict(setup_index=si,operation_index=oi,native_id=ident,turn_operation_type=kind,
                linked_feature_ids=[_object_id(doc,f,read) for f in links],suppressed=boolean(read(op,'Suppressed'))))
    stock=typed(read(machine,'IGetWorkpiece'),'ICWTurnWorkpiece')
    result=dict(machine_type=3,feature_setup_count=len(counts),feature_counts_by_setup=counts,feature_count=sum(counts),
        operation_setup_count=len(setups),operation_count=len(operations),operations=inventory,
        stock=dict(type=integer(read(stock,'GetTurnWorkpieceType')),parameters_modified=False,length_units='native_API_units_not_assumed'))
    return dict(inventory=result,operations=operations,feature_ids=feature_ids),handles


def read_nc(ids,handles,*,read,typed,publish=lambda rows:None):
    rows=[]
    for ident in ids:
        row=dict(operation_native_id=ident,status='error',stage='operation_identity');rows.append(row)
        try:
            require(ident in handles,'NC operation absent')
            row['stage']='IGetTurnNCParam';raw=read(handles[ident],'IGetTurnNCParam')
            require(raw is not None and bool(raw),'NC parameter object absent')
            row['stage']='ICWTurnNCParam';nc=typed(raw,'ICWTurnNCParam')
            row['stage']='GetSpndlSpeed';row['spindle_speed_native']=number(read(nc,'GetSpndlSpeed'))
            row['stage']='GetFeedRateIPM';row['feed_rate_ipm_native']=number(read(nc,'GetFeedRateIPM'))
            row.update(status='observed',stage='finished')
        except Exception as exc: row['issue']=_error(exc)
        publish(rows)
    return rows


def prepare(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_turn_configuration_binding','Exact read-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict PID required')
    require(type(p['expected_process_create_time']) in (int,float) and p['expected_process_create_time']>0,'Exact process creation time required')
    text(p['expected_sw_configuration'])
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader module changed')
    ids=p['nc_operation_ids'];require(type(ids) is list and 1<=len(ids)<=8 and all(type(i) is int and 0<i<2**31 for i in ids) and len(set(ids))==len(ids),'Bounded unique NC operation IDs required')
    pins=p['runtime_pins'];require(type(pins) is list and 1<=len(pins)<=128,'Bounded runtime module pins required')
    require(all(type(x) is dict and set(x)=={'path','sha256'} for x in pins),'Exact pin shape required')
    require(len({key(x['path']) for x in pins})==len(pins),'Duplicate module pin')
    loaded=__import__('sys').modules
    require(all(name in loaded and getattr(loaded[name],'__file__',None) for name in RUNTIME_MODULES),'Reader dependency module missing')
    current=[dict(path=str(Path(loaded[name].__file__).resolve()),sha256=_file_hash(loaded[name].__file__)) for name in RUNTIME_MODULES]
    expected={key(x['path']):x['sha256'] for x in pins}
    require(len(pins)==len(current) and all(expected.get(key(x['path']))==x['sha256'] for x in current),'Current reader dependency closure differs from request pins')
    pins=pins+[dict(path=__file__,sha256=p['module_sha256'])]+[dict(path=p[k+'_path'],sha256=p[k+'_sha256']) for k in ('typelib','generated','reference_receipt')]+[dict(path=p['expected_document_path'],sha256=p['expected_source_sha256'])]
    check_pins(pins)
    reference=json.loads(Path(p['reference_receipt_path']).read_text(encoding='utf-8-sig'))
    require(reference.get('scope')=='ROUGH_BORE_UNCERTAIN_TOOL_READ_V1' and reference.get('status')=='observed' and reference.get('readback_verified') is True,'Verified current RAM observation required')
    require(reference['request']['process_id']==p['process_id'] and key(reference['source_path'])==key(p['expected_document_path']) and reference['source_sha256']==p['expected_source_sha256'],'Reference source/owner mismatch')
    require(reference['before']==reference['after'],'Reference observation changed')
    ref=reference['after'];require(all(i in [x['native_id'] for x in ref['operations']] for i in ids),'NC operation not in reference')
    out=Path(p['receipt_path']);require(out.suffix=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh JSON receipt in existing directory required')
    require(key(out) not in {key(x['path']) for x in pins},'Receipt aliases input')
    classes,a=abi(p['typelib_path'],dict(path=p['generated_path'],sha256=p['generated_sha256']))
    return p,dict(pins=pins,reference=ref,output=out,classes=classes,abi=a)


class NativeReader:
    def __init__(self,sw,p,plan,report,publish):
        self.sw,self.p,self.plan,self.report,self.publish=sw,p,plan,report,publish
        self.session=None;self.calls=0;self.qis=0;self.known=set();self.retained=[]
    def retain(self,value):
        if value is not None and type(value) not in (int,float,bool,str,bytes,dict):
            self.known.add(id(value));self.retained.append(value)
        return value
    def events(self):
        if self.session is None:return
        s=self.session.summary();self.report['messages']=s
        require(s.get('active') is True and s.get('subscribed') is True and not any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM message requires stop')
    def owned(self):
        v=_process_identity(self.p['process_id'])
        require(v.get('alive') is True and v.get('process_id')==self.p['process_id'] and v.get('create_time')==self.p['expected_process_create_time'],'Owned process identity changed')
        require(Path(v.get('executable','')).name.casefold()=='sldworks.exe','Unexpected owned executable')
        require(type(_member(self.sw,'GetProcessID')) is int and _member(self.sw,'GetProcessID')==self.p['process_id'],'Connected PID differs')
    def document(self):
        self.owned();d=document_snapshot(self.sw);require(d is not None and d['type']==1,'Active saved part required')
        check_document_target(d['path'],d['title'],expected_path=self.p['expected_document_path'],required=True)
        model=_member(self.sw,'ActiveDoc');manager=_member(model,'ConfigurationManager');configuration=_member(manager,'ActiveConfiguration')
        d['configuration']=text(_member(configuration,'Name'))
        require(d['configuration']==self.p['expected_sw_configuration'],'Unexpected SW configuration');return d
    def boundary(self):
        self.events();check_pins(self.plan['pins']);d=self.document();self.events();return d
    def read(self,obj,name,*args):
        require(name in GETTERS and id(obj) in self.known,'Getter/owner outside retained read graph')
        require(self.calls+self.qis<512,'Native read budget exhausted')
        require(all(type(a) is int or id(a) in self.known for a in args),'Argument outside retained graph')
        self.events();self.calls+=1;self.report['current_read']=name
        result=_member(obj,name,*args);self.events();return self.retain(result)
    def typed(self,obj,name):
        require(name in INTERFACES and obj is not None and id(obj) in self.known,'Typed interface outside retained graph')
        require(self.calls+self.qis<512,'Native read budget exhausted');self.events();self.qis+=1
        result=obj.QueryInterface(self.plan['classes'][name]) if name in EXTRA_INTERFACES else _typed(obj,name,self.p['typelib_path'])
        self.events();return self.retain(result)
    def run(self):
        before=self.boundary();self.report['document_before']=before;self.publish()
        addin=_member(self.sw,'GetAddInObject',CAM_CLASS);require(addin is not None,'Existing CAM add-in required')
        app=self.typed(self.retain(_member(addin,'GetCWApp')),'ICWApp4')
        with CamMessageSession(app,self.p['typelib_path']) as session:
            self.session=session;self.events();require(self.boundary()==before,'Initial document changed')
            self.report['phase']='cam_binding';active=self.read(app,'IGetActiveDoc');doc=self.typed(active,'ICWDoc3')
            require(integer(self.read(doc,'GetDocType'))==1,'CAM part required')
            binding=config_binding(doc,before['configuration'],read=self.read,typed=self.typed)
            self.report['binding_before']=binding;self.publish();require_binding(binding)
            part=self.typed(active,'ICWPartDoc');machine=self.typed(self.read(part,'IGetMachine'),'ICWMachine')
            require(integer(self.read(machine,'MachType'))==3,'TURN machine required')
            self.report['phase']='route_binding';state,handles=read_inventory(doc,machine,read=self.read,typed=self.typed)
            self.report['observed_route']=state;self.publish()
            expected={k:self.plan['reference'][k] for k in ('inventory','operations','feature_ids')}
            require(state==expected,'Current operation identity/order/protected path metadata differs from reference')
            self.report['route_reference_matches']=True;self.report['phase']='nc_parameters'
            def nc_publish(rows): self.report['nc_parameters']=deepcopy(rows);self.publish()
            self.report['nc_parameters']=read_nc(self.p['nc_operation_ids'],handles,read=self.read,typed=self.typed,publish=nc_publish)
            self.events();self.report['phase']='after'
            after_binding=config_binding(doc,before['configuration'],read=self.read,typed=self.typed)
            self.report['binding_after']=after_binding;require_binding(after_binding);require(after_binding==binding,'CAM configuration changed')
            after=self.boundary();self.report['document_after']=after;require(after==before,'Document identity/dirty/config changed')
            self.report.update(readback_verified=True,nc_parameters_complete=all(r['status']=='observed' for r in self.report['nc_parameters']))
        self.report['messages']=session.summary();self.session=None
        require(not any(self.report['messages'].get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event/cleanup error')
        require(self.boundary()==before,'Document changed during event cleanup')
        self.report.update(status='observed',phase='finished',getter_calls=self.calls,query_interface_calls=self.qis)


def dispatch_request(request,*,validate_only=False):
    p,plan=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,abi=plan['abi'],pin_count=len(plan['pins']),nc_operation_ids=p['nc_operation_ids'])
    from scripts.sw_connect import connect_solidworks
    report=dict(scope=SCOPE,status='prepared',phase='entry',request=p,read_only=True,mutation_attempted=False,
        model_saved=False,GTP_attempted=False,tool_lookup_attempted=False,readback_verified=False,
        route_reference_matches=False,nc_parameters=[],nc_parameters_complete=False,abi=plan['abi'],
        limitations=['Single non-atomic observation; entry/exit identity and source checks.',
                    'No native CAM filepath getter was found. Binding combines explicit SW configuration mapping, unchanged owned document and exact known route identities.',
                    'No operation tool getter, setters, generation, Save or production qualification.',
                    'Protected path comparison covers generated flags and record counts, not CL byte hashes.'])
    _write_receipt(plan['output'],report,create=True);publish=lambda:_write_receipt(plan['output'],report)
    timer=perf_counter()
    try:
        with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
            sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
            reader=NativeReader(sw,p,plan,report,publish);reader.run()
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:report['elapsed_seconds']=perf_counter()-timer;publish()
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');a=parser.parse_args()
    value=dispatch_request(json.loads(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only)
    print(json.dumps({k:value[k] for k in ('scope','status','phase','readback_verified','native_called','binding_before','nc_parameters','issue','abi') if k in value},ensure_ascii=False,indent=2))
    raise SystemExit(0 if value['status'] in ('observed','validated_offline') else 2)
