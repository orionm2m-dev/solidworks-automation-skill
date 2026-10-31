"""Explicit pointer storage, narrow plane selection, and retained-guard tests."""
from copy import deepcopy
from ctypes import c_double,c_long
import importlib.util
from pathlib import Path
from types import SimpleNamespace as Node
import os
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_chamfer_clearance_read as m
spec=importlib.util.spec_from_file_location('clearance_guard_fixture',ROOT/'tests/test_chamfer_nc_planes.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
case=fixture.case


def pointer_object(distance=20.,basis=0,return_value=0,*,write_distance=True,write_basis=True):
    calls=[]
    def call(d,b):
        calls.append((d,b))
        assert type(d._obj) is c_double and type(b._obj) is c_long
        assert d._obj.value!=d._obj.value and b._obj.value==m.SENTINEL_LONG
        if write_distance:d._obj.value=distance
        if write_basis:b._obj.value=basis
        return return_value
    result=Node()
    for name in m.POINTER_FIELDS:setattr(result,'_ICWNCParam__com_'+name,call)
    return result,calls


@pytest.mark.parametrize('name',list(m.POINTER_FIELDS))
def test_exact_owned_storage_and_hresult(name):
    obj,calls=pointer_object();diag={}
    result=m.pointer_value(obj,name,diag)
    assert result['distance_native']==20. and result['basis_raw']==0 and result['hresult']==0
    assert diag['outputs_validated'] is True and len(calls)==1
    assert result['unit_binding_verified'] is result['enum_binding_verified'] is False


@pytest.mark.parametrize('value',[1,True,0.,None,-1])
def test_non_strict_s_ok_rejected(value):
    obj,calls=pointer_object(return_value=value);diag={}
    with pytest.raises(ValueError):m.pointer_value(obj,'GetClrPlanePrms',diag)
    assert len(calls)==1 and diag['returned'] and not diag['outputs_validated']


@pytest.mark.parametrize('opts',[{'write_distance':False},{'write_basis':False},{'distance':float('inf')},
    {'distance':float('nan')},{'basis':m.SENTINEL_LONG}])
def test_untouched_or_nonfinite_outputs_rejected(opts):
    obj,calls=pointer_object(**opts)
    with pytest.raises(ValueError):m.pointer_value(obj,'GetRpdPlnPrms',{})
    assert len(calls)==1


def test_exception_is_not_retried_and_prefix_is_retained():
    calls=[]
    def fail(*a):calls.append(1);raise RuntimeError('COM failure')
    obj=Node(_ICWNCParam__com_GetClrPlanePrms=fail);diag={}
    with pytest.raises(RuntimeError):m.pointer_value(obj,'GetClrPlanePrms',diag)
    assert calls==[1] and diag['attempted'] and not diag['returned']


def test_helper_reads_only_two_pointer_and_setup_fields_once():
    owner,calls=pointer_object();owner.GetClrPlaneUseSetupStatus=True;owner.GetRpdPlaneUseSetupStatus=False
    op=Node(IGetNCParam=lambda:owner)
    setup=Node(ClearancePlaneType=1,ClearancePlaneDistance=20.,RapidPlaneType=2,RapidPlaneDistance=1.)
    gets=[];queries=[];diag={}
    def read(obj,name,*a):gets.append(name);return m._member(obj,name,*a)
    def typed(obj,name):queries.append(name);return obj
    result=m.read_plane_parameters(op,setup,read=read,typed=typed,pointer_read=m.pointer_value,diagnostic=diag)
    assert len(calls)==2 and gets==['IGetNCParam',*m.USE_SETUP,*m.SETUP_FIELDS]
    assert queries==['ICWMillOperation','ICWNCParam','ICWOpSetup3']
    assert result['effective_selection']=={'clearance':'setup','rapid':'operation'}
    assert result['effective_world_plane_computed'] is False and diag['complete']
    assert 'FeedPlaneType' not in gets and 'IGetLeadin' not in gets


def test_second_pointer_failure_keeps_first_result():
    owner,calls=pointer_object();owner.GetClrPlaneUseSetupStatus=True;owner.GetRpdPlaneUseSetupStatus=True
    owner._ICWNCParam__com_GetRpdPlnPrms=lambda *a:None
    diag={};op=Node(IGetNCParam=lambda:owner)
    with pytest.raises(ValueError):
        m.read_plane_parameters(op,Node(),read=m._member,typed=lambda obj,name:obj,
                                pointer_read=m.pointer_value,diagnostic=diag)
    assert diag['complete'] is False and set(diag['partial']['local_planes'])=={'GetClrPlanePrms'}


def batch(case,**overrides):
    args=dict(process_id=123,expected_document=deepcopy(case.ident),source_sha256=m._file_hash(case.source),
        evidence_pins=[m.common._pin(case.proof)],verify_evidence=lambda:None,verify_owned_process=lambda:None,
        check_events=lambda:None,retained_objects=(case.doc,),verify_retained_binding=lambda:None,
        max_native_calls=3,generated_pin={})
    args.update(overrides)
    return m.ReadBatch(Node(GetProcessID=lambda:123,ActiveDoc=Node(
        GetPathName=lambda:case.ident['path'],GetTitle=lambda:case.ident['title'],
        GetType=lambda:case.ident['type'],GetSaveFlag=lambda:case.ident['needs_save'])), 'unused',**args)


def test_pointer_read_inside_actual_guard(case):
    obj,calls=pointer_object();case.doc._ICWNCParam__com_GetClrPlanePrms=obj._ICWNCParam__com_GetClrPlanePrms
    b=batch(case)
    with b:r=b.plane(case.doc,'GetClrPlanePrms',{})
    assert b.require_complete() and r['distance_native']==20. and len(calls)==1


@pytest.mark.parametrize('failure',['unretained','unknown','budget','dirty'])
def test_pointer_guard_rejects_invalid_scope(case,failure):
    obj,_=pointer_object();case.doc._ICWNCParam__com_GetClrPlanePrms=obj._ICWNCParam__com_GetClrPlanePrms
    b=batch(case,max_native_calls=1)
    with pytest.raises(ValueError):
        with b:
            if failure=='unknown':b.plane(case.doc,'SetClrPlanePrms',{})
            elif failure=='unretained':b.plane(obj,'GetClrPlanePrms',{})
            else:
                b.plane(case.doc,'GetClrPlanePrms',{})
                if failure=='budget':b.plane(case.doc,'GetClrPlanePrms',{})
                else:case.ident['needs_save']=True
    with pytest.raises(ValueError):b.require_complete()


def test_setup_binding_uses_saved_enumeration_not_guessed_kind(case):
    def col(values):return Node(Count=len(values),Item=lambda n:values[n])
    setups=[Node(ident=i) for i in (93,94,95)]
    setups[0].IGetEnumOperations=lambda:col([Node(ident=v['native_id']) for v in case.loaded['state']['operations']])
    machine=Node(MachType=1,IGetEnumOpSetups=lambda:col(setups));case.doc.IGetMachine=lambda:machine
    case.loaded['state']['operation_setups']=[{'native_id':i} for i in (93,94,95)]
    for row in case.loaded['state']['operations']:row['setup_native_id']=93
    result,raw=m.read_setup_binding(case.doc,case.loaded,read=m._member,typed=lambda obj,name:obj)
    assert result['setup_native_id']==93 and result['operation_ids'][-1]==271 and raw is setups[0]
    setups[0].IGetEnumOperations=lambda:col([Node(ident=271)])
    with pytest.raises(ValueError):m.read_setup_binding(case.doc,case.loaded,read=m._member,typed=lambda obj,name:obj)
