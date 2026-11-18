"""Versioned recovery capacity and fixed-flow parity; no CAD/native actions."""
import ast,copy,json,os,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];RT=Path(os.environ["SWMCP_RUNTIME_ROOT"]);sys.path.insert(0,str(RT))
import scripts
scripts.__path__.insert(0,str(ROOT/"scripts"))
from scripts import sw_cam_current_pocket_generation_recovery_v2 as c
from scripts import sw_cam_current_pocket_generation_recovery as old

def dump_node(module,name):
    return ast.dump(next(n for n in ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig")).body if getattr(n,"name",None)==name),include_attributes=False)

@pytest.mark.parametrize("name",["shape","strict_return","verify_partial","Backend","Journal","preflight","revoke"])
def test_existing_native_sequence_and_admission_exact_ast(name):
    assert dump_node(c,name)==dump_node(old,name)

def test_inherits_qualified_v2_full_captures_and_128_guard():
    assert c.Backend.capture_current is c.prior.Backend.capture_current
    assert c.Backend.guard is c.prior.Backend.guard
    assert c.prior.PIN_LIMIT==c.current.PIN_LIMIT==c.PIN_LIMIT==128
    assert c.prior.definition_capture.__name__.endswith("_v2")
    assert c.prior.SCOPE.endswith("_V2_PIN128")
    assert c.SCOPE!=old.SCOPE and c.GENERATED_SCOPE!=old.GENERATED_SCOPE

def test_save_bundle_128_preserves_every_canonical_root(tmp_path):
    pins=[dict(path=str(tmp_path/(str(i)+".json")),sha256=format(i,"064x"))for i in range(80)]
    bundle=dict(context=dict(pins=copy.deepcopy(pins),expected_document_path=str(tmp_path/"part.sldprt")),root_pins=copy.deepcopy(pins[:65]),receipt_pin=pins[-1],lineage_pins=[pins[-1]])
    saved=c.current.save_bundle_for_context(bundle)
    assert saved["context"]["pins"]==bundle["context"]["pins"]==pins
    assert saved["root_pins"]==[]
    assert len(c.current.pin_union(pins,pins))==80
    assert bundle["root_pins"]==pins[:65]
    with pytest.raises(ValueError,match="Conflicting"):
        c.current.pin_union(pins,[dict(pins[0],sha256="f"*64)])
    with pytest.raises(ValueError):
        c.current.pin_union([dict(path=str(tmp_path/(str(i)+".json")),sha256=format(i,"064x"))for i in range(129)])

def test_versioned_run_recomputes_save_bundle_after_abi():
    tree=ast.parse(Path(c.__file__).read_text(encoding="utf-8-sig"))
    run=next(n for n in tree.body if getattr(n,"name",None)=="run")
    text=ast.unparse(run)
    assert text.index("abi = preflight(tlb)")<text.index("current.pin_union")<text.index("current.save_bundle_for_context")<text.index("reader.definition.verify_files")<text.index("backend = _backend_factory")
    flow=next(n for n in tree.body if getattr(n,"name",None)=="run_backend")
    assert "data['save_bundle']" in ast.unparse(flow)
    assert "data['bundle']" not in ast.unparse(flow)

def test_actual_marker_path_matches_producer_path_conversion():
    raw=json.loads((ROOT/"tests/fixtures/observed_generation_v2_partial.json").read_text(encoding="utf-8"))
    literal=raw["request"]["receipt_path"]
    assert "/" in literal and str(Path(literal))!=literal
    expected=str(Path(literal))
    assert expected.replace(chr(92),"/")==literal
    tree=ast.parse(Path(c.__file__).read_text(encoding="utf-8-sig"))
    prepare=next(n for n in tree.body if getattr(n,"name",None)=="prepare")
    code=ast.unparse(prepare)
    assert "receipt_path=str(Path(original['receipt_path']))" in code
    assert "old_marker == expected" in code

def test_real_v2_receipt_is_never_relabelled_and_legacy_scope_rejected():
    raw=json.loads((ROOT/"tests/fixtures/observed_generation_v2_partial.json").read_text(encoding="utf-8"))
    request={k:copy.deepcopy(raw["request"][k])for k in c.IDENTITY}
    request.update(failed_generation_receipt_path="C:/cad/partial.json",failed_generation_receipt_sha256="a"*64,observed_xy_feed_before=raw["configured"]["parameters"][0]["nc"]["feeds_compensation"]["XYFeed"],observed_xy_feed_after=raw["generated"]["parameters"][0]["nc"]["feeds_compensation"]["XYFeed"],receipt_path="C:/cad/recovery.json",saved_cl_path="C:/cad/fresh/path.cl",qualification_only=True,acknowledge_observed_feed_save_export=True,message_policy="vendor_default")
    bundle=dict(state=raw["before"]["inventory"],parameters=raw["before"]["parameters"])
    proof=c.verify_partial(raw,request,bundle,raw["recipe"])
    assert proof["generation_proof"]["selected_record_count"]==21016
    assert raw["scope"]==c.prior.SCOPE and raw["status"]=="uncertain"
    with pytest.raises(ValueError,match="Exact post-generation"):
        old.verify_partial(raw,request,bundle,raw["recipe"])
