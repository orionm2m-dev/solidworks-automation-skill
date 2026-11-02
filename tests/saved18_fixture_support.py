from copy import deepcopy
from pathlib import Path
import os,sys,types,json
import pytest
from cam_public_test_support import add_runtime,required_module
R=add_runtime()
c=required_module('sw_cam_saved18_checkpoint')
m=required_module('sw_cam_saved18_preclose')

@pytest.fixture
def facts():
    tool=dict(native_id=9)
    ids=list(range(1,22));features={str(i):dict(native_id=i)for i in range(31,37)}
    ops=[dict(native_id=i,toolpath_generated=i>3,toolpath_record_counts=[i+1]if i>3 else[],assigned_tool=deepcopy(tool),linked_feature_ids=[31+(j%6)],mill_operation_type=j%2,setup_native_id=40)for j,i in enumerate(ids)]
    params=[dict(operation_native_id=i,feature_native_id=ops[i-1]['linked_feature_ids'][0],read_complete=True,tool=dict(generic=deepcopy(tool)))for i in list(range(4,12))+list(range(18,22))]
    snapshot=dict(binding=dict(features=features,operations=ops,operation_setups=[]),parameters=params)
    doc=dict(path='C:/model.sldprt',title='model.sldprt',type=1,needs_save=False)
    ownership=dict(process_id=50,create_time=1000.,executable='C:/SLDWORKS.exe',alive=True)
    q=dict(status='qualified_saved_input',original_receipt_status='uncertain',original_receipt_modified=False,source_sha256='b'*64,receipt_pin=dict(path='C:/raw.json',sha256='a'*64),generation_receipt_pin=dict(path='C:/raw.json',sha256='a'*64),configuration_receipt_pin=dict(path='C:/config.json',sha256='c'*64),saved_cl=dict(output=dict(path='C:/saved.cl',sha256='d'*64),expected_generated_operations=[dict(operation_native_id=o['native_id'],toolpath_record_counts=o['toolpath_record_counts'])for o in ops if o['toolpath_generated']]),direct_dependency_pins=[])
    conf=dict(names_consistent=True,associated_sw_configuration_matches=True,cam_configuration_name='Metric',configuration_object_name='Metric',sw_configuration_name='Default',associated_sw_configuration_name='Default')
    r=dict(saved_source_sha256='b'*64,source_sha256='c'*64,cleanup_session_active=False,messages=dict(active=False,disconnected=True),saved=deepcopy(snapshot),before=deepcopy(snapshot),configuration_receipt_pin=deepcopy(q['configuration_receipt_pin']),source_transition=dict(document=doc),live_pins=[dict(path='C:/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py',sha256='e'*64)],ownership=ownership,learned_targets=[dict(operation_native_id=i,feature_native_id=ops[i-1]['linked_feature_ids'][0],operation_type=ops[i-1]['mill_operation_type'],assigned_tool=deepcopy(tool))for i in range(18,22)],tool_dimensions={})
    config=dict(saved_source_sha256='c'*64,saved_checkpoint=dict(snapshot=deepcopy(snapshot),configuration=conf,tool_catalogue=[]))
    serial=dict(checkpoint=dict(state=dict(features=[dict(geometry=dict(native_id=i),setup_native_id=40)for i in range(31,37)]),registration=dict(addin_path='C:/CAM/cwaddinu.dll')),bootstrap_export_pins=[])
    return q,r,config,serial,dict(path='C:/serial.json',sha256='f'*64),dict(path='C:/authority.json',sha256='1'*64)

@pytest.fixture
def loaded(facts):return c.project(*facts)

def transition(loaded):
    handle=dict(process_id=50,executable='C:/SLDWORKS.exe',creation_filetime=m.process._EPOCH+10_000_000_000,alive=True)
    closed=dict(scope=m.SCOPE,status='saved_part_closed',phase='finished',readback_verified=True,close_verified=True,authority_pin=deepcopy(loaded['qualified_authority_pin']),ownership=deepcopy(loaded['ownership']),source_sha256=loaded['source_sha256'],source_path='C:/model.sldprt',cleanup_session_active=False,messages=dict(active=False,disconnected=True),open_documents_after_close=[],before_close_binding=deepcopy(loaded['current_snapshot']['binding']),actions={'CloseActiveDocument':dict(attempted=True,returned=True,status='verified',readback_verified=True,native_dispatch_pending=False,native_return=dict(python_type='int',value_recorded=True,value=0))},owner_handle_before=handle,owner_handle_before_close=handle)
    for k in ('save_attempted','GTP_attempted','exit_attempted','launch_attempted','automatic_retry'):closed[k]=False
    exited=dict(scope='OWNED_VERIFIED_EMPTY_SESSION_EXIT_V1',status='exited',phase='finished',exit_call_count=1,open_documents_before=[],open_documents_final=[],owner_before=handle,request=dict(process_id=50,expected_source_sha256='b'*64,expected_document_path='C:/model.sldprt',expected_creation_filetime=handle['creation_filetime'],expected_executable_path='C:/SLDWORKS.exe'))
    for k in ('readback_verified','process_exit_verified','empty_session_verified','saved_files_preserved','exit_attempted','exit_returned'):exited[k]=True
    for k in ('terminate_rights_requested','termination_attempted','save_attempted','close_document_attempted','launch_attempted','automatic_retry','native_dispatch_pending'):exited[k]=False
    startup=dict(status='ok',phase='connected',launch_mode='executable',launch_attempted=True,new_process_verified=True,process_id=60,known_process_ids_before=[99],process_identity=dict(process_id=60,create_time=1100.,executable='C:/SLDWORKS.exe',alive=True),executable='C:/SLDWORKS.exe',launch_intent_time=1099.)
    return closed,exited,startup
