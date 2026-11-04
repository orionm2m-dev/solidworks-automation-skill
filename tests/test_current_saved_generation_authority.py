import json,hashlib
from copy import deepcopy
from pathlib import Path
import pytest
from scripts import sw_cam_current_saved_generation as g
from test_current_saved_generation_delta import state

def save(p,d):
    p.write_text(json.dumps(d),encoding='utf-8');return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def authority(tmp_path):
    binding=dict(process_id=123,expected_document_path=str(tmp_path/'part.sldprt'),expected_process_create_time=12.5)
    pins={k:save(tmp_path/(k+'.json'),{})for k in('request','result','authority')}
    recipe=dict(schema_version=1,rows=[dict(operation_native_id=13,feature_native_id=102,operation_type=0,expected_tool_native_id=44,existing_tool_native_id=None,fields=[dict(field="side_allowance",expected=1.0,new=0.5)])])
    pins['recipe']=save(tmp_path/'recipe.json',recipe)
    d=dict(scope=g.CONFIG_SCOPE,action='apply',status='review_required',phase='finished',binding=binding,request_pin=dict(kind='canonical_binding',sha256=g._digest(binding)),qualified_read_pins=pins,recipe=recipe,saved=state(),confirm_saved=state(),source_after_sha256='a'*64,saved_file_sha256='a'*64,GTP_attempted=False,GOP_attempted=False,native_dispatch_pending=False,save_call_returned=True,save_hresult=0,messages=dict(active=False,subscribed=True,disconnected=True,event_count=0))
    d.update({k:True for k in g.CONFIG_FLAGS})
    for name in ('saved','confirm_saved'):d[name]['operation_parameters'][0]['rough']={'boundary':{'SideAllow':{'raw':0.5}}}
    return d

def load(tmp_path,d,**overrides):
    pin=save(tmp_path/'configuration.json',d)
    args=dict(process_id=123,source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64,selected_ids=[13]);args.update(overrides)
    return g.load_completed_configuration(pin['path'],pin['sha256'],**args)

def test_complete_configuration_authority(tmp_path):
    d=authority(tmp_path);out=load(tmp_path,d);assert out['state']==d['saved']and out['selected_ids']==[13]

@pytest.mark.parametrize('flag',g.CONFIG_FLAGS+('save_call_returned',))
def test_false_authority_flag_rejected(tmp_path,flag):
    d=authority(tmp_path);d[flag]=False
    with pytest.raises(ValueError):load(tmp_path,d)

@pytest.mark.parametrize('change',[lambda d:d.update(save_hresult=True),lambda d:d.update(save_hresult=None),lambda d:d.update(native_dispatch_pending=True),lambda d:d.update(GTP_attempted=True),lambda d:d.update(source_after_sha256='b'*64),lambda d:d['saved']['document'].update(needs_save=True),lambda d:d['confirm_saved']['operations'].reverse(),lambda d:d['request_pin'].update(kind='file'),lambda d:d['request_pin'].update(sha256='f'*64),lambda d:d['messages'].update(event_count=1),lambda d:d.update(issue={})])
def test_incomplete_or_stale_authority_rejected(tmp_path,change):
    d=authority(tmp_path);change(d)
    with pytest.raises(ValueError):load(tmp_path,d)

@pytest.mark.parametrize('args',[{'process_id':124},{'selected_ids':[14]},{'selected_ids':[999]},{'source_sha256':'b'*64}])
def test_binding_change_rejected(tmp_path,args):
    with pytest.raises(ValueError):load(tmp_path,authority(tmp_path),**args)

def test_recipe_file_pin_retained(tmp_path):
    d=authority(tmp_path);Path(d['qualified_read_pins']['recipe']['path']).write_text('{}')
    with pytest.raises(ValueError):load(tmp_path,d)

def test_runtime_revoke_preserves_success_captures_and_no_new_action(tmp_path):
    from test_current_saved_generation_engine import run
    b,j,r=run(tmp_path);r.update(receipt_path=str(j.receipt),dispatch_marker_path=str(j.marker),request_sha256='e'*64)
    j.persist();actions=deepcopy(r['actions']);before=deepcopy(r['saved'])
    g.revoke_runtime(r,RuntimeError('runtime drift'))
    assert r['status']=='uncertain'and not r['runtime_unchanged']and not r['readback_verified']
    assert r['actions']==actions and r['saved']==before
    assert json.loads(j.receipt.read_text(encoding='utf-8'))['runtime_unchanged']is False

def test_runtime_revoke_does_not_overwrite_foreign_receipt(tmp_path):
    p=tmp_path/'foreign.json';pin=save(p,dict(scope='other',request_sha256='x'))
    r=dict(scope=g.SCOPE,receipt_path=str(p),receipt_created=True,request_sha256='e'*64,mutation_attempted=True)
    g.revoke_runtime(r,RuntimeError('drift'));assert hashlib.sha256(p.read_bytes()).hexdigest()==pin['sha256']
    assert 'runtime_receipt_update_error'in r


def test_actual_completed_recipe_value_must_match(tmp_path):
    d=authority(tmp_path)
    for name in ('saved','confirm_saved'):d[name]['operation_parameters'][0]['rough']['boundary']['SideAllow']['raw']=0.75
    with pytest.raises(ValueError,match='actual value'):load(tmp_path,d)
