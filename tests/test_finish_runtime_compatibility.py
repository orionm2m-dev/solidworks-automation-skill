"""Two-file compatibility rejects unrelated changes and preserves historical bytes."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_finish_runtime_compatibility as m

@pytest.fixture
def records(tmp_path):
    r={k:[] for k in ('live_pins','offline_proof_pins','bootstrap_export_pins')};rep={}
    for name,role in m.NAMES.items():
        archive=tmp_path/('historical_'+name);archive.write_bytes(b'old code never executed')
        current=tmp_path/name;current.write_bytes(b'new code never executed')
        historical={'path':str(current),'sha256':m._file_hash(archive)}
        row=dict(name=name,role=role,historical_pin=historical,archive_pin=m.common._pin(archive),current_pin=m.common._pin(current))
        r[role].append(deepcopy(historical));rep[name]=row
    other=tmp_path/'third.py';other.write_bytes(b'unchanged');r['live_pins'].append(m.common._pin(other))
    return r,rep,other

def test_lists_resolve_exact_two_without_mutating_history(records):
    r,rep,other=records;before=deepcopy(r);out=m.checked_lists(r,rep)
    assert r==before
    assert out['live_pins'][0]==rep['sw_cam_comtypes.py']['current_pin']
    assert out['offline_proof_pins'][0]==rep['sw_cam_operation_profile.py']['archive_pin']

@pytest.mark.parametrize('kind',['third_file','old_archive','new_file','duplicate','wrong_role','extra_version','missing'])
def test_no_broad_rebase(records,kind):
    r,rep,other=records
    if kind=='third_file':other.write_bytes(b'changed')
    if kind=='old_archive':Path(rep['sw_cam_operation_profile.py']['archive_pin']['path']).write_bytes(b'changed')
    if kind=='new_file':Path(rep['sw_cam_comtypes.py']['current_pin']['path']).write_bytes(b'changed')
    if kind=='duplicate':r['live_pins'].append(deepcopy(r['live_pins'][0]))
    if kind=='wrong_role':r['bootstrap_export_pins'].append(r['live_pins'].pop(0))
    if kind=='extra_version':r['live_pins'][0]['sha256']='0'*64
    if kind=='missing':r['offline_proof_pins']=[]
    with pytest.raises(ValueError):m.checked_lists(r,rep)

def files(tmp_path,old,new):
    a=tmp_path/'old.py';b=tmp_path/'new.py';a.write_text(old);b.write_text(new);return a,b

def bridge_sources():
    old='_INTERFACES = {"Existing": "old-iid"}\ndef old_helper():\n    return 1\n'
    new='_INTERFACES = '+repr(dict(Existing='old-iid',**m.ADDED_INTERFACES))+'\ndef old_helper():\n    return 1\n'
    return old,new

def test_registry_additions_are_exact(tmp_path):
    a,b=files(tmp_path,*bridge_sources());assert m.verify_source_change('sw_cam_comtypes.py',a,b)['old_helpers_unchanged']

@pytest.mark.parametrize('kind',['changed_old_iid','changed_helper','third_iid','wrong_new_iid','top_level_effect'])
def test_incompatible_bridge_rejected(tmp_path,kind):
    old,new=bridge_sources()
    if kind=='changed_old_iid':new=new.replace('old-iid','changed-iid')
    if kind=='changed_helper':new=new.replace('return 1','return 2')
    if kind=='third_iid':new=new.replace("{'Existing'","{'Extra':'x', 'Existing'")
    if kind=='wrong_new_iid':new=new.replace(m.ADDED_INTERFACES['ICWDrillTool'],'wrong')
    if kind=='top_level_effect':new+='old_helper()\n'
    a,b=files(tmp_path,old,new)
    with pytest.raises(ValueError):m.verify_source_change('sw_cam_comtypes.py',a,b)

def profile_sources():
    old='def _integer(x):\n    return int(x)\ndef _read_tool(raw):\n    result={}\n    result["turn_tool_type_raw"]=raw\n    return result\ndef inspect_operation_profile():\n    pass\n'
    new='def _integer(x):\n    return int(x)\ndef _read_tool(raw, *, include_drill=False):\n    result={}\n    result["turn_tool_type_raw"]=raw\n    if result["turn_tool_type_raw"]==2 and include_drill:\n        return {"opt_in":True}\n    return result\ndef _read_drill_operation():\n    pass\ndef inspect_operation_profile():\n    pass\n'
    return old,new

def test_shared_profile_default_branch_exact(tmp_path):
    a,b=files(tmp_path,*profile_sources());v=m.verify_source_change('sw_cam_operation_profile.py',a,b)
    assert v['include_drill_default'] is False and v['full_profile_entrypoint_equivalence_claimed'] is False

@pytest.mark.parametrize('kind',['default_true','helper_changed','default_branch_changed','new_import','top_level_effect','guard_widened'])
def test_incompatible_profile_rejected(tmp_path,kind):
    old,new=profile_sources()
    if kind=='default_true':new=new.replace('include_drill=False','include_drill=True')
    if kind=='helper_changed':new=new.replace('return int(x)','return float(x)')
    if kind=='default_branch_changed':new=new.replace('return result','return None')
    if kind=='new_import':new='import arbitrary\n'+new
    if kind=='top_level_effect':new+='inspect_operation_profile()\n'
    if kind=='guard_widened':new=new.replace('==2 and include_drill','==2 or include_drill')
    a,b=files(tmp_path,old,new)
    with pytest.raises(ValueError):m.verify_source_change('sw_cam_operation_profile.py',a,b)

def test_regression_evidence_requires_nonempty_pass(tmp_path):
    p=tmp_path/'tests.xml';p.write_text('<testsuites><testsuite tests="4" failures="0" errors="0"/></testsuites>')
    assert m.verify_regression(m.common._pin(p))==4
    p.write_text('<testsuites><testsuite tests="4" failures="1" errors="0"/></testsuites>')
    with pytest.raises(ValueError):m.verify_regression(m.common._pin(p))

@pytest.fixture
def evidence(tmp_path,monkeypatch):
    from scripts import sw_cam_comtypes,sw_cam_operation_profile
    source=tmp_path/'part.sldprt';source.write_bytes(b'synthetic saved part')
    report=tmp_path/'parent.json';report.write_text('{}');parentpin=m.common._pin(report)
    regression=tmp_path/'tests.xml';regression.write_text('<testsuite tests="1" errors="0" failures="0"/>')
    r={k:[] for k in ('live_pins','offline_proof_pins','bootstrap_export_pins')}
    r.update(source_path=str(source),saved_source_sha256=m._file_hash(source))
    replacements=[]
    for name,role,source_pair,module in [
        ('sw_cam_comtypes.py','live_pins',bridge_sources(),sw_cam_comtypes),
        ('sw_cam_operation_profile.py','offline_proof_pins',profile_sources(),sw_cam_operation_profile)]:
        a=tmp_path/('archive_'+name);b=tmp_path/name
        a.write_text(source_pair[0]);b.write_text(source_pair[1]);monkeypatch.setattr(module,'__file__',str(b))
        old={'path':str(b),'sha256':m._file_hash(a)};r[role].append(old)
        replacements.append(dict(name=name,role=role,historical_pin=deepcopy(old),archive_pin=m.common._pin(a),current_pin=m.common._pin(b)))
    e=dict(scope=m.SCOPE,status='compatible_for_finish_definition',native_called=False,historical_code_executed=False,
        parent_receipt_pin=deepcopy(parentpin),source_pin=m.common._pin(source),verifier_pin=m.common._pin(m.__file__),
        regression_pin=m.common._pin(regression),replacements=replacements)
    return e,r,parentpin

def test_complete_evidence_binding(evidence):
    e,r,p=evidence;assert set(m.validate_evidence(e,r,p))==set(m.NAMES)

@pytest.mark.parametrize('kind',['old_archive','new_bytes','parent','source','verifier','role','duplicate','historical_hash','bad_status','failed_regression'])
def test_evidence_rejects_unbound_compatibility(evidence,kind):
    e,r,p=evidence
    if kind=='old_archive':Path(e['replacements'][0]['archive_pin']['path']).write_text('changed')
    if kind=='new_bytes':Path(e['replacements'][0]['current_pin']['path']).write_text('changed')
    if kind=='parent':e['parent_receipt_pin']['sha256']='0'*64
    if kind=='source':e['source_pin']['sha256']='0'*64
    if kind=='verifier':e['verifier_pin']['sha256']='0'*64
    if kind=='role':e['replacements'][0]['role']='offline_proof_pins'
    if kind=='duplicate':e['replacements'][1]=deepcopy(e['replacements'][0])
    if kind=='historical_hash':e['replacements'][0]['historical_pin']['sha256']='0'*64
    if kind=='bad_status':e['status']='unverified'
    if kind=='failed_regression':Path(e['regression_pin']['path']).write_text('<testsuite tests="1" failures="1"/>')
    with pytest.raises(ValueError):m.validate_evidence(e,r,p)


def test_prepare_evidence_writes_only_new_receipt(evidence,tmp_path):
    import json
    e,r,p=evidence
    Path(p['path']).write_text(json.dumps(r));parentpin=m.common._pin(p['path'])
    archives={row['name']:row['archive_pin']['path'] for row in e['replacements']}
    target=tmp_path/'compatibility.json';before=Path(p['path']).read_bytes()
    actual=m.prepare_evidence(parentpin['path'],parentpin['sha256'],archives=archives,regression_pin=e['regression_pin'],output_path=str(target))
    assert actual==m.common._pin(target) and Path(p['path']).read_bytes()==before
    with pytest.raises(ValueError):m.prepare_evidence(parentpin['path'],parentpin['sha256'],archives=archives,regression_pin=e['regression_pin'],output_path=str(target))
