"""Read three existing length properties of one protected saved operation.

Reuses the installed saved18 owner/session, guarded target binding and length
reader. No GTP, Save, WIP export, simulation, parameter changes or full snapshots.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_saved18_optimized_wip as wip
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt

common, group, require = wip.common, wip.group, wip.require
SCOPE = "SAVED_PROTECTED_OPERATION_LENGTH_READ_V1"
ACTION = "read_saved_protected_operation_lengths"
ACK = "read_one_saved_protected_operation_three_length_properties_no_changes"
WIP_SHA = "7e3acbd0d0fb8fb4c14069ec86dd6dee4ec90ddc1d0b55577e4e9dfca4704df1"
PARAMS = {
    "process_id", "expected_document_path", "expected_source_sha256",
    "saved_receipt_path", "saved_receipt_sha256", "module_sha256", "receipt_path",
    "operation_native_id", "feature_native_id", "calibration_preparation_path",
    "calibration_preparation_sha256", "prospective_preparation_path",
    "prospective_preparation_sha256", "acknowledgement"}


def prepare_request(request):
    require(type(request) is dict and set(request) == {"action","params"}
            and request["action"] == ACTION, "Exact protected-operation read action required")
    p=deepcopy(request["params"])
    require(type(p) is dict and set(p) == PARAMS and p["acknowledgement"] == ACK,
            "Exact bounded read request required")
    for key in ("process_id","operation_native_id","feature_native_id"):
        require(type(p[key]) is int and 0 < p[key] < 2**31, "Strict owned target identity required")
    for key,value in p.items():
        if key.endswith("_path"):require(type(value) is str and Path(value).is_absolute(), "Absolute path required")
        if key.endswith("_sha256"):wip.producer.opt.prior._sha(value)
    require(common._pin(__file__)["sha256"] == p["module_sha256"]
            and common._pin(wip.__file__)["sha256"] == WIP_SHA, "Frozen probe/WIP helper required")
    calibration_pin=common._pin(p["calibration_preparation_path"])
    prospective_pin=common._pin(p["prospective_preparation_path"])
    require(calibration_pin["sha256"]==p["calibration_preparation_sha256"]
            and prospective_pin["sha256"]==p["prospective_preparation_sha256"], "Prepared evidence changed")
    calibration=wip.read(calibration_pin)
    prospective=wip.read(prospective_pin)
    require(calibration["scope"]=="INDEPENDENT_PROTECTED322_HELIX_STATISTIC_PREPARATION_V1"
            and calibration["status"]=="FROZEN_BEFORE_ANY_322_NATIVE_LENGTH_READ"
            and calibration["native_length_observations_used"] is False, "Independent frozen calibration required")
    require(prospective["scope"]=="PROSPECTIVE_NATIVE_PROJECTED_CIRCLE_STATISTIC_PREPARATION_V1"
            and prospective["calibration_native_observed"] is False
            and prospective["independent_calibration_preparation_pin"]["sha256"]==calibration_pin["sha256"],
            "Prospective policy must precede calibration observation")
    loaded,bound,parent_pin=wip.parent_authority(p["saved_receipt_path"],p["saved_receipt_sha256"])
    require(loaded["ownership"]["process_id"]==p["process_id"]
            and loaded["source_sha256"]==p["expected_source_sha256"]==calibration["source_sha256"]==prospective["source_sha256"]
            and common._key(bound["source_path"])==common._key(p["expected_document_path"]),
            "Exact clean current saved source/owner required")
    require(bound["document"]["needs_save"] is False
            and bound["saved_cl"]["output"]["sha256"]==calibration["actual_cl_pin"]["sha256"]==prospective["cl_pin"]["sha256"],
            "Saved CL/calibration binding differs")
    expected=next(x for x in bound["snapshot"]["binding"]["operations"] if x["native_id"]==p["operation_native_id"])
    require(group.exact(expected,calibration["operation"])
            and expected["linked_feature_ids"]==[p["feature_native_id"]]
            and p["operation_native_id"] in [x["operation_native_id"] for x in bound["expected_generated_operations"][:14]]
            and expected["toolpath_generated"] is True and expected["suppressed"] is False,
            "Only the independently prepared protected prior operation may be read")
    require([p["operation_native_id"],p["feature_native_id"]]==[322,82]
            and expected["assigned_tool"]["native_id"]==273 and expected["toolpath_record_counts"]==[4500],
            "Exact frozen322 calibration identity required")
    wip.native_pins(loaded)
    loaded["pins"]=common._merge(loaded["pins"],[common._pin(__file__)])
    require(len(loaded["pins"])+1<=64, "Probe live closure plus current source exceeds64")
    loaded["phase_proof_pins"]=common._merge(loaded["phase_proof_pins"],[calibration_pin,prospective_pin])
    loaded["pin_partition"].update(live_file_count=len(loaded["pins"]),maximum_with_source=len(loaded["pins"])+1,
                                  phase_proof_count=len(loaded["phase_proof_pins"]),single_prior_operation_lengths=True)
    common._check(loaded["pins"]);common._check(loaded["phase_proof_pins"])
    registration=common.discover_export_registration(loaded,loaded["registration"]["clsid"])
    require(group.exact(registration,loaded["registration"]), "Saved CAM registration differs")
    typelib=str(Path(registration["addin_path"]).parent/"camworks.tlb")
    require(common._pin(typelib) in loaded["pins"], "Pinned current CAM metadata required")
    p["expected_configuration"]=loaded["guide_parameters"]["configuration"]["sw_configuration_name"]
    guard=wip.producer.opt.prior.guard_reuse.guard_constructor_preflight(p,loaded,typelib)
    audit=wip.lengths.audit(typelib,loaded["generated_pin"])
    receipt=common._local_receipt(p["receipt_path"])
    require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(), "Fresh local receipt required")
    protected={common._key(x["path"]) for x in loaded["pins"]+loaded["phase_proof_pins"]}|{common._key(p["expected_document_path"])}
    require(common._key(receipt) not in protected, "Receipt would overwrite protected input")
    return p,dict(loaded=loaded,bound=bound,parent_pin=parent_pin,expected_operation=expected,
        registration=registration,typelib=typelib,receipt=receipt,calibration_pin=calibration_pin,
        prospective_pin=prospective_pin,native_guard_preflight=guard,length_interface_audit=audit)


def observe_existing_three(backend,p,plan,report,persist):
    backend.learned=[dict(operation_native_id=p["operation_native_id"],feature_native_id=p["feature_native_id"])]
    report["document_before"]=backend.ctx.identity()
    require(group.exact(report["document_before"],plan["bound"]["document"])
            and report["document_before"]["needs_save"] is False, "Exact clean saved document required")
    with backend.ctx.guard() as guard:
        active=guard.read(backend.ctx.app,"IGetActiveDoc")
        doc=guard.typed(active,"ICWDoc3");part=guard.typed(active,"ICWPartDoc")
        machine=guard.typed(guard.read(part,"IGetMachine"),"ICWMachine")
        require(guard.read(doc,"GetDocType")==1 and guard.read(machine,"MachType")==1, "Exact MILL context required")
    report["phase"]="read_three_length_properties";persist()
    # Existing helper already performs target binding -> three getters -> target binding.
    wip.capture_lengths(backend,plan["bound"]["snapshot"],report,persist,"independent_prior",doc,machine)
    rows=report["native_length_readbacks"]
    require(len(rows)==1 and rows[0]["label"]=="independent_prior" and len(rows[0]["rows"])==1,
            "Exactly one bounded native target read required")
    row=rows[0]["rows"][0]
    require(row["operation_native_id"]==p["operation_native_id"]
            and row["toolpath_record_counts"]==plan["expected_operation"]["toolpath_record_counts"]
            and row["readback_verified"] is True
            and group.exact(row["binding_before"],row["binding_after"])
            and [x["key"]for x in row["scalar_observations"]]==[x[0]for x in wip.lengths.FIELDS],
            "Complete stable three-property observation required")
    report["lengths"]=deepcopy(row["lengths"]);report["length_property_read_count"]=3
    report["document_after"]=backend.ctx.identity()
    require(group.exact(report["document_before"],report["document_after"]), "Document changed during readonly probe")
    wip.direct(dict(path=p["expected_document_path"],sha256=p["expected_source_sha256"]))


def dispatch_request(request,*,validate_only=False):
    p,plan=prepare_request(request)
    if validate_only:
        return dict(status="validated_offline",native_called=False,operation_native_id=p["operation_native_id"],
                    target=plan["expected_operation"],pin_partition=plan["loaded"]["pin_partition"],
                    native_guard_preflight=plan["native_guard_preflight"],length_interface_audit=plan["length_interface_audit"],
                    calibration_pin=plan["calibration_pin"],prospective_pin=plan["prospective_pin"])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p["process_id"]):
        common._check(plan["loaded"]["pins"]);common._check(plan["loaded"]["phase_proof_pins"])
        sw,_=connect_solidworks(process_id=p["process_id"],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,status="prepared",phase="prepared",request=deepcopy(p),process_id=p["process_id"],
            source_path=p["expected_document_path"],source_sha256=p["expected_source_sha256"],
            operation_native_id=p["operation_native_id"],feature_native_id=p["feature_native_id"],
            module_pin=common._pin(__file__),parent_saved_receipt_pin=plan["parent_pin"],
            saved_cl_pin=deepcopy(plan["bound"]["saved_cl"]["output"]),
            calibration_preparation_pin=plan["calibration_pin"],prospective_preparation_pin=plan["prospective_pin"],
            runtime_pins=deepcopy(plan["loaded"]["pins"]),phase_proof_pins=deepcopy(plan["loaded"]["phase_proof_pins"]),
            pin_partition=deepcopy(plan["loaded"]["pin_partition"]),length_interface_audit=plan["length_interface_audit"],
            read_only=True,readback_verified=False,mutation_attempted=False,GTP_attempted=False,GOP_attempted=False,
            AFR_attempted=False,model_saved=False,setter_attempted=False,WIP_export_attempted=False,simulation_attempted=False,
            automatic_retry=False,automatic_replay=False,full_route_snapshot_attempted=False,
            native_length_read_pending=False,length_property_read_count=0,cleanup_session_active=False,
            units_semantics_verified=False,geometry_accepted=False,production_qualified=False)
        persist=lambda:_write_receipt(plan["receipt"],report)
        _write_receipt(plan["receipt"],report,create=True)
        backend=wip.ReadBackend(plan["loaded"],p,sw,plan["registration"]["clsid"],plan["typelib"],report,persist,
                                before_generate=wip.forbidden,exporter=wip.forbidden)
        success=False
        try:
            backend.start()
            observe_existing_three(backend,p,plan,report,persist)
            backend.finish()
            common._check(plan["loaded"]["pins"]);common._check(plan["loaded"]["phase_proof_pins"])
            require(group.exact(backend.ctx.identity(),plan["bound"]["document"]), "Post-cleanup document changed")
            success=True
        except Exception as exc:
            report.update(status="error",failed_phase=report["phase"],issue=_error(exc),readback_verified=False)
        finally:
            try:wip.generation.close_checked(backend,report)
            except Exception as exc:
                success=False;report.update(status="error",cleanup_issue=_error(exc),readback_verified=False)
            report["phase"]="finished"
            if success:
                require(report["cleanup_session_active"] is False and report["native_length_read_pending"] is False,
                        "Read or cleanup still pending")
                report.update(status="observed",readback_verified=True)
            persist()
        return report

