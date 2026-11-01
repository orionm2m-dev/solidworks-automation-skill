from pathlib import Path
import importlib.util,json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import pytest
S=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('outcome_staged',S/'scripts/sw_cam_wall_outcome.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def value(generated=False,bg=True):return dict(operation_native_id=144,feature_native_id=79,tool_native_id=273,background_over_before=bg,background_over_after=bg,generated=generated,generated_for_feature=generated,record_counts=[1200] if generated else [])

@pytest.mark.parametrize('generated',[False,True])
def test_completed_both_outcomes_preserved(generated):
    assert m.status_contract(value(generated),completed=True)['generated'] is generated

@pytest.mark.parametrize('field,new',[('background_over_before',False),('background_over_after',False),('generated_for_feature',True),('record_counts',[1]),('tool_native_id',145),('operation_native_id',143),('background_over_before',1)])
def test_pending_or_inconsistent_status_cannot_save(field,new):
    v=value();v[field]=new
    with pytest.raises(ValueError):m.status_contract(v,completed=True)

def test_pending_read_can_report_without_success_claim():assert m.status_contract(value(bg=False))['background_over_before'] is False

@pytest.mark.parametrize('generated',[False,True])
def test_native_status_sequence_uses_getters_only(generated):
    from scripts import sw_cam_mill_route_context as route
    log=[];op=SimpleNamespace(ident=144);feature=SimpleNamespace(ident=79);doc=object();app=object();tp=object()
    class G:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def typed(self,obj,name):return obj
        def read(self,obj,name,*args):
            log.append(name)
            if name=='IsBackgroundProcessForGTPOver':return True
            if name=='QueryInterface':return feature
            if name in ('GetIsToolpathGenerated','GetIsToolpathGeneratedForFeature'):return generated
            if name=='IGetEnumToolpaths':return [tp] if generated else []
            if name=='RecordCount':return 1200
            if name=='GetCWObjectID':return args[0].ident,True
            raise AssertionError(name)
    b=object.__new__(m.NativeBackend);b.ctx=SimpleNamespace(app=app,guard=lambda:G());b.native={'doc':doc};b.target=lambda g,i:(op,feature)
    with patch.object(m.wall.original.prior,'_items',lambda raw,*a:raw),patch.object(route,'read_generic_tool',return_value=({'native_id':273},None)):
        assert b.outcome()==value(generated)
    assert log.count('IsBackgroundProcessForGTPOver')==2
    assert not {'GenerateToolpath','SaveActiveDocument','SetTool'}&set(log)

def test_mutators_blocked_explicitly():
    b=object.__new__(m.NativeBackend)
    for method in ('generate','assign','set_field'):
        with pytest.raises(RuntimeError):getattr(b,method)(None)

def test_status_journal_does_not_claim_save_marker(tmp_path):
    r=dict(source_path='C:/source.sldprt',initial_source_sha256='a'*64,failed_pin={},actions={},status='prepared',phase='prepared',model_saved=False,readback_verified=False)
    marker=tmp_path/'save_marker.json';j=m.Journal(r,tmp_path/'status.json',marker);j.persist()
    assert not marker.exists() and json.loads((tmp_path/'status.json').read_text())['actions']=={}


from wall_test_fixtures import failed_wall_receipt


def test_synthetic_prior_receipt_is_valid_without_project_files(monkeypatch):
    def no_live_file(*args, **kwargs):
        pytest.fail("Receipt validation must not read a file")
    prior = failed_wall_receipt()
    monkeypatch.setattr(Path, "read_text", no_live_file)
    monkeypatch.setattr(Path, "read_bytes", no_live_file)
    assert m.validate_failed(prior) is prior["loaded_context_before"]


@pytest.mark.parametrize("change", [
    "pending_action", "bool_hresult", "extra_save", "missing_lead",
    "changed_lead", "generated_stream", "wrong_issue", "event_error",
    "floor_enabled", "saved_claim",
])
def test_synthetic_prior_tampering_rejected(change):
    prior = failed_wall_receipt()
    first = prior["actions"]["field:lead_in_angle"]
    if change == "pending_action":
        first["pending"] = True
    elif change == "bool_hresult":
        first["native_return_value"] = False
    elif change == "extra_save":
        prior["actions"]["SaveActiveDocument"] = deepcopy(first)
    elif change == "missing_lead":
        del prior["actions"]["field:lead_in_angle"]
    elif change == "changed_lead":
        first["observed"] = 45.
    elif change == "generated_stream":
        prior["generated"]["state"]["operations"][-1]["toolpath_record_counts"] = [1]
    elif change == "wrong_issue":
        prior["issue"]["locations"] = []
    elif change == "event_error":
        prior["messages"]["event_count"] = 1
    elif change == "floor_enabled":
        prior["configured"]["parameters"]["144"]["finish"]["BottomFinOpt"] = True
    elif change == "saved_claim":
        prior["model_saved"] = True
    with pytest.raises(ValueError):
        m.validate_failed(prior)


def test_synthetic_receipts_have_independent_nested_state():
    first, second = failed_wall_receipt(), failed_wall_receipt()
    first["configured"]["parameters"]["144"]["finish"]["SideAllow"] = 99.
    assert second["configured"]["parameters"]["144"]["finish"]["SideAllow"] == 0.
    assert first["generated"]["parameters"]["144"]["finish"]["SideAllow"] == 0.


def test_external_prior_receipt_opt_in():
    """Optional offline compatibility check, never required for unit tests."""
    import os
    path = os.environ.get("SW_CAM_WALL_RECEIPT")
    if not path:
        pytest.skip("Set SW_CAM_WALL_RECEIPT to explicitly test a saved receipt")
    m.validate_failed(json.loads(Path(path).read_text(encoding="utf-8-sig")))
