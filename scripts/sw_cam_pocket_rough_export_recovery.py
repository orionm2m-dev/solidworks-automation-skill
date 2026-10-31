"""Reconcile one completed CL export after a bounded offline parser failure.

This module never connects to CAD, regenerates, exports, saves, or changes the
original failed receipt/once-marker. New geometry and manufacturing remain pending.
"""
from copy import deepcopy
from pathlib import Path
import json
from scripts import sw_cam_pocket_rough_exports as export
from scripts import sw_cam_generic_cl_reader as parser
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require

common,group=export.common,export.group
SCOPE='SAVED_ROUGH_CL_OFFLINE_EXPORT_RECONCILIATION_V1'
FORBIDDEN=('model_saved','controller_changed','cnc_send_attempted','toolpath_generation_attempted',
    'GTP_attempted','GOP_attempted','AFR_attempted','simulation_attempted','stock_edit_attempted',
    'tool_edit_attempted','assignment_attempted','setter_attempted','automatic_replay','automatic_retry_permitted')


def verify_export_receipt(r):
    require(r.get('scope')==export.SCOPE and r.get('status')=='uncertain' and r.get('phase')=='finished',
        'Exact uncertain completed export scope required')
    require(type(r.get('native_hresult')) is int and r['native_hresult']==0
        and r.get('native_call_attempted') is True and r.get('native_call_returned') is True
        and r.get('native_dispatch_pending') is False and r.get('post_cleanup_document_file_verified') is True,
        'Returned strict HRESULT0 and completed cleanup required')
    require(all(r.get(k) is False for k in FORBIDDEN),'Unexpected action or automatic retry permission')
    require(r.get('readback_verified') is False and r.get('output_verified') is False
        and r.get('protected_streams_verified') is False and r.get('checkpoint_export_readback_verified') is False,
        'Only original failed offline verification may be reconciled')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue')),'Native or cleanup failure cannot be reconciled')
    error=r.get('phase_proof_error',{});where=error.get('locations',[])
    require(error.get('type')=='ValueError' and error.get('hresult') is None
        and any(v.get('file')=='sw_cam_pocket_rough_exports.py' and v.get('function')=='preserved_streams'
                and v.get('line')==96 for v in where),'Only recorded first parser/count gate failure allowed')
    require(group.exact(r['before'],r['after']),'Actual pre/post export state differs')
    clean_events(r)


def structural_blocks(raw,counts):
    require(type(raw) is bytes and 0<len(raw)<=64*1024*1024,'Bounded CL bytes required')
    lines=raw.decode('cp1251',errors='strict').splitlines()
    require(len(lines)<=100100 and type(counts) is list and len(counts)==5
        and all(type(v) is int and 0<v<=100000 for v in counts),'Exact bounded five block counts required')
    active=None;rows=[];finished=False
    for number,line in enumerate(lines,1):
        text=line.strip()
        if not text:continue
        require(not finished,'Nonblank record after FINI')
        name,sep,value=text.partition('/')
        require(name in parser.KNOWN and (name=='FINI' or sep=='/'),'Unknown or malformed CL vocabulary')
        if name=='OPFEATSTART':
            require(active is None and bool(value) and len(rows)<5,'Nested/excess/empty operation block')
            active=dict(start_line=number,label=value,command_count=0)
        elif name=='OPFEATEND':
            require(active is not None and active['label']==value,'Mismatched block endpoint')
            active['end_line']=number;rows.append(active);active=None
        elif name=='FINI':
            require(active is None and not sep and not value,'FINI before closed block')
            finished=True
        elif active is not None:active['command_count']+=1
    require(finished and active is None and [r['command_count'] for r in rows]==counts,
        'Exact complete five-block native counts required')
    return rows


def verify_phase_pins(r,historical_parser_archive_path):
    pins=common._merge(r['evidence_pins'],r['offline_export_proof_pins'],r['bootstrap_export_pins'])
    old=[p for p in pins if Path(p['path']).name=='sw_cam_generic_cl_reader.py']
    require(len(old)==1,'Exactly one original CL parser pin required')
    archive=common._pin(historical_parser_archive_path)
    require(archive['sha256']==old[0]['sha256'] and common._key(archive['path'])!=common._key(old[0]['path']),
        'Exact separate historical parser bytes required')
    common._check([p for p in pins if p not in old])
    return dict(original_parser_pin=deepcopy(old[0]),historical_parser_archive_pin=archive)


def reconcile(*,export_receipt_path,export_receipt_sha256,parser_sha256,historical_parser_archive_path,output_path):
    r,receipt_pin=read_pin(export_receipt_path,export_receipt_sha256);verify_export_receipt(r)
    require(_file_hash(parser.__file__)==parser_sha256
        and export.parse_generic_cl_bytes is parser.parse_generic_cl_bytes,'Exact explicit offline parser implementation required')
    parser_pin=common._pin(parser.__file__)
    snapshot=r['before'];state=snapshot['mill_state'];parent=r['saved_checkpoint_pin']
    from scripts.sw_cam_pocket_rough_apply import load_completed
    loaded=load_completed(parent['path'],parent['sha256'],process_id=r['process_id'],
        expected_document_path=state['document']['path'],expected_source_sha256=state['saved_file_sha256'])
    require(group.exact(state,loaded['state']) and group.exact(snapshot['expected_generated_operations'],export.operation_contract(loaded))
        and snapshot['expected_ungenerated_operation_ids']==export.UNGENERATED
        and (snapshot['selected_feature_native_id'],snapshot['selected_operation_native_id'],snapshot['selected_mill_operation_type'])==(79,143,0),
        'Exact actual saved checkpoint/selected inventory required')
    historical_parser=verify_phase_pins(r,historical_parser_archive_path)
    output=r['output'];path=Path(output['path'])
    require(_file_hash(path)==output['sha256'] and path.stat().st_size==output['bytes']
        and r['directory_entries']==[path.name] and sorted(p.name for p in path.parent.iterdir())==[path.name],
        'Recorded output SHA/size/single-file directory differs')
    marker_path=Path(r['marker_path']);marker=json.loads(marker_path.read_text(encoding='utf-8-sig'))
    require(marker.get('scope')==export.SCOPE and marker.get('operation_native_id')==143
        and marker.get('native_call_attempted') is True and marker.get('native_call_returned') is True
        and marker.get('native_dispatch_pending') is False and marker.get('automatic_replay') is False
        and marker.get('status')=='uncertain' and marker.get('phase')=='finished'
        and marker.get('source_sha256')==state['saved_file_sha256']
        and common._key(marker['source'])==common._key(state['document']['path'])
        and common._key(marker['receipt_path'])==common._key(export_receipt_path)
        and marker['parent_pin']['sha256']==parent['sha256'],'Original consumed export marker differs')
    reference=export.protected_reference(r['protected_cl_receipt_pin']['path'],r['protected_cl_receipt_pin']['sha256'],
        r['protected_cl_pin']['path'],loaded)
    loaded=dict(loaded,**reference)
    raw=path.read_bytes();counts=[v['toolpath_record_counts'][0] for v in export.operation_contract(loaded)]
    blocks=structural_blocks(raw,counts)
    parsed=parser.parse_generic_cl_bytes(raw,expected_block_record_counts=counts)
    require(parsed['parse_complete'] is True and parsed['native_count_matches'] is True,'Qualified offline parser still incomplete')
    association=export.preserved_streams(raw,loaded)
    output_file=Path(output_path)
    protected={common._key(p['path']) for p in r['evidence_pins']+r['offline_export_proof_pins']+r['bootstrap_export_pins']}
    protected.update(common._key(p) for p in (path,export_receipt_path,marker_path,state['document']['path'],parser.__file__))
    require(output_file.is_absolute() and output_file.parent.is_dir() and not output_file.exists()
        and not output_file.is_symlink() and common._key(output_file) not in protected,'Fresh separate reconciliation receipt required')
    result=dict(schema_version=1,scope=SCOPE,status='export_reconciled_geometry_review_pending',native_calls=0,
        original_export_receipt_pin=receipt_pin,original_export_marker_pin=common._pin(marker_path),
        saved_checkpoint_pin=deepcopy(parent),CL_pin=common._pin(path),parser_pin=parser_pin,
        recovery_module_pin=common._pin(__file__),historical_parser=historical_parser,original_receipt_rewritten=False,original_marker_rewritten=False,
        reexport_attempted=False,generation_attempted=False,model_saved=False,automatic_replay=False,
        saved_checkpoint_readback_verified=True,output_verified=True,protected_streams_verified=True,
        structural_blocks=blocks,expected_generated_operations=export.operation_contract(loaded),
        protected_stream_association=association,parse_complete=True,native_count_matches=True,
        circle_count=parsed['circle_count'],helix_count=parsed['helix_count'],motion_count=parsed['motion_count'],
        geometry_verified=False,production_qualified=False,productionNC=False,
        remaining=['Independent geometric review of new rough143 movements and removal envelope',
                   'Cutting data, holding, collision qualification and production release'])
    require(_file_hash(export_receipt_path)==export_receipt_sha256 and _file_hash(path)==output['sha256']
        and _file_hash(parser.__file__)==parser_sha256,'Inputs changed during offline reconciliation')
    _write_receipt(output_file,result,create=True)
    return result



def main(argv=None):
    import argparse
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--request',required=True);args=cli.parse_args(argv)
    request=json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='reconcile_written_cl',
        'Only offline written-CL reconciliation allowed')
    p=request['params'];require(type(p) is dict and set(p)=={'export_receipt_path','export_receipt_sha256',
        'parser_sha256','historical_parser_archive_path','output_path','module_sha256'},'Exact reconciliation parameters required')
    require(p['module_sha256']==_file_hash(__file__),'Exact recovery implementation required')
    result=reconcile(**{k:v for k,v in p.items() if k!='module_sha256'})
    print(json.dumps({k:result[k] for k in ('status','native_calls','output_verified','protected_streams_verified','geometry_verified')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
