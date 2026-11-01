"""Resumed checkpoint resolver regressions; immutable synthetic receipts only."""
from copy import deepcopy
import pytest
from test_guide_group_reopen import m,F,DOC,CONFIG,MESSAGES,saved_report,params,update
from scripts import sw_cam_guide_group_resume as resume


def resumed(monkeypatch):
    final=saved_report();initial=deepcopy(F['initial'])
    for row,oid in zip(initial['binding']['operations'],m.ORDER):row['native_id']=oid
    request={'process_id':52,'expected_source_sha256':'a'*64,'expected_configuration':'Default','addin_clsid':'synthetic'}
    partial=dict(scope=m.configuration.SCOPE,module_pin=m.common._pin(m.configuration.__file__),source_path=DOC['path'],source_sha256='a'*64,
        phase='328:previous_allowance',mutation_attempted=True,native_dispatch_pending=False,save_attempted=False,model_saved=False,GTP_attempted=False,
        recipe=deepcopy(F['recipe']),recipe_sha256='d'*64,before=deepcopy(initial),actions={},captures=[],current_document=deepcopy(DOC),
        request=deepcopy(request),ownership={'process_id':52},configuration_pins=deepcopy(final['configuration_pins']))
    state=deepcopy(initial)
    for target in partial['recipe']['rows']:
        oid=target['operation_native_id'];label='after_tool_'+str(oid)
        next(v for v in state['binding']['operations']if v['native_id']==oid)['assigned_tool']=deepcopy(F['wanted'])
        next(v for v in state['parameters']if v['operation_native_id']==oid)['tool']['generic']=deepcopy(F['wanted'])
        partial['captures'].append(dict(label=label,**deepcopy(state)))
        partial['actions'][str(oid)+':SetTool']=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,
            native_return=m.group.return_observation(0),observed=m.configuration.capture_reference(partial,label,state,oid))
    partial['after_tools']=deepcopy(state)
    for target,current in zip(partial['recipe']['rows'],state['parameters']):
        for spec in resume.specs(target):
            label=str(target['operation_native_id'])+':'+spec[0];value=target['fields'][spec[0]];update(current,spec,value)
            partial['actions'][label]=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,
                native_return=m.group.return_observation(0),observed=deepcopy(value))
            if label==partial['phase']:break
        if target['operation_native_id']==328:break
    partial_pin={'path':'partial.json','sha256':'e'*64,'canonical_path':'partial.json','bytes':100,'identity':[1,2,3]}
    exit_pin={'path':'exit.json','sha256':'f'*64};prepared_pin={'path':'prepared.json','sha256':'1'*64}
    exit_proof=dict(client_present=False,no_new_candidate_server_at_or_after_client_start=True,client_result_status='timeout',client_exit_code=1,
        native_receipt_sha256=partial_pin['sha256'],native_phase=partial['phase'],native_dispatch_pending=False,save_attempted=False,source=DOC['path'],source_sha256='a'*64)
    remaining=resume.reconcile(partial,state,F['wanted'])
    prepared=dict(scope=resume.PREPARE_SCOPE,module_pin=m.common._pin(resume.__file__),status='observed',phase='finished',readback_verified=True,
        continuation_ready=True,read_only=True,mutation_attempted=False,save_attempted=False,GTP_attempted=False,messages=deepcopy(MESSAGES),
        source_partial_receipt_pin=deepcopy(partial_pin),writer_exit_pin=deepcopy(exit_pin),ownership={'process_id':52},document=deepcopy(DOC),
        request=deepcopy(request),source_path=DOC['path'],source_sha256='a'*64,actual=deepcopy(state),remaining=remaining)
    final.update(scope=resume.SCOPE,module_pin=m.common._pin(resume.__file__),SetTool_attempted=False,automatic_retry=False,request=deepcopy(request),
        source_partial_receipt_pin=deepcopy(partial_pin),writer_exit_pin=deepcopy(exit_pin),prepared_receipt_pin=deepcopy(prepared_pin),
        source_after_tools_reference={'receipt_pin':deepcopy(partial_pin),'key':'after_tools','sha256':m.group._digest(partial['after_tools'])},
        inherited_verified_action_names=list(partial['actions']),actions={})
    for pk,hk,pin in (('partial_receipt_path','partial_receipt_sha256',partial_pin),('writer_exit_path','writer_exit_sha256',exit_pin),
            ('prepared_receipt_path','prepared_receipt_sha256',prepared_pin)):
        final['request'][pk]=pin['path'];final['request'][hk]=pin['sha256']
    final['saved_checkpoint_context']['prior_parameter_receipt_pin']=deepcopy(prepared_pin)
    for row in remaining:
        final['actions'][row['action']]=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,
            native_return=m.group.return_observation(0),observed=deepcopy(row['wanted']))
    final['actions']['SaveActiveDocument']=dict(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,
        native_return=m.group.return_observation(0))
    final.pop('after_tools');final.pop('captures')
    files={pin['path']:(value,deepcopy(pin)) for pin,value in ((partial_pin,partial),(exit_pin,exit_proof),(prepared_pin,prepared))}
    def read(path,sha):
        value,pin=files[path]
        if sha!=pin['sha256']:raise ValueError('pin changed')
        return deepcopy(value),deepcopy(pin)
    monkeypatch.setattr(m,'read_pin',read)
    return final,files


def test_resumed_checkpoint_resolves_distinct_history_without_rewriting(monkeypatch):
    report,files=resumed(monkeypatch);before=deepcopy(files)
    selected=m.completed_checkpoint(report,params())
    assert [v['native_id']for v in selected['baseline']['operations']]==m.ORDER
    assert len(selected['history_pins'])==5 and files==before
    assert 'after_tools' not in report and 'captures' not in report


@pytest.mark.parametrize('bad',['writer','after_tools_hash','prepared_pin','replay','native_return','prepared_scope','prepared_field','saved_unselected','prefix_pin_identity'])
def test_wrong_resumed_lineage_rejected(monkeypatch,bad):
    report,files=resumed(monkeypatch)
    if bad=='writer':report['module_pin']['sha256']='0'*64
    if bad=='after_tools_hash':report['source_after_tools_reference']['sha256']='0'*64
    if bad=='prepared_pin':report['saved_checkpoint_context']['prior_parameter_receipt_pin']={'path':'other.json','sha256':'0'*64}
    if bad=='replay':report['actions']['322:SetTool']=deepcopy(report['actions']['SaveActiveDocument'])
    if bad=='native_return':report['actions']['SaveActiveDocument']['native_return']['value']=1
    if bad=='prepared_scope':files['prepared.json'][0]['scope']='unrelated'
    if bad=='prepared_field':files['prepared.json'][0]['actual']['parameters'][0]['rough']['entry']['GetSpiralRadius']['raw']=99
    if bad=='saved_unselected':
        for key in ('saved','configured'):report[key]['parameters'][0]['nc']['foreign']=1
        report['saved_checkpoint_context']['snapshot_sha256']=m.group._digest(report['saved'])
    if bad=='prefix_pin_identity':report['source_partial_receipt_pin']['identity']=[0]
    with pytest.raises(ValueError):m.completed_checkpoint(report,params())
