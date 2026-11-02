from copy import deepcopy
from datetime import datetime,timezone
import pytest
from cam_public_test_support import add_runtime,required_module,required_test_module
R=add_runtime()
shared=required_test_module('test_cam_saved18_restart')
facts,loaded,transition=shared.facts,shared.loaded,shared.transition
m=required_module('sw_cam_saved18_restarted_verify')


@pytest.fixture
def late_facts(loaded):
    closed,exited,startup=transition(loaded)
    exited.update(status='exit_not_observed',process_exit_verified=False,readback_verified=False,exit_observation_source='WaitForSingleObject_on_retained_verified_process_handle',owner_after_timeout=deepcopy(exited['owner_before']))
    pin=dict(path='C:/timeout.json',sha256='a'*64)
    late=dict(scope='OWNED_EXIT_LATE_PROCESS_OBSERVATION_V1',status='exit_observed_after_deadline',observed_utc=datetime.fromtimestamp(1050,timezone.utc).isoformat(),original_exit_receipt_pin=deepcopy(pin),original_status='exit_not_observed',original_receipt_modified=False,owner_before=deepcopy(exited['owner_before']),observation=dict(api='OpenProcess',requested_access='query limited information and synchronize; no terminate',process_id=50,winerror=87,process_absent=True),expected_source_pin=dict(path='C:/model.sldprt',sha256='b'*64),exit_repeated=False,termination_attempted=False,launch_attempted=False)
    return [loaded,closed,exited,startup,late,pin,dict(path='C:/late.json',sha256='e'*64)]

def test_late_exit_qualifies_without_rewriting_original(late_facts):
    before=deepcopy(late_facts);out=m.verify_late_transition(*late_facts)
    assert late_facts==before and out['ownership']['process_id']==60
    assert out['ownership_transition']['original_exit_status']=='exit_not_observed'
    assert out['ownership_transition']['original_exit_receipt_modified']is False

@pytest.mark.parametrize('index,path,value',[(2,('status',),'uncertain'),(2,('process_exit_verified',),True),(2,('exit_call_count',),2),(2,('owner_after_timeout','creation_filetime'),5),(4,('original_receipt_modified',),True),(4,('original_exit_receipt_pin','sha256'),'0'*64),(4,('owner_before','process_id'),99),(4,('observation','winerror'),5),(4,('observation','process_id'),True),(4,('observation','process_absent'),False),(4,('exit_repeated',),True),(4,('termination_attempted',),True),(4,('launch_attempted',),True),(4,('expected_source_pin','sha256'),'c'*64),(4,('observed_utc',),'1970-01-01T00:20:00+00:00'),(4,('observed_utc',),'1970-01-01T00:17:30')])
def test_late_exit_rejects_incomplete_or_wrong_authority(late_facts,index,path,value):
    rows=deepcopy(late_facts);obj=rows[index]
    for k in path[:-1]:obj=obj[k]
    obj[path[-1]]=value
    with pytest.raises(ValueError):m.verify_late_transition(*rows)
