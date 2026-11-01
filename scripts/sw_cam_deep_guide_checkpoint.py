"""Saved deep17/14 authority with immutable historical source backup.

Validation never asks the current mutable document to retain its pre-Save hash.
The old source is verified only through its independent backup and exact receipts.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_deep_guide_group as writer
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_thread import _file_hash

group,common,cl,inspect=writer.group,writer.common,writer.cl,writer.inspect
authority=writer.authority
generation,reopen=writer.generation,writer.authority.reopen
SCOPE='SAVED_DEEP_GUIDE_CHECKPOINT_AUTHORITY_V1'
MAX_CHECKPOINT_PINS=64


def action_contract(r,targets):
    ids=[t['operation_native_id']for t in targets];writer.fields.learned_targets(targets)
    expected=['insert:'+t['key']for t in targets]+['SetTool:'+str(oid)for oid in ids]
    byid={x['operation_native_id']:x for x in r['after_tools']['parameters']}
    require(set(ids)<=set(byid),'Every learned target must have a post-assignment observation')
    for t in targets:
        oid=t['operation_native_id'];specs=writer.config.ROUGH_FIELDS if t['operation_type']==0 else writer.config.FINISH_FIELDS
        expected += [str(oid)+':'+s[0]for s in specs]
        old=byid[oid]['nc']['feeds_compensation'];wanted=t['reference_nc']
        if not group.exact(old,wanted):
            require(old['GetCNCComp']==1 and group.exact(dict(old,GetCNCComp=0),wanted),'Only observed CNC1 to0 change allowed')
            expected.append('CNC0:'+str(oid))
    expected += ['GTP:'+str(oid)for oid in ids]+['SaveActiveDocument']
    require(list(r['actions'])==expected,'Exact whole-packet action order required')
    for name,action in r['actions'].items():
        require(action.get('status')=='verified'and action.get('readback_verified')is True
          and action.get('native_dispatch_pending',False)is False,'Unverified or pending action: '+name)
        if name.startswith('insert:'):
            target=next(t for t in targets if name=='insert:'+t['key'])
            require(action.get('attempted')is True and action.get('returned')is True and action.get('returned_interface_pointer')is True
              and action.get('actual_native_id')==target['operation_native_id'],'Insertion must return actual verified ID')
        elif action.get('attempted')is False:
            require(name in [str(t['operation_native_id'])+':'+s[0]for t in targets for s in (writer.config.ROUGH_FIELDS if t['operation_type']==0 else writer.config.FINISH_FIELDS)]
              and action.get('returned')is False and action.get('observed',{}).get('already_satisfied')is True,'Only observed recipe fields may skip dispatch')
        else:
            ret=action.get('native_return',{})
            require(action.get('attempted')is True and action.get('returned')is True and ret.get('python_type')=='int'
              and ret.get('value_recorded')is True and type(ret.get('value'))is int and ret['value']==0,'Strict native S_OK0 required')
    return ids


def completed_packet(r,p):
    require(r.get('scope')==writer.SCOPE and r.get('module_pin')==common._pin(writer.__file__)
      and r.get('status')=='saved_deep_guides_review_required'and r.get('phase')=='finished','Exact completed installed deep writer required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),'Uncertain packet cannot authorize continuation')
    for key in ('readback_verified','model_saved','continuation_ready','save_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted'):
        require(r.get(key)is True,'Successful packet proof missing: '+key)
    for key in ('native_dispatch_pending','automatic_retry','automatic_rollback','persistence_after_reopen_verified'):
        require(r.get(key)is False,'Unexpected packet flag: '+key)
    clean_events(r);checkpoint=r['saved_checkpoint_context'];targets=checkpoint['learned_targets'];ids=action_contract(r,targets)
    require(group.exact(targets,r['learned_targets'])and ids==r['actual_new_ids'],'Learned target identity differs')
    require(type(p['process_id'])is int and p['process_id']==r['request']['process_id']==checkpoint['process_id']==r['ownership']['process_id']
      and group.exact(checkpoint['ownership'],r['ownership']),'Exact saved process ownership required')
    require(common._key(p['expected_document_path'])==common._key(r['source_path'])==common._key(checkpoint['document']['path'])
      and checkpoint['document']['type']==1 and checkpoint['document']['needs_save']is False,'Exact clean saved native document required')
    require(checkpoint['source_sha256']==r['saved_source_sha256']==p['expected_source_sha256']
      and checkpoint['prior_source_sha256']==r['source_sha256']and r['source_sha256']!=r['saved_source_sha256'],'One exact source Save transition required')
    backup=checkpoint['source_backup_pin']
    require(backup==common._pin(r['request']['source_backup_path'])and backup['sha256']==r['source_sha256']==r['request']['source_backup_sha256']
      and common._key(backup['path'])!=common._key(p['expected_document_path']),'Historical source belongs to independent pinned backup only')
    # Pure prior-receipt verification: deliberately avoid authority.load_checkpoint,
    # whose current-file check correctly belongs to the old pre-Save phase.
    op=r['inspect_receipt_pin'];observed,ip=read_pin(op['path'],op['sha256']);require(ip==op,'Exact historical inspect pin required')
    old_request=observed['request'];prior,prior_pin=read_pin(old_request['corrected_receipt_path'],old_request['corrected_receipt_sha256'])
    selector={k:old_request[k]for k in ('process_id','expected_document_path','expected_source_sha256')}
    selected,addin=authority.completed_corrected(prior,selector)
    require(selector['expected_source_sha256']==r['source_sha256']and common._key(selector['expected_document_path'])==common._key(r['source_path'])
      and group.exact(selected['expected_parameters'],observed['before']),'Historical source/inspector baseline differs')
    oldplan=inspect.compile_definition_plan(observed,r['request']['choices'])
    for row in oldplan['rows']:
        reference=next(x for x in selected['expected_parameters']['parameters']if x['operation_native_id']==row['reference_operation_native_id'])
        row['expected_levels']=deepcopy(reference['levels']);row['expected_levels']['levels']['machining_depth_native']=4.4
    predecessor_pins,predecessor=writer.load_zero_attempt(r['request'],dict(ownership=r['ownership'],deep_plan=oldplan))
    require(group.exact(predecessor,r.get('zero_attempt_predecessor')),'Exact failed-writer correction lineage required')
    require(all(pin in r['checkpoint_pins']for pin in predecessor_pins),'Prior failure closure missing from immutable checkpoint')
    baseline=deepcopy(selected['expected_parameters']);baseline['binding']['features'].update(observed['deep_headers_before'])
    require(group.exact(r['before'],baseline),'Packet initial extended baseline differs')
    authority.cl.verify_all(prior['saved_cl'],r['before_cl'])
    current=baseline['binding'];anchor=328
    for target,recipe in zip(targets,oldplan['rows']):
        require(all(group.exact(target[k],recipe[k])for k in recipe),'Learned recipe changed from actual inspected defaults')
        oid=target['operation_native_id'];captures=[c for c in r['captures']if c.get('label')=='after_'+recipe['key']]
        require(len(captures)==1,'Unique insertion readback required')
        after=captures[0]['binding'];new=writer.definitions.verify_one_addition(current,after,recipe,oid,anchor)
        require(group.exact(new,r['actions']['insert:'+recipe['key']]['observed']),'Insertion observed binding differs')
        current=after;anchor=oid
    require(group.exact(current,r['definitions']['binding'])and group.exact(r['definitions']['parameters'][:4],baseline['parameters']),
      'Complete definitions snapshot differs or altered protected parameters')
    writer.protected_binding(baseline['binding'],r['after_tools']['binding'])
    require(group.exact(r['after_tools']['parameters'][:4],baseline['parameters']),'Protected shallow settings changed')
    for target in targets:
        oid=target['operation_native_id'];old=next(x for x in r['definitions']['parameters']if x['operation_native_id']==oid)
        actual=next(x for x in r['after_tools']['parameters']if x['operation_native_id']==oid)
        writer.config.verify_automatic_target(old,actual)
        require(group.exact(actual,r['after_tool_parameters'][str(oid)])and group.exact(actual,r['actions']['SetTool:'+str(oid)]['observed'])
          and group.exact(actual['tool'],target['reference_tool_dimensions'])and group.exact(actual['levels'],target['expected_levels']),
          'Assignment/tool/depth readback differs')
    wanted=deepcopy(selected['targets'][0]['assigned_tool'])
    writer.verify_configured(r['after_tools'],r['configured'],targets,wanted)
    counts={oid:deepcopy(r['actions']['GTP:'+str(oid)]['observed']['record_counts'])for oid in ids}
    for target in targets:writer.generation.status_contract(r['actions']['GTP:'+str(target['operation_native_id'])]['observed'],target,True)
    writer.verify_generated(r['configured'],r['generated'],counts,targets)
    require(group.exact(r['generated'],r['saved'])and group.exact(checkpoint['saved_snapshot'],r['saved'])
      and checkpoint['snapshot_key']=='saved'and checkpoint['snapshot_sha256']==group._digest(r['saved']),'Exact final saved snapshot required')
    cl.verify_protected(r['before_cl'],r['generated_cl']);cl.verify_no_new_cutcom(r['generated_cl']);cl.verify_all(r['generated_cl'],r['saved_cl'])
    parsed=cl._verified(r['saved_cl']);signatures=[group._digest(cl.review.block_signature(parsed,i))for i in range(14)]
    require(checkpoint['saved_cl_pin']==r['saved_cl']['output']and checkpoint['saved_CL_block_signature_sha256']==signatures,'Final fourteen complete signatures differ')
    require(checkpoint['operation_order']==list(inspect.ORDER)+ids and checkpoint['generated_ids']==list(inspect.GENERATED)+ids
      and checkpoint['prior_inspect_receipt_pin']==op and checkpoint['persistence_after_reopen_verified']is False,'Final route/proof pointers differ')
    require(group.exact(checkpoint['live_pins'],r['live_pins'])and group.exact(checkpoint['checkpoint_pins'],r['checkpoint_pins'])
      and group.exact(checkpoint['post_assignment_parameters'],r['after_tool_parameters']),'Final immutable proof closure differs')
    transition=r['source_transition'];require(type(transition['strict_save_return'])is int and transition['strict_save_return']==0
      and transition['source_before_sha256']==r['source_sha256']and transition['source_after_sha256']==p['expected_source_sha256']
      and group.exact(transition['document'],checkpoint['document']),'Strict Save transition differs')
    result=dict(document=deepcopy(checkpoint['document']),configuration=deepcopy(checkpoint['configuration']),
      baseline=deepcopy(r['saved']['binding']),expected_parameters=deepcopy(r['saved']),targets=deepcopy(selected['targets']))
    require(group.exact(result['configuration'],selected['configuration']),'Saved CAM/SW configuration changed')
    return result,addin


class ParameterBackend(authority.ParameterBackend):
    batch=writer.NativeBackend.batch
    capture_snapshot=writer.NativeBackend.capture_snapshot
    capture_binding=writer.NativeBackend.capture_binding
    def __init__(self,*args):
        super().__init__(*args);self.learned=deepcopy(self.loaded['deep_targets'])
    def capture_parameters(self,label):return self.capture_snapshot(label,full=True)


def load_checkpoint(p):
    r,pin=read_pin(p['deep_receipt_path'],p['deep_receipt_sha256']);selected,addin=completed_packet(r,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current post-Save source changed')
    pins=deepcopy(r['live_pins']);require(1<=len(pins)<=64,'Bounded live code closure required')
    generated=[v for v in pins if Path(v['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(v['path']).suffix=='.py']
    require(len(generated)==1,'Exact generated interface metadata required')
    loaded=dict(pins=pins,ownership=deepcopy(r['ownership']),guide_parameters=selected,generated_pin=generated[0],generated=r,
      deep_targets=deepcopy(r['learned_targets']),configuration_tool=deepcopy(r['learned_targets'][0]['assigned_tool']),
      configuration_pins=deepcopy(r['checkpoint_pins']),bootstrap_export_pins=[common._pin(authority.reopen.installation.__file__)],
      checkpoint_pins=common._merge(r['checkpoint_pins'],[pin]+[r[key]['output']for key in ('before_cl','generated_cl','saved_cl')]
        +[common._pin(__file__),common._pin(writer.__file__)]))
    require(len(loaded['checkpoint_pins'])<=MAX_CHECKPOINT_PINS,'Bounded deep checkpoint proof closure required')
    common._check(pins);common._check(loaded['checkpoint_pins'])
    registration=common.discover_export_registration(loaded,addin);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in pins,'Installed interface metadata differs')
    abi=writer.generation.audit(typelib,loaded['generated_pin']);p['expected_configuration']=selected['configuration']['sw_configuration_name']
    return loaded,registration,typelib,abi,pin
