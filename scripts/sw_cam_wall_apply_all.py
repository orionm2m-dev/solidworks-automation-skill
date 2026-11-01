"""Apply one saved wall lead-propagation candidate and generate it once.

Nine bounded writes: enable ApplyToAll, then reapply eight unchanged lead
values. Keep gouge checking enabled. Save only a real selected toolpath.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
from scripts import sw_cam_saved_wall_configuration as saved
from scripts import sw_cam_wall_outcome as outcome
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_rough_firstcut import require

wall = outcome.wall
original, common, group = wall.original, wall.common, wall.group
SCOPE = "SAVED_WALL_APPLY_ALL_CANDIDATE_V1"
SPEC = ("apply_to_all", "ICWFinishMillOp3", "LeadInOutApplyToAll",
        "LeadInOutApplyToAll", "property", False, True)
LEADS = tuple(x[:5] + (deepcopy(x[6]), deepcopy(x[6])) for x in wall.FIELDS)
FIELDS = (SPEC,) + LEADS
ACTIONS = tuple("field:" + x[0] for x in FIELDS) + ("GenerateToolpath", "SaveActiveDocument")
FORBIDDEN = wall.FORBIDDEN + ("automatic_replay", "global_generation_attempted",
                             "gouge_check_setter_attempted")
PARAMS = {"process_id", "expected_document_path", "expected_source_sha256", "addin_clsid",
          "checkpoint_receipt_path", "checkpoint_receipt_sha256", "diagnostic_receipt_path",
          "diagnostic_receipt_sha256", "plan_path", "plan_sha256", "receipt_path",
          "progress_path", "module_sha256"}


def validate_request(request):
    require(type(request) is dict and set(request) == {"action", "params"}
            and request["action"] == "apply_wall_leads_to_all", "Exact candidate action required")
    p = deepcopy(request["params"])
    require(type(p) is dict and set(p) == PARAMS, "Exact candidate fields required")
    require(type(p["process_id"]) is int and p["process_id"] > 0, "Owned PID required")
    for key, value in p.items():
        if key.endswith("_path"):
            require(type(value) is str and Path(value).is_absolute(), "Absolute path required")
        if key.endswith("_sha256"):
            require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value), "Strict digest required")
    require(p["module_sha256"] == _file_hash(__file__), "Candidate module changed")
    require(type(p["addin_clsid"]) is str and re.fullmatch(r"\{[0-9A-Fa-f-]{36}\}", p["addin_clsid"]),
            "Exact CAM registration required")
    return p


def validate_diagnostic(d, p, loaded):
    require(d["scope"] == "SAVED_FINISH_DIAGNOSTIC_READ_V1" and d["status"] == "observed"
            and d["phase"] == "finished" and d["readback_verified"] is True and d["read_only"] is True,
            "Completed native diagnostic required")
    require(all(d[key] is False for key in ("mutation_attempted", "GTP_attempted", "save_attempted",
                                            "native_dispatch_pending")), "Diagnostic is not read-only")
    require(d["process_id"] == p["process_id"] and d["source_sha256"] == p["expected_source_sha256"]
            and common._key(d["source_path"]) == common._key(p["expected_document_path"])
            and d["checkpoint_pin"]["sha256"] == p["checkpoint_receipt_sha256"], "Diagnostic binding differs")
    require(group.exact(d["before"], d["after"]) and d["batch"]["read_scope_complete"] is True,
            "Stable completed diagnostic required")
    row = d["operations"]["144"]
    require(row["operation_native_id"] == 144 and row["feature_native_id"] == 79
            and row["supported_fields_read_complete"] is True, "Exact supported finish fields required")
    values = row["values"]["ICWFinishMillOp3"]
    require(values["LeadInOutApplyToAll"] is False and values["GougeCheck"] is True,
            "Saved candidate starts with ApplyToAll false and GougeCheck true")
    for oid, actual in d["after"].items():
        source = next(x for x in loaded["state"]["operations"] if x["native_id"] == int(oid))
        expected = dict(native_id=int(oid), suppressed=source["suppressed"],
                        generated=source["toolpath_generated"], feature_ids=source["linked_feature_ids"],
                        tool_id=source["assigned_tool"]["native_id"], record_counts=source["toolpath_record_counts"],
                        mill_type=source["mill_operation_type"])
        require(group.exact(actual, expected), "Diagnostic does not describe saved route")
    clean_events(d)


def validate_plan(plan, p):
    """The engineering plan supplies its pinned executable contract separately."""
    contract = plan["execution_contract"]
    expected = dict(scope=SCOPE, source_sha256=p["expected_source_sha256"],
                    checkpoint_sha256=p["checkpoint_receipt_sha256"],
                    diagnostic_sha256=p["diagnostic_receipt_sha256"],
                    operation_native_id=144, feature_native_id=79, tool_native_id=273,
                    apply_to_all_before=False, apply_to_all_after=True,
                    reapply_lead_fields=True, gouge_check_preserved=True,
                    selected_gtp_max_calls=1, save_only_if_generated=True,
                    automatic_replay=False, production_qualified=False)
    require(group.exact(contract, expected), "Exact reviewed candidate contract required")
    require(plan["status"] == "ready_for_single_candidate", "Plan is not ready for this candidate")
    require(group.exact(plan["setter_specs"], [list(x) for x in FIELDS]), "Approved setter list differs")
    common._check(plan["source_pins"])


def load_inputs(p):
    loaded = saved.load_completed(p["checkpoint_receipt_path"], p["checkpoint_receipt_sha256"],
        **{k: p[k] for k in ("process_id", "expected_document_path", "expected_source_sha256")})
    saved.parent.qualify_scope(loaded)
    diagnostic, diagnostic_pin = read_pin(p["diagnostic_receipt_path"], p["diagnostic_receipt_sha256"])
    validate_diagnostic(diagnostic, p, loaded)
    plan, plan_pin = read_pin(p["plan_path"], p["plan_sha256"])
    validate_plan(plan, p)
    common._check(diagnostic["runtime_pins"])
    loaded.update(pins=common._merge(loaded["pins"], [common._pin(__file__)]),
        offline_export_proof_pins=common._merge(loaded["offline_export_proof_pins"],
                                              [diagnostic_pin, plan_pin],
                                              [x for x in plan["source_pins"] if common._key(x["path"])
                                               != common._key(p["expected_document_path"])]))
    require(len(loaded["pins"]) <= 64, "Bounded runtime closure required")
    return loaded, diagnostic_pin, plan_pin


def restrictions(value, enabled):
    require(type(value) is dict and set(value) == {"LeadInOutApplyToAll", "GougeCheck"}
            and value["LeadInOutApplyToAll"] is enabled and value["GougeCheck"] is True,
            "ApplyToAll or protected GougeCheck differs")


def verify_capture(loaded, value, *, enabled=False, generated=False, saved_sha=None):
    counts = wall.verify_capture(loaded, value, configured=False, generated=generated, saved_sha=saved_sha)
    restrictions(value["restrictions"], enabled)
    return counts


class NativeBackend(outcome.NativeBackend):
    def set_field(self, spec, pending):
        require(spec in FIELDS and group.exact(list(spec), list(next(x for x in FIELDS if x[0] == spec[0]))),
                "Only reviewed apply-all and unchanged lead values are writable")
        return original.NativeBackend.set_field(self, spec, pending)

    def generate(self, pending):
        restrictions(self.restrictions(), True)
        return original.NativeBackend.generate(self, pending)

    def restrictions(self):
        with self.ctx.guard() as guard:
            owner, _, _ = self.owner(guard, SPEC)
            return {key: guard.read(owner, key) for key in ("LeadInOutApplyToAll", "GougeCheck")}

    def capture_full(self, label):
        value = super().capture_full(label)
        value["restrictions"] = self.restrictions()
        return value

    def capture_narrow(self, label):
        value = super().capture_narrow(label)
        value["restrictions"] = self.restrictions()
        return value


def marker_path(source, sha):
    # Independent of output filename and plan hash: a revised report cannot replay this candidate.
    return common.local_evidence_root() / ("wall_apply_all_" + _digest(dict(
        scope=SCOPE, source=common._key(source), source_sha256=sha, operation=144)) + ".json")


class Journal(original.prior.tools.Journal):
    def marker_state(self):
        r = self.report
        return dict(scope=SCOPE, source_path=r["source_path"], initial_source_sha256=r["initial_source_sha256"],
                    checkpoint_pin=r["checkpoint_pin"], diagnostic_pin=r["diagnostic_pin"], plan_pin=r["plan_pin"],
                    actions=deepcopy(r["actions"]), status=r["status"], phase=r["phase"],
                    model_saved=r["model_saved"], readback_verified=r["readback_verified"])


def configure(backend, journal, loaded):
    r = journal.report
    r["initial_status"] = backend.outcome(); journal.persist()
    saved.parent.no_output(r["initial_status"])
    r["initial"] = backend.capture_full("apply_all_initial"); journal.persist()
    verify_capture(loaded, r["initial"])
    r["initial_full_capture_verified"] = True; journal.persist()
    for spec in FIELDS:
        label = "field:" + spec[0]
        initial = backend.field(spec)
        require(group.exact(initial, spec[5]), "Direct field changed before candidate write")
        result = backend.set_field(spec, lambda label=label: journal.pending(label))
        journal.returned(label, result)
        require(type(result) is int and result == 0, "Strict native setter HRESULT0 required")
        backend.refresh_dirty()
        actual = backend.field(spec)
        r["actions"][label]["observed"] = deepcopy(actual); journal.persist()
        require(group.exact(actual, spec[6]), "Direct field readback differs")
        r["actions"][label]["readback_verified"] = True; journal.persist()
    r["configured"] = backend.capture_narrow("apply_all_configured"); journal.persist()
    verify_capture(loaded, r["configured"], enabled=True)
    r["configuration_readback_verified"] = True; journal.persist()


def save_generated(backend, journal, loaded):
    r = journal.report
    reference = wall.save_projection(r["generated"]); r["save_stage"] = {}
    def guard():
        backend.boundary()
        actual = backend.outcome(); saved.parent.status_25d(actual)
        require(group.exact(actual, r["generation_status"]), "Selected path changed during save")
        restrictions(backend.restrictions(), True)
    def capture(label):
        if label == "before":
            guard(); return deepcopy(reference)
        r["final"] = backend.capture_full("apply_all_saved"); journal.persist()
        counts = verify_capture(loaded, r["final"], enabled=True, generated=True,
                                saved_sha=r["saved_source_sha256"])
        require(group.exact(counts, r["generated_record_counts"]), "Saved path counts differ")
        return wall.equivalent_projection(reference, wall.save_projection(r["final"]))
    def save():
        result = backend.save(); journal.returned("SaveActiveDocument", result); return result
    def saved_hash():
        sha = backend.saved_hash(r["save_stage"])
        require(sha != r["initial_source_sha256"], "Changed saved CAM bytes required")
        r["saved_source_sha256"] = sha; journal.persist(); return sha
    wall.run_one_existing_save(r["save_stage"], capture=capture,
        verify=lambda value: wall.equivalent_projection(reference, value), guard=guard,
        claim=lambda: journal.pending("SaveActiveDocument"), persist=journal.persist,
        save=save, saved_hash=saved_hash)
    r["actions"]["SaveActiveDocument"]["readback_verified"] = True
    r.update(status="saved_generated_review_required", phase="finished", model_saved=True, readback_verified=True)


def generate_once(backend, journal, loaded):
    r = journal.report
    require(r.get("configuration_readback_verified") is True, "Verified candidate required")
    saved.parent.no_output(backend.outcome())
    restrictions(backend.restrictions(), True)
    result = backend.generate(lambda: journal.pending("GenerateToolpath"))
    journal.returned("GenerateToolpath", result)
    require(type(result) is int and result == 0, "Strict selected GTP HRESULT0 required")
    backend.refresh_dirty()
    r["generation_status"] = backend.outcome(); journal.persist()
    saved.parent.status_25d(r["generation_status"])
    generated = r["generation_status"]["generated"]
    r["generated"] = backend.capture_narrow("apply_all_generated"); journal.persist()
    counts = verify_capture(loaded, r["generated"], enabled=True, generated=generated)
    require(group.exact(counts, r["generation_status"]["record_counts"]), "Actual stream count differs")
    r["generated_record_counts"] = counts
    r["actions"]["GenerateToolpath"]["readback_verified"] = True
    r["generation_verified"] = generated; journal.persist()
    if not generated:
        r.update(status="no_toolpath_no_save", phase="finished", model_saved=False, readback_verified=True)
        journal.persist(); return
    save_generated(backend, journal, loaded)


def run_backend(backend, journal, loaded):
    r = journal.report
    try:
        backend.start(); configure(backend, journal, loaded); generate_once(backend, journal, loaded)
        backend.finish(); clean_events(r)
    except Exception as exc:
        r.update(status="uncertain" if r["mutation_attempted"] else "error", failed_phase=r["phase"],
                 phase="finished", readback_verified=False, issue=_error(exc))
    finally:
        try:
            backend.close()
        except Exception as exc:
            r.update(status="uncertain", readback_verified=False, cleanup_issue=_error(exc))
        journal.persist()
    return r



def validate_terminal(r):
    require(r["scope"] == SCOPE and r["status"] == "saved_generated_review_required"
            and r["phase"] == "finished" and all(r[key] is True for key in
                ("readback_verified", "model_saved", "generation_verified", "phase_proofs_verified",
                 "configuration_readback_verified", "initial_full_capture_verified")),
            "Only a completed saved path is export authority")
    require(not any(key in r for key in ("issue", "failed_phase", "cleanup_issue", "phase_proof_error"))
            and all(r[key] is False for key in FORBIDDEN) and set(r["actions"]) == set(ACTIONS),
            "Uncertain or unexpected actions cannot become authority")
    loaded = r["loaded_context_before"]
    saved.parent.no_output(r["initial_status"])
    verify_capture(loaded, r["initial"])
    verify_capture(loaded, r["configured"], enabled=True)
    for key in ("generated", "final"):
        counts = verify_capture(loaded, r[key], enabled=True, generated=True,
                                saved_sha=r["saved_source_sha256"] if key == "final" else None)
        require(group.exact(counts, r["generated_record_counts"]), "Terminal path counts differ")
    for action in r["actions"].values():
        wall.history.verified_action(action)
    for field in FIELDS:
        require(group.exact(r["actions"]["field:" + field[0]]["observed"], field[6]),
                "Terminal direct field readback differs")
    saved.parent.status_25d(r["generation_status"])
    require(r["generation_status"]["generated"] is True
            and group.exact(r["generation_status"]["record_counts"], r["generated_record_counts"]),
            "Terminal selected generation not established")
    require(r["save_stage"]["save_readback_verified"] is True
            and r["save_stage"]["saved_file_sha256"] == r["saved_source_sha256"], "Save stage incomplete")
    transition = r["source_transition"]
    require(type(transition["strict_save_return"]) is int and transition["strict_save_return"] == 0
            and transition["source_before_sha256"] == r["initial_source_sha256"]
            and transition["source_after_sha256"] == r["saved_source_sha256"]
            and r["saved_source_sha256"] != r["initial_source_sha256"], "Saved source transition differs")
    wall.equivalent_projection(wall.save_projection(r["generated"]), wall.save_projection(r["final"]))
    clean_events(r)
    context = original.make_context(r)
    context["generated_pocket_finish"].update(floor_candidate_included=False, bottom_finish_enabled=False,
                                              lead_apply_to_all=True, gouge_check_preserved=True)
    context["wall_apply_all_recipe"] = dict(scope=SCOPE, operation_native_id=144,
        feature_native_id=79, fields=[list(x) for x in FIELDS], restrictions=deepcopy(r["final"]["restrictions"]),
        plan_pin=deepcopy(r["plan_pin"]), geometry_acceptance_complete=False)
    return context


def load_completed(path, digest, *, process_id, expected_document_path, expected_source_sha256):
    r, pin = read_pin(path, digest)
    require(r["module_pin"] == common._pin(__file__) and r["process_id"] == process_id
            and common._key(r["source_path"]) == common._key(expected_document_path)
            and r.get("saved_source_sha256") == expected_source_sha256 == _file_hash(expected_document_path),
            "Saved candidate source/runtime/owner differs")
    for key in ("live_pins", "offline_proof_pins", "bootstrap_export_pins"):
        common._check(r[key])
    context = validate_terminal(r)
    require(r["checkpoint_digest"] == _digest(group.current_projection(context)), "Completed context digest differs")
    marker = marker_path(r["source_path"], r["initial_source_sha256"])
    actual, marker_pin = read_pin(str(marker), r["marker_pin"]["sha256"])
    require(group.exact(actual, Journal(r, path, marker).marker_state()), "Terminal once-marker differs")
    live = common._merge([x for x in r["live_pins"]
        if common._key(x["path"]) != common._key(r["checkpoint_pin"]["path"])], [pin])
    require(len(live) <= 64, "Bounded completed runtime closure required")
    context.update(pins=live, offline_export_proof_pins=common._merge(r["offline_proof_pins"],
        [r["checkpoint_pin"], marker_pin]), parent_pin=pin, group_marker_pin=marker_pin)
    return context


def audit(typelib, generated):
    from ctypes import POINTER
    from ctypes.wintypes import VARIANT_BOOL
    rows = original.audit_recipe(typelib, generated)["members"]
    cls = original.interface_class("ICWFinishMillOp3", typelib, generated)
    for name, ident, args, flags in (
        ("_get_LeadInOutApplyToAll", 129, (POINTER(VARIANT_BOOL),), (10,)),
        ("_set_LeadInOutApplyToAll", 129, (VARIANT_BOOL,), (1,)),
        ("_get_GougeCheck", 130, (POINTER(VARIANT_BOOL),), (10,)),
    ):
        members = [x for x in cls._methods_ if x.name == name]
        require(len(members) == 1, "Unique exact property required")
        original.prior.require_abi(members[0], ident, args, flags)
        rows.append(dict(interface="ICWFinishMillOp3", name=name, dispid=ident))
    require(hasattr(POINTER(cls), "_ICWFinishMillOp3__com__set_LeadInOutApplyToAll"),
            "Raw property HRESULT wrapper required")
    return dict(native_calls=0, all_resolved=True, members=rows)


def dispatch_request(request, *, validate_only=False):
    p = validate_request(request); loaded, diagnostic_pin, plan_pin = load_inputs(p)
    receipt = common._local_receipt(p["receipt_path"])
    marker = marker_path(p["expected_document_path"], p["expected_source_sha256"])
    paths = [receipt, marker] + [Path(p["progress_path"]).with_name(
        Path(p["progress_path"]).stem + "." + x + ".json")
        for x in ("apply_all_initial", "apply_all_configured", "apply_all_generated", "apply_all_saved")]
    protected = {common._key(x["path"]) for x in loaded["pins"] + loaded["offline_export_proof_pins"] + loaded["bootstrap_export_pins"]}
    protected.add(common._key(p["expected_document_path"]))
    require(len({common._key(x) for x in paths}) == len(paths)
            and not protected.intersection(common._key(x) for x in paths), "Evidence aliases input")
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),
            "Fresh evidence and candidate marker required")
    reg = common.discover_export_registration(loaded, p["addin_clsid"])
    typelib = str(Path(reg["addin_path"]).parent / "camworks.tlb")
    abi = audit(typelib, loaded["generated_pin"])
    if validate_only:
        return dict(status="validated_offline", native_called=False, setter_count=len(FIELDS),
                    live_pin_count=len(loaded["pins"]), interface_audit=abi)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=p["process_id"]):
        sw, _ = connect_solidworks(process_id=p["process_id"], launch_new_instance=False, wait_seconds=1)
        r = dict(scope=SCOPE, status="prepared", phase="prepared", process_id=p["process_id"],
            source_path=p["expected_document_path"], initial_source_sha256=p["expected_source_sha256"],
            module_pin=common._pin(__file__), checkpoint_pin=loaded["parent_pin"], diagnostic_pin=diagnostic_pin,
            plan_pin=plan_pin, loaded_context_before=loaded, live_pins=loaded["pins"],
            offline_proof_pins=loaded["offline_export_proof_pins"], bootstrap_export_pins=loaded["bootstrap_export_pins"],
            actions={}, mutation_attempted=False, model_saved=False, readback_verified=False,
            configuration_readback_verified=False, initial_full_capture_verified=False,
            generation_verified=False,
            interface_audit=abi, **{key: False for key in FORBIDDEN})
        journal = Journal(r, receipt, marker); _write_receipt(receipt, r, create=True)
        backend = NativeBackend(loaded, p, sw, reg["clsid"], typelib, r, journal.persist)
        run_backend(backend, journal, loaded)
        try:
            for key in ("pins", "offline_export_proof_pins", "bootstrap_export_pins"):
                common._check(loaded[key])
            r["phase_proofs_verified"] = True
            if r.get("status") == "saved_generated_review_required":
                context = validate_terminal(r)
                r["checkpoint_digest"] = _digest(group.current_projection(context)); journal.persist()
                r["marker_pin"] = common._pin(marker); journal.persist()
                require(r["marker_pin"]["sha256"] == _file_hash(marker), "Stable terminal marker required")
        except Exception as exc:
            r.update(status="uncertain", readback_verified=False, phase_proof_error=_error(exc))
        journal.persist(); return r


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(args.request).read_text(encoding="utf-8-sig")), validate_only=args.validate_only)
    print(json.dumps({key: result.get(key) for key in ("status", "readback_verified", "model_saved",
        "generation_verified", "generated_record_counts", "saved_source_sha256", "issue", "native_called")}, ensure_ascii=False))
    return 0 if result.get("readback_verified") is True or result.get("status") == "validated_offline" else 1


if __name__ == "__main__":
    raise SystemExit(main())
