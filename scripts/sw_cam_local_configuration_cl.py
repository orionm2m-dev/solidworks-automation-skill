"""Save-only checkpoint export: old14 streams, four new definitions ungenerated."""
from copy import deepcopy
from pathlib import Path
import hashlib
from scripts import sw_cam_local_operation_cl as original
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_rough_firstcut import require
prior,engine,group,post,review=original.prior,original.engine,original.group,original.post,original.review
_fresh_path,_session,_parse=original._fresh_path,original._session,original._parse

def contract(binding,baseline,targets):
    engine.protect_binding(baseline,binding,4)
    wanted=engine.ids(targets,'operation_native_id');ops=binding['operations'];extra=ops[17:]
    require(len(ops)==21 and len(extra)==4 and [v['native_id']for v in extra]==wanted,'Exact21 definitions required')
    for op,t in zip(extra,targets):
        require(op['linked_feature_ids']==[t['feature_native_id']] and op['mill_operation_type']==t['operation_type'] and op['suppressed']is False and group.exact(op['assigned_tool'],t['assigned_tool']),'Actual assigned definition differs')
        require(op['toolpath_generated']is False and op['toolpath_record_counts']==[],'Configuration checkpoint cannot contain generated new paths')
    rows=[dict(operation_native_id=v['native_id'],toolpath_record_counts=deepcopy(v['toolpath_record_counts']))for v in ops if v['toolpath_generated']is True]
    old=[dict(operation_native_id=v['native_id'],toolpath_record_counts=deepcopy(v['toolpath_record_counts']))for v in baseline['operations']if v['toolpath_generated']is True]
    require(len(rows)==14 and group.exact(rows,old),'Only protected14 paths may be exported')
    return rows

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
    require(len(after['expected_generated_operations'])==14,'Exactly14 saved paths required')
    require(group.exact(before['expected_generated_operations'],after['expected_generated_operations']),'Saved old path identities/counts changed')
    proof=prior.verify_all(before,after)
    require(len(saved['binding']['operations'])==21 and all(v['toolpath_generated']is False and v['toolpath_record_counts']==[] for v in saved['binding']['operations'][17:]),'No new paths may be generated')
    return dict(protected_fourteen_cl_verified=True,proof=proof,new_generated_paths=0,geometry_qualified=False,production_qualified=False)

def export_saved(backend,label,binding):
    require(label=='saved','Exactly one post-Save export required')
    diagnostic={};backend.report.setdefault('cl_exports',{})[label]=diagnostic;backend.persist()
    return export_current_cl(backend,label,binding,backend.args['saved_cl_path'],diagnostic)
