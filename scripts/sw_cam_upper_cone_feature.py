"""One tapered circular CAM feature on an explicitly rebound terminal route.

The branch never generates operations/toolpaths, saves, edits solids or retries.
A saved terminal finish checkpoint and an unsaved verified circle are mandatory.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import base64, hashlib, json, math, re
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_comtypes import _is_comtypes_pointer
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_executable_launch import _process_identity, _same_path
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_profile_sketch import _input, _state_digest, _same_bodies, _read_sketch
from scripts.sw_cam_mill_units_qualification import _circle_feature, _circle_sketch, _features, _bodies, _nonnull
from scripts.sw_cam_mill_circle_geometry import _circle_chain
from scripts.sw_cam_mill_selected_plan_context import read_header, read_options
from scripts.sw_cam_mill_profile_headers import read_profile_feature_headers
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_empty_mill_stock_export import _export_stock
from scripts.sw_cam_mill_qualification import _snapshot, _bootstrap
from scripts.sw_cam_mill_route_context import read_route_operations, read_generic_tool
from scripts.sw_cam_completed_sandvik_assignment import capture_assignment_snapshot, read_assignment_candidate
from scripts.sw_cam_finish_read_batch import ScopedFinishReadBatch
from scripts.sw_cam_finish_observation import read_finish_details
from scripts.sw_cam_finish_lead_observation import read_lead_details
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_mill_levels import read_mill_level_values
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope

BASELINE_SCOPE='MILL_UPPER_CONE_BRANCH_BASELINE_V1'
SCOPE='MILL_UPPER_CONE_FEATURE_ONLY_V1'
MAX_BASELINE_BYTES=32*1024*1024
MAX_ARCHIVE_BYTES=24*1024*1024
IDS=('target_feature_native_id','target_operation_native_id','target_operation_setup_native_id',
     'expected_candidate_tool_native_id','finish_operation_native_id','finish_tool_native_id')
# Prior lifecycle loaders are used once by the offline builder, never after cutover.
RETIRED_RUNTIME=frozenset({'sw_cam_route_manifest.py','sw_cam_route_batch_qualification.py',
 'sw_cam_route_read_batch_qualification.py','sw_cam_route_checkpoint.py','sw_cam_completed_gtp_wip.py',
 'sw_cam_completed_sandvik_save.py','sw_cam_route_entry_continuation.py','sw_cam_finish_recipe.py',
 'sw_cam_straight_cutter_geometry.py','sw_cam_shared_cutter_config.py','sw_cam_shared_cutter_geometry.py',
 'sw_cam_finish_continuation_evidence.py','sw_cam_finish_continuation.py','sw_cam_mill_generic_cl.py',
 'sw_cam_cl_inventory.py','sw_cam_ud14_save.py'})
EXTRA_RUNTIME=('sw_cam_upper_cone_feature.py','sw_cam_profile_sketch.py','sw_cam_feature_sketch.py',
 'sw_cam_mill_units_qualification.py','sw_cam_mill_circle_geometry.py','sw_cam_mill_selected_plan_context.py',
 'sw_cam_mill_profile_headers.py','sw_cam_empty_mill_stock_export.py',
 'sw_cam_turn_feature_attribute.py','sw_cam_mill_stock.py')
CONTEXT_KEYS=('state','payload','finish_payload','ownership','qualification','observation_pin',
 'read_mode','base_saved_pin','source_sha256','holder_recipe')


def _key(path): return str(Path(path).resolve()).casefold()
def _pin(path): return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _sha(value): require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'SHA256 required');return value

def runtime_root():
    import scripts.sw_cam as module
    return Path(module.__file__).resolve().parent

def _json_pin(path,digest,limit=MAX_BASELINE_BYTES):
    p=Path(path);_sha(digest)
    require(p.is_absolute() and p.is_file() and not p.is_symlink() and p.stat().st_size<=limit,'Bounded existing regular evidence required')
    raw=p.read_bytes();require(hashlib.sha256(raw).hexdigest()==digest,'Evidence content changed')
    data=json.loads(raw.decode('utf-8-sig'));require(type(data) is dict,'JSON object required')
    return data,_pin(p)

def _archive(pin):
    p=Path(pin['path']);raw=p.read_bytes()
    require(len(raw)<=16*1024*1024 and hashlib.sha256(raw).hexdigest()==pin['sha256'],'Pinned archive member differs')
    return dict(pin=deepcopy(pin),bytes=len(raw),base64=base64.b64encode(raw).decode('ascii'))

def _verify_archive(rows):
    require(type(rows) is list and 1<=len(rows)<=96,'Bounded original evidence archive required')
    seen=set();total=0
    for row in rows:
        require(type(row) is dict and set(row)=={'pin','bytes','base64'},'Exact archive member required')
        key=_key(row['pin']['path']);require(key not in seen,'Duplicate archived path');seen.add(key)
        require(type(row['bytes']) is int and 0<row['bytes']<=16*1024*1024,'Bounded archived size required')
        raw=base64.b64decode(row['base64'],validate=True);total+=len(raw)
        require(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['pin']['sha256'],'Archive member hash differs')
    require(total<=MAX_ARCHIVE_BYTES,'Archive total exceeded')
    return seen


def build_upper_cone_baseline(final_receipt_path,final_receipt_sha256,*,output_path,new_server_sha256,**args):
    """Offline only, before runtime replacement. Verify old final Save exactly once."""
    from scripts.sw_cam_finish_continuation_evidence import load_finish_continuation, selected
    _sha(new_server_sha256)
    terminal,terminal_pin=read_pin(final_receipt_path,final_receipt_sha256)
    require(terminal.get('action')=='save' and terminal.get('parent_action') in ('cl','export_cl'),'Only terminal Save after CL can start this branch')
    if terminal.get('scope')=='RECOVERED_FINISH_SAVE_V1':
        import importlib.util
        recovery=terminal['recovery_module_pin'];rp=Path(recovery['path'])
        require(rp.is_file() and not rp.is_symlink() and rp.name=='sw_cam_finish_recovery.py' and _file_hash(rp)==recovery['sha256'],'Exact completed recovery implementation required')
        spec=importlib.util.spec_from_file_location('_upper_cone_terminal_recovery',rp)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        loaded=module.load_completed_recovery(final_receipt_path,final_receipt_sha256,action='save',**args)
        require(terminal.get('parent_action')=='export_cl','Recovery Save requires its CL predecessor')
    else:
        require(terminal.get('parent_action')=='cl','Original Save requires its CL predecessor')
        loaded=load_finish_continuation(final_receipt_path,final_receipt_sha256,action='save',**args)
    selected(loaded['state'],args,generated=True)
    require(loaded['state']['document']['needs_save'] is False and len(loaded['state']['features'])==19,'Exact clean saved19-feature route required')
    scripts_dir=runtime_root();server=scripts_dir.parent/'mcp-server/server.py'
    original=[];seen={}
    for item in loaded['pins']+loaded.get('lineage_pins',[]):
        key=_key(item['path'])
        require(key not in seen or seen[key]==item['sha256'],'Conflicting archived dependency')
        if key not in seen:original.append(deepcopy(item));seen[key]=item['sha256']
    require(len(original)<=96,'Bounded archived dependency closure required')
    original_by_path={_key(p['path']):p for p in original}
    require(_key(server) in original_by_path and _file_hash(server)==original_by_path[_key(server)]['sha256'],'Original server binding required')
    require(new_server_sha256!=original_by_path[_key(server)]['sha256'],'Explicit changed server registration hash required')
    # Archive everything exactly; only completed branch ancestors and unused old
    # runtime modules stop being separate live pins. Unknown markers stay live.
    completed={_key(p['path']) for p in loaded.get('active_continuation_pins',[])+loaded.get('lineage_pins',[])}
    # Completed recipe outputs remain live unless their exact ownership was exposed.
    live=[];retired=[];runtime=[]
    for pin in loaded['pins']:
        p=Path(pin['path']);is_runtime=(_key(p.parent)==_key(scripts_dir) and p.suffix=='.py') or _key(p)==_key(server)
        if _key(p) in completed or (is_runtime and p.name in RETIRED_RUNTIME):retired.append(pin);continue
        item=deepcopy(pin)
        if _key(p)==_key(server):item=dict(path=str(server),sha256=new_server_sha256)
        live.append(item)
        if is_runtime:runtime.append(item)
    for name in EXTRA_RUNTIME:
        destination=scripts_dir/name
        source=Path(__file__) if name==Path(__file__).name else destination
        pin=dict(path=str(destination),sha256=_file_hash(source));live.append(pin);runtime.append(pin)
    stock=loaded['state']['stock'];require(_file_hash(stock['stl_path'])==stock['stl_sha256'],'Pinned STL changed')
    live.append(dict(path=stock['stl_path'],sha256=stock['stl_sha256']))
    live=canonical_evidence_pins(live);runtime=canonical_evidence_pins(runtime)
    # Baseline plus one independently verified sketch receipt will be live.
    require(len(live)+2<=64,'Upper-cone dependency budget exceeds unchanged64 guard limit')
    context={k:deepcopy(loaded[k]) for k in CONTEXT_KEYS if k in loaded}
    require(all(k in context for k in ('state','payload','finish_payload','ownership','read_mode','observation_pin')),'Complete terminal context required')
    data=dict(schema_version=1,scope=BASELINE_SCOPE,status='verified_offline_terminal_branch',
        terminal_pin=terminal_pin,terminal_checkpoint=deepcopy(terminal['checkpoint']),
        source_path=args['expected_document_path'],source_sha256=args['expected_source_sha256'],process_id=args['process_id'],
        ids={k:args[k] for k in IDS},context=context,context_sha256=_digest(context),
        live_pins=live,runtime_pins=runtime,archived_inputs=[_archive(p) for p in original],
        retired_live_pins=retired,old_server_pin=original_by_path[_key(server)],new_server_pin=dict(path=str(server),sha256=new_server_sha256),
        candidate_pin=dict(path=str(scripts_dir/Path(__file__).name),sha256=_file_hash(__file__)),
        old_loader_verified=True,old_runtime_checked_before_cutover=True,native_calls=0,
        runtime_rebind_explicit=True,cad_source_rebound=False,projected_live_pins_with_sketch=len(live)+2)
    _verify_archive(data['archived_inputs'])
    raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
    require(len(raw)<=MAX_BASELINE_BYTES,'Baseline JSON size exceeded')
    output=Path(output_path);require(output.is_absolute() and output.parent.is_dir() and not output.exists() and not output.is_symlink(),'Fresh absolute baseline required')
    protected={_key(p['path']) for p in original}|{_key(args['expected_document_path'])}
    require(_key(output) not in protected,'Baseline aliases source/evidence')
    _write_receipt(output,data,create=True)
    return dict(status='built_offline',baseline_pin=_pin(output),live_pin_count=len(live)+2,native_calls=0)


def load_upper_cone_baseline(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    data,pin=_json_pin(path,digest)
    require(data.get('scope')==BASELINE_SCOPE and data.get('status')=='verified_offline_terminal_branch'
        and data.get('old_loader_verified') is True and data.get('runtime_rebind_explicit') is True,'Verified terminal branch baseline required')
    require(type(process_id) is int and data['process_id']==process_id and data['source_sha256']==expected_source_sha256,'Exact branch source/process required')
    check_document_target(data['source_path'],None,expected_path=expected_document_path,required=True)
    require(_file_hash(expected_document_path)==expected_source_sha256,'Branch saved source changed')
    archived=_verify_archive(data['archived_inputs']);require(_key(data['terminal_pin']['path']) in archived,'Terminal receipt must remain archived')
    terminal_rows=[r for r in data['archived_inputs'] if _key(r['pin']['path'])==_key(data['terminal_pin']['path'])]
    require(len(terminal_rows)==1 and terminal_rows[0]['pin']['sha256']==data['terminal_pin']['sha256'],'Exact archived terminal receipt required')
    terminal=json.loads(base64.b64decode(terminal_rows[0]['base64'],validate=True).decode('utf-8-sig'))
    require(terminal['checkpoint']==data['terminal_checkpoint'],'Archived terminal checkpoint differs')
    require(data['context_sha256']==_digest(data['context']),'Context digest differs')
    checkpoint=data['terminal_checkpoint'];ctx=data['context']
    require(checkpoint['state']==ctx['state'] and checkpoint['payload']==dict(rough=ctx['payload'],finish=ctx['finish_payload'])
        and checkpoint['source_sha256']==expected_source_sha256,'Terminal checkpoint/context mismatch')
    require(ctx['state']['document']['needs_save'] is False and len(ctx['state']['features'])==19 and len(ctx['state']['operations'])==6,'Exact terminal19/6 inventory required')
    require(_key(data['candidate_pin']['path'])==_key(__file__) and data['candidate_pin']['sha256']==_file_hash(__file__),'Installed branch implementation differs')
    require(_key(data['new_server_pin']['path'])==_key(runtime_root().parent/'mcp-server/server.py'),'Unexpected server path')
    pins=canonical_evidence_pins(data['live_pins'],[pin]);require(len(pins)+1<=64,'Sketch pin would exceed guard bound')
    for p in pins:require(_file_hash(p['path'])==p['sha256'],'Current branch dependency changed')
    result=deepcopy(ctx);result.update(pin=pin,pins=pins,historical_only=False,ids=deepcopy(data['ids']),baseline=data)
    return result


def validate_cone_request(*,sketch_spec,taper_angle_native,taper_type,acknowledge_unqualified_taper):
    spec=_input(sketch_spec)
    require(spec['plane_axis']=='Z' and spec['plane_offset_mm']==26.0 and spec['profile']==dict(kind='circle',center_model_mm=[0.,0.,26.],radius_mm=23.55),'Exact upper circle Z26 D47.1 required')
    require(type(taper_angle_native) in (int,float) and math.isfinite(taper_angle_native) and 0<taper_angle_native<=90,'Explicit finite nonzero taper input required')
    require(type(taper_type) is int and taper_type in (0,1),'Explicit IN0/OUT1 taper type required')
    require(acknowledge_unqualified_taper is True,'Explicit unqualified taper unit/reference/sign acknowledgement required')
    return spec


def cone_marker(source,source_sha256):
    # Taper values, sketch spelling and receipt name cannot rearm the same region.
    key=_digest(dict(scope=SCOPE,source=_key(source),source_sha256=source_sha256,region='upper_Z26_25p8_D47p1_46p7'))
    return Path(source).resolve().parent/('upper_cone_feature_'+key+'.json')


def load_sketch_prerequisite(path,digest,loaded,spec,process_id):
    data,pin=read_pin(path,digest);state=loaded['state']
    require(data.get('status')=='ok' and data.get('phase')=='finished' and data.get('native_readback_verified') is True
        and data.get('mutation_attempted') is True and data.get('saved') is False and data.get('CAD_solid_edit_attempted') is False
        and type(data.get('CAM_calls')) is int and data['CAM_calls']==0 and not any(k in data for k in ('issue','receipt_write_error','cleanup_errors')),'Completed unsaved sketch-only prerequisite required')
    a,b=data['before'],data['after']
    for v in (a,b):
        require(v['pid']==process_id and v['saved_file_sha256']==state['saved_file_sha256'] and v['spec']==spec,'Sketch binding differs')
        check_document_target(v['path'],None,expected_path=state['document']['path'],required=True)
    require(data['state_sha256']==_state_digest(a) and data['after_state_sha256']==_state_digest(b),'Sketch state digest differs')
    require(a['needs_save'] is False and b['needs_save'] is True and a['features']==state['sw_reference']['feature_tree']
        and _same_bodies(a['solids'],state['sw_reference']['solids']) and _same_bodies(a['solids'],b['solids']),'Sketch source tree/body/dirty delta differs')
    created=data['created_features'];wanted=[dict(name=spec['sketch_name'],type='ProfileFeature')]
    if len(created)==2:wanted.insert(0,dict(name=spec['plane_name'],type='RefPlane'))
    require(created==wanted,'Only exact circle and optional plane may be new')
    names={v['name'] for v in wanted}
    require(not any(v['name'] in names for v in a['features']) and [v for v in b['features'] if v['name'] not in names]==a['features']
        and [v for v in b['features'] if v['name'] in names]==wanted,'Sketch changed existing features')
    expected=deepcopy(state);expected['document']['needs_save']=True
    expected['sw_reference']=dict(feature_tree=deepcopy(b['features']),solids=deepcopy(b['solids']))
    return data,pin,expected


def verify_cone_geometry(observed,sketch_circle_m,new_id,*,expected_taper_angle_native=45.0,tolerance_mm=1e-6):
    require(type(new_id) is int and new_id>0 and type(tolerance_mm) in (int,float) and 0<tolerance_mm<=1e-5,'Exact feature ID and bounded tolerance required')
    require(observed['native_id']==new_id and observed['volume_type']==2 and observed['suppressed'] is False,'New unsuppressed pocket identity required')
    close=lambda a,b: type(a) in (int,float) and math.isfinite(a) and abs(a-b)<=tolerance_mm
    vec=lambda a,b: type(a) in (list,tuple) and len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    require(close(observed['depth_native'],0.2) and vec(observed['axis_native'],[0,0,-1])
        and vec(observed['start_native'],[0,0,26]) and vec(observed['bounds_native'],[47.1,47.1,0.2]),'Upper cone header differs')
    require(observed['taper_enabled'] is True and type(observed['taper_angle_readback']) in (int,float)
        and math.isfinite(observed['taper_angle_readback']) and observed['taper_angle_readback']!=0
        and close(observed['taper_angle_readback'],expected_taper_angle_native),'Exact requested nonzero native taper readback required')
    require(vec([v*1000 for v in sketch_circle_m['center_model_m']],[0,0,26])
        and close(sketch_circle_m['radius_m']*1000,23.55),'Model-space upper sketch differs')
    top=_circle_chain(observed['top_curves_native'],1e-8,1e-8,1e-7,'top')
    bottom=_circle_chain(observed['bottom_curves_native'],1e-8,1e-8,1e-7,'bottom')
    require(vec(top['center'],[0,0,26]) and close(top['radius'],23.55),'Exact full top circle Z26 D47.1 required')
    require(close(bottom['radius'],23.35),'Exact full lower-profile diameter D46.7 required')
    coplanar=vec(bottom['center'],top['center'])
    distinct=vec(bottom['center'],[0,0,25.8])
    require(coplanar or distinct,'Unexpected native bottom-profile plane or centre')
    for row in (top,bottom):require(vec([0,0,abs(row['normal'][2])],[0,0,1]) and abs(row['normal'][0])<1e-7 and abs(row['normal'][1])<1e-7,'Parallel XY contours required')
    return dict(native_configuration_verified=True,complete_circular_profiles_verified=True,
        raw_top_center_native=top['center'],raw_bottom_center_native=bottom['center'],
        raw_top_radius_native=top['radius'],raw_bottom_radius_native=bottom['radius'],
        raw_header_depth_native=observed['depth_native'],raw_axis_native=observed['axis_native'],
        raw_taper_angle_native=observed['taper_angle_readback'],raw_profiles_coplanar=coplanar,
        distinct_native_planes_observed=distinct,coordinate_frame_qualified=False,
        geometric_depth_verified=False,lower_world_boundary_synthesized=False,
        target_only=dict(top_z_mm=26,bottom_z_mm=25.8,top_diameter_mm=47.1,bottom_diameter_mm=46.7),
        taper_api_units_qualified=False,complete_conical_surface_proved=False,
        contract_review='mill_units_qualification_20261026/top_bottom_contract_review_20261026/RESULT.json',
        limit='Native configuration only. Top/Bottom SDK pages do not define contour frames. Raw coplanar profiles are retained without displacement; physical depth/frame require independent CL/WIP evidence before engineering acceptance.')


MASS_RAW_REL_TOL=1e-12


def require_state_equivalent(reference,observed,*,diagnostic=None):
    """Compare raw states, tolerating only bounded body mass-property roundoff.

    IBody2.GetMassProperties(1) yields twelve mixed-dimension doubles. No
    absolute tolerance is applied. This is a numeric fingerprint check, not a
    geometric/manufacturing tolerance. Original observations are never edited.
    """
    diag={} if diagnostic is None else diagnostic
    require(type(diag) is dict,'Comparison diagnostic must be an object')
    diag.update(scope='BODY_MASS_RAW_RELATIVE_COMPARISON_V1',relative_tolerance=MASS_RAW_REL_TOL,
        absolute_tolerance=0.0,accepted_numeric_deltas=[],state_equivalent=False,
        raw_observations_preserved=True,manufacturing_tolerance=False)
    require(type(reference) is dict and type(observed) is dict,'Exact state objects required')
    normalized=deepcopy(observed)
    a=reference.get('sw_reference',{}).get('solids');b=normalized.get('sw_reference',{}).get('solids')
    require(type(a) is list and type(b) is list and 1<=len(a)<=64 and len(a)==len(b),
        'Exact bounded solid body count required')
    for i,(old,new) in enumerate(zip(a,b)):
        require(type(old) is dict and type(new) is dict,'Exact body fingerprints required')
        x=old.get('mass_raw');y=new.get('mass_raw')
        require(type(x) is list and type(y) is list and len(x)==len(y)==12,
            'Exact twelve-component solid mass-property arrays required')
        for j,(expected,actual) in enumerate(zip(x,y)):
            require(type(expected) is float and type(actual) is float
                and math.isfinite(expected) and math.isfinite(actual),'Finite strict mass-property doubles required')
            if expected==actual:continue
            delta=abs(actual-expected);scale=max(abs(expected),abs(actual))
            require(math.isclose(expected,actual,rel_tol=MASS_RAW_REL_TOL,abs_tol=0.0),
                'Body mass-property change exceeds relative-only numeric bound')
            diag['accepted_numeric_deltas'].append(dict(path=f'/sw_reference/solids/{i}/mass_raw/{j}',
                reference=expected,observed=actual,absolute_delta=delta,relative_delta=delta/scale))
            y[j]=expected
    # Digest comparison also preserves scalar types; no other numeric coercion.
    require(_digest(reference)==_digest(normalized),'State differs outside permitted mass-property roundoff')
    diag['state_equivalent']=True
    return normalized


def verify_feature_delta(before,after,new_id,owner_id,*,diagnostic=None):
    old=before['features'];rows=after['features'];oldids=[r['geometry']['native_id'] for r in old]
    require(len(old)==19 and len(rows)==20 and len({r['geometry']['native_id'] for r in rows})==20 and new_id not in oldids,'Exactly one new feature required')
    added=[r for r in rows if r['geometry']['native_id'] not in oldids]
    require(len(added)==1 and added[0]['geometry']['native_id']==new_id and added[0]['setup_native_id']==owner_id,'Exact new owner/feature required')
    retained=[r for r in rows if r['geometry']['native_id'] in oldids]
    for a,b in zip(old,retained):
        x,y=deepcopy(a),deepcopy(b);x.pop('feature_index');y.pop('feature_index');require(x==y,'Existing feature changed')
    require(len(before['feature_setups'])==len(after['feature_setups']) and sum(r['native_id']==owner_id for r in before['feature_setups'])==1,'Exactly unchanged setups and one owner required')
    expected=deepcopy(before);expected['features']=deepcopy(rows);expected['document']['needs_save']=after['document']['needs_save']
    require(type(after['document']['needs_save']) is bool,'Strict dirty flag required')
    for i,(a,b) in enumerate(zip(before['feature_setups'],after['feature_setups'])):
        target=deepcopy(a)
        if a['native_id']==owner_id:target['feature_count']+=1
        require(target==b,'Unexpected feature setup delta')
        local=[r for r in rows if r['setup_index']==i]
        require(len(local)==b['feature_count'] and [r['feature_index'] for r in local]==list(range(len(local))),'Feature order/count differs')
    expected['feature_setups']=deepcopy(after['feature_setups'])
    require_state_equivalent(expected,after,diagnostic=diagnostic)
    return deepcopy(added[0])


class UpperConeContext:
    def __init__(self,loaded,args,sw,typelib_path,app,events,expected_state):
        self.loaded,self.args,self.sw,self.typelib_path,self.app,self.events=loaded,args,sw,typelib_path,app,events
        self.expected_document=deepcopy(expected_state['document'])
    def files(self):
        for p in self.loaded['pins']:require(_file_hash(p['path'])==p['sha256'],'Branch dependency changed')
    def owned(self):
        got=_process_identity(self.args['process_id']);want=self.loaded['ownership']
        require(type(got.get('process_id')) is int and got['process_id']==self.args['process_id'] and got.get('alive') is True
            and got.get('create_time')==want['create_time'] and _same_path(got.get('executable',''),want['executable']),'Owned PID exited or was reused')
    def identity(self):
        require(type(_member(self.sw,'GetProcessID')) is int and _member(self.sw,'GetProcessID')==self.args['process_id'],'Owned process differs')
        self.owned();doc=raw_part_identity(self.sw)
        require(doc==self.expected_document and _file_hash(self.args['expected_document_path'])==self.args['expected_source_sha256'],'Exact branch document/dirty/source differs')
        return doc
    def guard(self):
        return ScopedCamDispatchGuard(self.sw,self.typelib_path,process_id=self.args['process_id'],
            expected_document=self.identity(),source_sha256=self.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.files,verify_owned_process=self.owned,check_events=self.events)


HEADER_READ_MEMBERS=frozenset({
    'GetCWObjectID','GetCWObjectFromID','Count','Item','IGetEnumFeatures',
    'GetEMFFeatTypeOptions','GetEMFPartPeriTypeOptions','GetEMFTypeOptions',
    'FeatureCreationStyle','EMFHoleMaxDiameter','EMFHoleMinimumIncludedAngle',
    'VolumeType','SubType','Shape','Suppressed','FeatureName','Axis','Depth',
    'GetBoundParams','GetStartPosition','GetOwner','IGetIslandCount',
    'GetSketchCount','GetSketchNameList','GetEndCondition1','GetEndCondition2',
    'IGetEnumOpSetups','IGetEnumOperations','OpernType','GetIsToolpathGenerated',
    'IGetAllFeatures','IGetEnumToolpaths','RecordCount','IGetTool','IsMillTool',
    'ToolType','CutDiameter','Protrusion',
})
HEADER_READ_INTERFACES=frozenset({
    'ICWBaseSetup','ICWDispatchCollection','ICWFeature','ICWMillFeature',
    'ICWProfileFeature','ICWBaseOpSetup','ICWOperation','ICWMillOperation',
    'ICWToolpath','ICWTool',
})


class ScopedUpperHeaderReadBatch(ScopedCamReadBatch):
    """Existing header readers on retained CAM roots; globals remain strong."""
    def __init__(self,*args,native_context,reference_state,**kwargs):
        require(type(native_context) is dict and all(k in native_context for k in ('doc','machine','setups')),
            'Strong-resolved CAM header roots required')
        setups=native_context['setups'];rows=reference_state['feature_setups']
        require(type(setups) in (list,tuple) and 1<=len(setups)<=8 and len(setups)==len(rows),
            'Exact bounded setup roots required')
        ids=tuple(row['native_id'] for row in rows)
        require(all(type(i) is int and 0<i<2**32 for i in ids) and len(set(ids))==len(ids),
            'Unique strict setup identities required')
        self._header_doc=native_context['doc'];self._header_machine=native_context['machine']
        self._header_setups=tuple(zip(ids,setups));self._binding_checks=0;self._binding_reads=0
        check=kwargs.get('check_events');require(callable(check),'Per-read event verifier required')
        def binding():
            def read(obj,name,*values):
                check();self._binding_reads+=1;value=_member(obj,name,*values);check();return value
            kind=read(self._header_doc,'GetDocType');machine_kind=read(self._header_machine,'MachType')
            require(type(kind) is int and kind==1 and type(machine_kind) is int and machine_kind==1,
                'Retained header document/MILL binding changed')
            for expected,setup in self._header_setups:
                require(_object_id(self._header_doc,setup,read)==expected,'Retained header setup ID changed')
            self._binding_checks+=1
        super().__init__(*args,retained_objects=(self._header_doc,self._header_machine)+tuple(setups),
            verify_retained_binding=binding,max_native_calls=1500,**kwargs)
    def read(self,obj,name,*args):
        try:
            require(type(name) is str and name in HEADER_READ_MEMBERS,'Getter outside bounded header scope')
            if name=='Item':
                require(len(args)==1 and type(args[0]) is int and 0<=args[0]<=64,'Bounded collection index required')
            elif name=='GetCWObjectFromID':
                require(len(args)==2 and type(args[0]) is int and args[0]==1
                    and type(args[1]) is int and 0<args[1]<2**32,'Exact feature lookup required')
            elif name=='GetCWObjectID':
                require(len(args)==1 and id(args[0]) in self._known_objects,'Retained object ID lookup required')
            elif name in ('GetEMFFeatTypeOptions','GetEMFPartPeriTypeOptions','GetEMFTypeOptions'):
                limit={'GetEMFFeatTypeOptions':6,'GetEMFPartPeriTypeOptions':2,'GetEMFTypeOptions':4}[name]
                require(len(args)==1 and type(args[0]) is int and 0<=args[0]<limit,'Bounded option index required')
            else:require(not args,'Header getter takes no arguments')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(type(name) is str and name in HEADER_READ_INTERFACES,'Interface outside bounded header scope')
            return self._observe_read(obj,'qi',lambda:_typed(obj,name,self.typelib_path))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def summary(self):
        result=super().summary()
        result.update(scope='BOUNDED_UPPER_CONE_HEADER_READ_BATCH_V1',retained_setup_binding_checks=self._binding_checks,
            retained_setup_binding_native_calls=self._binding_reads,original_route_qualification_extended=False,
            header_native_equivalence_verified=False)
        return result


def _capture_headers(ctx,clsid,reference,count,diagnostic):
    """Same complete19/20 header state, with strong global checks around a read batch."""
    require(type(count) is int and count in (19,20) and len(reference['features'])==19,
        'Upper branch pre/post inventory required')
    started=perf_counter();diagnostic.update(header_read_mode='bounded_header_batch',capture_complete=False)
    state=native=batch=None
    try:
        ctx.files();ctx.events();doc=ctx.identity()
        before_started=perf_counter()
        with ctx.guard() as g:
            try:
                state,native=_snapshot(ctx.sw,clsid,ctx.typelib_path,ctx.args['expected_document_path'],
                    check=g._fast,diagnostic=diagnostic,required_machine_type=1)
                diagnostic['header_state']=state
                diagnostic['capture_complete']=False
                require(state['document']==doc and sum(r['feature_count'] for r in state['feature_setups'])==count,
                    'Exact branch feature count required')
                state['stock'],_=_export_stock(g.read(native['machine'],'IGetWorkpiece'),ctx.typelib_path,g.read,diagnostic)
                require(state['stock']==reference['stock'],'Stock changed')
            finally:diagnostic['header_strong_before']=g.summary()
        diagnostic['header_strong_before_seconds']=perf_counter()-before_started
        batch=ScopedUpperHeaderReadBatch(ctx.sw,ctx.typelib_path,native_context=native,reference_state=state,
            process_id=ctx.args['process_id'],expected_document=ctx.identity(),source_sha256=ctx.args['expected_source_sha256'],
            evidence_pins=ctx.loaded['pins'],verify_evidence=ctx.files,verify_owned_process=ctx.owned,check_events=ctx.events)
        try:
            with batch:
                state['recognition_options'],state['recognition_method']=read_options(native['doc'],batch.read)
                state['features']=[];ids=set()
                for si,raw in enumerate(native['setups']):
                    setup=batch.typed(raw,'ICWBaseSetup');sid=_object_id(native['doc'],setup,batch.read)
                    require(sid==state['feature_setups'][si]['native_id'],'Setup ID differs')
                    values=_items(batch.read(setup,'IGetEnumFeatures'),batch.typed,batch.read,count)
                    require(len(values)==state['feature_setups'][si]['feature_count'],'Feature count changed')
                    for fi,value in enumerate(values):
                        header,_=read_header(value,native['doc'],batch.read,batch.typed,sid)
                        state['features'].append(dict(setup_index=si,feature_index=fi,setup_native_id=sid,geometry=header))
                        require(header['native_id'] not in ids,'Duplicate feature ID');ids.add(header['native_id'])
                previous=reference['selected_profile_headers']
                selection=dict(feature_native_id=previous['native_id'],owner_setup_native_id=previous['owner_setup_native_id'],
                    volume_type=previous['volume_type'],shape=previous['shape'],island_count=previous['island_count'],include_contours=False)
                state['selected_profile_headers']=read_profile_feature_headers(native['doc'],selected=selection,
                    read=batch.read,typed=batch.typed,diagnostic=diagnostic.setdefault('header_profile',{}))
                read_route_operations(state,native,batch.read,batch.typed,diagnostic=diagnostic.setdefault('header_operations',{}))
            batch.require_complete()
        finally:diagnostic['header_read_batch']=deepcopy(batch.summary())
        after_started=perf_counter()
        with ctx.guard() as g:
            try:
                model=g.read(ctx.sw,'ActiveDoc');g._fast();tree,_=_features(model);g._fast();solids=_bodies(model);g._fast()
                state['sw_reference']=dict(feature_tree=tree,solids=solids)
                visible=g.read(model,'GetBodies2',0,True)
                require(visible is None or (type(visible) in (list,tuple) and len(visible)<=64),'Bounded visible body collection required')
                state.update(visible_solid_body_count=0 if visible is None else len(visible),all_solid_body_count=len(solids))
                final,_=_snapshot(ctx.sw,clsid,ctx.typelib_path,ctx.args['expected_document_path'],check=g._fast,required_machine_type=1)
                diagnostic['header_final_snapshot']=deepcopy(final)
                require(all(state[key]==value for key,value in final.items()),'Native machine/header changed during capture')
            finally:diagnostic['header_strong_after']=g.summary()
        diagnostic['header_strong_after_seconds']=perf_counter()-after_started
        require(ctx.identity()==doc,'Document changed during header capture');ctx.files();ctx.events()
        diagnostic.update(capture_complete=True,expected_feature_count=count)
        return state,native
    finally:
        diagnostic['header_elapsed_seconds']=perf_counter()-started
        if state is not None:diagnostic['observed_state']=deepcopy(state)


def _capture_payload(ctx,state,native,diagnostic):
    """Reuse original rough/finish getters; inventory was freshly bounded above."""
    def units():
        with ctx.guard() as g:
            return read_document_cam_unit_scope(g.read(ctx.sw,'ActiveDoc'),ctx.app,sw_read=g.read,cam_read=g.read)
    metric=units();binding={k:native[k] for k in ('doc','machine','operations')}
    batch=ScopedFinishReadBatch(ctx.sw,ctx.typelib_path,native_context=binding,reference_state=state,
        process_id=ctx.args['process_id'],expected_document=ctx.identity(),source_sha256=ctx.args['expected_source_sha256'],
        evidence_pins=ctx.loaded['pins'],verify_evidence=ctx.files,verify_owned_process=ctx.owned,check_events=ctx.events,max_native_calls=1500)
    try:
        with batch:
            fresh,bound,levels,firstcut,entry=capture_assignment_snapshot(ctx.app,read=batch.read,typed=batch.typed,
                reference_state=state,current_document=state['document'],source_sha256=ctx.args['expected_source_sha256'],
                target_feature_native_id=ctx.args['target_feature_native_id'],target_operation_native_id=ctx.args['target_operation_native_id'],
                boundary=ctx.events,diagnostic=diagnostic,native_context=binding,feature_dispatch_reader=batch.feature_dispatch)
            require(fresh==state,'Operation summaries changed between header and payload reads')
            candidate=read_assignment_candidate(bound,ctx.app,ctx.sw,read=batch.read,typed=batch.typed,
                expected_candidate_tool_native_id=ctx.args['expected_candidate_tool_native_id'],reference=ctx.loaded['payload']['candidate'],
                observation_pin=ctx.loaded['observation_pin'],firstcut=firstcut,diagnostic={},metric_scope=metric)
            raw=bound['operations'][ctx.args['finish_operation_native_id']]
            generic,tool=read_generic_tool(raw,bound['doc'],batch.read,batch.typed)
            expected=[r for r in state['operations'] if r['native_id']==ctx.args['finish_operation_native_id']]
            require(len(expected)==1 and generic==expected[0]['assigned_tool'],'Finish tool assignment changed')
            found=batch.read(bound['doc'],'GetCWObjectFromID',1,ctx.args['target_feature_native_id'])
            require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Protected feature lookup failed')
            feature=batch.typed(found[0],'ICWFeature');require(_object_id(bound['doc'],feature,batch.read)==ctx.args['target_feature_native_id'],'Protected feature ID changed')
            def read_native(label,invoke,decoder=None,interface=False,validator=None):
                value=batch.feature_dispatch(feature) if label=='QueryInterface.IDispatch.feature' else invoke()
                if interface:require(value is not None and bool(value),'Non-null level interface required')
                if validator:validator(value)
                return decoder(value) if decoder else value
            def getter(obj,interface_name,name,*values,**kw):return read_native(interface_name+'.'+name,lambda:batch.read(obj,name,*values),**kw)
            finish_levels={};read_mill_level_values(feature,raw,native_read=read_native,typed=batch.typed,getter=getter,report=finish_levels)
            details=read_finish_details(raw,found[0],tool,read=batch.read,typed=batch.typed,diagnostic={})
            leads=read_lead_details(raw,found[0],read=batch.read,typed=batch.typed,lead_typed=batch.lead_interface)
            full=read_full_mill_tool(tool,generic=generic,read=batch.read,typed=batch.typed,diagnostic={})
        batch.require_complete();after_units=units();require(metric==after_units,'Units changed across payload batch')
        result=dict(rough=dict(candidate=candidate,levels=levels,entry=entry),
            finish=dict(details=details,levels=finish_levels,leads=leads,full_tool=full,unit_record=after_units))
        diagnostic['observed_payload']=deepcopy(result)
        require(result==dict(rough=ctx.loaded['payload'],finish=ctx.loaded['finish_payload']),'Protected completed rough/finish payload changed')
        diagnostic['full_parent_payload_matched']=True
        return result
    finally:diagnostic['read_batch']=deepcopy(batch.summary())


def _read_sketch_and_cone(ctx,native,spec,new_id=None):
    with ctx.guard() as g:
        model=g.read(ctx.sw,'ActiveDoc');feature=g.read(model,'FeatureByName',spec['sketch_name'])
        require(feature is not None,'Required circle sketch missing')
        sketch=g.read(feature,'GetSpecificFeature2');g._fast();measured=_read_sketch(ctx.sw,sketch,spec);g._fast()
        circle=_circle_sketch(measured,spec)
        if new_id is None:return dict(sketch=measured,sketch_circle_m=circle)
        found=g.read(native['doc'],'GetCWObjectFromID',1,new_id)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'New feature lookup failed')
        base=g.typed(found[0],'ICWFeature')
        require(_object_id(native['doc'],g.read(base,'GetOwner'),g.read)==69,'New feature owner differs')
        observed=_circle_feature(found[0],native['doc'],ctx.typelib_path,g.read,g.typed)
        mill=g.typed(found[0],'ICWMillFeature')
        observed['taper_enabled']=g.read(mill,'Taper');observed['taper_angle_readback']=g.read(mill,'IGetTaperAngle')
        return dict(sketch=measured,sketch_circle_m=circle,feature=observed)


def create_upper_cone_feature(sw,clsid,typelib_path,*,baseline_path,baseline_sha256,
        sketch_receipt_path,sketch_receipt_sha256,process_id,expected_document_path,expected_source_sha256,
        sketch_spec,taper_angle_native,taper_type,acknowledge_unqualified_taper,
        receipt_path,qualification_only,acknowledge_disposable_copy,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True and message_policy=='vendor_default','Explicit disposable qualification required')
    spec=validate_cone_request(sketch_spec=sketch_spec,taper_angle_native=taper_angle_native,taper_type=taper_type,acknowledge_unqualified_taper=acknowledge_unqualified_taper)
    loaded=load_upper_cone_baseline(baseline_path,baseline_sha256,process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    sketch_evidence,sketch_pin,expected=load_sketch_prerequisite(sketch_receipt_path,sketch_receipt_sha256,loaded,spec,process_id)
    loaded['pins']=canonical_evidence_pins(loaded['pins'],[sketch_pin])
    marker=cone_marker(expected_document_path,expected_source_sha256);receipt=Path(receipt_path)
    require(receipt.is_absolute() and receipt.suffix.casefold()=='.json' and receipt.parent.is_dir()
        and not receipt.exists() and not receipt.is_symlink() and not marker.exists() and not marker.is_symlink(),'Fresh receipt and unattempted upper region required')
    protected={_key(p['path']) for p in loaded['pins']}|{_key(expected_document_path)}
    require(_key(receipt) not in protected and _key(marker) not in protected and _key(marker)!=_key(receipt),'Output/evidence/source aliases')
    args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        baseline_pin=loaded['pin'],sketch_receipt_pin=sketch_pin,evidence_pins=deepcopy(loaded['pins']),
        receipt_path=str(receipt),marker_path=str(marker),requested_taper=dict(value=taper_angle_native,type=taper_type,units_reference_sign_qualified=False),
        mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,
        creator_call_count=0,GOP_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,
        sketch_edit_attempted=False,CAD_solid_edit_attempted=False,automatic_retry=False,automatic_replay=False,
        automatic_rollback=False,readback_verified=False,production_qualified=False,may_generate=False,snapshot_diagnostics=[])
    created=claimed=False;session=ctx=None
    def persist():
        if created:_write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event/transport requires stop')
    def capture(phase,count):
        report['phase']=phase;diagnostic=dict(phase=phase);report['snapshot_diagnostics'].append(diagnostic);persist()
        state,native=_capture_headers(ctx,clsid,expected,count,diagnostic)
        diagnostic['observed_state']=deepcopy(state);persist()
        try:payload=_capture_payload(ctx,state,native,diagnostic)
        finally:persist()
        return state,native,payload
    def pending():
        nonlocal claimed
        require(not report['creator_call_count'],'No second creator call')
        report.update(phase='CreateMillFeature2',mutation_attempted=True,native_call_attempted=True,native_dispatch_pending=True,creator_call_count=1)
        _write_receipt(marker,dict(scope=SCOPE,status='dispatch_pending',source=expected_document_path,source_sha256=expected_source_sha256,receipt_path=str(receipt),automatic_replay=False),create=True)
        claimed=True;persist()
    try:
        _write_receipt(receipt,report,create=True);created=True
        ctx=UpperConeContext(loaded,args,sw,typelib_path,None,events,expected);ctx.files();ctx.identity()
        ctx.app=_bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity();session=CamMessageSession(ctx.app,typelib_path)
        with session:
            before,native,before_payload=capture('before',19)
            report['before']=before;report['before_payload']=before_payload;persist()
            require_state_equivalent(expected,before,diagnostic=report.setdefault('precreate_state_comparison',{}))
            report['sketch_before']=_read_sketch_and_cone(ctx,native,spec);persist()
            owners=[i for i,row in enumerate(before['feature_setups']) if row['native_id']==69]
            require(len(owners)==1 and before['feature_setups'][owners[0]]['axis_native']==[0.,0.,-1.],'Exact existing negativeZ owner69 required')
            with ctx.guard() as g:
                setup=g.typed(native['setups'][owners[0]],'ICWSetup')
                require(_object_id(native['doc'],setup,g.read)==69,'Creator owner changed')
                value=g.dispatch_once(lambda:_member(setup,'CreateMillFeature2',0,spec['sketch_name'],False,0.2,
                    False,False,False,False,float(taper_angle_native),taper_type,False,0,0),persist_pending=pending)
                report.update(native_call_returned=True,native_dispatch_pending=False);persist()
            report['dispatch_guard']=g.summary();_nonnull(value,'CreateMillFeature2 return')
            require(_is_comtypes_pointer(value),'CreateMillFeature2 must return typed IDispatch, not a scalar HRESULT')
            with ctx.guard() as g:new_id=_object_id(native['doc'],value,g.read)
            report['new_feature_native_id']=new_id;persist()
            after,native,after_payload=capture('after',20)
            report['after']=after;report['after_payload']=after_payload
            report['new_feature']=verify_feature_delta(before,after,new_id,69,diagnostic=report.setdefault('postcreate_state_comparison',{}))
            observation=_read_sketch_and_cone(ctx,native,spec,new_id);report['cone_observation']=observation;persist()
            report['geometry_acceptance']=verify_cone_geometry(observation['feature'],observation['sketch_circle_m'],new_id,expected_taper_angle_native=float(taper_angle_native))
            require(before_payload==after_payload,'Protected payload changed')
        events(False);ctx.files();require(ctx.identity()==after['document'],'Document changed during cleanup')
        report.update(status='review_required',phase='finished',readback_verified=True,feature_delta_verified=True,
            native_configuration_captured=True,geometric_end_conditions_verified=False,
            coordinate_frame_qualified=False,geometric_depth_verified=False,source_after_sha256=_file_hash(expected_document_path),
            reason='ONE_UNSAVED_TAPERED_FEATURE_CONFIGURATION_ONLY_PHYSICAL_DEPTH_FRAME_UNVERIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:
            persist()
            if claimed:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],source=expected_document_path,
                source_sha256=expected_source_sha256,receipt_path=str(receipt),receipt_sha256=_file_hash(receipt),
                native_call_attempted=report['native_call_attempted'],native_call_returned=report['native_call_returned'],
                readback_verified=report['readback_verified'],automatic_replay=False))
        except Exception as exc:report.update(status='uncertain',readback_verified=False,receipt_write_error=_error(exc))
    return report
