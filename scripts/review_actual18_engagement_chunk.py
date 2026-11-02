"""Bounded, restartable offline engagement review of one actual appended CL block."""
import argparse,hashlib,json,sys,time
from pathlib import Path
import actual_cl_engagement_adapter as a


def pin(p):
    p=Path(p);return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)

def load(p,sha):
    p=Path(p);raw=p.read_bytes()
    a.require(0<len(raw)<=32*1024*1024 and hashlib.sha256(raw).hexdigest()==sha,'Bounded exact saved evidence required')
    return json.loads(raw.decode('utf-8-sig'),parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def bind_prefix(prior,current,old_rows,new_rows,targets,signature):
    a.require(prior.get('parse_complete')is True and current.get('parse_complete')is True
        and prior.get('native_count_matches')is True and current.get('native_count_matches')is True,'Complete counted actual CL required')
    a.require(len(prior['operation_blocks'])==14 and len(current['operation_blocks'])==18,'Exact14-to18 context required')
    a.require(len(old_rows)==14 and len(new_rows)==18 and new_rows[:14]==old_rows,'Exact protected native counts/order required')
    all_ids=[r['operation_native_id']for r in new_rows]
    a.require(all(type(i)is int and i>0 for i in all_ids)and len(set(all_ids))==18,'Distinct complete native operation identities required')
    a.require(all(type(r['toolpath_record_counts'])is list and len(r['toolpath_record_counts'])==1
        and type(r['toolpath_record_counts'][0])is int and r['toolpath_record_counts'][0]>0 for r in new_rows),'One positive native record count per stream required')
    a.require(len(targets)==4 and [t['key']for t in targets]==['left_rough','left_finish','right_rough','right_finish'],'Exact four learned roles required')
    ids=[t['operation_native_id']for t in targets]
    a.require(all(type(i)is int and i>0 for i in ids)and len(set(ids))==4,'Four unique actual IDs required')
    a.require([r['operation_native_id']for r in new_rows[14:]]==ids,'Appended native operation order differs')
    a.require([t['operation_type']for t in targets]==[0,1,0,1],'Rough/finish pairs required')
    a.require(targets[0]['feature_native_id']==targets[1]['feature_native_id']and targets[2]['feature_native_id']==targets[3]['feature_native_id']
        and targets[0]['feature_native_id']!=targets[2]['feature_native_id'],'Two distinct feature pairs required')
    sigs=[signature(current,i)for i in range(18)]
    for i in range(14):
        old=signature(prior,i)
        a.require(sigs[i]==old and sum(s==old for s in sigs)==1,'Protected complete CL stream changed or ambiguous')
    return {'protected14_full_streams_unchanged':True,'candidate_new_blocks':[dict(block=14+i,native_id=oid)for i,oid in enumerate(ids)],
            'actual_new_feature_geometry_mapping_verified':False}


def run(args):
    sys.path.insert(0,str(args.skill_root))
    from scripts import sw_cam_generic_cl_reader as parser
    from scripts.sw_cam_chamfer_cl_review import block_signature
    started=time.monotonic()
    authority=load(args.prior_authority,args.prior_authority_sha256)
    old=load(authority['receipt_pin']['path'],authority['receipt_pin']['sha256'])
    r=load(args.receipt,args.receipt_sha256)
    a.require(r.get('scope')=='EXISTING_LOCAL_DEFINITIONS_DEPTH_REPRESENTATION_CONTINUATION_V1'
        and r.get('status')=='saved_existing_local_group_review_required'and r.get('phase')=='finished'
        and all(r.get(k)is True for k in ['readback_verified','model_saved','continuation_ready']), 'Actual saved local continuation required')
    old_cl,new_cl=old['saved_cl'],r['saved_cl']
    for cl in [old_cl,new_cl]:a.require(pin(cl['output']['path'])['sha256']==cl['output']['sha256'],'Pinned actual CL changed')
    def parse(cl):return parser.parse_generic_cl_bytes(Path(cl['output']['path']).read_bytes(),expected_block_record_counts=[v['toolpath_record_counts'][0]for v in cl['expected_generated_operations']])
    prior,current=parse(old_cl),parse(new_cl);targets=r['learned_targets']
    prefix=bind_prefix(prior,current,old_cl['expected_generated_operations'],new_cl['expected_generated_operations'],targets,block_signature)
    profiles={int(k):v for k,v in authority['profiles_by_block'].items()}
    rows={p['operation_native_id']:p for p in r['saved']['parameters']}
    for block,target in zip(range(14,18),targets):
        p=rows[target['operation_native_id']];t=p['tool'];g=t['generic'];m=t['mill']
        a.require(p['read_complete']is True and t['dimension_read_complete']is True and g['native_id']==342
            and g['cut_diameter_native']==.8 and m['EffCutlength']['raw']==4 and m['OverallLen']['raw']==45 and m['EndRadius']['raw']==0,
            'Observed actual tool342 flat0.8 LOC4 OAL45 required')
        profiles[block]=dict(operation_native_id=target['operation_native_id'],tool_native_id=342,radius_mm='0.4',cutting_length_mm='4',overall_length_mm='45')
    events,skipped=a.collect_events(current,profiles,z_offset=26);index=a.PrefixIndex(events)
    eligible=[i for i,m in enumerate(current['motions'])if m['block']==args.block and m['mode']=='feed']
    a.require(0<=args.first<=len(eligible)and 0<args.count<=256 and args.max_cells>0,'Bounded chunk required')
    selected=eligible[args.first:args.first+args.count]
    result={'scope':'ACTUAL_LOCAL_CL_BOUNDED_ENGAGEMENT_CHUNK_V1','receipt_pin':pin(args.receipt),'prior_authority_pin':pin(args.prior_authority),
        'actual_CL_pin':new_cl['output'],'source_sha256':r['saved_source_sha256'],'prefix_check':prefix,'block':args.block,
        'operation_native_id':targets[args.block-14]['operation_native_id'],'first_feed_ordinal':args.first,'requested_count':args.count,
        'total_feed_records_in_block':len(eligible),'complete_block_review':False,'rows':[],'unreviewed_feed_count':len(eligible),
        'producer_terminal_semantics_independently_revalidated':False,'requires_parent_terminal_acceptance':True,
        'kernel_scope':'exact nominal exported-coordinate model; not physical stock qualification',
        'skipped_prior_blocks_without_full_flat_profile':skipped,'actual_CL_coordinate_error_enclosure_verified':False,
        'actual_new_feature_geometry_mapping_verified':False,'production_qualified':False,'native_calls':0}
    out=Path(args.output);a.require(not out.exists(),'Fresh output required');out.parent.mkdir(parents=True,exist_ok=True)
    for i in selected:
        m=current['motions'][i]
        row=a.query_actual_motion(current,m,current['motions'][i-1]if i else None,events,target_profile=profiles[args.block],motion_index=i,prefix_index=index,max_cells=args.max_cells)
        if 'prefix'in row:
            row['prefix']['credited_source_count']=len(row['prefix'].pop('sources'))
        result['rows'].append(row);result['unreviewed_feed_count']=len(eligible)-len(result['rows'])
        result['seconds']=time.monotonic()-started;out.write_text(json.dumps(result,indent=2)+'\n')
        print('reviewed line',m['line'],row['status'],flush=True)
    result['complete_block_review']=args.first==0 and len(selected)==len(eligible)
    result['all_selected_model_bounds_proved']=bool(selected)and all(v['status']=='PROVED_NOMINAL_EXPORTED_COORDINATE_MODEL'for v in result['rows'])
    result['whole_operation_model_bound_proved']=result['complete_block_review']and result['all_selected_model_bounds_proved']
    result['seconds']=time.monotonic()-started;out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(pin(out)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--skill-root',type=Path,required=True)
    p.add_argument('--prior-authority',type=Path,required=True);p.add_argument('--prior-authority-sha256',required=True)
    p.add_argument('--receipt',type=Path,required=True);p.add_argument('--receipt-sha256',required=True)
    p.add_argument('--block',type=int,choices=range(14,18),required=True);p.add_argument('--first',type=int,default=0)
    p.add_argument('--count',type=int,default=16);p.add_argument('--max-cells',type=int,default=2000)
    p.add_argument('--output',type=Path,required=True);run(p.parse_args())
