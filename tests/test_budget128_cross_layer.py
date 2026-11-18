"""Independent synthetic capacity/lineage tests. No native application or receipts."""
from copy import deepcopy
from pathlib import Path
import hashlib, importlib.util, os, sys
import pytest
RT=Path(os.environ['SWMCP_RUNTIME_ROOT'])
STAGE=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(RT))
import scripts
if str(STAGE/'scripts') not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_current_pocket_context_v2 as c2
from scripts import sw_cam_current_pocket_context as legacy
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_operation_guard import SolidWorksDocumentMismatch
spec=importlib.util.spec_from_file_location('budget128_legacy_probe',RT/'tests/test_current_pocket_context.py')
legacy_fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy_fixture)

def pin(path):return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
def pins(tmp_path,n):
    out=[]
    for i in range(n):
        p=tmp_path/('pin_%03d.bin'%i);p.write_bytes(('bounded-%03d'%i).encode());out.append(pin(p))
    return out

def keys(rows):return {(legacy.definition.creator.canonical(p['path']),p['sha256'])for p in rows}

class Model:
    def __init__(self,path):self.path=str(path);self.dirty=False
    def GetPathName(self):return self.path
    def GetTitle(self):return Path(self.path).name
    def GetType(self):return 1
    def GetSaveFlag(self):return self.dirty
class SW:
    def __init__(self,path):self.ActiveDoc=Model(path);self.pid=123
    def GetProcessID(self):return self.pid

def guard(tmp_path,n,**options):
    rows=pins(tmp_path,n);sw=SW(rows[0]['path']);calls=[]
    expected=dict(path=rows[0]['path'],title=Path(rows[0]['path']).name,type=1,needs_save=False)
    def files():
        calls.append('files')
        assert all(pin(Path(p['path']))['sha256']==p['sha256']for p in rows)
    g=ScopedCamDispatchGuard(sw,'offline-unused.tlb',process_id=123,expected_document=expected,
        source_sha256=rows[0]['sha256'],evidence_pins=rows,verify_evidence=files,
        verify_owned_process=lambda:calls.append('owned'),check_events=lambda:calls.append('events'),**options)
    return g,sw,rows,calls

@pytest.mark.parametrize('n',[1,64])
def test_default_guard_still_accepts_legacy_capacity(tmp_path,n):
    g,_,_,_=guard(tmp_path,n)
    with g:g._boundary()
    assert g.summary()['unique_file_count']==n

def test_default_guard_rejects_65_before_any_callbacks(tmp_path):
    with pytest.raises(ValueError):guard(tmp_path,65)

@pytest.mark.parametrize('n',[65,68,128])
def test_explicit_guard_accepts_each_complete_pin_and_boundaries(tmp_path,n):
    g,_,rows,calls=guard(tmp_path,n,evidence_pin_limit=128)
    with g:g._boundary()
    assert g.summary()['unique_file_count']==n
    assert g.summary()['content_hash_reads']>=2*n
    assert calls.count('owned')>=2
    assert len(rows)==n

def test_explicit_guard_rejects_129(tmp_path):
    with pytest.raises(ValueError):guard(tmp_path,129,evidence_pin_limit=128)

@pytest.mark.parametrize('limit',[True,False,0,65,127,129,128.0,'128',None])
def test_guard_limit_requires_exact_explicit_supported_integer(tmp_path,limit):
    with pytest.raises(ValueError):guard(tmp_path,1,evidence_pin_limit=limit)

@pytest.mark.parametrize('n',[64,68,128])
def test_context_unique_capacity_preserves_every_pin(tmp_path,n):
    rows=pins(tmp_path,n);assert keys(c2._pins(rows))==keys(rows)
    assert keys(c2.pin_union(rows,rows))==keys(rows)

def test_context_rejects_129_unique_and_conflict_before_dedup(tmp_path):
    rows=pins(tmp_path,129)
    with pytest.raises(ValueError):c2._pins(rows)
    with pytest.raises(ValueError):c2.pin_union(rows)
    conflict=dict(rows[0],sha256='0'*64)
    with pytest.raises(ValueError):c2.pin_union(rows[:68],[conflict])

def test_alias_dedup_preserves_hash_and_legacy_raw_bound(tmp_path):
    rows=pins(tmp_path,64);alias=dict(rows[0],path=rows[0]['path'].upper())
    assert keys(c2.pin_union(rows,[alias]))==keys(rows)
    with pytest.raises(ValueError):legacy._pins(rows+[alias])
    with pytest.raises(ValueError):c2.pin_union(rows,[dict(alias,sha256='0'*64)])

def test_final_full_hash_rejects_metadata_preserving_rewrite(tmp_path):
    g,_,rows,_=guard(tmp_path,68,evidence_pin_limit=128);p=Path(rows[-1]['path'])
    with g:
        stat=p.stat();old=p.read_bytes();p.write_bytes(b'X'*len(old));os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with pytest.raises(ValueError):g._boundary()

@pytest.mark.parametrize('fault',['pid','document','dirty','owned_lifetime','event'])
def test_changed_boundary_prevents_mutation_callback(tmp_path,fault):
    g,sw,_,_=guard(tmp_path,68,evidence_pin_limit=128);invoked=[];pending=[]
    with g:
        if fault=='pid':sw.pid=124
        elif fault=='document':sw.ActiveDoc.path=str(tmp_path/'foreign.sldprt')
        elif fault=='dirty':sw.ActiveDoc.dirty=True
        elif fault=='owned_lifetime':g.verify_owned_process=lambda:(_ for _ in ()).throw(ValueError('lifetime changed'))
        else:g.check_events=lambda:(_ for _ in ()).throw(ValueError('event'))
        with pytest.raises((ValueError,SolidWorksDocumentMismatch)):g.dispatch_once(lambda:invoked.append(1),persist_pending=lambda:pending.append(1))
    assert invoked==[] and pending==[]

def test_dispatch_once_keeps_durable_order_and_no_replay(tmp_path):
    g,_,_,_=guard(tmp_path,68,evidence_pin_limit=128);order=[]
    with g:
        assert g.dispatch_once(lambda:(order.append('invoke'),0)[1],persist_pending=lambda:order.append('pending'))==0
        with pytest.raises(ValueError):g.dispatch_once(lambda:order.append('replay'),persist_pending=lambda:None)
    assert order==['pending','invoke']

@pytest.fixture
def expanded_flow(tmp_path):
    # Make one genuine synthetic v1 callback Save first, then load its actual
    # fixture receipt. This produces the two-entry lineage used by recovery.
    p=legacy_fixture.probe.__wrapped__(tmp_path)
    first=legacy_fixture.run(p);request=legacy_fixture.terminal(p,first,'legacy_saved_fixture.json')
    loaded=legacy.load_current_baseline(request)
    extra=pins(tmp_path,64)
    loaded['root_pins'].extend(deepcopy(extra[:53]))
    loaded['context']['pins'].extend(deepcopy(extra))
    loaded['pins']=loaded['context']['pins']
    assert len(loaded['root_pins'])==55 and len(loaded['context']['pins'])==68
    p['bundle']=loaded;p['expected']=dict(inventory=deepcopy(loaded['state']),parameters=deepcopy(loaded['parameters']))
    p['observed'].clear();p['observed'].update(deepcopy(p['expected']));p['report'].clear();p['calls'].clear()
    def save():p['calls'].append('save');p['target'].write_bytes(b'after_v2_fixture');return 0
    p['kw']['save']=save
    return p

def run_v2(p):
    b=c2.save_bundle_for_context(p['bundle'])
    return c2.save_current_baseline(p['report'],b,p['expected'],**p['kw'])

def test_68_full_pin_Save_roundtrip_retains_every_immutable_authority(expanded_flow):
    p=expanded_flow;before=keys(p['bundle']['context']['pins']);target=legacy.definition.creator.canonical(str(p['target']))
    original=deepcopy(p['bundle']);b=c2.save_bundle_for_context(p['bundle'])
    assert p['bundle']==original and keys(b['context']['pins'])==before
    assert len(b['root_pins'])==1
    out=run_v2(p);assert len(out['payload']['root_pins'])==66
    assert out['payload']['scope']==c2.SCOPE and p['calls'].count('save')==1
    request=legacy_fixture.terminal(p,out,'v2_saved_fixture.json');loaded=c2.load_current_baseline(request)
    assert len(loaded['context']['pins'])==69
    assert {p for p in before if p[0]!=target}<=keys(loaded['context']['pins'])
    assert loaded['state']==out['state'] and loaded['parameters']==out['parameters']
    assert loaded['context']['creator']['status']=='uncertain'
    assert loaded['context']['expected_source_sha256']==hashlib.sha256(p['target'].read_bytes()).hexdigest()

@pytest.mark.parametrize('fault',['dropped_root','changed_root','GTP_flag','automatic_replay','unverified','source','predecessor'])
def test_v2_loader_rejects_bad_authority_after_large_Save(expanded_flow,fault):
    p=expanded_flow;out=run_v2(p);request=legacy_fixture.terminal(p,out,'v2_negative_fixture.json');r=p['report']
    if fault=='dropped_root':r['current_context']['root_pins']=r['current_context']['root_pins'][1:]
    elif fault=='changed_root':r['current_context']['root_pins'][0]['sha256']='0'*64
    elif fault=='GTP_flag':r['GTP_attempted']=True
    elif fault=='automatic_replay':r['automatic_replay']=True
    elif fault=='unverified':r['current_context_verified']=False
    elif fault=='source':p['target'].write_bytes(b'foreign content')
    elif fault=='predecessor':r['current_context']['predecessor_pin']['sha256']='0'*64
    if fault!='source':request['current_context_receipt_sha256']=legacy_fixture.write(Path(request['current_context_receipt_path']),r)['sha256']
    with pytest.raises(ValueError):c2.load_current_baseline(request)

def test_save_bundle_missing_original_root_rejects_before_Save(expanded_flow):
    p=expanded_flow;removed=p['bundle']['root_pins'][-1]
    p['bundle']['context']['pins']=[x for x in p['bundle']['context']['pins']if keys([x])!=keys([removed])]
    with pytest.raises(ValueError):run_v2(p)
    assert 'save'not in p['calls']


def test_reserved_slots_allow_exact_128_loaded_context(expanded_flow,tmp_path):
    p=expanded_flow;more=tmp_path/'reserved';more.mkdir()
    p['bundle']['context']['pins'].extend(pins(more,59))
    assert len(p['bundle']['context']['pins'])==127
    out=run_v2(p)
    assert len(out['payload']['root_pins'])==125
    request=legacy_fixture.terminal(p,out,'max_v2_fixture.json')
    assert len(c2.load_current_baseline(request)['context']['pins'])==128

def test_save_reserve_rejects_future_129_before_Save(expanded_flow,tmp_path):
    p=expanded_flow;more=tmp_path/'reserve_over';more.mkdir()
    p['bundle']['context']['pins'].extend(pins(more,60))
    assert len(p['bundle']['context']['pins'])==128
    with pytest.raises(ValueError,match='Reserve slots'):run_v2(p)
    assert 'save'not in p['calls']


def test_versioned_71_pin_Save_roundtrip_keeps_three_new_namespace_pins(expanded_flow,tmp_path):
    p=expanded_flow;more=tmp_path/'versioned_new_namespaces';more.mkdir()
    added=pins(more,3);p['bundle']['context']['pins'].extend(added)
    original=keys(p['bundle']['context']['pins']);assert len(original)==71
    out=run_v2(p);assert len(out['payload']['root_pins'])==69
    request=legacy_fixture.terminal(p,out,'versioned71_v2_fixture.json')
    loaded=c2.load_current_baseline(request)
    assert len(loaded['context']['pins'])==72
    target=legacy.definition.creator.canonical(str(p['target']))
    assert {x for x in original if x[0]!=target}<=keys(loaded['context']['pins'])
    assert keys(added)<=keys(loaded['root_pins'])
