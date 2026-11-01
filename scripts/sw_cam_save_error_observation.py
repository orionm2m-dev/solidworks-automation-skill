"""Observe owned SOLIDWORKS CAM Save errors without COM or window commands.

The caller supplies the existing PID-filtered window enumerator. This observer
must run outside the CAM/COM operation lock so a blocked Save remains observable.
No click, dismissal, focus, process mutation or automatic recovery is performed.
"""
from copy import deepcopy
import math,ntpath
from scripts.sw_cam_rough_firstcut import require
SCOPE='OWNED_CAM_SAVE_ERROR_OBSERVATION_V1'
KNOWN_SAVE_ERROR=('проблемы сохранения данных solidworks cam.','в файле сохранены последние успешно сохраненные данные solidworks cam.')


def _text(value,limit):
    require(type(value) is str and len(value)<=limit,'Bounded native window text required');return value


def _identity(value,pid,created):
    require(type(value) is dict and type(value.get('process_id')) is int and value['process_id']==pid and value.get('alive') is True
        and type(value.get('create_time')) in (int,float) and value['create_time']==created
        and type(value.get('executable')) is str and ntpath.basename(value['executable']).casefold()=='sldworks.exe','Exact live owned SOLIDWORKS process required')
    return {k:value[k] for k in ('process_id','create_time','executable','alive')}


def classify_snapshot(snapshot):
    require(type(snapshot) in (tuple,list) and len(snapshot)==3,'Existing enumerator triple required')
    main,dialogs,error=snapshot
    require(type(dialogs) is list and len(dialogs)<=32,'Bounded dialog collection required')
    if error is not None:_text(error,4000)
    observed=[];known=[];cam=[];complete=error is None
    for item in dialogs:
        require(type(item) is dict and type(item.get('handle')) is int and item['handle']>0,'Exact window handle required')
        title=_text(item.get('title'),2000);cls=_text(item.get('class'),128);texts=item.get('texts',[])
        require(type(texts) is list and len(texts)<=40,'Bounded child text required')
        row=dict(handle=item['handle'],title=title,window_class=cls,texts=[])
        for child in texts:
            require(type(child) is dict,'Window child text record required')
            row['texts'].append(dict(window_class=_text(child.get('class'),128),text=_text(child.get('text'),2000)))
        if item.get('text_error'):
            row['text_error']=_text(item['text_error'],1000);complete=False
        observed.append(row)
        title_normal=' '.join(title.casefold().split())
        if cls=='#32770' and 'solidworks cam' in title_normal:
            cam.append(row)
            body=' '.join(' '.join(t['text'] for t in row['texts']).casefold().split())
            if all(fragment in body for fragment in KNOWN_SAVE_ERROR):known.append(row)
    return dict(dialogs=observed,cam_dialogs=cam,known_save_error_dialogs=known,window_probe_error=error,enumeration_complete=complete)


def observe(*,process_id,expected_creation_time,save_attempt_key,enumerate_windows,read_identity,previous_observation=None):
    require(type(process_id) is int and 0<process_id<2**32,'Explicit positive PID required')
    require(type(expected_creation_time) in (int,float) and math.isfinite(expected_creation_time) and expected_creation_time>0,'Exact process creation time required')
    require(type(save_attempt_key) is str and 0<len(save_attempt_key)<=1024,'Exact bounded Save attempt key required')
    require(callable(enumerate_windows) and callable(read_identity),'Explicit read-only observation callbacks required')
    old=previous_observation
    if old is not None:
        require(type(old) is dict and old.get('scope')==SCOPE and old.get('process_id')==process_id and old.get('process_creation_time')==expected_creation_time
            and old.get('save_attempt_key')==save_attempt_key and type(old.get('save_error_observed')) is bool
            and type(old.get('observation_count')) is int and 1<=old['observation_count']<100000,'Previous observation must belong to this exact Save attempt')
    result=dict(scope=SCOPE,status='inconclusive',process_id=process_id,process_creation_time=expected_creation_time,save_attempt_key=save_attempt_key,observation_count=(old['observation_count']+1 if old else 1),read_only=True,COM_called=False,window_commands_sent=False,focus_changed=False,dialog_dismissed=False,process_mutated=False,native_save_called=False,save_error_observed=bool(old and old['save_error_observed']),save_error_evidence=deepcopy(old.get('save_error_evidence',[])) if old else [],persistence_verified=False,persistence_unverified=True,save_completion_must_be_rejected=True,absence_of_dialog_proves_success=False)
    try:
        before=_identity(read_identity(process_id),process_id,expected_creation_time)
        result.update(process_identity_before=deepcopy(before),process_identity_unchanged=False,snapshot_owner_verified=False)
        snapshot=classify_snapshot(enumerate_windows(process_id))
        # Preserve observed text before a failing post-read ownership check.
        # It remains unverified evidence until both process identities match.
        result.update(snapshot)
        after=_identity(read_identity(process_id),process_id,expected_creation_time)
        result['process_identity_after']=deepcopy(after)
        require(before==after,'Owned process identity changed during window observation')
        result.update(process_identity=before,process_identity_unchanged=True,snapshot_owner_verified=True)
        if snapshot['known_save_error_dialogs']:
            result['save_error_observed']=True
            if not result['save_error_evidence']:result['save_error_evidence']=deepcopy(snapshot['known_save_error_dialogs'])
        if result['save_error_observed']:result['status']='save_error_observed'
        elif snapshot['cam_dialogs']:result['status']='unclassified_cam_dialog_observed'
        elif snapshot['enumeration_complete']:result['status']='no_save_error_observed'
        result['save_completion_must_be_rejected']=result['save_error_observed'] or bool(snapshot['cam_dialogs']) or not snapshot['enumeration_complete']
    except Exception as exc:
        result.update(status='inconclusive',observation_error=dict(type=type(exc).__name__,message=str(exc)[:4000]),save_completion_must_be_rejected=True)
    return result


def assess_save_return(observation,native_return):
    """An HRESULT cannot erase an observed CAM save failure or prove disk data."""
    require(type(observation) is dict and observation.get('scope')==SCOPE,'Save observation required')
    success=type(native_return) is int and native_return==0
    rejected=observation.get('save_completion_must_be_rejected') is not False or not success
    return dict(native_return_type=type(native_return).__name__,native_return_value=native_return if native_return is None or type(native_return) in (bool,int,float,str) else None,hresult_success=success,save_error_observed=observation.get('save_error_observed') is True,save_completion_must_be_rejected=rejected,persistence_verified=False,independent_disk_persistence_check_required=True,reason='observed_CAM_save_error_or_inconclusive_observation' if rejected else 'no_observed_window_error_is_not_disk_persistence_proof')