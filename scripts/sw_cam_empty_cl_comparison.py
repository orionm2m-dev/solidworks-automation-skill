"""Pure comparison projection; raw empty CL block remains explicitly incomplete."""
from hashlib import sha256

def reconcile(raw,before_raw,before_rows,positive_rows,*,empty_native_id,added_native_id,expected_empty_label):
    from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes as parser
    from scripts.sw_cam_current_saved_generation_delta import compare_cl
    from scripts.sw_cam_chamfer_cl_review import block_signature
    def need(ok,msg):
        if not ok: raise ValueError(msg)
    need(type(empty_native_id)is int and type(added_native_id)is int and empty_native_id>0 and added_native_id>0 and empty_native_id!=added_native_id,'Explicit distinct native identities required')
    counts=[r['toolpath_record_counts'] for r in positive_rows]; old_counts=[r['toolpath_record_counts'] for r in before_rows]
    need(all(type(x)is list and len(x)==1 and type(x[0])is int and x[0]>0 for x in counts+old_counts),'Positive single-path rows required')
    need(empty_native_id not in [r['operation_native_id'] for r in positive_rows],'Empty failed operation is not a machining path')
    observed=parser(raw)
    need(observed['declared_units']==['MM'] and observed['unknown_commands']==[] and observed['invalid_commands']==[],'Metric valid known raw commands required')
    blocks=observed['operation_blocks']; empty=[b for b in blocks if b['command_count']==0]
    need(len(blocks)==len(positive_rows)+1 and len(empty)==1,'Exactly one additional empty block required')
    b=empty[0]; index=b['index']
    need(b['label']==expected_empty_label and b['end_line']==b['start_line']+1,'Exact adjacent empty markers required')
    issues=[{'error':'Exact explicitly bounded operation block count required'},{'block':index,'error':'Every operation block requires a validated motion'}]
    need(observed['parse_complete']is False and observed['structure_issues']==issues,'Only the understood empty-block rejection may be reconciled')
    commands=[c for c in observed['commands'] if b['start_line']<=c['line']<=b['end_line']]
    need([c['name'] for c in commands]==['OPFEATSTART','OPFEATEND'],'Empty block contains commands')
    need(not any(m['block']==index for m in observed['motions']) and not any(c['block']==index for c in observed['circle_records']),'Empty block contains motion metadata')
    lines=raw.splitlines(keepends=True)
    projected_raw=b''.join(lines[:b['start_line']-1]+lines[b['end_line']:])
    projected=parser(projected_raw,expected_block_record_counts=[c[0] for c in counts])
    before=parser(before_raw,expected_block_record_counts=[c[0] for c in old_counts])
    comparison=compare_cl(before,projected,before_rows,positive_rows,[added_native_id])
    raw_indices=[i for i in range(len(blocks)) if i!=index]
    need(all(block_signature(observed,i)==block_signature(projected,j) for j,i in enumerate(raw_indices)),'Projection altered a positive stream')
    ni=next(i for i,r in enumerate(positive_rows) if r['operation_native_id']==added_native_id)
    proof=dict(scope='EXACT_ONE_EMPTY_CL_BLOCK_COMPARISON_PROJECTION_V1',raw_sha256=sha256(raw).hexdigest(),raw_parse_complete=False,raw_structure_issues=issues,raw_block_count=len(blocks),raw_block_command_counts=observed['block_command_counts'],
      empty_block=dict(b,native_id=empty_native_id,native_identity_inferred_from_label=False,identity_basis='Explicit sole failed empty native row plus complete positive stream mapping',exact_raw_markers=[x['raw'] for x in commands]),
      comparison_projection=dict(sha256=sha256(projected_raw).hexdigest(),bytes=len(projected_raw),removed_raw_line_numbers=[b['start_line'],b['end_line']],parse_complete=projected['parse_complete'],native_count_matches=projected['native_count_matches'],saved_to_original_file=False,positive_stream_signatures_identical=True),
      CL_preservation=comparison,positive_block_count=len(positive_rows),positive_record_count=sum(x[0] for x in counts),
      new_operation=dict(operation_native_id=added_native_id,positive_block_index=ni,raw_block_index=raw_indices[ni],native_record_count=counts[ni][0],label=blocks[raw_indices[ni]]['label']),
      world_geometry_verified=False,production_qualified=False,native_calls=0)
    return proof,projected,observed
