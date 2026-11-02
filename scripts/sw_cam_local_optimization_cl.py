"""Bounded200k export for an existing selected-four regeneration; old14 exact."""
from copy import deepcopy
from pathlib import Path
import hashlib
from scripts import sw_cam_deep_guide_cl as prior
from scripts import sw_cam_local_operation_group as engine
from scripts import sw_cam_generic_cl_reader_bounded as parser
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_rough_firstcut import require

group,post,review=prior.group,prior.post,prior.review
_fresh_path,_session=prior._fresh_path,prior._session

def _parse(raw,rows):
    parsed=parser.parse_generic_cl_bytes(raw,expected_block_record_counts=[r['toolpath_record_counts'][0]for r in rows])
    require(parsed['parse_complete']is True and parsed['native_count_matches']is True and len(parsed['operation_blocks'])==len(rows)and parsed['declared_units']==['MM'],'Complete bounded metric native-count CL required')
    return parsed

def _verified(result):
    require(result.get('status')=='export_verified'and result.get('output_verified')is True and result.get('readback_verified')is True and result.get('parent_session_preserved')is True,'Completed same-session export required')
    p=Path(result['output']['path']);require(p.is_file()and not p.is_symlink()and 0<p.stat().st_size<=64*1024*1024,'Bounded regular exported CL required')
    raw=p.read_bytes();require(len(raw)==result['output']['bytes']and hashlib.sha256(raw).hexdigest()==result['output']['sha256']==_file_hash(p),'Pinned parsed CL bytes changed')
    return _parse(raw,result['expected_generated_operations'])


def contract(binding,baseline,targets):
    require(len(targets)==4,'Four learned targets required')
    engine.protect_binding(baseline,binding,4)
    wanted=engine.ids(targets,'operation_native_id');ops=binding['operations'];extra=ops[17:]
    require([r['native_id']for r in extra]==wanted,'Appended native order differs')
    for op,t in zip(extra,targets):
        require(op['linked_feature_ids']==[t['feature_native_id']]and op['mill_operation_type']==t['operation_type']and op['suppressed']is False,'Selected CL identity differs')
        require(group.exact(op['assigned_tool'],t['assigned_tool']),'Selected CL tool differs')
    generated=[dict(operation_native_id=r['native_id'],toolpath_record_counts=deepcopy(r['toolpath_record_counts']))for r in ops if r['toolpath_generated']is True]
    old=[r['native_id']for r in baseline['operations']if r['toolpath_generated']is True]
    require(len(old)==14 and [r['operation_native_id']for r in generated]==old+wanted,'Exact eighteen generated streams required')
    require(all(type(r['toolpath_generated'])is bool for r in ops),'Strict generated flags required')
    require(all(len(r['toolpath_record_counts'])==1 and type(r['toolpath_record_counts'][0])is int and r['toolpath_record_counts'][0]>0 for r in generated),'One positive native stream per generated operation')
    return generated


def export_current_cl(backend,label,binding,path,diagnostic):
    """Caller attaches diagnostic to its durable report before invoking this once.

No bootstrap/subscription, GTP, model Save or session cleanup is performed.
The caller provides capture_binding(label), ctx.guard and durable persist().
"""
    require(type(diagnostic) is dict and not diagnostic,'Fresh attached export diagnostic required')
    require(type(label) is str and 1<=len(label)<=64,'Bounded export label required')
    output=_fresh_path(path);canonical=str(output.resolve());rows=contract(binding,backend.baseline['binding'],backend.learned)
    session=backend.session;_session(backend,session);backend.boundary()
    initial=deepcopy(backend.ctx.identity());sha=backend.ctx.args['expected_source_sha256']
    diagnostic.update(label=label,status='pending',expected_generated_operations=rows,source_sha256=sha,
        document=initial,output_path=str(output),native_dispatch_pending=False,native_call_attempted=False,
        native_call_returned=False,output_verified=False,readback_verified=False,parent_session_preserved=False,
        GTP_attempted=False,model_saved=False,production_qualified=False)
    backend.persist()
    before=backend.capture_binding(label+'_before_cl')
    require(group.exact(before,binding),'Current CL inventory differs from expected route')
    def pending():
        _session(backend,session)
        diagnostic.update(native_dispatch_pending=True,native_call_attempted=True);backend.persist()
    with backend.ctx.guard() as guard:
        part=guard.typed(backend.doc,'ICWPartDoc');machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine')
        require(guard.read(machine,'MachType')==1,'Current MILL machine required')
        target=guard.typed(machine,'ICWMachine5')
        controller=post._controller(guard.read(target,'GetController2'))
        diagnostic['controller']=controller;backend.persist()
        output.parent.mkdir()
        require(not output.parent.is_symlink() and str(output.resolve())==canonical,'Exclusive output directory changed')
        diagnostic.update(output_directory_created=True,output_absent_before_dispatch=not output.exists());backend.persist()
        require(not output.exists(),'CL output appeared before native dispatch')
        returned=guard.dispatch_once(lambda:_member(target,'SaveCLFile',str(output)),persist_pending=pending)
    diagnostic.update(native_call_returned=True,native_dispatch_pending=False,native_return=group.return_observation(returned))
    backend.persist();require(type(returned) is int and returned==0,'Exact SaveCLFile S_OK0 required')
    _session(backend,session);backend.boundary()
    after=backend.capture_binding(label+'_after_cl')
    require(group.exact(before,after),'CL export changed current operation bindings')
    with backend.ctx.guard() as guard:
        part=guard.typed(backend.doc,'ICWPartDoc');machine=guard.typed(guard.read(part,'IGetMachine'),'ICWMachine5')
        controller_after=post._controller(guard.read(machine,'GetController2'))
    require(controller_after==controller and backend.ctx.identity()==initial
        and backend.ctx.args['expected_source_sha256']==sha,'CL export changed controller/document/source')
    require(output.is_file() and not output.is_symlink() and not output.parent.is_symlink()
        and str(output.resolve())==canonical and 0<output.stat().st_size<=64*1024*1024
        and sorted(q.name for q in output.parent.iterdir())==[output.name],'Invalid or additional native CL output')
    raw=output.read_bytes();digest=hashlib.sha256(raw).hexdigest();parsed=_parse(raw,rows)
    require(_file_hash(output)==digest,'CL output changed during parsing')
    diagnostic.update(status='export_verified',output=dict(path=str(output),sha256=digest,bytes=len(raw)),
        parse_summary=dict(parse_complete=True,native_count_matches=True,block_count=len(rows),declared_units=parsed['declared_units']),
        output_verified=True,readback_verified=True,parent_session_preserved=True)
    _session(backend,session);backend.boundary();backend.persist()
    return diagnostic


def verify_saved(before,after,targets,saved):
    return verify_streams(_verified(before),_verified(after),before['expected_generated_operations'],after['expected_generated_operations'],targets,saved)


def verify_streams(a,b,old,new,targets,saved):
    prior._shared(a,b)
    require(len(old)==14 and len(new)==18 and group.exact(new[:14],old),'Exact saved14 to18 export context required')
    wanted=engine.ids(targets,'operation_native_id')
    require([v['operation_native_id']for v in new[14:]]==wanted,'Actual appended CL order differs')
    require(new==[dict(operation_native_id=r['native_id'],toolpath_record_counts=r['toolpath_record_counts'])for r in saved['binding']['operations']if r['toolpath_generated']is True],'CL counts do not match saved route')
    signatures=[review.block_signature(b,i)for i in range(18)]
    for i in range(14):
        signature=review.block_signature(a,i)
        require(signatures[i]==signature and sum(v==signature for v in signatures)==1,'A protected complete CL stream changed or is ambiguous')
    blocks=set(range(14,18));motions=[v for v in b['motions']if v['block']in blocks]
    require({v['block']for v in motions}==blocks,'Every new CL stream must contain motion')
    require(not any(c.get('block')in blocks for c in b['cutcom_records']),'New CL contains CNC compensation')
    require(all(v.get('cutcom_state',{}).get('status')=='not_declared'for v in motions),'New cutter compensation state differs')
    return dict(protected_complete_streams_verified=True,protected_count=14,
        candidate_new_blocks=[dict(native_id=oid,block=14+i)for i,oid in enumerate(wanted)],
        new_block_native_id_mapping_verified=False,geometry_verified=False,production_qualified=False,
        actual_feed_validation_required=True)


def export_saved(backend,label,binding):
    require(label=='saved','This adapter exports once only after the single model Save')
    diagnostic={};backend.report.setdefault('cl_exports',{})[label]=diagnostic;backend.persist()
    return export_current_cl(backend,label,binding,backend.args['saved_cl_path'],diagnostic)
