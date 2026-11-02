"""Bounded offline engagement work from one shared saved-generation authority."""
from pathlib import Path
import argparse,importlib,json,sys,time
import saved_generation_engagement as authority

def run(args):
    started=time.monotonic();v=authority.load_qualified(args.qualified,args.qualified_sha256)
    authority.require(type(args.block)is int and 14<=args.block<18 and type(args.first)is int and args.first>=0 and type(args.count)is int and 1<=args.count<=256 and type(args.max_cells)is int and 1<=args.max_cells<=100000,'Bounded selected block/chunk/cell budget required')
    out=Path(args.output);authority.require(out.is_absolute() and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh explicit chunk output required')
    kernel_pin=next(p for p in v['direct_dependency_pins']if Path(p['path']).name=='continuous_radial_engagement.py')
    adapter_pin=next(p for p in v['direct_dependency_pins']if Path(p['path']).name=='actual_cl_engagement_adapter.py')
    sys.path[:0]=[str(Path(adapter_pin['path']).parent),str(Path(v['extended_parser_pin']['path']).parents[1])]
    a=importlib.import_module('actual_cl_engagement_adapter')
    authority.require(authority.pin(a.__file__)['sha256']==adapter_pin['sha256'] and authority.pin(a.k.__file__)['sha256']==kernel_pin['sha256'],'Imported frozen math differs')
    parsed=authority.parse_qualified(v);profiles={int(k):x for k,x in v['profiles_by_block'].items()}
    events,skipped=a.collect_events(parsed,profiles,z_offset=v['frame']['z_offset_mm']);index=a.PrefixIndex(events)
    eligible=[i for i,m in enumerate(parsed['motions'])if m['block']==args.block and m['mode']=='feed']
    authority.require(args.first<=len(eligible),'Feed ordinal outside actual block')
    selected=eligible[args.first:args.first+args.count]
    result=dict(scope='RECONCILED_LOCAL_CL_BOUNDED_ENGAGEMENT_CHUNK_V1',qualified_authority_pin=authority.pin(args.qualified),implementation_pin=authority.pin(__file__),actual_CL_pin=v['saved_cl']['output'],source_sha256=v['source_sha256'],prefix_check=v['prefix_check'],block=args.block,operation_native_id=v['learned_targets'][args.block-14]['operation_native_id'],first_feed_ordinal=args.first,requested_count=args.count,total_feed_records_in_block=len(eligible),complete_block_review=False,rows=[],unreviewed_feed_count=len(eligible),producer_terminal_semantics_independently_revalidated=True,requires_parent_terminal_acceptance=False,kernel_scope='exact nominal exported-coordinate model; not physical stock qualification',skipped_prior_blocks_without_full_flat_profile=skipped,actual_CL_coordinate_error_enclosure_verified=False,actual_new_feature_geometry_mapping_verified=False,production_qualified=False,native_calls=0)
    def persist():
        result['seconds']=time.monotonic()-started;out.write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    persist()
    for i in selected:
        m=parsed['motions'][i]
        row=a.query_actual_motion(parsed,m,parsed['motions'][i-1]if i else None,events,target_profile=profiles[args.block],motion_index=i,prefix_index=index,max_cells=args.max_cells)
        if 'prefix'in row:row['prefix']['credited_source_count']=len(row['prefix'].pop('sources'))
        result['rows'].append(row);result['unreviewed_feed_count']=len(eligible)-len(result['rows']);persist()
        print('reviewed actual line',m['line'],row['status'],flush=True)
    result['complete_block_review']=args.first==0 and len(selected)==len(eligible)
    result['all_selected_model_bounds_proved']=bool(selected)and all(x['status']=='PROVED_NOMINAL_EXPORTED_COORDINATE_MODEL'for x in result['rows'])
    result['whole_operation_model_bound_proved']=result['complete_block_review']and result['all_selected_model_bounds_proved']
    authority.load_qualified(args.qualified,args.qualified_sha256)
    persist();return result,authority.pin(out)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--qualified',type=Path,required=True);p.add_argument('--qualified-sha256',required=True)
    p.add_argument('--block',type=int,choices=range(14,18),required=True);p.add_argument('--first',type=int,default=0);p.add_argument('--count',type=int,default=8);p.add_argument('--max-cells',type=int,default=2000);p.add_argument('--output',type=Path,required=True)
    result,pin=run(p.parse_args());print(json.dumps(pin),flush=True)
