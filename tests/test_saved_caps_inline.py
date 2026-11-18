"""Current circle branch reads only geometry, never creates the fallback plane."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from test_autodetected_pocket_contract import core,packet,body
from test_saved_caps_pocket import caps_packet


class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def _observe(self,fn):return fn()
    def _boundary(self):pass
    def read(self,obj,name,*args):
        value=getattr(obj,name)
        return value(*args) if callable(value) else value


@pytest.mark.parametrize('damage',[None,'tree','body','suppressed','plane'])
def test_inline_saved_circle_reads_twice_and_rejects_current_drift(caps_packet,monkeypatch,damage):
    from scripts import sw_cam_profile_sketch as profile
    d=core.prepare(caps_packet['v']);spec=d['spec'];reads=[]
    inverse=object();raw=SimpleNamespace(ModelToSketchTransform=SimpleNamespace(Inverse=lambda:inverse))
    feature=SimpleNamespace(GetTypeName2=lambda:'ProfileFeature',IsSuppressed=lambda:damage=='suppressed',GetSpecificFeature2=lambda:raw)
    model=SimpleNamespace(FeatureByName=lambda name:feature)
    state=dict(pid=caps_packet['v']['process_id'],path=caps_packet['v']['expected_document_path'],saved_file_sha256=caps_packet['v']['expected_source_sha256'],needs_save=False,features=deepcopy(d['caps_data']['baseline']['feature_tree']),solids=[body()],planes=[],spec=spec)
    if damage=='tree':state['features'].append({'name':'unreviewed','type':'Attribute'})
    if damage=='body':state['solids'][0]['box_m'][0]-=.01
    monkeypatch.setattr(core,'sketch_snapshot',lambda *args:(deepcopy(state),model,[]))
    monkeypatch.setattr(core,'_read_sketch',lambda *args,**kwargs:reads.append('circle') or {'entities':[{'type':'circle'}]})
    monkeypatch.setattr(profile,'_rigid_transform',lambda _:None)
    monkeypatch.setattr(profile,'_point',lambda mu,xyz,t:[xyz[0],xyz[1],xyz[2]+(.0268 if damage=='plane' else .0258)])
    ctx=SimpleNamespace(data=d,v=caps_packet['v'],r={},expected={'needs_save':False},persist=lambda:None,guard=lambda:Guard(),sw=SimpleNamespace(GetMathUtility=lambda:None))
    if damage:
        with pytest.raises(ValueError):core.verify_saved_caps_sketch(ctx)
    else:
        core.verify_saved_caps_sketch(ctx)
        assert reads==['circle','circle'] and ctx.r['saved_caps_sketch_checks'][0]['readback_verified']
        assert ctx.r['saved_caps_sketch_checks'][0]['after']['sketch_plane_geometry']['normal']==[0.,0.,1.]
        assert spec['plane_name'] not in [x['name'] for x in state['features']]


def test_saved_recovery_uses_observed_dirty_state_and_exact_suffix(caps_packet):
    from scripts import sw_cam_autodetected_pocket_recovery as recovery
    v=caps_packet['v'];d=core.prepare(v);suffix=[{'name':'CW reviewed','type':'Attribute'}]
    raw={'request':v,'post_create_document_observation':{'after':{'needs_save':False}}}
    data=dict(d,old=raw,attribute_suffix=suffix)
    ctx=recovery.ReadContext(None,'none','none',{'receipt_path':v['receipt_path']},data,{},lambda:None,lambda:None)
    assert ctx.data['initial_dirty'] is False
    assert ctx.data['caps_data']['baseline']['feature_tree']==d['caps_data']['baseline']['feature_tree']+suffix
    assert d['caps_data']['baseline']['feature_tree']!=ctx.data['caps_data']['baseline']['feature_tree']
    with pytest.raises(ValueError):ctx.create()


def test_recovery_allowlist_permits_only_added_read_getter(monkeypatch):
    from scripts import sw_cam_autodetected_pocket_recovery as recovery
    from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
    monkeypatch.setattr(ScopedCamDispatchGuard,'read',lambda self,obj,name,*args:False)
    g=object.__new__(recovery.ReadGuard)
    assert g.read(None,'IsSuppressed') is False
    with pytest.raises(ValueError):g.read(None,'SetSaveFlag')
