from pathlib import Path
from copy import deepcopy
import importlib.util,json,os,sys
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(R))
P=Path(__file__).resolve().parents[1]
MODULE=Path(os.environ.get('SW_CAM_LONG_CUT_FIX_MODULE',str(R/'scripts/sw_cam_long_cut_tool_definition.py')))
spec=importlib.util.spec_from_file_location('factory_guard_fix',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.fixture
def actual():
 root=evidence_root('SW_CAM_FACTORY_FAILURE_FIXTURE')
 loaded=json.loads(required_evidence(root,'FAILED_BEFORE_MUTATION_CONTEXT.json').read_text())
 receipt=json.loads(required_evidence(root,'FAILED_BEFORE_MUTATION_NATIVE.json').read_text())
 return loaded,receipt['request']


def test_real_original87_guard_constructor_rejects_without_native(actual):
 loaded,p=actual;assert len(loaded['pins'])==87
 with pytest.raises(ValueError,match='bounded complete evidence pin'):
  m.guard_constructor_preflight(p,loaded,'metadata-only')

def test_real_repartitioned64_guard_constructor_accepts_and_all_evidence_preserved(actual,monkeypatch):
 loaded,p=actual;old=deepcopy(loaded['pins']);offline=deepcopy(loaded['offline_export_proof_pins'])
 # The immutable failed source is historical. This test validates the current
 # fixed writer bytes in its place; every other old pin remains exact.
 loaded['pins']=[m.common._pin(MODULE)if Path(v['path']).name==MODULE.name else v for v in old]
 live,proof,partition=m.partition_native_pins(loaded['pins'],offline)
 assert len(live)==64 and len(partition['retired'])==23
 assert {m.common._key(v['path'])for v in loaded['pins']+offline}=={m.common._key(v['path'])for v in live+proof}
 loaded['pins']=live;result=m.guard_constructor_preflight(p,loaded,'metadata-only')
 assert result['constructor_verified']and result['native_calls']==0 and result['entered']is False
 assert result['source_and_unique_files']==65

@pytest.mark.parametrize('damage',['unknown_extra','missing_reviewed_role','duplicate_reviewed_role'])
def test_partition_rejects_unreviewed_closure(actual,monkeypatch,damage):
 loaded,p=actual;monkeypatch.setattr(m.common,'_check',lambda x:None)
 if damage=='unknown_extra':loaded['pins'].append({'path':str(P/'unexpected.py'),'sha256':'a'*64})
 elif damage=='missing_reviewed_role':loaded['pins']=[v for v in loaded['pins']if Path(v['path']).name!='installed_profile_nominal.json']
 else:loaded['pins'].append(next(v for v in loaded['pins']if Path(v['path']).name=='installed_profile_nominal.json'))
 with pytest.raises(ValueError):m.partition_native_pins(loaded['pins'],loaded['offline_export_proof_pins'])

def test_active_metadata_helpers_never_retired(actual,monkeypatch):
 loaded,p=actual;monkeypatch.setattr(m.common,'_check',lambda x:None)
 live,proof,part=m.partition_native_pins(loaded['pins'],loaded['offline_export_proof_pins'])
 names={Path(x['path']).name for x in live}
 assert {'sw_cam_fresh_finish_recipe.py','sw_cam_pocket_finish_apply.py','sw_cam_mill_units_qualification.py','sw_cam_chamfer_nc_planes.py','sw_cam_chamfer_clearance_read.py','sw_cam_feature_sketch.py'}<=names
 assert 'sw_cam_exact_cutter_reuse.py'not in names

def test_guard_preflight_rejects_wrong_current_document(actual,monkeypatch):
 loaded,p=actual;p=dict(p,expected_document_path=str(P/'different.SLDPRT'))
 with pytest.raises(ValueError,match='exact request'):m.guard_constructor_preflight(p,loaded,'metadata-only')


def test_pure_policy_has_immediate_checks_on_both_sides():
 import ast,inspect
 tree=ast.parse(inspect.getsource(m.run_backend))
 statements=next(n.body for n in ast.walk(tree)if isinstance(n,ast.Try))
 policy=next(i for i,x in enumerate(statements)if isinstance(x,ast.Assign)and isinstance(x.value,ast.Call)and isinstance(x.value.func,ast.Attribute)and x.value.func.attr=='require_new_exact_cutter')
 assert 'REUSE_POLICY_PIN'in ast.unparse(statements[policy-1])
 # Following persist is separated by a semicolon and remains its own statement.
 assert any('REUSE_POLICY_PIN'in ast.unparse(x)for x in statements[policy+1:policy+3])
