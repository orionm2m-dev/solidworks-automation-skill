"""Pure source-transition regressions; optional saved project fixtures."""
from copy import deepcopy
from pathlib import Path
import os,sys,json
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT))
import scripts
if not(ROOT/'scripts/sw_cam_long_cut_tool_definition.py').is_file():scripts.__path__.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scripts import sw_cam_long_cut_tool_definition as m

@pytest.fixture(scope='session')
def actual():
    d=evidence_root('SW_CAM_ROOT_REST_EVIDENCE_ROOT')
    request=json.loads(required_evidence(d,'root_rest_tool_definition_20261101/REQUEST_READY.json').read_text(encoding='utf-8'))
    old=json.loads(Path(request['params']['checkpoint_receipt_path']).read_text(encoding='utf-8'))
    fresh=json.loads((d/'deep_guide_group_fix_20261102/ACTUAL_DEEP_SAVED_NATIVE.json').read_text(encoding='utf-8'))
    legacy=m.saved.validate_terminal(old)
    current={'guide_parameters':{'expected_parameters':fresh['saved'],'document':fresh['saved_checkpoint_context']['document']},'ownership':fresh['ownership']}
    return legacy,old,current,fresh


def test_actual_nine_unchanged_and_seventeen_transferred(actual):
    args=deepcopy(actual);out=m.compatible_context(*args)
    assert out['state']['operation_count']==17
    assert out['state']['operation_counts']==[17,0,0]
    assert out['ownership']==args[3]['ownership']
    assert out['source_sha256']==args[3]['saved_source_sha256']
    assert out['neck_tool_candidate']==args[0]['neck_tool_candidate']
    assert out['state']['features']==args[0]['state']['features']
    assert len(out['long_cut_initial_catalogue'])==19
    assert args==actual

@pytest.mark.parametrize('damage',['old_path','old_tool','old_link','old_suppressed','old_order','catalogue_id','catalogue_order','guide_missing','parameters_missing','current_path'])
def test_incompatible_transition_rejected(actual,damage):
    a=deepcopy(actual);binding=a[2]['guide_parameters']['expected_parameters']['binding']
    if damage=='old_path':binding['operations'][8]['toolpath_record_counts']=[2285]
    elif damage=='old_tool':binding['operations'][8]['assigned_tool']['protrusion_native']=25.
    elif damage=='old_link':binding['operations'][8]['linked_feature_ids']=[80]
    elif damage=='old_suppressed':binding['operations'][8]['suppressed']=True
    elif damage=='old_order':binding['operations'][6],binding['operations'][7]=binding['operations'][7],binding['operations'][6]
    elif damage=='catalogue_id':a[3]['tool_catalogue_ids'][-1]=999
    elif damage=='catalogue_order':a[3]['tool_catalogue_ids'].reverse()
    elif damage=='guide_missing':binding['features'].pop('80')
    elif damage=='parameters_missing':a[2]['guide_parameters']['expected_parameters']['parameters'].pop()
    elif damage=='current_path':a[2]['guide_parameters']['document']['path']='C:/different.SLDPRT'
    with pytest.raises(ValueError):m.compatible_context(*a)
