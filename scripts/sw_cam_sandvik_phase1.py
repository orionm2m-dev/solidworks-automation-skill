"""One bounded configured UD cutter observation; no assignment, paths or save."""
from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
import hashlib
import math
import time

from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _items
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_ud14_qualification import read_ud14_tool, capture_local_tools
from scripts.sw_cam_ud14_probe_core import verify_one_new_tool
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains
from scripts.sw_cam_shared_holder_geometry import read_holder_recipe, verify_holder_profile
from scripts.sw_cam_sandvik_mt import load_candidate_contract, render_candidate_mt, write_candidate_mt, validate_native_profiles
from scripts.sw_cam_stock_mesh_compare import (
    _read_pinned, _decode, _mesh, _sub, _cross, _dot, _connected,
    MAX_TRIANGLES, MAX_VERTICES)
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target

SCOPE = "SANDVIK_UD14_NUMERIC_PORTIONS_V1"
BINDING_KEYS = ("process_id","expected_document_path","expected_source_sha256",
    "expected_feature_native_id","expected_operation_native_ids",
    "expected_operation_setup_native_id","expected_tool_native_id")
FIELDS = (("OverallLength",63),("ShankDia",8),("CutDiameter",8),("CutLength",19),
          ("Flutes",4),("TipOffset",0),("TipLength",0),("MillUDToolOutputType",1),("Protrusion",25))
INTEGER_FIELDS = {"Flutes","MillUDToolOutputType"}
RAW_TOLERANCE = 0.0001
MAX_READS = 12000

def field_equal(name, actual, expected):
    if name in INTEGER_FIELDS:
        return type(actual) is int and actual == expected
    return type(actual) in (int,float) and math.isfinite(actual) and abs(actual-expected) <= 1e-9

def apply_ud_fields(*, targets, read, dispatch, report, persist, read_scope=nullcontext):
    """One coherent ordered property batch, stopping on any unexpected coupling."""
    def values():
        return {key:read(targets["tool" if key in ("CutDiameter","Protrusion") else "ud"],key)
                for key,_ in FIELDS}
    with read_scope():current=values()
    for key,value in current.items():
        if not field_equal(key,value,value):raise ValueError("Invalid initial field: "+key)
    wanted=dict(FIELDS)
    for key,value in FIELDS:
        obj=targets["tool" if key in ("CutDiameter","Protrusion") else "ud"]
        with read_scope():actual=read(obj,key)
        if not field_equal(key,actual,current[key]):raise ValueError("Field changed before setter: "+key)
        row=dict(property=key,before=actual,requested=value,setter_attempted=False)
        report["field_attempts"].append(row)
        if not field_equal(key,actual,value):
            row["setter_attempted"]=True
            dispatch("property:"+key,lambda obj=obj,key=key,value=value:setattr(obj,key,value))
        with read_scope():
            immediate=read(obj,key);row["immediate"]=immediate
            if not field_equal(key,immediate,value):raise ValueError("Setter readback differs: "+key)
            observed=values()
        for other,result in observed.items():
            if not (field_equal(other,result,current[other]) or field_equal(other,result,wanted[other])):
                raise ValueError("Unexpected coupled field: "+other)
        if not field_equal(key,observed[key],value):raise ValueError("Field changed during readback")
        row.update(readback_verified=True,after=deepcopy(observed))
        current=observed;persist()
    if not all(field_equal(key,current[key],value) for key,value in FIELDS):
        raise ValueError("Incomplete coherent field batch")
    return current

def attempt_marker(path, source_sha, candidate_sha):
    source=Path(path).resolve()
    key=_digest(dict(scope=SCOPE,action="create_configure_export",document=str(source).casefold(),
                     source_sha256=source_sha,candidate_sha256=candidate_sha))
    return source.parent/("sandvik_ud14_attempt_"+key+".json")

def fresh_output(path,suffix,blocked):
    p=Path(path)
    if (not p.is_absolute() or p.suffix.casefold()!=suffix or not p.parent.is_dir()
        or p.exists() or p.is_symlink() or p.resolve() in blocked):
        raise ValueError("Fresh distinct absolute output required: "+str(path))
    return p

def noncutting_mesh_health(triangles):
    """Bounded closed oriented manifold topology; no stock or genus assumption.

    Components, Euler characteristics and signed volumes are observations.
    No disjointness, nesting, self-intersection or material-union proof is made.
    """
    if type(triangles) is not list or not 1 <= len(triangles) <= MAX_TRIANGLES:
        raise ValueError("Bounded nonempty noncutting triangle collection required")
    vertices=[];lookup={};faces=[];edges=defaultdict(list);links=defaultdict(list)
    canonical=Counter()
    for fi,triangle in enumerate(triangles):
        if (type(triangle) not in (tuple,list) or len(triangle)!=3
            or any(type(p) not in (tuple,list) or len(p)!=3 for p in triangle)
            or any(type(v) not in (int,float) or not math.isfinite(v) for p in triangle for v in p)):
            raise ValueError("Finite three-point noncutting triangle required")
        triangle=tuple(tuple(p) for p in triangle)
        key=tuple(sorted(triangle));canonical[key]+=1
        if canonical[key]!=1 or len(set(triangle))!=3:
            raise ValueError("Duplicate or degenerate noncutting triangle")
        normal=_cross(_sub(triangle[1],triangle[0]),_sub(triangle[2],triangle[0]))
        area2=math.sqrt(_dot(normal,normal))
        if not math.isfinite(area2) or area2<=0:
            raise ValueError("Zero-area noncutting triangle")
        ids=[]
        for point in triangle:
            if point not in lookup:
                if len(vertices)>=MAX_VERTICES:raise ValueError("Noncutting vertex budget exceeded")
                lookup[point]=len(vertices);vertices.append(point)
            ids.append(lookup[point])
        face=tuple(ids);faces.append(face)
        for a,b in zip(face,face[1:]+face[:1]):edges[tuple(sorted((a,b)))].append((fi,a,b))
        for i,v in enumerate(face):links[v].append((face[(i+1)%3],face[(i+2)%3]))
    adjacency=defaultdict(set)
    for incidents in edges.values():
        if (len(incidents)!=2 or incidents[0][1]!=incidents[1][2]
            or incidents[0][2]!=incidents[1][1]):
            raise ValueError("Noncutting mesh is not a closed consistently oriented edge manifold")
        a,b=incidents[0][0],incidents[1][0];adjacency[a].add(b);adjacency[b].add(a)
    for segments in links.values():
        graph=defaultdict(set)
        for a,b in segments:graph[a].add(b);graph[b].add(a)
        if (any(len(v)!=2 for v in graph.values())
            or len(_connected(graph,next(iter(graph))))!=len(graph)):
            raise ValueError("Noncutting vertex link is not one manifold cycle")
    components=[];unseen=set(range(len(faces)))
    while unseen:
        if len(components)>=64:raise ValueError("Noncutting component budget exceeded")
        indexes=_connected(adjacency,min(unseen));unseen.difference_update(indexes)
        component_vertices={v for i in indexes for v in faces[i]}
        component_edges={tuple(sorted((a,b))) for i in indexes
                         for a,b in zip(faces[i],faces[i][1:]+faces[i][:1])}
        center=tuple(math.fsum(vertices[v][axis] for v in component_vertices)/len(component_vertices)
                     for axis in range(3))
        volume=math.fsum(_dot(_sub(vertices[a],center),
            _cross(_sub(vertices[b],center),_sub(vertices[c],center)))
            for i in indexes for a,b,c in [faces[i]])/6.
        if not math.isfinite(volume):raise ValueError("Non-finite noncutting signed volume")
        points=[vertices[v] for v in component_vertices]
        bounds=[min(p[j] for p in points) for j in range(3)]+[max(p[j] for p in points) for j in range(3)]
        components.append(dict(triangles=len(indexes),vertices=len(component_vertices),
            edges=len(component_edges),Euler_characteristic=len(component_vertices)-len(component_edges)+len(indexes),
            bounds_native=bounds,signed_volume_native_cubed=volume))
    bounds=[min(p[j] for p in vertices) for j in range(3)]+[max(p[j] for p in vertices) for j in range(3)]
    facts=dict(triangles=len(faces),vertices=len(vertices),edges=len(edges),
        bounds_native=bounds,signed_volume_native_cubed=math.fsum(c["signed_volume_native_cubed"] for c in components),
        component_count=len(components),components=components,
        Euler_characteristic=len(vertices)-len(edges)+len(faces),
        closed_consistently_oriented_edge_manifold=True,vertex_links_single_cycles=True,
        single_component_required=False,genus_restricted=False,volume_sign_is_acceptance_criterion=False,
        self_intersections_checked=False,component_disjointness_verified=False,
        component_nesting_verified=False,material_union_verified=False,
        limits=["Topology health does not establish self-intersection freedom, shell disjointness, nesting or a material union.",
                "Signed shell volumes are observations, not confirmation of material volume or outward physical orientation.",
                "Stored coordinates are inspected without scaling, alignment, repair or a claim of physical units."])
    return dict(vertices=vertices,facts=facts)


def numeric_mesh_observation(path, portion):
    """Strict mesh health; noncutting contents are not specified by the SDK."""
    if portion not in ("cutting","noncutting"):raise ValueError("Exact classified portion required")
    raw,pin=_read_pinned(path);triangles,encoding=_decode(raw)
    mesh=_mesh(triangles) if portion=="cutting" else noncutting_mesh_health(triangles)
    vertices=mesh["vertices"];z0,z1=(0.,19.) if portion=="cutting" else (19.,63.)
    lo=min(v[2] for v in vertices);hi=max(v[2] for v in vertices)
    incompatibilities=[]
    if abs(lo-z0)>RAW_TOLERANCE or abs(hi-z1)>RAW_TOLERANCE:
        incompatibilities.append("axial_extent_differs_from_expected_numeric_envelope")
    max_radius=0.;outside=False
    for x,y,z in vertices:
        r=math.hypot(x,y);max_radius=max(max_radius,r)
        allowed=min(4.,3.8+z) if portion=="cutting" else min(4.,66.4-z)
        if r>allowed+RAW_TOLERANCE:outside=True
    if outside:incompatibilities.append("vertices_outside_expected_numeric_envelope")
    if abs(max_radius-4.)>RAW_TOLERANCE:
        incompatibilities.append("maximum_radius_differs_from_expected_numeric_envelope")
    # The cutting portion retains its existing bounded numeric rejection.
    # The SDK does not define whether the noncutting STL also includes the holder.
    # A healthy unexpected noncutting shape is evidence for later comparison, not
    # a failed tool, an accepted assembly envelope, or permission to generate.
    if portion=="cutting" and incompatibilities:
        raise ValueError("Cutting mesh differs from bounded nominal envelope: "+",".join(incompatibilities))
    facts=mesh["facts"]
    result=dict(pin=pin,encoding=encoding,portion=portion,mesh_health_verified=True,
        bounds_native=facts["bounds_world_mm"] if portion=="cutting" else facts["bounds_native"],
        signed_volume_native_cubed=facts["signed_volume_mm3"] if portion=="cutting" else facts["signed_volume_native_cubed"],
        triangles=facts["triangles"],vertices=facts["vertices"],maximum_radius_native=max_radius,
        axial_extent_native=[lo,hi],raw_tolerance=RAW_TOLERANCE,
        tolerance_is_manufacturing_tolerance=False,fixed_frame_no_alignment_or_scaling=True,
        outer_bound_compatible=not incompatibilities,envelope_observation_issues=incompatibilities,
        classification_pending=True,filled_rotational_coverage_verified=False,
        cutting_partition_verified=False,units_verified=False,physical_tool_qualified=False,
        reason="Closed mesh and numeric bounds only; full rotational coverage requires independent geometric proof.")
    if portion=="noncutting":
        result.update(topology_health_verified=True,topology_observation=facts,
            expected_shank_envelope_compatible=not incompatibilities,
            expected_shank_numeric_scope=dict(axial_extent=[19.,63.],maximum_radius=4.),
            native_noncutting_contents_status="SDK_UNSPECIFIED_SHANK_OR_SHANK_PLUS_HOLDER",
            holder_inclusion_verified=False,
            reason="Closed oriented manifold topology observed; self-intersection and shell relationships are unverified. SDK does not define noncutting export contents. Compare raw mesh with shank and shank-plus-holder without scaling or reframing.")
    return result

def holder_objects(crib, doc, read, typed):
    rows={}
    for raw in _items(read(crib,"GetAllTools"),typed,read,128):
        tool=typed(raw,"ICWTool");tid=_object_id(doc,tool,read)
        holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
        if holder is None:raise ValueError("Existing holder interface missing")
        rows[tid]=holder
    return rows

def com_identity(obj, read=None):
    from ctypes import cast, c_void_p
    from comtypes import IUnknown
    pointer = obj.QueryInterface(IUnknown) if read is None else read(obj,"QueryInterface",IUnknown)
    return cast(pointer,c_void_p).value

def reject_holder_alias(holder, old_holders, identity=com_identity):
    current=identity(holder)
    if not current or any(current==identity(old) for old in old_holders.values()):
        raise ValueError("New holder aliases an existing tool holder")
    return True

def qualify_sandvik_ud14(sw,clsid,typelib_path,*,candidate_contract_path,candidate_contract_sha256,
        source_cad_path,source_cad_sha256,reference_mt_path,reference_mt_sha256,
        profile_analysis_path,profile_analysis_sha256,candidate_mt_path,holder_file_path,holder_file_sha256,
        holder_recipe_path,holder_recipe_sha256,cutting_stl_path,noncutting_stl_path,
        expected_sw_document_units_raw,expected_cam_use_document_units,acknowledge_experimental,
        firstcut_receipt_path,firstcut_receipt_sha256,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status="error",phase="preflight",process_id=args.get("process_id"),
        mutation_attempted=False,native_dispatch_pending=False,new_tool_native_id=None,
        operation_assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,
        simulation_attempted=False,model_saved=False,save_attempted=False,TechDB_write_attempted=False,
        automatic_replay=False,automatic_rollback=False,units_verified=False,physical_tool_qualified=False,
        cutting_partition_verified=False,production_qualified=False,may_continue=False,
        numeric_profile_verified=False,holder_profile_verified=False,exports_verified=False,
        protected_context_unchanged=False,exact_one_tool_created=False,post_cleanup_CAM_getters=False,
        field_attempts=[],dispatches=[],snapshot_diagnostics=[],native_read_count=0,guard_diagnostics=[])
    anchor=receipt=marker=session=None;created=claimed=False;baseline=None;started=time.monotonic()
    def persist():
        report["elapsed_seconds"]=time.monotonic()-started
        if created:
            if claimed:
                _write_receipt(marker,dict(scope=SCOPE,phase=report["phase"],status=report["status"],
                    receipt_path=str(receipt),document=args["expected_document_path"],
                    source_sha256=args["expected_source_sha256"],candidate_sha256=report["candidate_asset"]["sha256"],
                    native_dispatch_pending=report["native_dispatch_pending"],
                    new_tool_native_id=report["new_tool_native_id"],dispatches=report["dispatches"],automatic_replay=False))
            _write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report["messages"]=value
        if (value.get("subscribed") is not True or value.get("active") is not active
            or (not active and value.get("disconnected") is not True)
            or any(value.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count",
                                         "subscription_error","disconnect_errors"))):
            raise ValueError("CAM event or transport requires stop")
    def identity():
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid!=args["process_id"]:raise ValueError("Exact process changed")
        anchor.check_runtime_identity();doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=args["expected_document_path"],required=True)
        if _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:
            raise ValueError("Saved source changed")
        if baseline is not None and doc!=dict(baseline,needs_save=doc["needs_save"]):
            raise ValueError("Active document identity changed")
        return doc
    def verify_files():
        anchor.check_files()
        for p in pins:
            if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Pinned candidate or holder changed")
    @contextmanager
    def guard():
        with ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
                expected_document=identity(),source_sha256=args["expected_source_sha256"],
                evidence_pins=anchor.pins+pins,verify_evidence=verify_files,
                verify_owned_process=anchor.check_runtime_identity,check_events=events) as g:
            try:yield g
            finally:report["guard_diagnostics"].append(g.summary())
    active_guard=None
    @contextmanager
    def reads():
        nonlocal active_guard
        if active_guard is not None:raise ValueError("Nested native read scope")
        with guard() as g:
            active_guard=g
            try:yield
            finally:active_guard=None
    def read(obj,name,*values):
        if active_guard is None:raise ValueError("Native getter outside bounded read scope")
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Read budget exceeded")
        return active_guard.read(obj,name,*values)
    def typed(obj,name):
        if active_guard is None:raise ValueError("Interface query outside bounded read scope")
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Read budget exceeded")
        return active_guard.typed(obj,name)
    def dispatch(label,invoke):
        nonlocal claimed
        if active_guard is not None:raise ValueError("Mutation in read-only scope")
        entry=dict(label=label,pending=True,attempted=False,returned=False)
        report["dispatches"].append(entry);report.update(phase=label,native_dispatch_pending=True,mutation_attempted=True)
        def pending():
            nonlocal claimed
            if not claimed:
                _write_receipt(marker,dict(scope=SCOPE,status="dispatch_pending",receipt_path=str(receipt),
                    document=args["expected_document_path"],source_sha256=args["expected_source_sha256"],
                    candidate_sha256=report["candidate_asset"]["sha256"],automatic_replay=False),create=True)
                claimed=True
            entry["attempted"]=True;persist()
        with guard() as g:result=g.dispatch_once(invoke,persist_pending=pending)
        entry.update(returned=True,pending=False,return_type=type(result).__name__,
            return_value=result if type(result) in (int,float,bool,str,type(None)) else None)
        report["native_dispatch_pending"]=False;persist()
        return result
    def getter(obj,name,*values):
        if active_guard is not None:return read(obj,name,*values)
        with reads():return read(obj,name,*values)
    def details(state,native,read,typed,diag,boundary):
        read_selected_operation_tool_details(state,native,read,typed,diag,
            feature_native_id=args["expected_feature_native_id"],boundary=boundary)
        source=anchor.data["request"]
        for mode in ("three_step_profile","strategy"):
            read_compound_strategy(state,native,read,typed,diag.setdefault(mode,{}),
                feature_id=source["reference_feature_native_id"],owner_id=source["owner_setup_native_id"],
                step_count=3,expected_header=anchor.profile["header"],boundary=boundary,observation=mode)
        verify_protected_details(anchor,state,diag)
        for key in ("three_step_profile","strategy"):
            if diag[key]!=anchor.data["saved_details"][key]:raise ValueError("Protected compound changed")
    def capture(phase,full=False):
        report["phase"]=phase;diag=dict(phase=phase);report["snapshot_diagnostics"].append(diag);persist()
        state,native=capture_selected_plan(sw,clsid,typelib_path,args["expected_document_path"],
            process_id=args["process_id"],expected_source_sha256=args["expected_source_sha256"],
            evidence=anchor,check=events,diagnostic=diag,progress=persist,
            operation_details_reader=details if full else None)
        expected=deepcopy(state);expected["document"]["needs_save"]=anchor.state["document"]["needs_save"]
        anchor.verify(expected);report[phase]=state;persist()
        return state,native
    try:
        validate_inventory_request(**{k:args[k] for k in ("process_id","expected_document_path",
            "expected_source_sha256","qualification_only","acknowledge_disposable_copy","receipt_path","message_policy")})
        if acknowledge_experimental is not True:raise ValueError("Explicit experimental qualification required")
        if (type(expected_sw_document_units_raw) is not list or len(expected_sw_document_units_raw)!=5
            or any(type(v) is not int for v in expected_sw_document_units_raw)
            or expected_sw_document_units_raw[0]!=0 or expected_cam_use_document_units is not True):
            raise ValueError("Explicit metric document scope required")
        anchor=load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],args["saved_plan_receipt_sha256"],
            **{k:args[k] for k in BINDING_KEYS})
        if anchor.data.get("scope")!="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1":
            raise ValueError("Saved additive upper-pocket plan required")
        if len(anchor.state["features"])!=19 or len(anchor.state["operations"])!=6:
            raise ValueError("Exact nineteen-feature six-operation scope required")
        if any(o["toolpath_generated"] is not False or o["toolpath_record_counts"]!=[] for o in anchor.state["operations"]):
            raise ValueError("Only definitions without existing toolpaths supported")
        from scripts.sw_cam_rough_firstcut import load_firstcut_receipt, read_firstcut_settings
        rough=[o for o in anchor.data["new_operations"] if o["mill_operation_type"]==0]
        if len(rough)!=1:raise ValueError("One exact added rough operation required")
        rough_id=rough[0]["native_id"]
        firstcut=load_firstcut_receipt(firstcut_receipt_path,firstcut_receipt_sha256,
            process_id=args["process_id"],expected_document_path=args["expected_document_path"],
            expected_source_sha256=args["expected_source_sha256"],
            target_feature_native_id=anchor.data["new_feature_native_id"],
            target_operation_native_id=rough_id,target_operation_setup_native_id=rough[0]["setup_native_id"])
        firstcut_pin=dict(path=firstcut_receipt_path,sha256=firstcut_receipt_sha256)
        candidate=load_candidate_contract(candidate_contract_path,candidate_contract_sha256,source_cad_path,
            source_cad_sha256,reference_mt_path,reference_mt_sha256,profile_analysis_path,profile_analysis_sha256)
        holder=read_holder_recipe(holder_file_path,holder_file_sha256,holder_recipe_path,holder_recipe_sha256)
        if (len(holder["records"])!=17 or sum(r["kind"]=="arc" for r in holder["records"])!=3
            or holder_file_sha256!="f6a30a764a148467e06c674b6492672da76656060156222a97183cd4444a2157"):
            raise ValueError("Exact pinned C40-M08EM2 holder required")
        immutable={Path(p["path"]).resolve() for p in anchor.pins+candidate["pins"]+holder["pins"]+[firstcut_pin]}
        immutable.add(Path(args["expected_document_path"]).resolve())
        outputs=[fresh_output(p,suffix,immutable) for p,suffix in ((candidate_mt_path,".mt"),
            (cutting_stl_path,".stl"),(noncutting_stl_path,".stl"),(args["receipt_path"],".json"))]
        if len({p.resolve() for p in outputs})!=4:raise ValueError("Outputs must be distinct")
        digest=hashlib.sha256(render_candidate_mt(candidate)).hexdigest()
        marker=attempt_marker(args["expected_document_path"],args["expected_source_sha256"],digest)
        if marker.exists() or marker.is_symlink() or marker.resolve() in immutable|{p.resolve() for p in outputs}:
            raise ValueError("Existing attempt marker or output collision; no replay")
        receipt=outputs[-1];_write_receipt(receipt,report,create=True);created=True
        baseline=identity()
        if baseline!=firstcut["after_document"]:raise ValueError("Current document differs from verified firstcut checkpoint")
        report["candidate_asset"]=write_candidate_mt(candidate,candidate_mt_path,acknowledge_experimental=True)
        report["candidate_contract"]=candidate;report["holder_recipe"]=holder;report["anchor"]=anchor.summary()
        report["dispatch_marker_path"]=str(marker)
        report["expected_document_path"]=args["expected_document_path"]
        report["expected_source_sha256"]=args["expected_source_sha256"]
        report["before_document"]=deepcopy(baseline)
        report["source_before_sha256"]=args["expected_source_sha256"]
        report["request_binding"]={k:deepcopy(args[k]) for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
        report["request_binding"].update(firstcut_receipt_path=firstcut_receipt_path,firstcut_receipt_sha256=firstcut_receipt_sha256)
        pins=candidate["pins"]+holder["pins"]+[firstcut_pin,dict(path=candidate_mt_path,sha256=digest)]
        report["firstcut_anchor"]=dict(pin=firstcut_pin,after_settings=deepcopy(firstcut["after_settings"]))
        verify_files();app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"])
        if identity()!=baseline:raise ValueError("Identity changed acquiring CAM host")
        session=CamMessageSession(app,typelib_path)
        with session:
            before,native=capture("before")
            with reads():
                report["metric_scope"]=read_document_cam_unit_scope(sw.ActiveDoc,app,
                    sw_read=lambda o,n:read(o,n),cam_read=read)
                if (report["metric_scope"]["SW_document_units_raw"]!=expected_sw_document_units_raw
                    or report["metric_scope"]["CAM_use_document_units_raw"] is not True):
                    raise ValueError("Metric document scope differs")
                report["before_firstcut"]=read_firstcut_settings(native["operations"][rough_id],read,typed)
                if report["before_firstcut"]!=firstcut["after_settings"]:raise ValueError("Current firstcut settings differ")
                crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
                before_tools=capture_local_tools(crib,native["doc"],read,typed)
                old_holders=holder_objects(crib,native["doc"],read,typed)
            report["before_tools"]=before_tools;persist()
            raw=dispatch("AddNewTool3",lambda:_member(crib,"AddNewTool3",19))
            with reads():
                tool=typed(raw,"ICWTool");ud=typed(raw,"ICWMillUDTool")
                new_id=_object_id(native["doc"],tool,read);report["new_tool_native_id"]=new_id
                verify_one_new_tool(before_tools,capture_local_tools(crib,native["doc"],read,typed),new_id)
                if read(tool,"IsMillTool") is not True:raise ValueError("Created object is not MILL")
                new_holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
                reject_holder_alias(new_holder,old_holders,identity=lambda obj:com_identity(obj,read))
            persist()
            result=dispatch("SetToolName",lambda:_member(ud,"SetToolName",candidate_mt_path))
            if type(result) is not int or result!=0:raise ValueError("Unexpected MT load HRESULT")
            check_document_target(getter(ud,"GetToolName"),None,expected_path=candidate_mt_path,required=True)
            apply_ud_fields(targets=dict(tool=tool,ud=ud),read=getter,dispatch=dispatch,report=report,persist=persist,read_scope=reads)
            with reads():
                new_holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
                reject_holder_alias(new_holder,old_holders,identity=lambda obj:com_identity(obj,read))
            if str(Path(getter(new_holder,"GetName")).resolve()).casefold()==str(Path(holder_file_path).resolve()).casefold():
                raise ValueError("Unexpected preassigned holder; no replay")
            result=dispatch("SetFilePathForUserDefinedHolder",
                lambda:_member(new_holder,"SetFilePathForUserDefinedHolder",holder_file_path))
            if type(result) is not int or result!=0:raise ValueError("Unexpected holder setter HRESULT")
            check_document_target(getter(new_holder,"GetName"),None,expected_path=holder_file_path,required=True)
            with reads():
                observed=read_ud14_tool(tool,doc=native["doc"],read=read,typed=typed,diagnostic=report.setdefault("tool_diagnostic",{}))
                if not all(field_equal(k,observed["parameters"][k],v) for k,v in FIELDS):
                    raise ValueError("Final tool scalars differ")
                report["tool"]=observed;report["numeric_profile"]=validate_native_profiles(candidate,observed["profiles"])
                current_holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
                if com_identity(current_holder,read)!=com_identity(new_holder,read):
                    raise ValueError("Holder interface changed after assignment")
                hp={};read_segment_chains(current_holder,"GetHolderProfile",read=read,typed=typed,
                    diagnostic={"state":hp},budget=dict(curves=0,chains=0,islands=0))
                report["holder_profile"]=hp;report["holder_verification"]=verify_holder_profile(hp,holder,25)
            report.update(numeric_profile_verified=True,holder_profile_verified=True);persist()
            report["exports"]={}
            for portion,path,method in (("cutting",cutting_stl_path,"CreateSTLOfCuttingPortion"),
                                       ("noncutting",noncutting_stl_path,"CreateSTLOfNonCuttingPortion")):
                fresh_output(path,".stl",immutable)
                result=dispatch(method,lambda method=method,path=path:_member(tool,method,path))
                if type(result) is not int or result!=0:raise ValueError("Unexpected STL export HRESULT")
                report["exports"][portion]=numeric_mesh_observation(path,portion);persist()
            report["exports_verified"]=True
            after,after_native=capture("after",full=True)
            with reads():
                report["after_firstcut"]=read_firstcut_settings(after_native["operations"][rough_id],read,typed)
                if report["after_firstcut"]!=report["before_firstcut"]:raise ValueError("Firstcut settings changed")
                after_tools=capture_local_tools(crib,native["doc"],read,typed)
                verify_one_new_tool(before_tools,after_tools,new_id)
                report["after_tools"]=after_tools
                if report["metric_scope"]!=read_document_cam_unit_scope(sw.ActiveDoc,app,
                        sw_read=lambda o,n:read(o,n),cam_read=read):raise ValueError("Metric scope changed")
                current_holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
                if com_identity(current_holder,read)!=com_identity(new_holder,read):
                    raise ValueError("Holder interface changed after classified exports")
                reject_holder_alias(current_holder,old_holders,identity=lambda obj:com_identity(obj,read))
                final_fields={k:read(tool if k in ("CutDiameter","Protrusion") else ud,k) for k,v in FIELDS}
                report["final_scalar_observation"]=final_fields
                if not all(field_equal(k,final_fields[k],v) for k,v in FIELDS):
                    raise ValueError("Candidate scalar changed after exports")
                check_document_target(read(ud,"GetToolName"),None,expected_path=candidate_mt_path,required=True)
                check_document_target(read(current_holder,"GetName"),None,expected_path=holder_file_path,required=True)
                if read(tool,"ToolType")!=14 or _object_id(native["doc"],tool,read)!=new_id:
                    raise ValueError("Candidate identity changed after exports")
            report.update(protected_context_unchanged=True,exact_one_tool_created=True)
        events(active=False);report["after_document"]=identity();verify_files()
        report.update(status="review_required",phase="finished",readback_verified=True,
            reason="NUMERIC_PROFILE_HOLDER_AND_MESH_EXPORTS_OBSERVED_FILLED_COVERAGE_AND_PHYSICAL_MM_PENDING")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(receipt_write_error=_error(exc),status="uncertain",readback_verified=False)
    return report

