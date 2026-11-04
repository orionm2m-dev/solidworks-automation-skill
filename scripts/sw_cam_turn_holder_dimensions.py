"""Bounded in-place dimensions for an existing TURN diamond boring-bar holder.

Only BoringBarDiameter, ShankLength and LeadAngle are writable. No tool rebinding,
creation, generation, Save or retry. Logical document/tool membership and owner/crib readback replace canonical holder equality.
"""
from copy import deepcopy
from pathlib import Path
import math
import os

from scripts import sw_cam_turn_tool as single
from scripts import sw_cam_turn_feature_regenerate as guard
from scripts import sw_cam_operation_profile as profile
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_toolcrib_diagnostic import read_tools
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import absolute_document_path

SCOPE = "TURN_DIAMOND_BORING_HOLDER_DIMENSIONS_V1"
FIELDS = frozenset({"BoringBarDiameter", "ShankLength", "LeadAngle"})
COMMON = ("ShankLength", "LeadAngle", "BackClearAngle", "FrontClearAngle", "ZInsertOffset", "XInsertOffset", "Protrusion")
require = guard.require


def validate(config, values, protected):
    for key in ("process_id", "expected_operation_native_id", "expected_tool_native_id"):
        require(type(config[key]) is int and 0 < config[key] < 2**32, "Strict native identity required: " + key)
    require(type(config["expected_holder_id"]) is int and 0 <= config["expected_holder_id"] < 2**31, "Exact holder catalogue ID required")
    single._reference({k:config[k] for k in ("setup_index", "operation_index", "expected_operation_type")})
    require(config["expected_operation_type"] in (5, 6), "Only TURN rough/finish bore operations supported")
    require(type(config["expected_process_create_time"]) in (int,float) and math.isfinite(config["expected_process_create_time"])
        and config["expected_process_create_time"] > 0, "Exact process lifetime required")
    require(type(config["expected_document_path"]) is str and absolute_document_path(config["expected_document_path"])
        and Path(config["expected_document_path"]).suffix.casefold() == ".sldprt" and guard.sha(config["expected_source_sha256"]), "Exact saved copy pin required")
    require(type(values) is dict and 1 <= len(values) <= 3 and set(values) <= FIELDS, "Only three documented holder dimensions supported")
    result = {}
    for field in sorted(values):
        value = profile._number(values[field])
        require(field == "LeadAngle" or value > 0, "Bar diameter and length must be positive")
        result[field] = value
    require(type(protected) is list and 1 <= len(protected) <= 16, "Protected original part pins required")
    for pin in protected:
        require(type(pin) is dict and set(pin) == {"path", "sha256"} and type(pin["path"]) is str
            and absolute_document_path(pin["path"]) and guard.sha(pin["sha256"]), "Exact protected pin required")
    require(len({guard.key(x["path"]) for x in protected}) == len(protected), "Duplicate protected paths")
    return result


def files(config, protected):
    target = Path(config["expected_document_path"])
    require(target.is_file() and not target.is_symlink() and _file_hash(target) == config["expected_source_sha256"], "Saved copy changed")
    stat = target.stat(); require(stat.st_ino != 0, "Stable copy file identity required")
    for pin in protected:
        path = Path(pin["path"])
        require(path.is_file() and not path.is_symlink() and guard.key(path) != guard.key(target)
            and not os.path.samefile(path,target), "Copy aliases protected source")
        require(_file_hash(path) == pin["sha256"], "Protected source changed")
    return dict(device=stat.st_dev,inode=stat.st_ino)


def _holder_dimensions(holder, kind, read):
    if kind not in (1,2):
        return dict(available=False,reason="unsupported_holder_kind")
    values = {k:profile._number(read(holder,k)) for k in COMMON}
    values["HolderShape"] = profile._integer(read(holder,"HolderShape"))
    values["GetHolderThickness"] = profile._number(read(holder,"GetHolderThickness"))
    field = "BoringBarDiameter" if kind == 2 else "ShankWidth"
    values[field] = profile._number(read(holder,field))
    return dict(available=True,dimensions_native=values)


def snapshot(sw, clsid, typelib, config, report, check, *, probe_identity=False):
    require(type(probe_identity) is bool, "Strict private identity policy required")
    selected = {k:config[k] for k in ("setup_index","operation_index","expected_operation_type")}
    diagnostic = {}; report["snapshot_diagnostics"].append(diagnostic)
    state,native = single._snapshot(sw,clsid,typelib,selected,check=check,diagnostics=diagnostic,guarded_readers=True)
    def read(obj,name,*args):
        check(); value = _member(obj,name,*args); check(); return value
    assignment = next(x for x in state["operation_tools"] if x["operation"] == selected)
    require(assignment["operation_native_id"] == config["expected_operation_native_id"]
        and assignment["tool_native_id"] == config["expected_tool_native_id"], "Selected own operation/tool IDs differ")
    tool = state["selected_tool"]
    require(tool.get("tool_type_raw") == 15 and tool.get("turn_tool_type_raw") == 1 and tool.get("insert_type_raw") == 1
        and tool.get("parameters_status") == "available", "Only existing TURN diamond insert supported")
    holder = _typed(read(native["turn_tool"],"IGetTurnToolHolder"),"ICWTurnToolHolder",typelib)
    holder_identity = single._identity(holder)
    require(profile._integer(read(holder,"GetHolderType")) == 2 and profile._integer(read(holder,"GetHolderId")) == config["expected_holder_id"], "Exact existing boring holder required")
    _,_,_,machine,_ = _context(sw,clsid,typelib,read)
    rows=[];holders={};identities={}
    diagnostic["holder_inventory_stage"] = "collecting_crib"
    diagnostic["holder_profile_observed"] = deepcopy(tool["holder"])
    diagnostic["holder_crib_rows"] = rows
    diagnostic["retained_own_holder_classification_verified"] = dict(
        holder_type_raw=2,holder_id_raw=config["expected_holder_id"])
    def typed(obj,name):
        result = _typed(obj,name,typelib)
        if name == "ICWTurnToolHolder":
            ident=rows[-1]["native_id"];holders[ident]=result;identities[ident]=single._identity(result)
        return result
    read_tools(machine,native["native_doc"],read=read,typed=typed,
        items=lambda raw,limit:_items(raw,typelib,read,limit=limit),rows=rows,publish=lambda:None)
    target = config["expected_tool_native_id"]
    # These groups are local comparison labels, never native IDs or storage proof.
    group_identities=[holder_identity];group_rows=[]
    for ident,canonical in sorted(identities.items()):
        group=next((i for i,value in enumerate(group_identities) if canonical == value),None)
        if group is None:
            group=len(group_identities);group_identities.append(canonical)
        group_rows.append(dict(tool_native_id=ident,canonical_identity_group=group))
    diagnostic["holder_identity_observation"] = dict(
        scope="canonical_IUnknown_equality_within_this_snapshot_only",
        selected_tool_native_id=target,own_retained_holder_identity_group=0,
        selected_crib_holder_present=target in holders,
        selected_crib_same_canonical_identity=(identities[target] == holder_identity) if target in identities else None,
        crib_holder_identity_groups=group_rows,
        all_com_references_retained_during_comparison=True,
        scalar_equality_proves_identity=False,storage_independence_verified=False)
    diagnostic["holder_inventory_stage"] = "canonical_identity_guards"
    require(target in holders, "Selected tool has no current crib holder")
    if not probe_identity:
        require(identities[target] == holder_identity, "Own holder differs from its current crib holder")
    if probe_identity:
        require(not any(i != target and v == identities[target] for i,v in identities.items()),
            "Selected crib holder COM object is shared by different tool IDs")
    aliases = sorted(i for i,v in identities.items() if v == holder_identity)
    require(not any(i != target for i in aliases), "Selected holder COM object is shared by different tool IDs")
    if not probe_identity:
        require(aliases == [target], "Selected holder COM object is shared by different tool IDs")
    catalogue_aliases=[]
    for row in rows:
        ident=row["native_id"]
        if ident in holders:
            row["observed_holder"] = _holder_dimensions(holders[ident],row["holder_type_raw"],read)
            if ident != target and (row["holder_type_raw"],row["holder_id_raw"]) == (2,config["expected_holder_id"]):
                catalogue_aliases.append(ident)
    require({x["cam_object_id"] for x in state["tool_groups"]} <= {x["native_id"] for x in rows}, "Assigned tool absent from current crib")
    own_row=next(x for x in rows if x["native_id"] == target)
    require(own_row.get("candidate") is True, "Selected crib row is not a diamond boring holder")
    require(own_row["insert_dimensions_native"] == state["selected_tool"]["dimensions_native"], "Own insert/crib dimensions differ")
    require(all(state["selected_tool"]["holder"]["dimensions_native"].get(k) == v
        for k,v in own_row["observed_holder"]["dimensions_native"].items() if k != "HolderShape"), "Own holder/crib dimensions differ")
    require(state["selected_tool"]["holder"]["shape_raw"] == own_row["observed_holder"]["dimensions_native"]["HolderShape"], "Own holder/crib shape differs")
    state["toolcrib"] = rows
    state["holder_alias_observation"] = dict(selected_same_com_tool_ids=aliases,
        equal_catalogue_other_tool_ids=sorted(catalogue_aliases),catalogue_alias_storage_independence_verified=False,
        excluded_tool_ids=[r["native_id"] for r in rows if r["native_id"] not in holders],all_holder_sharing_qualified=False)
    native.update(holder=holder,holder_identity=holder_identity,held_crib_holders=holders,held_crib_identities=identities)
    require(document_snapshot(sw) == state["document"], "Document changed during holder inventory")
    diagnostic["holder_inventory_stage"] = "complete"
    return state,native



def _logical_abi(typelib):
    """核对三项既有标量与只读文件字段的声明，不扩展写入白名单。"""
    from ctypes import HRESULT, POINTER, c_double, c_int
    from comtypes import BSTR
    from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
    interface=_interface_class('ICWTurnToolHolder',typelib)
    require(str(interface._iid_).upper()==_INTERFACES['ICWTurnToolHolder'],'Exact holder interface IID required')
    specs=[]
    for name,disp in [('ShankLength',13),('LeadAngle',14),('BoringBarDiameter',29)]:
        specs.extend([(name,disp,'propget',(POINTER(c_double),),(10,)),(name,disp,'propput',(c_double,),(1,))])
    specs.extend([('HolderShape',11,'propget',(POINTER(c_int),),(10,)),
        ('HolderShapeFilePath',25,'propget',(POINTER(BSTR),),(10,)),
        ('HolderShapeFileUnit',26,'propget',(POINTER(c_int),),(10,))])
    for name,disp,kind,args,flags in specs:
        ms=[m for m in interface._methods_ if m.name==('_get_' if kind=='propget' else '_set_')+name and kind in m.idlflags]
        require(len(ms)==1,'Unique declared holder field required: '+name);m=ms[0]
        require(m.restype is HRESULT and m.idlflags[0]==disp and m.argtypes==args and tuple(x[0] for x in m.paramflags)==flags,'Exact holder field ABI differs: '+name)
    return dict(interface='ICWTurnToolHolder',scalar_write_allowlist=sorted(FIELDS),file_getters_only=True,native_calls=0)


def _logical_snapshot(sw,clsid,typelib,config,report,check):
    """按文档原生 ID 重读全部自有刀具与刀库，保留原始 COM 相等性诊断。"""
    from scripts.sw_cam_turn_holder_stl import _holder_file
    state,native=snapshot(sw,clsid,typelib,config,report,check,probe_identity=True)
    diagnostic=report['snapshot_diagnostics'][-1]
    # 原始相等性仍在 diagnostic 中；不能把两次封送的指针作为字段写入资格。
    state['holder_alias_observation'].pop('selected_same_com_tool_ids',None)
    diagnostic['logical_state']=state;diagnostic['logical_capture_complete']=False
    def read(obj,name,*args):
        check();v=_member(obj,name,*args);check();return v
    _,doc,_,machine,_=_context(sw,clsid,typelib,read)
    doc=_typed(doc,'ICWDoc3',typelib)
    target=config['expected_tool_native_id'];selected=config['expected_operation_native_id']
    for row in state['toolcrib']:
        if row['native_id'] in native['held_crib_holders']:
            row['holder_file']={};_holder_file(native['held_crib_holders'][row['native_id']],read,row['holder_file'])
    own_rows=[];state['observed_operation_tools']=own_rows;target_rows=[];selected_seen=False
    for si,raw_setup in enumerate(_items(read(machine,'IGetEnumOpSetups'),typelib,read,limit=512)):
        setup=_typed(raw_setup,'ICWBaseOpSetup',typelib)
        for oi,raw_op in enumerate(_items(read(setup,'IGetEnumOperations'),typelib,read,limit=512-len(own_rows))):
            op=_typed(raw_op,'ICWOperation',typelib);oid=_object_id(doc,op,read)
            prior=[x for x in state['operation_tools'] if x['operation']['setup_index']==si and x['operation']['operation_index']==oi]
            require(len(prior)==1 and prior[0]['operation_native_id']==oid,'Repeated operation ID differs')
            linked=[_object_id(doc,f,read) for f in _items(read(op,'IGetAllFeatures'),typelib,read,limit=64)]
            require(len(linked)==len(set(linked)),'Duplicate linked feature IDs')
            raw_tool=read(op,'IGetTool');tool=_typed(raw_tool,'ICWTool',typelib);tid=_object_id(doc,tool,read)
            require(tid==prior[0]['tool_native_id'],'Repeated own-tool ID differs')
            observed={};row=dict(operation=deepcopy(prior[0]['operation']),operation_native_id=oid,tool_native_id=tid,linked_feature_ids=linked,observed_tool=observed)
            own_rows.append(row);profile._read_tool(raw_tool,op,typelib,read,observed,include_drill=True)
            hd=observed.get('holder',{})
            if observed.get('turn_tool_type_raw')==1 and hd.get('holder_type_raw') in (1,2):
                turn=_typed(raw_tool,'ICWTurnTool',typelib);holder=_typed(read(turn,'IGetTurnToolHolder'),'ICWTurnToolHolder',typelib)
                row['holder_file']={};_holder_file(holder,read,row['holder_file'])
            if tid==target:
                require(observed.get('tool_type_raw')==15 and observed.get('turn_tool_type_raw')==1 and observed.get('insert_type_raw')==1 and observed.get('parameters_status')=='available','Affected own tool is not a diamond insert')
                require(hd.get('holder_type_raw')==2 and hd.get('holder_id_raw')==config['expected_holder_id'],'Affected holder classification differs')
                require(observed['dimensions_native']==state['selected_tool']['dimensions_native'] and hd['dimensions_native']==state['selected_tool']['holder']['dimensions_native'],'Shared own/selected scalar readbacks disagree')
                require(hd['shape_raw']==state['selected_tool']['holder']['shape_raw'],'Shared own holder shape differs')
                target_rows.append(row)
                if oid==selected:
                    require(row['operation']==state['selected_operation'],'Selected operation reference differs')
                    native.update(native_doc=doc,operation=op,tool=tool,turn_tool=turn,holder=holder);selected_seen=True
    require(len(own_rows)==len(state['operation_tools']) and selected_seen,'Complete own-tool membership required')
    require(len({x['operation_native_id'] for x in own_rows})==len(own_rows),'Duplicate own operation identity')
    require(sorted((r['operation'] for r in target_rows),key=single._ref_key)==sorted(state['affected_operations'],key=single._ref_key),'Complete affected operation membership differs')
    crib=next(x for x in state['toolcrib'] if x['native_id']==target)
    require(all(r['holder_file']==crib['holder_file'] for r in target_rows),'Own/crib holder file fields disagree')
    selected_file=deepcopy(crib['holder_file']);state['selected_holder_file']=selected_file
    require(selected_file['shape_raw'] in (0,1),'Only standard or custom STL holder shape supported')
    if selected_file['shape_raw']==1:
        path=selected_file['path_raw']
        require(type(path) is str and absolute_document_path(path) and Path(path).suffix.casefold()=='.stl','Custom holder requires exact absolute STL path')
    require(document_snapshot(sw)==state['document'] and _inventory(machine,typelib,read)==state['inventory'],'Document or inventory changed during logical capture')
    diagnostic['logical_capture_complete']=True
    return state,native


def _verify_logical_changes(before,after,changes,tool_id):
    """只允许选中共享刀柄的请求标量变化；文件、形状、其他刀具字段保持一致。"""
    expected=deepcopy(before)
    require(type(after['document']['needs_save']) is bool,'Strict save flag required')
    expected['document']['needs_save']=after['document']['needs_save']
    expected['selected_tool']['info_raw']=after['selected_tool']['info_raw']
    row=next(x for x in expected['toolcrib'] if x['native_id']==tool_id)
    actual=next(x for x in after['toolcrib'] if x['native_id']==tool_id);row['info_raw']=actual['info_raw']
    for field,value in changes.items():
        expected['selected_tool']['holder']['dimensions_native'][field]=value
        row['holder_dimensions_native'][field]=value;row['observed_holder']['dimensions_native'][field]=value
    require(len(expected['observed_operation_tools'])==len(after['observed_operation_tools']),'Own-tool observation count changed')
    for a,b in zip(expected['observed_operation_tools'],after['observed_operation_tools']):
        if a['tool_native_id']==tool_id:
            a['observed_tool']['info_raw']=b['observed_tool']['info_raw']
            for field,value in changes.items():a['observed_tool']['holder']['dimensions_native'][field]=value
    require(expected==after,'Unexpected change outside requested holder scalars or derived target tool display')


def verify_changes(before, after, changes, tool_id):
    expected=deepcopy(before)
    require(type(after["document"]["needs_save"]) is bool, "Strict observed save flag required")
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    expected["selected_tool"]["info_raw"] = after["selected_tool"]["info_raw"]
    row=next(x for x in expected["toolcrib"] if x["native_id"] == tool_id)
    actual=next(x for x in after["toolcrib"] if x["native_id"] == tool_id)
    row["info_raw"] = actual["info_raw"]
    for field,value in changes.items():
        expected["selected_tool"]["holder"]["dimensions_native"][field] = value
        row["holder_dimensions_native"][field] = value
        row["observed_holder"]["dimensions_native"][field] = value
    require(expected == after, "Holder write changed more than explicitly requested scalar fields")


def marker_path(identity, tool_id):
    return local_evidence_root()/("turn_holder_dimensions_"+single._digest(dict(scope=SCOPE,copy_file_identity=identity,tool_native_id=tool_id))+".json")


def configure_turn_holder_dimensions(sw,clsid,typelib_path,*,process_id,expected_process_create_time,expected_document_path,
        expected_source_sha256,setup_index,operation_index,expected_operation_type,expected_operation_native_id,expected_tool_native_id,
        expected_holder_id,protected_part_pins,values_native,action="prepare",expected_state_sha256=None,
        allowed_affected_operations=None,receipt_path=None,qualification_only,message_policy,completed_length_probe=None):
    config=dict(process_id=process_id,expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,setup_index=setup_index,operation_index=operation_index,
        expected_operation_type=expected_operation_type,expected_operation_native_id=expected_operation_native_id,
        expected_tool_native_id=expected_tool_native_id,expected_holder_id=expected_holder_id)
    report=dict(scope=SCOPE,status="error",phase="preflight",readback_verified=False,apply_eligible=False,mutation_attempted=False,
        native_dispatch_pending=False,native_calls_returned_count=0,model_saved=False,GOP_attempted=False,GTP_attempted=False,
        tool_assignment_attempted=False,automatic_retry=False,automatic_rollback=False,physical_tool_qualified=False,
        native_units_verified=False,all_holder_sharing_qualified=False,storage_independence_verified=False,
        protected_CL_bytes_compared=False,all_nc_parameters_verified=False,full_model_geometry_verified=False,persistence_verified=False,production_qualified=False,
        setters=[],snapshot_diagnostics=[],captures=[],receipt_created=False,receipt_path=None,
        logical_binding_verified=False,holder_file_fields_preserved=False)
    from scripts import sw_cam_turn_holder_continuation as continuation
    session=None;receipt=None;created=False;prior_evidence=None
    def persist():
        if created:_write_receipt(receipt,report)
    try:
        values=validate(config,values_native,protected_part_pins)
        completed_length_probe=continuation.validate_completed_length_probe(completed_length_probe,values)
        report["getter_setter_abi"]=_logical_abi(typelib_path)
        require(qualification_only is True and message_policy == "vendor_default", "Explicit qualification/default-message policy required")
        require(action in ("prepare","apply"), "Only prepare/apply supported")
        require(action == "apply" or all(v is None for v in (expected_state_sha256,allowed_affected_operations,receipt_path)), "Prepare rejects apply inputs")
        identity=files(config,protected_part_pins);marker=marker_path(identity,expected_tool_native_id)
        legacy_marker=marker
        lead_marker=continuation.continuation_marker_path(legacy_marker,identity,expected_tool_native_id)
        continuation.require_known(not lead_marker.exists() and not lead_marker.is_symlink(),"HOLDER_LEAD_ALREADY_CLAIMED")
        if completed_length_probe is None:
            continuation.require_known(not marker.exists() and not marker.is_symlink(),"HOLDER_PRIOR_ATTEMPT_EXISTS")
        else:
            prior_evidence=continuation.load_completed_length_probe(completed_length_probe,legacy_marker,identity,config)
            report["completed_length_probe"]=prior_evidence;marker=lead_marker
        if action == "apply":
            require(guard.sha(expected_state_sha256), "Exact prepared state required")
            require(type(allowed_affected_operations) is list and 1 <= len(allowed_affected_operations) <= 512, "Exact shared-operation references required")
            refs=[single._reference(x) for x in allowed_affected_operations]
            require(len({single._ref_key(x) for x in refs}) == len(refs), "Duplicate shared-operation reference")
            require(type(receipt_path) is str and absolute_document_path(receipt_path), "Fresh absolute JSON receipt required")
            receipt=Path(receipt_path)
            require(receipt.suffix.casefold() == ".json" and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink()
                and guard.key(receipt) != guard.key(marker), "Fresh nonaliased receipt required")
            _write_receipt(receipt,report,create=True);created=True;report.update(receipt_created=True,receipt_path=str(receipt))
        report["request"]=dict(config,protected_part_pins=deepcopy(protected_part_pins),values_native=values,action=action)
        if completed_length_probe is not None:report["request"]["completed_length_probe"]=deepcopy(completed_length_probe)
        guard.isolated(sw,config,lambda:None)
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path);session=CamMessageSession(app,typelib_path)
        def check():
            m=session.summary();report["messages"]=m
            require(m.get("subscribed") is True and m.get("active") is True and not any(m.get(k) for k in guard.EVENT_ERRORS), "CAM event requires stop")
        def boundary(reference=None):
            check();guard.isolated(sw,config,check)
            require(files(config,protected_part_pins) == identity,"Copy/protected file identity changed")
            if prior_evidence is not None:continuation.verify_evidence_pins(completed_length_probe)
            if reference is not None:require(document_snapshot(sw) == reference,"Document changed before holder write")
        def observe(label):
            report["phase"]=label;entry=dict(label=label,capture_complete=False);report["captures"].append(entry)
            try:
                state,native=_logical_snapshot(sw,clsid,typelib_path,config,report,check)
                entry.update(state=deepcopy(state),capture_complete=True)
                if prior_evidence is not None and not label.startswith("after_"):
                    continuation.verify_current_completed_length(state,prior_evidence,expected_tool_native_id)
                return state,native
            finally:persist()
        with session:
            boundary()
            before,native=observe("before");report["before"]=before
            require(before["document"]["needs_save"] is False,"Initially clean saved qualification copy required")
            confirm,native=observe("confirm_before");require(confirm==before,"Two complete logical captures must agree")
            boundary(before["document"])
            affected=before["affected_operations"];generated=[x for x in before["inventory"]["operations"] if x["toolpath_generated"]
                and any((x["setup_index"],x["operation_index"]) == (r["setup_index"],r["operation_index"]) for r in affected)]
            old=before["selected_tool"]["holder"]["dimensions_native"]
            changes={k:v for k,v in values.items() if old[k] != v}
            digest_data=dict(config=config,protected_part_pins=protected_part_pins,values_native=values,state=before)
            if prior_evidence is not None:digest_data["completed_length_probe"]=prior_evidence
            digest=single._digest(digest_data)
            report.update(state_sha256=digest,affected_operations=affected,affected_generated_operations=generated,
                changed_fields=list(changes),no_changes_required=not changes)
            current=before;applied={}
            if action == "apply":
                require(digest == expected_state_sha256,"Prepared holder state/recipe changed")
                require(sorted(refs,key=single._ref_key) == sorted(affected,key=single._ref_key),"All and only sharing operations must be explicitly allowed")
                require(not generated and bool(changes),"Generated sharing or no-op recipe forbids holder writes")
                report["marker_path"]=str(marker)
                marker_data=dict(scope=SCOPE,status="claimed_no_replay",copy_file_identity=identity,
                    tool_native_id=expected_tool_native_id,source_sha256=expected_source_sha256,state_sha256=digest,
                    receipt_path=str(receipt))
                if prior_evidence is not None:
                    marker_data.update(scope=continuation.SCOPE,field="LeadAngle",completed_length_probe=deepcopy(prior_evidence))
                try:
                    _write_receipt(marker,marker_data,create=True)
                except FileExistsError:
                    raise continuation.ContinuationGuardError("HOLDER_LEAD_ALREADY_CLAIMED" if prior_evidence is not None else "HOLDER_PRIOR_ATTEMPT_EXISTS") from None
                for field,value in changes.items():
                    boundary(current["document"])
                    item=dict(field=field,old_value_native=old[field],value_native=value,attempted=False,returned=False,readback_verified=False)
                    report["setters"].append(item)
                    fresh,native=observe("dispatch_guard_"+field)
                    require(fresh==current,"Full logical owner/crib state changed before write")
                    boundary(current["document"])
                    report.update(phase="property_put",mutation_attempted=True,native_dispatch_pending=True)
                    item["attempted"]=True;persist();boundary(current["document"])
                    setter_error=None
                    try:
                        setattr(native["holder"],field,value)
                        item["returned"]=True;report["native_calls_returned_count"]+=1
                        report.update(native_dispatch_pending=False,phase="property_put_returned")
                    except Exception as error:
                        setter_error=error;item["setter_error"]=_error(error)
                        report["phase"]="property_put_failed"
                    persist();check()
                    # setter 异常也只观察一次实际状态；禁止再次 setter 或自动回滚。
                    after,native=observe("after_"+field);item["after"]=after
                    report["after"]=after;current=after;persist()
                    if setter_error is not None:raise setter_error
                    applied[field]=value;_verify_logical_changes(before,after,applied,expected_tool_native_id)
                    item["observed_value_native"]=after["selected_tool"]["holder"]["dimensions_native"][field]
                    item["readback_verified"]=True;boundary(current["document"]);persist()
            report["after"]=current;check()
        m=session.summary();report["messages"]=m
        require(m.get("subscribed") is True and m.get("disconnected") is True and m.get("active") is False
            and not any(m.get(k) for k in guard.EVENT_ERRORS),"Event cleanup uncertain")
        require(document_snapshot(sw) == current["document"] and files(config,protected_part_pins) == identity,"Post-cleanup document/source changed")
        guard.isolated(sw,config,lambda:None)
        if prior_evidence is not None:continuation.verify_evidence_pins(completed_length_probe)
        report.update(status="prepared" if action == "prepare" else "review_required",phase="finished",readback_verified=action == "apply",
            apply_eligible=action == "prepare" and not generated and bool(changes),final_state=current,final_state_sha256=single._digest(current),
            logical_binding_verified=True,holder_file_fields_preserved=action=="apply",
            reason="SCALAR_HOLDER_DEFINITION_ONLY_PHYSICAL_ASSEMBLY_UNITS_CL_AND_PERSISTENCE_UNQUALIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],phase="finished",
            readback_verified=False,apply_eligible=False,issue=_error(exc))
        report.update(continuation.known_reason(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain" if report["mutation_attempted"] else "error",readback_verified=False,apply_eligible=False,receipt_write_error=_error(exc))
    return report


def revoke_runtime_verification(result,error,expected_receipt_path):
    """保留已返回的实际证据，撤销运行时资格；只重写本次创建的匹配回执。"""
    import json
    result['historical_verification_before_runtime_drift']={k:result.get(k) for k in ('status','readback_verified','apply_eligible','logical_binding_verified','holder_file_fields_preserved')}
    result.update(status='uncertain' if result.get('mutation_attempted') else 'error',readback_verified=False,
        apply_eligible=False,logical_binding_verified=False,holder_file_fields_preserved=False,
        runtime_unchanged=False,may_continue=False,reason='RUNTIME_CHANGED_AFTER_NATIVE_CALL',
        runtime_error=_error(error),runtime_drift_receipt_updated=False)
    if result.get('receipt_created') is True and expected_receipt_path is not None and result.get('receipt_path')==str(expected_receipt_path):
        try:
            path=Path(expected_receipt_path)
            require(path.is_file() and not path.is_symlink(),'Owned runtime-drift receipt missing or aliased')
            disk=json.loads(path.read_text(encoding='utf-8'))
            require(disk.get('scope')==SCOPE and disk.get('receipt_created') is True and disk.get('receipt_path')==str(path)
                and disk.get('request')==result.get('request'),'Runtime-drift receipt belongs to a different invocation')
            result['runtime_drift_receipt_updated']=True
            _write_receipt(path,result)
        except Exception as exc:
            result['runtime_drift_receipt_updated']=False;result['runtime_drift_receipt_error']=_error(exc)
    return result


PROBE_SCOPE = "TURN_HOLDER_SINGLE_SHANK_LENGTH_WRITE_THROUGH_PROBE_V1"


def _probe_comparable(state):
    result=deepcopy(state)
    # Fresh getters may expose different COM objects; record this outside scalar authority.
    result["holder_alias_observation"]["selected_same_com_tool_ids"] = []
    return result


def _verify_probe_delta(before,after,value,tool_id):
    expected=_probe_comparable(before);actual=_probe_comparable(after)
    require(type(actual["document"]["needs_save"]) is bool,"Strict observed save flag required")
    expected["document"]["needs_save"] = actual["document"]["needs_save"]
    expected["selected_tool"]["holder"]["dimensions_native"]["ShankLength"] = value
    row=next(x for x in expected["toolcrib"] if x["native_id"] == tool_id)
    row["holder_dimensions_native"]["ShankLength"] = value
    row["observed_holder"]["dimensions_native"]["ShankLength"] = value
    require(actual == expected,"Probe changed more than selected ShankLength")


def _retained_probe_holders(native, read):
    def capture(holder):
        kind=profile._integer(read(holder,"GetHolderType"))
        return dict(holder_type_raw=kind,holder_id_raw=profile._integer(read(holder,"GetHolderId")),
            observed_holder=_holder_dimensions(holder,kind,read))
    return dict(own=capture(native["holder"]),crib=[dict(tool_native_id=ident,**capture(holder))
        for ident,holder in sorted(native["held_crib_holders"].items())])


def _verify_retained_probe_delta(before, after, value, tool_id):
    expected=deepcopy(before)
    expected["own"]["observed_holder"]["dimensions_native"]["ShankLength"]=value
    next(x for x in expected["crib"] if x["tool_native_id"] == tool_id)["observed_holder"]["dimensions_native"]["ShankLength"]=value
    require(after == expected,"Retained holder views changed beyond selected ShankLength or failed write-through")


def qualify_turn_holder_write_through(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,copy_source_path,copy_source_sha256,
        setup_index,operation_index,expected_operation_type,expected_operation_native_id,expected_tool_native_id,
        expected_holder_id,protected_part_pins,expected_shank_length_native,shank_length_native,
        action="prepare",expected_state_sha256=None,allowed_affected_operations=None,receipt_path=None,
        qualification_only,message_policy):
    """One property-put on an isolated saved copy; attached-view behavior is unproven."""
    config=dict(process_id=process_id,expected_process_create_time=expected_process_create_time,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        setup_index=setup_index,operation_index=operation_index,expected_operation_type=expected_operation_type,
        expected_operation_native_id=expected_operation_native_id,expected_tool_native_id=expected_tool_native_id,
        expected_holder_id=expected_holder_id)
    report=dict(scope=PROBE_SCOPE,status="error",phase="preflight",mutation_attempted=False,
        native_dispatch_pending=False,native_calls_returned_count=0,readback_verified=False,apply_eligible=False,
        owner_write_through_verified=False,write_through_outcome="not_attempted",model_saved=False,
        persistence_verified=False,GOP_attempted=False,GTP_attempted=False,tool_assignment_attempted=False,
        database_save_attempted=False,automatic_retry=False,automatic_rollback=False,physical_tool_qualified=False,
        native_units_verified=False,all_holder_sharing_qualified=False,storage_independence_verified=False,
        protected_CL_bytes_compared=False,all_nc_parameters_verified=False,full_model_geometry_verified=False,
        production_qualified=False,setters=[],snapshot_diagnostics=[])
    receipt=None;created=False;session=None
    def persist():
        if created:_write_receipt(receipt,report)
    try:
        value=validate(config,{"ShankLength":shank_length_native},protected_part_pins)["ShankLength"]
        old=profile._number(expected_shank_length_native)
        require(old > 0 and old != value,"Distinct positive expected and proposed lengths required")
        require(qualification_only is True and message_policy == "vendor_default","Explicit qualification/default-message policy required")
        require(action in ("prepare","probe"),"Only prepare/probe supported")
        require(action == "probe" or all(x is None for x in (expected_state_sha256,allowed_affected_operations,receipt_path)),"Prepare rejects probe inputs")
        require(type(copy_source_path) is str and absolute_document_path(copy_source_path)
            and Path(copy_source_path).suffix.casefold() == ".sldprt"
            and guard.sha(copy_source_sha256) and copy_source_sha256 == expected_source_sha256,"Exact saved copy-source pin required")
        require(len(protected_part_pins) >= 2 and any(guard.key(x["path"]) == guard.key(copy_source_path)
            and x["sha256"] == copy_source_sha256 for x in protected_part_pins),"Protect copy source and an additional original file")
        identity=files(config,protected_part_pins);marker=marker_path(identity,expected_tool_native_id)
        require(not marker.exists() and not marker.is_symlink(),"Earlier holder attempt exists; no replay")
        if action == "probe":
            require(guard.sha(expected_state_sha256),"Exact prepared probe state required")
            require(type(allowed_affected_operations) is list and 1 <= len(allowed_affected_operations) <= 512,"Exact affected references required")
            refs=[single._reference(x) for x in allowed_affected_operations]
            require(len({single._ref_key(x) for x in refs}) == len(refs),"Duplicate affected reference")
            require(type(receipt_path) is str and absolute_document_path(receipt_path),"Fresh absolute receipt required")
            receipt=Path(receipt_path)
            require(receipt.suffix.casefold() == ".json" and receipt.parent.is_dir() and not receipt.exists()
                and not receipt.is_symlink() and guard.key(receipt) != guard.key(marker),"Fresh nonaliased receipt required")
            _write_receipt(receipt,report,create=True);created=True
        report["request"]=dict(config,copy_source_path=copy_source_path,copy_source_sha256=copy_source_sha256,
            protected_part_pins=deepcopy(protected_part_pins),expected_shank_length_native=old,shank_length_native=value,action=action)
        guard.isolated(sw,config,lambda:None)
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path);session=CamMessageSession(app,typelib_path)
        def check():
            m=session.summary();report["messages"]=m
            require(m.get("subscribed") is True and m.get("active") is True and not any(m.get(k) for k in guard.EVENT_ERRORS),"CAM event requires stop")
        def boundary(document=None):
            check();guard.isolated(sw,config,check)
            require(files(config,protected_part_pins) == identity,"Copy/protected file identity changed")
            if document is not None:require(document_snapshot(sw) == document,"Document changed before probe")
        def read(obj,name,*args):
            check();result=_member(obj,name,*args);check();return result
        with session:
            boundary();report["phase"]="before"
            before,retained=snapshot(sw,clsid,typelib_path,config,report,check,probe_identity=True)
            report["before"]=before;current=before
            require(before["document"]["needs_save"] is False,"Initially clean saved qualification copy required")
            require(before["selected_tool"]["holder"]["dimensions_native"]["ShankLength"] == old,"Expected original length differs")
            affected=before["affected_operations"]
            generated=[x for x in before["inventory"]["operations"] if x["toolpath_generated"] and
                any((x["setup_index"],x["operation_index"]) == (a["setup_index"],a["operation_index"]) for a in affected)]
            retained_before=_retained_probe_holders(retained,read)
            report["retained_holders_before"]=retained_before
            require(retained_before["own"]["observed_holder"]["dimensions_native"] ==
                dict(before["selected_tool"]["holder"]["dimensions_native"],HolderShape=before["selected_tool"]["holder"]["shape_raw"]),
                "Retained own holder differs from selected profile")
            for held in retained_before["crib"]:
                row=next(x for x in before["toolcrib"] if x["native_id"] == held["tool_native_id"])
                require(held["holder_type_raw"] == row["holder_type_raw"] and held["holder_id_raw"] == row["holder_id_raw"]
                    and held["observed_holder"] == row["observed_holder"],"Retained crib holder changed during collection")
            digest=single._digest(dict(scope=PROBE_SCOPE,request=report["request"] | {"action":"prepared_recipe"},
                copy_file_identity=identity,state=_probe_comparable(before),retained_holders=retained_before))
            report.update(state_sha256=digest,affected_operations=affected,affected_generated_operations=generated)
            boundary(before["document"])
            if action == "probe":
                require(digest == expected_state_sha256,"Prepared probe source/recipe/state changed")
                require(sorted(refs,key=single._ref_key) == sorted(affected,key=single._ref_key),"All and only affected refs required")
                require(not generated,"Generated operation shares selected tool")
                # Write only the retained own-holder object, without a rebind or commit call.
                require(_object_id(retained["native_doc"],retained["operation"],read) == expected_operation_native_id,"Retained operation changed")
                require(_object_id(retained["native_doc"],retained["tool"],read) == expected_tool_native_id,"Retained tool changed")
                fresh_tool=_typed(read(retained["operation"],"IGetTool"),"ICWTool",typelib_path)
                require(_object_id(retained["native_doc"],fresh_tool,read) == expected_tool_native_id,"Own tool assignment changed")
                holder=retained["holder"]
                require(profile._integer(read(holder,"GetHolderType")) == 2 and profile._integer(read(holder,"GetHolderId")) == expected_holder_id,"Retained holder classification changed")
                require(_holder_dimensions(holder,2,read)["dimensions_native"] == dict(before["selected_tool"]["holder"]["dimensions_native"],HolderShape=before["selected_tool"]["holder"]["shape_raw"]),"Retained own holder scalars differ before probe")
                report["marker_path"]=str(marker)
                _write_receipt(marker,dict(scope=PROBE_SCOPE,status="claimed_no_replay",copy_file_identity=identity,
                    source_sha256=expected_source_sha256,tool_native_id=expected_tool_native_id,state_sha256=digest,
                    receipt_path=str(receipt)),create=True)
                item=dict(field="ShankLength",old_value_native=old,value_native=value,attempted=True,returned=False,readback_verified=False)
                report["setters"].append(item);report.update(phase="property_put",mutation_attempted=True,native_dispatch_pending=True)
                persist();boundary(before["document"])
                setattr(holder,"ShankLength",value)
                item["returned"]=True;report.update(native_dispatch_pending=False,native_calls_returned_count=1,phase="property_put_returned")
                persist();check()
                report["phase"]="retained_holder_readback"
                retained_after=_retained_probe_holders(retained,read)
                report["retained_holders_after"]=retained_after
                observed=retained_after["own"]["observed_holder"]["dimensions_native"]["ShankLength"]
                item["retained_value_native"]=observed;persist()
                report["phase"]="fresh_owner_and_crib_readback"
                after,fresh=snapshot(sw,clsid,typelib_path,config,report,check,probe_identity=True)
                report["after"]=after;item["after"]=after;current=after;persist()
                own=after["selected_tool"]["holder"]["dimensions_native"]["ShankLength"]
                crib=next(x for x in after["toolcrib"] if x["native_id"] == expected_tool_native_id)["holder_dimensions_native"]["ShankLength"]
                report["length_readback_native"]=dict(retained_holder=observed,fresh_own_holder=own,current_crib_holder=crib)
                if own == old and crib == old:
                    _verify_probe_delta(before,after,old,expected_tool_native_id)
                    negative_expected=deepcopy(retained_before)
                    require(observed in (old,value),"Retained holder returned an unexpected length")
                    negative_expected["own"]["observed_holder"]["dimensions_native"]["ShankLength"]=observed
                    held_crib=next(x for x in retained_after["crib"] if x["tool_native_id"] == expected_tool_native_id)
                    held_length=held_crib["observed_holder"]["dimensions_native"]["ShankLength"]
                    require(held_length in (old,value),"Retained selected crib returned an unexpected length")
                    next(x for x in negative_expected["crib"] if x["tool_native_id"] == expected_tool_native_id)["observed_holder"]["dimensions_native"]["ShankLength"]=held_length
                    require(retained_after == negative_expected,"Retained holder coupling makes negative result uncertain")
                    report["write_through_outcome"]="not_persisted_to_observed_owner"
                    require(False,"Property put did not persist to fresh owner and crib observations")
                require(observed == value and own == value and crib == value,"Holder views disagree after property put")
                _verify_probe_delta(before,after,value,expected_tool_native_id)
                _verify_retained_probe_delta(retained_before,retained_after,value,expected_tool_native_id)
                item["readback_verified"]=True
                report["write_through_outcome"]="observed_in_fresh_owner_and_crib"
                boundary(after["document"]);persist()
            report["after"]=current;check()
        m=session.summary();report["messages"]=m
        require(m.get("subscribed") is True and m.get("disconnected") is True and m.get("active") is False
            and not any(m.get(k) for k in guard.EVENT_ERRORS),"Event cleanup uncertain")
        require(document_snapshot(sw) == current["document"] and files(config,protected_part_pins) == identity,"Post-cleanup document/source changed")
        guard.isolated(sw,config,lambda:None)
        report.update(status="prepared" if action == "prepare" else "review_required",phase="finished",
            apply_eligible=action == "prepare" and not generated,readback_verified=action == "probe",
            owner_write_through_verified=action == "probe",final_state=current,final_state_sha256=single._digest(current),
            reason="SINGLE_PROPERTY_RAM_QUALIFICATION_ONLY_SAVE_REOPEN_PHYSICAL_AND_STORAGE_SCOPE_UNQUALIFIED")
    except Exception as exc:
        if report["mutation_attempted"] and report["write_through_outcome"] != "not_persisted_to_observed_owner":
            report["write_through_outcome"]="uncertain"
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],phase="finished",
            readback_verified=False,owner_write_through_verified=False,apply_eligible=False,issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status="uncertain" if report["mutation_attempted"] else "error",readback_verified=False,
                owner_write_through_verified=False,apply_eligible=False,receipt_write_error=_error(exc))
            if report["write_through_outcome"] != "not_persisted_to_observed_owner":report["write_through_outcome"]="uncertain"
    return report
