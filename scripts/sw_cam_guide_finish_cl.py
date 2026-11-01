"""Offline eight-stream protection and absence of finish CUTCOM commands."""
from scripts import sw_cam_guide_group_cl as cl

PROTECTED = (0,1,2,3,4,5,6,8)
FINISH = (7,9)


def _ten(result):
    rows=result['expected_generated_operations']
    cl.require([r['operation_native_id'] for r in rows]==cl.OLD+cl.NEW,
               'Exact existing ten-operation export contract required')
    return cl._verified(result)


def verify_protected_eight(before_cl, after_cl):
    before=_ten(before_cl);after=_ten(after_cl);cl._shared(before,after)
    old_rows=before_cl['expected_generated_operations'];new_rows=after_cl['expected_generated_operations']
    signatures=[cl.review.block_signature(after,i) for i in range(10)]
    matches=[]
    for index in PROTECTED:
        cl.require(old_rows[index]==new_rows[index], 'Protected native count or identity changed')
        signature=cl.review.block_signature(before,index)
        hits=[j for j,value in enumerate(signatures) if value==signature]
        cl.require(hits==[index], 'Protected complete CL changed, moved or became ambiguous')
        matches.append(dict(operation_native_id=old_rows[index]['operation_native_id'],block=index))
    return dict(protected_eight_complete_streams_verified=True,unchanged=matches,
        finish_candidate_blocks=list(FINISH),finish_native_mapping_verified=False,
        basis='Unique whole command/motion/circle signatures and pinned native count lists; labels are not native IDs',
        geometry_verified=False,production_qualified=False)


def verify_finish_without_cutcom(after_cl):
    parsed=_ten(after_cl)
    commands=[c for c in parsed['commands'] if c.get('block') in FINISH and c['name']=='CUTCOM']
    records=[c for c in parsed.get('cutcom_records',[]) if c.get('block') in FINISH]
    moves=[v for v in parsed['motions'] if v['block'] in FINISH]
    cl.require(not commands and not records,'Finish CL contains a CUTCOM command')
    cl.require(moves and {m['block'] for m in moves}==set(FINISH),'Both finish blocks need actual motion')
    cl.require(all(v.get('cutcom_state',{}).get('status')=='not_declared' for v in moves),
               'Finish motion compensation state is not explicitly absent')
    return dict(finish_CL_without_CUTCOM_verified=True,finish_candidate_blocks=list(FINISH),
        finish_native_mapping_verified=False,CNC_raw_zero_meaning='Empirical exporter observation only; numeric SDK enum not qualified',
        controller_qualification=False,geometry_verified=False,production_qualified=False)
