"""Offline compact saved-caps capture and current Save/load regressions."""
from copy import deepcopy
import json
import pytest
from scripts import sw_cam_current_pocket_context as c
from test_current_pocket_context import probe, run, terminal


def caps(p):
    d=p['bundle']['context']
    d['request']['source_variant']='saved_cam_caps'
    d['origin_kind']='recovery'
    d['creator']['circle_readback']={'current_circle':23.35}
    d['sketch']['sketch_readback']={'historical_circle':23.35}
    return d


def test_legacy_compaction_keeps_exact_previous_shape(probe):
    d=probe['bundle']['context'];out=c._compact(d)
    assert set(out)==set(c.CAPTURE_KEYS)|{'request','creator','sketch'}
    assert out['request']==d['request'] and out['creator']==d['creator']
    assert out['sketch']==d['sketch'] and 'origin_kind' not in out


def test_current_save_and_load_preserve_actual_circle_origin_and_variant(probe):
    p=probe;full=caps(p);original=deepcopy(full)
    p['bundle']['context']=dict(c._compact(full),pins=full['pins'])
    out=run(p);v=terminal(p,out);loaded=c.load_current_baseline(v)
    for d in (out['payload']['capture_context'],loaded['context']):
        assert d['request']['source_variant']=='saved_cam_caps'
        assert d['origin_kind']=='recovery' and d['creator']['status']=='uncertain'
        assert d['creator']['circle_readback']==original['creator']['circle_readback']
        assert d['sketch']['sketch_readback']==original['sketch']['sketch_readback']
        assert d['creator']['circle_readback']!=d['sketch']['sketch_readback']
    assert full==original and p['calls'].count('save')==1


@pytest.fixture
def capture_case(probe,monkeypatch):
    full=caps(probe);d=c.definition
    full['spec']['sketch_name']='current_outer'
    full['expected_inventory']={'sw_reference':{},'all_solid_body_count':1,
        'cam_configuration_name':'Mill','associated_sw_configuration':'Default'}
    native_state={'cam_configuration_name':'Mill','associated_sw_configuration':'Default'}
    for key in d.OP_KEYS:
        value=[] if key in ('operation_setups','operations') else 0
        full['expected_inventory'][key]=deepcopy(value);native_state[key]=deepcopy(value)
    seen=[];current_circle=deepcopy(full['creator']['circle_readback'])
    class Guard:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def typed(self,obj,name):seen.append(('QI',name));return obj
        def read(self,obj,name,*args):
            seen.append(('read',name))
            return 'ProfileFeature' if name=='GetTypeName2' else name
        def _observe(self,callback):return callback()
        def _boundary(self):pass
    monkeypatch.setattr(d,'ScopedCamDispatchGuard',Guard)
    monkeypatch.setattr(d,'identity',lambda sw,context: {'document':deepcopy(context['saved_transition']['document']),'saved_file_sha256':context['expected_source_sha256']})
    monkeypatch.setattr(d.inventory,'capture_import_inventory',lambda *a,**k:deepcopy(native_state))
    monkeypatch.setattr(d.inventory,'_items',lambda obj,*a: ['setup'] if obj=='IGetEnumSetups' else ['feature'])
    monkeypatch.setattr(d,'_object_id',lambda *a:20)
    monkeypatch.setattr(d,'_feature_header',lambda *a:(deepcopy(full['creator']['feature_header']),'feature'))
    monkeypatch.setattr(d,'_snapshot',lambda *a:(deepcopy(full['current_sketch_baseline']),'model',None))
    monkeypatch.setattr(d,'_read_sketch',lambda *a:deepcopy(current_circle))
    return full,current_circle,seen


def do_capture(d):
    return c.definition.capture(object(),'fixed-clsid','metadata-only',d,lambda:None,{})[0]


def test_compact_context_reads_same_actual_circle_and_authority(capture_case):
    full,actual,seen=capture_case
    before=do_capture(full)
    compact=json.loads(json.dumps(c._compact(full)));compact['pins']=[]
    after=do_capture(compact)
    assert before==after
    assert after['definition_authority']['origin_kind']=='recovery'
    assert ('read','GetSpecificFeature2') in seen
    assert not any(name in {'SaveActiveDocument','GenerateToolpath','SetTool'} for _,name in seen)


def test_changed_actual_circle_is_rejected_after_compaction(capture_case):
    full,actual,seen=capture_case
    compact=c._compact(full);compact['pins']=[]
    actual['current_circle']=23.34
    with pytest.raises(ValueError,match='Native sketch circle differs'):
        do_capture(compact)


@pytest.mark.parametrize('missing',['circle_readback','origin_kind'])
def test_saved_caps_missing_actual_capture_field_is_not_legacy_fallback(probe,missing):
    full=caps(probe)
    if missing=='circle_readback':full['creator'].pop(missing)
    else:full.pop(missing)
    with pytest.raises(KeyError):c._compact(full)
