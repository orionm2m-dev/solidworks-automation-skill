"""Append one independent Finish definition after a saved empty Finish.

The request names the source operation, its feature and exact default. Existing
contour insertion and defaults readers are reused. No parameter transfer or GTP.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_chamfer_insert_defaults as insert
from scripts import sw_cam_wall_apply_all_save as parent
from scripts import sw_cam_chamfer_catalogue_preflight as catalogue
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
common,group=insert.exports,insert.group
SCOPE='SAVED_FRESH_FINISH_DEFINITION_V1'
TYPE=1
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','checkpoint_receipt_path','checkpoint_receipt_sha256',
 'source_operation_native_id','feature_native_id','anchor_operation_native_id','default_operation_id','default_operation_name','module_sha256','receipt_path'}
COMPAT_PARAMS={'runtime_compatibility_receipt_path','runtime_compatibility_receipt_sha256'}
FORBIDDEN=('GTP_attempted','GOP_attempted','AFR_attempted','setter_attempted','tool_assignment_attempted','tool_creation_attempted',
 'tool_edit_attempted','feature_edit_attempted','operation_delete_attempted','operation_copy_attempted','move_attempted','automatic_replay','automatic_rollback','production_qualified')


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='insert_fresh_finish_definition','Exact creation-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p) in (PARAMS,PARAMS|COMPAT_PARAMS),'Exact creation-only fields required')
    for k in ('process_id','source_operation_native_id','feature_native_id','anchor_operation_native_id','default_operation_id'):
        require(type(p[k]) is int and 0<p[k]<2**31,'Strict positive native identity required')
    require(p['source_operation_native_id']==p['anchor_operation_native_id'],'Source Finish must be the append anchor')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact SHA256 required')
    require(type(p['default_operation_name']) is str and 0<len(p['default_operation_name'])<=1000 and '\x00' not in p['default_operation_name'],'Bounded exact default name required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM registration required')
    require(p['module_sha256']==_file_hash(__file__),'Creation-only module changed');return p


def binding(loaded,p):
    state=loaded['state'];fid,aid=p['feature_native_id'],p['anchor_operation_native_id']
    checkpoint=loaded['wall_apply_all_configuration']
    require(checkpoint['operation_native_id']==aid==p['source_operation_native_id']
        and checkpoint['feature_native_id']==fid,'Source/feature must match the saved Finish checkpoint')
    features=[x for x in state['features'] if x['geometry']['native_id']==fid]
    rows=[x for x in state['operations'] if x['native_id']==aid]
    require(len(features)==len(rows)==1,'Unique feature/source operation required');feature,op=features[0],rows[0]
    require(op['linked_feature_ids']==[fid] and op['mill_operation_type']==TYPE and op['suppressed'] is False
        and op['toolpath_generated'] is False and op['toolpath_record_counts']==[],'Source must be an existing empty Finish on the same feature')
    require(state['operations'][-1]['native_id']==aid and state['document']['needs_save'] is False,'Append only after the last saved operation')
    require(len(state['operations'])<32 and state['operation_count']==len(state['operations']),'Bounded operation capacity required')
    return dict(feature=deepcopy(feature),source=deepcopy(op),operation_count=state['operation_count'],
        operation_ids=[x['native_id'] for x in state['operations']],
        expected_source_restrictions=deepcopy(loaded['wall_apply_all_configuration']['restrictions']))


def verify_before(loaded,value,p):
    b=binding(loaded,p)
    require(group.exact(value['route'],insert.base.expected_route(loaded)),'Current route differs from saved authority')
    require(group.exact(value['tools'],loaded['neck_tool_checkpoint']['catalogue']),'Current scalar tool catalogue differs')
    require(group.exact(value['feature'],b['feature']),'Current feature metadata differs')
    require(group.exact(value['source_restrictions'],b['expected_source_restrictions']),'Protected source restrictions differ')
    insert.defaults.validate_defaults(value['source_defaults'])


def verify_added(before,observed,new_id,fid,aid):
    result=insert.verify_added(before,observed,new_id,fid,aid)
    require(group.exact(before['source_defaults'],observed['source_defaults'])
        and group.exact(before['source_restrictions'],observed['source_restrictions']),
        'Insertion changed source Finish defaults or restrictions')
    return result


class NativeBackend(insert.NativeBackend):
    def selected_feature(self):
        with self.ctx.guard() as g:
            fid=self.args['feature_native_id'];found=g.read(self.native['doc'],'GetCWObjectFromID',1,fid)
            require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact feature lookup required')
            feature=g.typed(found[0],'ICWMillFeature')
            require(_object_id(self.native['doc'],feature,g.read)==fid,'Feature identity differs')
            saved=binding(self.loaded,self.args)['feature']
            row,_=insert.read_header(feature,self.native['doc'],g.read,g.typed,saved['setup_native_id'])
            require(group.exact(row,saved['geometry']),'Saved feature header differs')
            return feature,deepcopy(saved)
    def source_restrictions(self):
        with self.ctx.guard() as g:
            raw=self.native['operations'][self.args['source_operation_native_id']]
            cls=parent.candidate.original.interface_class('ICWFinishMillOp3',self.typelib_path,self.loaded['generated_pin'])
            owner=g.read(raw,'QueryInterface',cls)
            require(owner is not None and bool(owner) and isinstance(owner,cls),'Exact Finish interface required')
            value={k:g.read(owner,k) for k in ('LeadInOutApplyToAll','GougeCheck')}
            require(all(type(v) is bool for v in value.values()),'Strict Boolean source restrictions required')
            return value
    def catalogue_preflight(self):
        feature,_=self.selected_feature()
        with self.ctx.guard() as g:
            value=catalogue.decode_catalogue(g.read(feature,'IGetAllDefaultOperations',TYPE),
                lambda name:g.read(feature,'GetTdbIdForDefaultOperation',TYPE,name))
        selected=[x for x in value['entries'] if x['name']==self.args['default_operation_name'] and x['default_operation_id']==self.args['default_operation_id']]
        require(len(selected)==1,'Requested default is absent or ambiguous in the actual feature catalogue')
        self.report['actual_default_catalogue']=value;self.persist();return value
    def snapshot(self,label):
        value=super().snapshot(label)
        value['source_defaults']=self.operation_defaults(self.args['source_operation_native_id'],label+'_source',self.args['feature_native_id'])
        value['source_restrictions']=self.source_restrictions();return value
    def bind_inserted(self,raw):
        with self.ctx.guard() as g:oid=_object_id(self.native['doc'],raw,g.read)
        require(oid not in {x['native_id'] for x in self.loaded['neck_tool_checkpoint']['catalogue']},'New operation collides with current tool identity')
        return super().bind_inserted(raw)


class Journal(insert.Journal):
    def pending(self,label):
        require(label in ('InsertOperation','SaveActiveDocument'),'Only insertion and one save are allowed');return super().pending(label)
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE,checkpoint_pin=self.report['checkpoint_pin'])


def marker_path(source,sha,fid,aid):
    return common.local_evidence_root()/('fresh_finish_definition_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,feature_id=fid,anchor_id=aid))+'.json')


def load_inputs(p):
    identity={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    if COMPAT_PARAMS.issubset(p):
        from scripts import sw_cam_finish_runtime_compatibility as compatibility
        loaded=compatibility.load_saved_configuration(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],
            compatibility_path=p['runtime_compatibility_receipt_path'],
            compatibility_sha256=p['runtime_compatibility_receipt_sha256'],**identity)
    else:loaded=parent.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**identity)
    b=binding(loaded,p)
    runtime=[common._pin(x.__file__) for x in (insert,insert.defaults,catalogue)]+[common._pin(__file__)]
    retired=[x for x in loaded['pins'] if Path(x['path']).name in ('sw_cam_wall_apply_all_save.py','sw_cam_wall_apply_all.py')]
    loaded.update(pins=common._merge([x for x in loaded['pins'] if x not in retired],runtime),
        offline_export_proof_pins=common._merge(loaded['offline_export_proof_pins'],retired),fresh_finish_binding=b)
    require(len(loaded['pins'])<=64,'Bounded insertion closure required')
    common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins']);return loaded


def run_backend(backend,journal,loaded,p):
    r=journal.report
    try:
        backend.start();backend.catalogue_preflight()
        r['before']=backend.snapshot('before');verify_before(loaded,r['before'],p);journal.persist()
        raw=backend.insert(lambda:journal.pending('InsertOperation'));journal.returned('InsertOperation',raw,pointer=True)
        backend.refresh_dirty();new_id=backend.bind_inserted(raw);r['new_operation_native_id']=new_id
        r['inserted_observation']=backend.snapshot('inserted')
        r['new_operation']=verify_added(r['before'],r['inserted_observation'],new_id,p['feature_native_id'],p['anchor_operation_native_id'])
        r['new_defaults']=backend.operation_defaults(new_id,'new_defaults');insert.defaults.validate_defaults(r['new_defaults']);journal.persist()
        expected=dict(observation=r['inserted_observation'],defaults=r['new_defaults'])
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(expected)
            observed=backend.snapshot('saved');verify_added(r['before'],observed,new_id,p['feature_native_id'],p['anchor_operation_native_id'])
            defaults=backend.operation_defaults(new_id,'saved_defaults');insert.defaults.validate_defaults(defaults)
            r.update(final_observation=observed,final_defaults=defaults,final_state=deepcopy(backend.current_state));journal.persist()
            return dict(observation=observed,defaults=defaults)
        def verify(value):require(group.exact(expected,value),'Save changed new defaults or protected observations')
        def save():value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['initial_source_sha256'],'Saved definition must change source bytes')
            r['saved_source_sha256']=value;journal.persist();return value
        r['save_stage']={};insert.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        r['actions']['InsertOperation']['readback_verified']=True;r['actions']['SaveActiveDocument']['readback_verified']=True
        backend.finish();r.update(status='saved_definition_no_toolpath',phase='finished',readback_verified=True,model_saved=True,exactly_one_operation_inserted=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


def validate_saved(r):
    require(r['scope']==SCOPE and r['status']=='saved_definition_no_toolpath' and r['phase']=='finished'
        and all(r[k] is True for k in ('readback_verified','model_saved','exactly_one_operation_inserted','phase_proofs_verified')),'Completed creation-only checkpoint required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')) and all(r[k] is False for k in FORBIDDEN)
        and set(r['actions'])=={'InsertOperation','SaveActiveDocument'},'Unexpected or uncertain actions')
    action=r['actions']['InsertOperation']
    require(action['attempted'] is True and action['returned'] is True and action['pending'] is False
        and action['returned_interface_pointer'] is True and action['readback_verified'] is True,'One verified returned operation pointer required')
    parent.wall.history.verified_action(r['actions']['SaveActiveDocument'])
    loaded=deepcopy(r['loaded_context_before']);verify_before(loaded,r['before'],r['request'])
    for key in ('inserted_observation','final_observation'):
        verify_added(r['before'],r[key],r['new_operation_native_id'],r['feature_native_id'],r['anchor_operation_native_id'])
    insert.defaults.validate_defaults(r['new_defaults']);insert.defaults.validate_defaults(r['final_defaults'])
    require(group.exact(r['new_defaults'],r['final_defaults']) and group.exact(r['inserted_observation'],r['final_observation']),'Saved defaults/observations changed')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save stage incomplete')
    t=r['source_transition'];require(type(t['strict_save_return']) is int and t['strict_save_return']==0
        and t['source_before_sha256']==r['initial_source_sha256'] and t['source_after_sha256']==r['saved_source_sha256']
        and r['saved_source_sha256']!=r['initial_source_sha256'],'Strict source transition required')
    require(r['final_state']['document']['needs_save'] is False and r['final_state']['saved_file_sha256']==r['saved_source_sha256'],'Clean saved inventory required')
    for key in ('operations','operation_counts','operation_setups'):
        require(group.exact(r['final_state'][key],r['final_observation']['route'][key]),'Final inventory differs from the observed saved route')
    require(r['final_state']['operation_count']==len(r['final_state']['operations'])
        and group.exact(r['final_state']['features'],loaded['state']['features']),'Final inventory feature/count differs')
    clean_events(r)
    loaded.update(state=deepcopy(r['final_state']),source_sha256=r['saved_source_sha256'],authority_kind='saved_fresh_finish_definition_no_toolpath')
    loaded['fresh_finish_definition']=dict(native_id=r['new_operation_native_id'],feature_native_id=r['feature_native_id'],
        source_operation_native_id=r['request']['source_operation_native_id'],defaults=deepcopy(r['final_defaults']),tool_assigned_by_adapter=False,
        parameters_transferred=False,toolpath_generated=False,geometry_acceptance_complete=False)
    loaded['current_context_sha256']=_digest(group.current_projection(loaded));return loaded


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved definition owner/source/writer differs')
    for k in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[k])
    context=validate_saved(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Completed context differs')
    marker=marker_path(r['source_path'],r['initial_source_sha256'],r['feature_native_id'],r['anchor_operation_native_id'])
    actual,markerpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(actual,Journal(r,path,marker).marker_state()),'Completed once-marker differs')
    live=common._merge([x for x in r['live_pins'] if common._key(x['path'])!=common._key(r['checkpoint_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded completed closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[r['checkpoint_pin'],markerpin]),parent_pin=pin,group_marker_pin=markerpin)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p['expected_document_path'],p['expected_source_sha256'],p['feature_native_id'],p['anchor_operation_native_id'])
    protected={common._key(x['path']) for x in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']};protected.add(common._key(p['expected_document_path']))
    require(common._key(receipt)!=common._key(marker) and not protected.intersection((common._key(receipt),common._key(marker))),'Outputs alias protected evidence')
    require(all(x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in (receipt,marker)),'Fresh receipt and once-marker required')
    reg=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(reg['addin_path']).parent/'camworks.tlb')
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),binding=loaded['fresh_finish_binding'],actions=['InsertOperation','SaveActiveDocument'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],
            module_pin=common._pin(__file__),checkpoint_pin=loaded['parent_pin'],loaded_context_before=loaded,request=p,
            feature_native_id=p['feature_native_id'],anchor_operation_native_id=p['anchor_operation_native_id'],actions={},mutation_attempted=False,
            readback_verified=False,model_saved=False,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],**{k:False for k in FORBIDDEN})
        journal=Journal(r,receipt,marker);_write_receipt(receipt,r,create=True)
        backend=NativeBackend(loaded,p,sw,reg['clsid'],typelib,r,journal.persist);run_backend(backend,journal,loaded,p)
        try:
            for k in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[k])
            clean_events(r);r['phase_proofs_verified']=True
            if r['readback_verified'] is True:
                context=validate_saved(r);r['checkpoint_digest']=_digest(group.current_projection(context));journal.persist()
                r['marker_pin']=common._pin(marker);journal.persist();require(r['marker_pin']['sha256']==_file_hash(marker),'Stable once-marker required')
        except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
        journal.persist();return r


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','new_operation_native_id','saved_source_sha256','issue','native_called')}))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
