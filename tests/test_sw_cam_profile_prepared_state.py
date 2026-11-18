"""Prepared snapshot authority regressions. All native operations are mocked."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import sw_cam_profile_sketch as m
from test_mcp_cam_apt_sketch import context, cores, inputs, invoke, server

FIXTURES=Path(__file__).parent/'fixtures'
def saved(name):return json.loads((FIXTURES/name).read_text(encoding='utf-8'))
@pytest.fixture
def pair():return saved('PREPARE_PROFILE_SNAPSHOT_01.json'),saved('APPLY_PROFILE_SNAPSHOT_01.json')

def test_actual_noise_pair_old_digest_differs_existing_tolerance_accepts(pair):
    a,b=pair
    assert m._state_digest(a)=='a27dd5c39183f1ce8d0b5b000f487b76be416a3982698c74e408975c18109600'
    assert m._state_digest(b)=='b6a6dc55c3ca7c23e9fb7b1394d4bdcf603e053d01a1bc98a2f1a51929e46737'
    assert m._same_bodies(a['solids'],b['solids'])
    m._verify_expected_state(a,b,m._state_digest(a))

@pytest.mark.parametrize('index',range(12))
@pytest.mark.parametrize('factor,accept',[(1+5e-11,True),(1+2e-10,False)])
def test_every_mass_component_uses_unchanged_relative_tolerance(pair,index,factor,accept):
    a,b=pair;b=deepcopy(a);assert a['solids'][0]['mass_raw'][index]!=0
    b['solids'][0]['mass_raw'][index]*=factor
    if accept:m._verify_expected_state(a,b,m._state_digest(a))
    else:
        with pytest.raises(ValueError):m._verify_expected_state(a,b,m._state_digest(a))

def test_zero_mass_has_no_absolute_tolerance(pair):
    a,b=pair;a['solids'][0]['mass_raw'][0]=0.;b=deepcopy(a);b['solids'][0]['mass_raw'][0]=1e-300
    with pytest.raises(ValueError):m._verify_expected_state(a,b,m._state_digest(a))

@pytest.mark.parametrize('change',[
    lambda s:s.update(pid=s['pid']+1),lambda s:s.update(path=s['path']+'x.sldprt'),
    lambda s:s.update(saved_file_sha256='f'*64),lambda s:s.update(needs_save=True),
    lambda s:s['features'][0].update(name='Changed'),lambda s:s['features'][0].update(type='Changed'),
    lambda s:s['features'].reverse(),lambda s:s['planes'][0].update(name='Changed'),
    lambda s:s['planes'][0]['origin_m'].__setitem__(0,1e-30),
    lambda s:s['planes'][0]['normal'].__setitem__(0,1e-30),
    lambda s:s['planes'][0]['plane_to_model'].__setitem__(15,1e-30),
    lambda s:s['solids'][0]['box_m'].__setitem__(0,s['solids'][0]['box_m'][0]+1e-12),
    lambda s:s['spec'].update(sketch_name='Changed'),lambda s:s['spec'].update(plane_name='Changed'),
    lambda s:s['spec']['profile'].update(radius_mm=23.36),
    lambda s:s['solids'][0]['mass_raw'].append(0.),lambda s:s['solids'][0]['mass_raw'].pop(),
    lambda s:s.update(artifacts=[]),lambda s:s['solids'][0].update(extra=False),
])
def test_nonmass_and_tail_shape_changes_fail(pair,change):
    a,b=pair;b=deepcopy(a);change(b)
    with pytest.raises(ValueError):m._verify_expected_state(a,b,m._state_digest(a))

@pytest.mark.parametrize('value',[True,False,'1',None,float('nan'),float('inf'),float('-inf'),[],{}])
@pytest.mark.parametrize('where',['mass','box','plane','spec'])
def test_strict_numbers_rejected_before_comparison(pair,value,where):
    a,b=pair
    if where=='mass':a['solids'][0]['mass_raw'][0]=value
    elif where=='box':a['solids'][0]['box_m'][0]=value
    elif where=='plane':a['planes'][0]['origin_m'][0]=value
    else:a['spec']['profile']['radius_mm']=value
    with pytest.raises((ValueError,TypeError)):m._validate_expected_state(a)

@pytest.mark.parametrize('change',[
    lambda s:s.update(pid=True),lambda s:s.update(needs_save=0),lambda s:s.update(path='relative.sldprt'),
    lambda s:s.update(features=[]),lambda s:s.update(features=s['features']*513),
    lambda s:s.update(solids=s['solids']*65),lambda s:s.update(planes=tuple(s['planes'])),
    lambda s:s['solids'][0].update(mass_raw=[1.]*33),
    lambda s:s['spec']['profile'].update(center_model_mm=(0,0,25.8)),
])
def test_bounded_strict_json_shape(pair,change):
    a,b=pair;change(a)
    with pytest.raises(ValueError):m._validate_expected_state(a)

def test_expected_payload_sha_is_authority(pair):
    a,b=pair
    with pytest.raises(ValueError,match='hash'):m._verify_expected_state(a,b,'0'*64)

def stubbed_apply(pair,tmp_path,monkeypatch,include_snapshot=True,change=None):
    a,b=deepcopy(pair);part=tmp_path/'part.SLDPRT';part.write_bytes(b'offline fixture')
    for state in (a,b):state['path']=str(part.resolve());state['saved_file_sha256']=m._sha(part)
    expected=deepcopy(a);sha=m._state_digest(expected)
    if change:change(b)
    monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kw:nullcontext())
    monkeypatch.setattr(m,'_identity',lambda *args:object())
    monkeypatch.setattr(m,'_snapshot',lambda *args:(deepcopy(b),object(),[]))
    calls=[]
    def create(sw,model,before,refs,check,report):
        calls.append('create');check()
        names=[b['spec']['plane_name'],b['spec']['sketch_name']]
        b['features'] += [{'name':names[0],'type':'RefPlane'},{'name':names[1],'type':'ProfileFeature'}]
        b['needs_save']=True
        return names
    monkeypatch.setattr(m,'_create',create)
    extra={'expected_state':expected} if include_snapshot else {}
    receipt=tmp_path/'receipt.json'
    result=m.create_cam_profile_sketch(object(),expected_process_id=a['pid'],expected_document_path=str(part),
        action='apply',spec=a['spec'],expected_state_sha256=sha,receipt_path=str(receipt),**extra)
    return result,calls,receipt,expected

def test_optional_raw_snapshot_accepts_real_noise_and_persists_authority(pair,tmp_path,monkeypatch):
    r,c,p,a=stubbed_apply(pair,tmp_path,monkeypatch)
    assert r['status']=='ok' and c==['create'] and r['native_readback_verified']
    assert not r['saved'] and not r['CAD_solid_edit_attempted'] and r['CAM_calls']==0
    disk=json.loads(p.read_text(encoding="utf-8"));assert disk['expected_state']==a
    assert disk['expected_state_sha256']==m._state_digest(a)
    assert disk['prepared_state_comparison']=='exact_nonmass_fields_and_existing_same_bodies'

def test_no_payload_preserves_legacy_exact_digest_gate(pair,tmp_path,monkeypatch):
    r,c,p,a=stubbed_apply(pair,tmp_path,monkeypatch,False)
    assert r['status']=='error' and not r['mutation_attempted'] and not c and not p.exists()

def test_payload_rejects_change_before_receipt_or_creator(pair,tmp_path,monkeypatch):
    r,c,p,a=stubbed_apply(pair,tmp_path,monkeypatch,change=lambda s:s['solids'][0]['mass_raw'].__setitem__(11,-1e-12))
    assert r['status']=='error' and not r['mutation_attempted'] and not c and not p.exists()

def test_schema_and_endpoint_forward_exact_payload(context,cores,pair):
    a,b=pair;p=inputs(context,'sketch','apply',expected_state=a,expected_state_sha256=m._state_digest(a))
    invoke('sketch',p)
    assert cores.sketch.call_args.kwargs['expected_state']==a
    assert p.model_dump()['expected_state']==a

@pytest.mark.parametrize('action',['inspect','prepare','verify_existing'])
@pytest.mark.parametrize('value',[None,{}])
def test_schema_snapshot_field_is_apply_only(context,action,value):
    with pytest.raises(ValueError):inputs(context,'sketch',action,expected_state=value)

@pytest.mark.parametrize('value',[[],(),{'pid':True}])
def test_schema_does_not_coerce_payload(context,value):
    with pytest.raises(ValueError):inputs(context,'sketch','apply',expected_state=value)
