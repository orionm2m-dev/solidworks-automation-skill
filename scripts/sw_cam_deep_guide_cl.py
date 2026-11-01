"""Deep-guide machine CL exports preserving ten previously saved streams."""
from copy import deepcopy
from pathlib import Path
import hashlib
from scripts import sw_cam_cl_inventory as inventory
from scripts import sw_cam_generic_cl_reader as parser
from scripts import sw_cam_chamfer_cl_review as review
from scripts import sw_cam_thread_postprocess as post
from scripts import sw_cam_grouped_face_recipe as group
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_rough_firstcut import require

ORDER=[195,196,267,247,248,271,143,144,320,322,324,326,328]
OLD=[267,247,248,271,143,320,322,324,326,328]
FEATURE_PAIRS=[(80,0),(80,1),(81,0),(81,1)]


def dependency_pins():
    return [group._pin(p) for p in (__file__,inventory.__file__,parser.__file__,review.__file__,post.__file__)]


def _fresh_path(value):
    require(type(value) is str,'Explicit output path required')
    p=Path(value)
    require(p.is_absolute() and p.suffix.lower()=='.cl' and 1<=len(p.name)<=80
        and not any(c in p.name for c in '<>:"/\\|?*\x00') and '..' not in p.parts
        and p.drive and not p.drive.startswith('\\') and not p.parent.exists()
        and not p.parent.is_symlink() and p.parent.parent.is_dir()
        and not Path(p.resolve()).drive.startswith('\\'),'New local CL directory required')
    return p


def validate_outputs(p):
    rows=[_fresh_path(p[k]) for k in ('before_cl_path','generated_cl_path','saved_cl_path')]
    key=lambda q:str(Path(q).resolve()).casefold()
    require(len({key(q.parent) for q in rows})==3,'Three distinct exclusive CL directories required')
    protected={key(v) for k,v in p.items() if k.endswith('_path') and k not in ('before_cl_path','generated_cl_path','saved_cl_path') and isinstance(v,str)}
    require(not protected.intersection(key(q) for q in rows),'CL output aliases authority')
    return [str(q) for q in rows]


def contract(binding):
    ops=binding['operations'];require([r['native_id']for r in ops[:13]]==ORDER,'Protected thirteen-operation prefix required')
    require(len(ops)in(13,17),'Exactly13 or17 definitions required')
    extra=ops[13:];require(not extra or [(r['linked_feature_ids'],r['mill_operation_type'])for r in extra]==[([f],k)for f,k in FEATURE_PAIRS],'Exact four linked deep operations required')
    ids=[r['native_id']for r in ops];require(all(type(v)is int and v>0 for v in ids)and len(set(ids))==len(ids),'Actual unique positive IDs required')
    generated=[dict(operation_native_id=r['native_id'],toolpath_record_counts=deepcopy(r['toolpath_record_counts']))for r in ops if r['toolpath_generated']is True]
    require([r['operation_native_id']for r in generated]==OLD+[r['native_id']for r in extra],'Only complete ten or fourteen generated streams allowed')
    require(all(type(r['toolpath_generated'])is bool for r in ops),'Strict generated flags required')
    missing=[r['native_id']for r in ops if r['toolpath_generated']is False]
    require(missing==[195,196,144],'Protected empty operations changed')
    inventory.verify_export_operation_inventory(ops,OLD[0],generated[0]['toolpath_record_counts'],missing,generated)
    return generated


def _parse(raw,rows):
    parsed=parser.parse_generic_cl_bytes(raw,expected_block_record_counts=[r['toolpath_record_counts'][0] for r in rows])
    require(parsed['parse_complete'] is True and parsed['native_count_matches'] is True
        and len(parsed['operation_blocks'])==len(rows) and parsed['declared_units']==['MM'],'Complete metric native-count-matched CL required')
    return parsed


def _session(backend,session):
    require(backend.session is session and backend.session_active is True,'Original parent event session must remain active')
    backend.events()


def export_current_cl(backend,label,binding,path,diagnostic):
    """Caller attaches diagnostic to its durable report before invoking this once.

No bootstrap/subscription, GTP, model Save or session cleanup is performed.
The caller provides capture_binding(label), ctx.guard and durable persist().
"""
    require(type(diagnostic) is dict and not diagnostic,'Fresh attached export diagnostic required')
    require(type(label) is str and 1<=len(label)<=64,'Bounded export label required')
    output=_fresh_path(path);canonical=str(output.resolve());rows=contract(binding)
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


def _verified(result):
    require(result.get('status')=='export_verified' and result.get('output_verified') is True
        and result.get('readback_verified') is True and result.get('parent_session_preserved') is True,
        'Completed same-session export required')
    p=Path(result['output']['path']);require(p.is_file() and not p.is_symlink()
        and p.stat().st_size==result['output']['bytes'] and _file_hash(p)==result['output']['sha256'],'Exported CL bytes changed')
    return _parse(p.read_bytes(),result['expected_generated_operations'])


def _shared(a,b):
    require(a['declared_units']==b['declared_units']==['MM'],'CL units changed')
    require([x['raw'] for x in a['commands'] if x['name']=='BOX']==[x['raw'] for x in b['commands'] if x['name']=='BOX'],'CL stock declaration changed')


def verify_protected(before,after):
    a=_verified(before);b=_verified(after);_shared(a,b)
    old=before['expected_generated_operations'];new=after['expected_generated_operations']
    require([r['operation_native_id']for r in old]==OLD and len(new)==14 and new[:10]==old,'Exact ten-to-fourteen export context required')
    ids=[r['operation_native_id']for r in new];require(len(set(ids))==14,'Unique CL context IDs required')
    signatures=[review.block_signature(b,i)for i in range(14)];matches=[]
    for i in range(10):
        sig=review.block_signature(a,i);hits=[j for j,v in enumerate(signatures)if v==sig]
        require(len(hits)==1,'Protected complete CL changed or ambiguous');matches.append(hits[0])
    require(matches==list(range(10)),'Protected CL order changed')
    return dict(unchanged_native_ids=OLD,protected_complete_streams_verified=True,protected_count=10,
        candidate_new_blocks=[dict(native_id=oid,block=i+10)for i,oid in enumerate(ids[10:])],new_block_native_id_mapping_verified=False,geometry_verified=False)


def verify_all(generated,saved):
    a=_verified(generated);b=_verified(saved);_shared(a,b)
    rows=generated['expected_generated_operations'];require(rows==saved['expected_generated_operations']and len(rows)==14,'Exact fourteen-stream Save context required')
    require(all(review.block_signature(a,i)==review.block_signature(b,i)for i in range(14)),'Save changed complete CL stream')
    return dict(all_fourteen_complete_streams_unchanged=True,geometry_verified=False,production_qualified=False)


def verify_no_new_cutcom(result):
    parsed=_verified(result);require(len(parsed['operation_blocks'])==14,'Fourteen blocks required')
    blocks=set(range(10,14));commands=[c for c in parsed['commands']if c.get('block')in blocks and c['name']=='CUTCOM']
    records=[c for c in parsed.get('cutcom_records',[])if c.get('block')in blocks]
    motions=[v for v in parsed['motions']if v['block']in blocks]
    require(not commands and not records and {v['block']for v in motions}==blocks,'Each new block must move without CUTCOM')
    require(all(v.get('cutcom_state',{}).get('status')=='not_declared'for v in motions),'New motion CUTCOM state differs')
    return dict(new_four_cutcom_absent=True,numeric_enum_meaning_qualified=False,geometry_verified=False)
