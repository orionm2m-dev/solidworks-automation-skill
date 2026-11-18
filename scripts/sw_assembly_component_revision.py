"""Guarded instance translations/removals in a qualified assembly copy.

Pilot native operation: prepare is read-only; apply leaves an unsaved copy for
independent inspection. No save, rebuild, fallback, automatic retry or rollback.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from scripts.sw_cam import _error, _member
from scripts.sw_cam_feature_sketch import _call_method as call, _double_array
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_native_transfer import _path, _hash, _frozen, _check_files, _documents
from scripts.sw_native_assembly_audit import _guard, _snapshot, _components
from scripts.sw_operation_guard import _path_identity

_IDENTITY = [1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.]
_TARGET_KEYS = {'name','reference','path','sha256','configuration','native_id','matrix','fixed'}
_TOLERANCE = 1e-10


def _matrix(value):
    if type(value) is not list or len(value) != 16:
        raise ValueError('Explicit 16-value transform required')
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in value):
        raise ValueError('Finite transform values required')
    result = [float(v) for v in value]
    if any(result[i] != _IDENTITY[i] for i in range(16) if i not in (9,10,11)):
        raise ValueError('This pilot accepts translations only, without rotation or scale')
    if any(abs(result[i]) > 1. for i in (9,10,11)):
        raise ValueError('Translation exceeds bounded one-metre workspace')
    return result


def _actions(moves, removals):
    if type(moves) is not list or type(removals) is not list or not 1 <= len(moves)+len(removals) <= 16:
        raise ValueError('One to sixteen explicit component operations required')
    if len(moves)>8 or len(removals)>8:
        raise ValueError('At most eight moves and eight removals')
    seen=set()
    for moving, rows in ((True,moves),(False,removals)):
        for row in rows:
            required=_TARGET_KEYS|({'target_matrix'} if moving else set())
            if type(row) is not dict or set(row)!=required:
                raise ValueError('Exact component identity, file pin, pose and fixed state required')
            for key in ('name','reference','configuration'):
                if type(row[key]) is not str or not row[key]:
                    raise ValueError('Nonempty component '+key+' required')
            if '/' in row['name'] or row['name'] in seen:
                raise ValueError('Only unique direct child instances are supported')
            seen.add(row['name'])
            path=_path(row['path'],{'.sldprt'})
            if _file_hash(path)!=_hash(row['sha256']):
                raise ValueError('Component source SHA changed')
            if type(row['native_id']) is not int or row['native_id']<0 or type(row['fixed']) is not bool:
                raise ValueError('Exact component ID and boolean fixed state required')
            _matrix(row['matrix'])
            if moving:
                target=_matrix(row['target_matrix'])
                if target==row['matrix']:
                    raise ValueError('No-op translation is not an edit')
                if math.dist(target[9:12],row['matrix'][9:12])>.1:
                    raise ValueError('Translation delta exceeds 100 mm pilot limit')


def _read_pinned_json(path, digest):
    path=_path(path,{'.json'})
    if path.stat().st_size>32*1024*1024 or _file_hash(path)!=_hash(digest):
        raise ValueError('Pinned JSON size or SHA differs')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _copy_proof(source, source_sha, target, target_sha, receipt_path, receipt_sha):
    prior=_read_pinned_json(receipt_path,receipt_sha)
    config=prior.get('before',{}).get('config',{})
    if (prior.get('phase')!='finished' or prior.get('status')!='review_required'
            or prior.get('native_reference_calls_returned') is not True
            or prior.get('source_files_unchanged') is not True
            or prior.get('copied_source_sha256')!=source_sha
            or prior.get('output_sha256')!=target_sha
            or config.get('action','apply')!='apply'
            or _path_identity(config.get('source_path',''))!=_path_identity(source)
            or _path_identity(config.get('output_path',''))!=_path_identity(target)
            or _path_identity(prior.get('output_path',''))!=_path_identity(target)
            or config.get('source_sha256')!=source_sha):
        raise ValueError('Completed native reference-copy receipt does not qualify this target')
    if _path_identity(source)==_path_identity(target) or Path(source).samefile(target):
        raise ValueError('Working copy aliases the immutable source')
    return prior


def _same_rows(actual, expected):
    if len(actual)!=len(expected):
        raise ValueError('Component roster count changed outside the approved operations')
    actual=sorted(actual,key=lambda v:v['name']);expected=sorted(expected,key=lambda v:v['name'])
    for got,want in zip(actual,expected):
        if set(got)!=set(want):
            raise ValueError('Unexpected component fields')
        for key in want:
            if key=='matrix':
                for values in (got[key],want[key]):
                    if (type(values) not in (list,tuple) or len(values)!=16
                            or any(type(value) not in (int,float) or not math.isfinite(value) for value in values)):
                        raise ValueError('Component transform must contain sixteen finite numbers: '+want['name'])
                if any(abs(a-b)>_TOLERANCE for a,b in zip(got[key],want[key])):
                    raise ValueError('Component transform differs: '+want['name'])
            elif key=='path':
                if _path_identity(got[key])!=_path_identity(want[key]):
                    raise ValueError('Component path differs: '+want['name'])
            elif got[key]!=want[key]:
                raise ValueError('Component '+key+' differs: '+want['name'])


def _session_guard(sw,pid,target,other_documents,*,clean=False):
    model,identity=_guard(sw,pid,target,clean=clean)
    edit_target=call(model,'GetEditTarget')
    if edit_target is None or call(sw,'IsSame',edit_target,model)!=1:
        raise ValueError('Assembly itself must be the exact edit target')
    if _member(_member(model,'SketchManager'),'ActiveSketch') is not None:
        raise ValueError('Assembly must not be in sketch edit mode')
    current=[d for d in _documents(sw) if _path_identity(d['path'])!=_path_identity(target)]
    if current!=other_documents:
        raise ValueError('Another open document changed during this operation')
    return model,identity


def _select(model, objects):
    call(model,'ClearSelection2',True)
    manager=_member(model,'SelectionManager')
    data=call(manager,'CreateSelectData')
    if data is None:raise ValueError('SelectData unavailable')
    data.Mark=0
    for index,obj in enumerate(objects):
        if call(obj,'Select4',index>0,data,False) is not True:
            raise ValueError('Explicit component selection failed')
    if call(manager,'GetSelectedObjectCount2',-1)!=len(objects):
        raise ValueError('Selected object count differs')
    for index,obj in enumerate(objects,1):
        selected=call(manager,'GetSelectedObject6',index,-1)
        if selected is None or (call(selected,'GetID')!=call(obj,'GetID')
                or _member(selected,'Name2')!=_member(obj,'Name2')
                or _path_identity(call(selected,'GetPathName'))!=_path_identity(call(obj,'GetPathName'))):
            raise ValueError('Selected component identity differs')


def qualify_component_revision(sw, *, process_id, expected_document_path, expected_file_sha256,
        source_path, source_sha256, prior_copy_receipt_path, prior_copy_receipt_sha256,
        moves, removals, action, qualification_only, frozen_files=None,
        expected_state_sha256=None, receipt_path=None):
    """Prepare/apply only a proven copy; exact pose edits and instance deletions.

    Success means in-memory component readback, never saved/reopened or production
    qualification. On any partial error stop with a durable uncertain receipt.
    """
    values=dict(locals());values.pop('sw');values['frozen_files']=frozen_files or []
    report=dict(status='error',phase='preflight',mutation_attempted=False,may_continue=False,
        native_qualification='pilot',saved=False,reopened_verified=False,production_release=False,
        animation_verified=False,operations=[],component_readback_verified=False)
    receipt=None
    try:
        if qualification_only is not True or action not in {'prepare','apply'}:
            raise ValueError('Explicit qualification prepare/apply required')
        if action=='prepare' and (expected_state_sha256 is not None or receipt_path is not None):
            raise ValueError('Prepare cannot accept mutation inputs')
        if action=='apply':
            _hash(expected_state_sha256);_path(receipt_path,{'.json'},new=True)
        source=_path(source_path,{'.sldasm'});target=_path(expected_document_path,{'.sldasm'})
        if _file_hash(source)!=_hash(source_sha256) or _file_hash(target)!=_hash(expected_file_sha256):
            raise ValueError('Source or working-copy SHA changed')
        prior=_copy_proof(source,source_sha256,target,expected_file_sha256,
            prior_copy_receipt_path,prior_copy_receipt_sha256)
        _actions(moves,removals)
        frozen=_frozen(values['frozen_files'])
        required=[{'path':str(source),'sha256':source_sha256},
                  {'path':prior_copy_receipt_path,'sha256':prior_copy_receipt_sha256}]
        required.extend(prior['before']['frozen_files'].values())
        required.extend({'path':r['path'],'sha256':r['sha256']} for r in moves+removals)
        for row in required:
            key=_path_identity(row['path'])
            if key==_path_identity(target):raise ValueError('Target cannot be an immutable dependency')
            if key in frozen and frozen[key]['sha256']!=row['sha256']:
                raise ValueError('Contradictory frozen dependency')
            frozen.update(_frozen([row]))
        model,_=_guard(sw,process_id,str(target),clean=True)
        docs=_documents(sw)
        if any(d['needs_save'] or not d['path'] for d in docs):
            raise ValueError('All open documents must initially be saved and clean')
        others=[d for d in docs if _path_identity(d['path'])!=_path_identity(target)]
        _session_guard(sw,process_id,str(target),others,clean=True)
        manager=_member(model,'SelectionManager')
        if call(manager,'GetSelectedObjectCount2',-1)!=0:
            raise ValueError('Initial selection must be empty')
        before=_snapshot(model,{})
        if len(before['configuration_names'])!=1 or before['explode_views'] or before['native_step_sequence']:
            raise ValueError('Pilot requires one configuration with no explode views in the edited subassembly')
        rows,objects=_components(model)
        _same_rows(rows,before['components'])
        lookup={r['name']:r for r in rows}
        for row in rows:
            path=_path(row['path'],{'.sldprt','.sldasm'})
            key=_path_identity(path)
            if key==_path_identity(target):raise ValueError('Cyclic assembly reference')
            frozen.setdefault(key,{'path':str(path),'sha256':_file_hash(path)})
        for requested in moves+removals:
            obj=objects.get(requested['name']);found=lookup.get(requested['name'])
            if obj is None or found is None:raise ValueError('Requested component instance absent')
            expected={key:deepcopy(requested[key]) for key in ('name','reference','path','configuration','native_id','matrix','fixed')}
            expected.update(loaded=True,suppressed=False)
            _same_rows([found],[expected])
            if call(obj,'GetChildren') or call(obj,'GetMates'):
                raise ValueError('Only unmated leaf parts may be moved or removed')
        _check_files(frozen)
        state={'config':{k:deepcopy(v) for k,v in values.items() if k not in {'action','expected_state_sha256','receipt_path'}},
               'before':before,'other_documents':others,'frozen_files':frozen}
        report.update(before=state,state_sha256=_digest(state))
        if action=='prepare':
            report.update(status='ok',phase='prepared',apply_eligible=True);return report
        if _hash(expected_state_sha256)!=report['state_sha256']:
            raise ValueError('Prepared state changed')
        receipt=_path(receipt_path,{'.json'},new=True)
        _write_receipt(receipt,report,create=True)
        expected_rows=deepcopy(rows)
        def record(name,fn):
            _session_guard(sw,process_id,str(target),others)
            _check_files(frozen)
            if _file_hash(target)!=expected_file_sha256:raise ValueError('Working copy changed on disk')
            report['mutation_attempted']=True;report['phase']=name
            item={'method':name,'attempted':True,'returned':False};report['operations'].append(item)
            _write_receipt(receipt,report)
            value=fn();item['returned']=True
            if type(value) in (str,int,float,bool) or value is None:item['native_return']=value
            _write_receipt(receipt,report)
            return value
        utility=call(sw,'GetMathUtility')
        if moves and utility is None:raise ValueError('Math utility unavailable')
        for row in moves:
            obj=objects[row['name']]
            record('select_move:'+row['name'],lambda:_select(model,[obj]))
            if row['fixed']:
                record('UnfixComponent:'+row['name'],lambda:call(model,'UnfixComponent'))
                if call(obj,'IsFixed') is not False:raise ValueError('Component did not become floating')
            transform=call(utility,'CreateTransform',_double_array(row['target_matrix']))
            if transform is None:raise ValueError('CreateTransform returned null')
            if record('SetTransformAndSolve2:'+row['name'],lambda:call(obj,'SetTransformAndSolve2',transform)) is not True:
                raise ValueError('Native transform did not return true')
            if row['fixed']:
                record('select_fix:'+row['name'],lambda:_select(model,[obj]))
                record('FixComponent:'+row['name'],lambda:call(model,'FixComponent'))
            call(model,'ClearSelection2',True)
            next(r for r in expected_rows if r['name']==row['name'])['matrix']=deepcopy(row['target_matrix'])
            _same_rows(_components(model)[0],expected_rows)
        if removals:
            record('select_remove',lambda:_select(model,[objects[r['name']] for r in removals]))
            if record('DeleteSelection2',lambda:call(_member(model,'Extension'),'DeleteSelection2',0)) is not True:
                raise ValueError('Native instance deletion did not return true')
            removed={r['name'] for r in removals}
            expected_rows=[r for r in expected_rows if r['name'] not in removed]
            call(model,'ClearSelection2',True)
            _same_rows(_components(model)[0],expected_rows)
        _,identity=_session_guard(sw,process_id,str(target),others)
        after=_snapshot(model,{})
        expected=deepcopy(before);expected['components']=expected_rows
        _same_rows(after['components'],expected['components'])
        if {k:v for k,v in after.items() if k!='components'}!={k:v for k,v in expected.items() if k!='components'}:
            raise ValueError('Assembly configuration, explode or motion metadata changed unexpectedly')
        _check_files(frozen)
        if _file_hash(target)!=expected_file_sha256:raise ValueError('Working copy unexpectedly saved')
        if not identity['needs_save']:raise ValueError('Edited working copy is not marked dirty')
        report.update(status='review_required',phase='finished',after=after,expected_after=expected,
            component_readback_verified=True,unchanged_other_components_verified=True,source_files_unchanged=True,
            requires_explicit_save_and_close_reopen=True,needs_save=True,
            reason='IN_MEMORY_COMPONENT_READBACK_ONLY_SAVE_AND_REOPEN_REQUIRED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc))
    finally:
        if receipt:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),component_readback_verified=False)
    return report
