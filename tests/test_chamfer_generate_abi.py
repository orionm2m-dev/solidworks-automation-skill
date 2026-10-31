"""Write-ABI contract tests use declarations only and never call native CAM."""
from ctypes import HRESULT, c_double, c_long, c_short, POINTER
from ctypes.wintypes import VARIANT_BOOL
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from comtypes.automation import IDispatch

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', STAGE))
sys.path.insert(0, str(RUNTIME))
import scripts
scripts.__path__.insert(0, str(STAGE/'scripts'))
from scripts import sw_cam_chamfer_generate as m
from scripts import sw_cam_comtypes as typed


@pytest.fixture
def abi(monkeypatch):
    declarations = {}
    # Generated comtypes dispatch property writes carry the _set_ prefix.
    records = [
        ('ICWFinishMillOp3','SetIsChamferMachining',(VARIANT_BOOL,),False),
        ('ICWFinishMillOp3','SetChamferType',(c_long,),False),
        ('ICWFinishMillOp3','SetChamferLength',(c_double,),False),
        ('ICWFinishMillOp3','SetChamferClearance',(c_double,),False),
        ('ICWFinishMillOp','_set_SideAllow',(c_double,),True),
        ('ICWFinishMillOp','_set_DepthAllow',(c_double,),True),
        ('ICWFinishMillOp','_set_SpringPass',(c_long,),True),
        ('ICWMillOperation3','SetOverrideMachiningDepth',(POINTER(IDispatch),VARIANT_BOOL),False),
        ('ICWMillOperation3','SetMachiningDepthValue',(POINTER(IDispatch),c_double),False),
        ('ICWMillOperation','SetTool',(POINTER(IDispatch),),False),
        ('ICWMillOperation','GenerateToolpath',(),False),
    ]
    for index,(interface,name,args,prop) in enumerate(records):
        row=SimpleNamespace(name=name,argtypes=args,restype=HRESULT,
            idlflags=[index]+(['propput'] if prop else []),
            paramflags=tuple((1,'p'+str(i)) for i in range(len(args))))
        declarations.setdefault(interface,SimpleNamespace(_methods_=[]))._methods_.append(row)
    calls=[]
    def discover(name,path):
        calls.append(('declaration',name,path))
        return declarations[name]
    def inherited(names,path,*,generated_pin):
        calls.append(('parent_audit',set(names),path,deepcopy(generated_pin)))
    monkeypatch.setattr(typed,'_interface_class',discover)
    monkeypatch.setattr(m.prior,'audit_interfaces',inherited)
    pin=dict(path='verified-generated.py',sha256='1'*64)
    def run(): return m.audit_recipe_interfaces('offline-camworks.tlb',pin)
    def find(name):
        return next(v for cls in declarations.values() for v in cls._methods_ if v.name==name)
    return SimpleNamespace(run=run,find=find,declarations=declarations,calls=calls,pin=pin)


def test_generated_declaration_spelling_and_input_types_accepted_without_native_calls(abi):
    result=abi.run()
    assert result['all_resolved'] is True and result['native_calls']==0
    assert len(result['members'])==11
    assert result['generated_pin']==abi.pin
    assert abi.calls[0]==('parent_audit',set(abi.declarations),'offline-camworks.tlb',abi.pin)
    assert len([c for c in abi.calls if c[0]=='declaration'])==11
    assert {(x['member'],x['kind']) for x in result['members']} >= {
        ('SideAllow','property'),('SpringPass','property'),
        ('SetTool','dispatch'),('GenerateToolpath','noargs')}
    assert abi.find('_set_SpringPass').argtypes == (c_long,)


@pytest.mark.parametrize('fault', ['plain_property_name','missing_propput','method_as_property',
    'missing_dispatch_argument','extra_argument','wrong_scalar_type','wrong_hresult',
    'output_parameter','missing_parameter_flags','duplicate_declaration'])
def test_mismatched_write_abi_is_rejected_before_use(abi,fault):
    if fault=='plain_property_name':abi.find('_set_SideAllow').name='SideAllow'
    elif fault=='missing_propput':abi.find('_set_SideAllow').idlflags=[4]
    elif fault=='method_as_property':abi.find('SetChamferType').idlflags.append('propput')
    elif fault=='missing_dispatch_argument':abi.find('SetOverrideMachiningDepth').argtypes=(VARIANT_BOOL,)
    elif fault=='extra_argument':abi.find('GenerateToolpath').argtypes=(c_long,)
    elif fault=='wrong_scalar_type':abi.find('SetChamferType').argtypes=(c_short,)
    elif fault=='wrong_hresult':abi.find('SetTool').restype=c_double
    elif fault=='output_parameter':abi.find('SetTool').paramflags=((2,'tool'),)
    elif fault=='missing_parameter_flags':abi.find('SetTool').paramflags=()
    else:abi.declarations['ICWMillOperation']._methods_.append(deepcopy(abi.find('SetTool')))
    with pytest.raises(ValueError):abi.run()
    assert all(c[0] in ('parent_audit','declaration') for c in abi.calls)


def test_rejected_generated_module_audit_prevents_member_use(abi,monkeypatch):
    def rejected(*args,**kwargs): raise ValueError('generated declaration source changed')
    monkeypatch.setattr(m.prior,'audit_interfaces',rejected)
    with pytest.raises(ValueError,match='generated declaration source changed'):abi.run()
    assert abi.calls==[]

