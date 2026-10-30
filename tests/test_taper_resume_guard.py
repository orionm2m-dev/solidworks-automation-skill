
"""Pure unit inference and guarded extension ordering; no native application."""
import importlib,os,sys
from pathlib import Path
from types import SimpleNamespace
import math
import pytest

ROOT=Path(os.environ['SOLIDWORKS_SKILL_ROOT'])
sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
m=importlib.import_module('scripts.sw_cam_taper_tool_resume')


@pytest.mark.parametrize('angle,status,accepted',[(45.,'degrees',True),
    (math.pi/4,'radians',False),(2.,'inconsistent',False),(True,'unknown_default_cone',False)])
def test_default_cone_distinguishes_units_without_normalizing_values(angle,status,accepted):
    raw=dict(EndDia=1.,MaxDia=3.,TaperLength=1.,TaperAngle=angle)
    value=m.infer_default_angle_units(raw)
    assert value['status']==status and value['degree_compatible'] is accepted
    assert value['raw']==raw and value['raw']['TaperAngle'] is angle


@pytest.mark.parametrize('key,value',[('TaperLength',0.),('EndDia',3.),('MaxDia',0.),
    ('TaperAngle',0.),('TaperLength',float('nan')),('EndDia',-1.)])
def test_zero_or_invalid_defaults_stay_unknown(key,value):
    p=dict(EndDia=1.,MaxDia=3.,TaperLength=1.,TaperAngle=45.);p[key]=value
    r=m.infer_default_angle_units(p)
    assert r['degree_compatible'] is False and r['status']=='unknown_default_cone'


def test_tiny_default_angle_is_ambiguous_and_stops():
    p=dict(EndDia=0.,MaxDia=2e-10,TaperLength=1.,TaperAngle=1e-10)
    r=m.infer_default_angle_units(p)
    assert r['degrees_match'] is True and r['radians_match'] is True
    assert r['degree_compatible'] is False and r['status']=='ambiguous'


def test_audit_failure_occurs_before_bootstrap(monkeypatch):
    b=object.__new__(m.NativeBackend)
    b.loaded={'generated_pin':{'path':'p','sha256':'h'}};b.typelib_path='tlb'
    b.report={};b.persist=lambda:None;calls=[]
    monkeypatch.setattr(m.base.NativeBackend,'start',lambda self:calls.append('bootstrap'))
    def reject(*args,**kwargs):calls.append('audit');raise ValueError('Wrong generated declaration')
    monkeypatch.setattr(m.taper,'audit_taper_interface',reject)
    with pytest.raises(ValueError):b.start()
    assert calls==['audit'] and b.interface_preflight_passed is False


def test_successful_audit_precedes_start_and_native_qi(monkeypatch):
    b=object.__new__(m.NativeBackend)
    b.loaded={'generated_pin':{'path':'p','sha256':'h'}};b.typelib_path='tlb'
    b.report={};calls=[];b.persist=lambda:calls.append('persist')
    monkeypatch.setattr(m.base.NativeBackend,'start',lambda self:calls.append('bootstrap'))
    monkeypatch.setattr(m.taper,'audit_taper_interface',lambda *a,**k:dict(all_resolved=True))
    b.start()
    assert b.interface_preflight_passed is True and calls==['persist','bootstrap']
    g=SimpleNamespace(_fast=lambda:calls.append('guard'),typed=lambda o,n:None)
    raw=object();typed=object()
    def query(obj,name,path,*,generated_pin):
        calls.append('QI');assert obj is raw and name=='ICWTaperTool'
        assert path=='tlb' and generated_pin==b.loaded['generated_pin'];return typed
    monkeypatch.setattr(m.taper,'query_taper_interface',query)
    assert b.exact_typed(g,raw,'ICWTaperTool') is typed
    assert calls[-3:]==['guard','QI','guard']


def test_no_creator_can_be_reached_from_resume():
    b=object.__new__(m.NativeBackend)
    with pytest.raises(ValueError,match='cannot create'):b.create(lambda:None,lambda x:None)


def test_native_qi_without_metadata_audit_is_blocked(monkeypatch):
    b=object.__new__(m.NativeBackend);b.interface_preflight_passed=False
    monkeypatch.setattr(m.taper,'query_taper_interface',lambda *a,**k:pytest.fail('QI must not run'))
    with pytest.raises(ValueError):b.exact_typed(None,object(),'ICWTaperTool')


def test_unsupported_requests_cannot_enable_creation():
    with pytest.raises(ValueError):m.validate_request({'action':'create_taper_candidate','params':{}})
