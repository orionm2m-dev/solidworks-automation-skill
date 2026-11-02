"""One saved-generation qualification; reusable pinned input for offline geometry.

Historical configuration is validated without asserting its old hash on the
current source. Only the new saved source is checked as current. No COM calls.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,importlib,json,sys,math
SCOPE='RECONCILED_SAVED_LOCAL_GENERATION_GEOMETRY_INPUT_V1'
PARSER_SHA='a88008105525458d4d9ceae3ec54401ae0c85a4272a23edd3d57af2ecdd81ad5'
CONTRACT_SHA='774ef7a013abe04cdb79e71f2cd4d58b63b53ca8a077cc306196f6eb22eb4033'
PRODUCER_SHA='d3e629fc6c55e5ac076a31f5bbeed7cb817f929bbebb195b843375c94e723329'
CONTEXT_SHA='6671802416abde17186fafcca5f9ebc1b279f37f5c6c70200599333f97eb926a'
PRIOR_AUTHORITY_SHA='6796d09a22bd946bf81081b9988ab38aa5af77404476dc0b2821f33161d4ace6'
REUSE={'continuous_radial_engagement.py':'19e79a01f0815d91ad5a47807bf60677fdd75539d3b3f0131f7e7d87e842c1a6',
 'actual_cl_engagement_adapter.py':'64c904b0fb518474ca8e772e0540b551cebb9e5bac885bd7b6d10e784713961c',
 'review_actual18_engagement_chunk.py':'1fb89cce8a1dd277153e7bd92e27a74b10fb90a3ba57fd8fb4dc27b7f3f4b6ad'}
def require(value,message):
    if not value:raise ValueError(message)
def pin(path):
    p=Path(path);require(p.is_file()and not p.is_symlink(),'Regular pinned file required')
    return dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
def check(p):
    q=pin(p['path']);require(q['sha256']==p['sha256']and ('bytes'not in p or type(p['bytes'])is int and q['bytes']==p['bytes']),'Pinned file differs');return q
def read(path,sha):
    p=Path(path);require(p.is_file()and not p.is_symlink()and 0<p.stat().st_size<=32*1024*1024,'Bounded regular JSON required')
    raw=p.read_bytes();require(hashlib.sha256(raw).hexdigest()==sha,'JSON pin changed')
    def pairs(items):
        out={}
        for k,v in items:require(k not in out,'Duplicate JSON field');out[k]=v
        return out
    def finite_float(v):
        n=float(v);require(math.isfinite(n),'Nonfinite JSON');return n
    value=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_float=finite_float,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    require(type(value)is dict,'JSON object required');return value
def environment(skill_root,reuse_root):
    root=Path(skill_root);old=Path(reuse_root)/'scripts'
    require(pin(root/'scripts/sw_cam_local_generation.py')['sha256']==PRODUCER_SHA,'Frozen generation producer required')
    require(pin(root/'scripts/sw_cam_local_saved_context.py')['sha256']==CONTEXT_SHA,'Frozen historical context required')
    for name,sha in REUSE.items():require(pin(old/name)['sha256']==sha,'Frozen geometry reuse dependency differs')
    sys.path[:0]=[str(root),str(old)]
    from scripts import sw_cam_local_generation as producer
    from scripts import sw_cam_generic_cl_reader_bounded as parser
    require(pin(parser.__file__)['sha256']==PARSER_SHA,'Exact extended bounded parser required')
    from scripts.sw_cam_chamfer_cl_review import block_signature
    adapter=importlib.import_module('actual_cl_engagement_adapter');prior=importlib.import_module('review_actual18_engagement_chunk')
    for name,mod in [('actual_cl_engagement_adapter.py',adapter),('continuous_radial_engagement.py',adapter.k),('review_actual18_engagement_chunk.py',prior)]:require(pin(mod.__file__)['sha256']==REUSE[name],'Imported reuse implementation differs')
    require(pin(producer.__file__)['sha256']==PRODUCER_SHA and pin(producer.context.__file__)['sha256']==CONTEXT_SHA,'Imported producer/context differs')
    return producer,parser,block_signature,adapter,prior

def selected_profiles(r,prior_profiles):
    profiles={int(k):deepcopy(v)for k,v in prior_profiles.items()}
    rows=r['saved']['parameters'];require(len(rows)==12 and len({v['operation_native_id']for v in rows})==12,'Exactly12 unique saved parameter groups required')
    byid={v['operation_native_id']:v for v in rows};targets=r['learned_targets']
    require(len(targets)==4 and [v['key']for v in targets]==['left_rough','left_finish','right_rough','right_finish'],'Four exact learned local roles required')
    for block,target in zip(range(14,18),targets):
        p=byid[target['operation_native_id']];tool=p['tool'];g=tool['generic'];m=tool['mill']
        require(p['read_complete']is True and tool['dimension_read_complete']is True and g['native_read_complete']is True,'Complete actual342 profile readback required')
        require(type(g['native_id'])is int and g['native_id']==342 and g['cut_diameter_native']==.8 and m['EffCutlength']['raw']==4 and m['OverallLen']['raw']==45 and m['EndRadius']['raw']==0,'Actual flat342 geometry differs')
        require(p['feature_native_id']==target['feature_native_id'],'Tool parameter/feature mapping differs')
        profiles[block]=dict(operation_native_id=target['operation_native_id'],tool_native_id=342,radius_mm='0.4',cutting_length_mm='4',overall_length_mm='45')
    return profiles

def parse_cl(cl,parser):
    raw=check(cl['output']);require(raw['bytes']<=64*1024*1024,'Bounded actual CL required')
    counts=[v['toolpath_record_counts'][0]for v in cl['expected_generated_operations']]
    return parser.parse_generic_cl_bytes(Path(raw['path']).read_bytes(),expected_block_record_counts=counts)

def load_historical_configuration(producer,r):
    cfg=r['configuration_receipt_pin']
    return producer.context.load_completed(cfg['path'],cfg['sha256'],process_id=r['request']['process_id'],expected_document_path=r['source_path'],expected_source_sha256=r['source_sha256'],check_current=False)

def qualify(receipt_path,receipt_sha256,prior_authority_path,prior_authority_sha256,output,*,skill_root,reuse_root,archived_cl_pin,source_backup_pin):
    out=Path(output);require(out.is_absolute()and out.parent.is_dir()and not out.exists()and not out.is_symlink(),'Fresh explicit qualification output required')
    producer,parser,signature,adapter,prior=environment(skill_root,reuse_root)
    require(prior_authority_sha256==PRIOR_AUTHORITY_SHA,'Existing reviewed prior14 authority required')
    history=read(prior_authority_path,prior_authority_sha256);r=read(receipt_path,receipt_sha256)
    require(r['module_pin']==producer.common._pin(producer.__file__),'Exact actual generation producer pin required')
    cfg=r['configuration_receipt_pin']
    loaded,outer,config_verification,proofs=load_historical_configuration(producer,r)
    from scripts import generation_saved_reconciliation as reconciliation
    require(pin(reconciliation.__file__)['sha256']==CONTRACT_SHA,'Exact offline reconciliation contract required')
    require(producer.group.exact(r['ownership'],loaded['ownership']),'Generation ownership differs from saved configuration')
    require(r['source_sha256']==loaded['source_sha256'] and r['request']['process_id']==loaded['ownership']['process_id'],'Generation previous source/PID differs')
    require(producer.common._key(r['source_path'])==producer.common._key(loaded['guide_parameters']['document']['path']),'Saved document lineage differs')
    verified=reconciliation.native_completion(r,loaded,producer)
    export_observation=reconciliation.completed_export_observation(r,producer)
    already={(producer.common._key(v['path']),v['sha256'])for v in proofs}
    newproofs=producer.common._merge(r['live_pins'],r['phase_proof_pins'])
    producer.common._check([v for v in newproofs if (producer.common._key(v['path']),v['sha256'])not in already])
    source=pin(r['source_path']);require(source['sha256']==r['saved_source_sha256'],'Only actual new saved source may be current')
    backup=check(source_backup_pin);require(backup['sha256']==source['sha256'] and producer.common._key(backup['path'])!=producer.common._key(source['path']),'Separate exact saved-source backup required')
    markpath=producer.marker_path(r['request']);mark=read(markpath,pin(markpath)['sha256'])
    require(producer.group.exact(mark,producer.Journal(r,r['request']['receipt_path'],str(markpath))._marker_state()),'Final generation once marker differs')
    old=read(history['receipt_pin']['path'],history['receipt_pin']['sha256'])
    for evidence in history['implementation_pins']+[history['historical145_observation_pin'],history['frame_authority_pin']]:check(evidence)
    require(history['scope']=='ACTUAL_PRIOR14_NOMINAL_FLAT_CYLINDER_REMOVAL_V1'and history['frame']['qualification_verified']is True and history['frame']['xy_identity']is True and history['frame']['z_offset_mm']==26,'Existing exact CL frame authority required')
    old_cl=old['saved_cl'];export_file=pin(export_observation['output_path']);archived=check(archived_cl_pin)
    require(archived['sha256']==export_file['sha256'] and archived['bytes']==export_file['bytes'],'Archived CL differs from actual export')
    require(sorted(q.name for q in Path(export_file['path']).parent.iterdir())==[Path(export_file['path']).name],'Export directory changed')
    new_cl=dict(output=archived,expected_generated_operations=deepcopy(export_observation['expected_generated_operations']),source_sha256=r['saved_source_sha256'],original_export_status=export_observation['status'],offline_full_parse_verified=True,native_export_return_verified=True)
    before,current=parse_cl(old_cl,parser),parse_cl(new_cl,parser)
    prefix=reconciliation.cl_protection(before,current,old_cl['expected_generated_operations'],new_cl['expected_generated_operations'],r['learned_targets'],signature,prior.bind_prefix)
    require(producer.group.exact(loaded['generated']['saved_cl']['expected_generated_operations'],old_cl['expected_generated_operations']),'Historicalconfiguration/prior14 native order differs')
    profiles=selected_profiles(r,history['profiles_by_block'])
    pins=[pin(__file__),pin(producer.__file__),pin(producer.context.__file__),pin(adapter.__file__),pin(adapter.k.__file__),pin(prior.__file__),pin(parser.__file__),pin(receipt_path),pin(cfg['path']),pin(prior_authority_path),pin(markpath),source,backup,export_file,pin(reconciliation.__file__),check(old_cl['output']),check(new_cl['output'])]
    result=dict(scope=SCOPE,status='qualified_saved_input',native_calls=0,producer_terminal_semantics_independently_revalidated=True,
        generation_receipt_pin=pin(receipt_path),configuration_receipt_pin=pin(cfg['path']),generation_producer_pin=pin(producer.__file__),
        historical_context_producer_pin=pin(producer.context.__file__),qualifier_pin=pin(__file__),prior_authority_pin=pin(prior_authority_path),source_pin=source,source_backup_pin=backup,reconciliation_contract_pin=pin(reconciliation.__file__),extended_parser_pin=pin(parser.__file__),
        original_receipt_status=r['status'],original_receipt_modified=False,original_native_readback_verified=False,offline_postcleanup_proof_closure_verified=True,persistence_after_reopen_verified=False,
        source_sha256=source['sha256'],receipt_pin=pin(receipt_path),producer_pin=pin(producer.__file__),
        tool_profile_authority=dict(receipt_pin=pin(receipt_path),tool_native_id=342,observed_tool_dimensions=deepcopy(loaded['local_tool_dimensions']),native_saved_profile_verified=True,physical_tool_identity_qualified=False),
        terminal_verification=verified,historical_configuration_verification=config_verification,historical_configuration_current_hash_required=False,
        saved_cl=deepcopy(new_cl),prior_cl=deepcopy(old_cl),learned_targets=deepcopy(r['learned_targets']),profiles_by_block=profiles,frame=deepcopy(history['frame']),prefix_check=prefix,
        counts=dict(operations=21,parameters=12,paths=18,protected_paths=14),direct_dependency_pins=pins,
        ancestry_verified_once=True,ancestry_proof_count=len(producer.common._merge(proofs,newproofs)),
        ancestry_rechecked_per_chunk=False,direct_inputs_rechecked_per_chunk=True,
        exact_nominal_exported_coordinate_model_only=True,physical_tool_identity_qualified=False,CL_coordinate_error_enclosure_verified=False,
        actual_new_feature_geometry_mapping_verified=False,production_qualified=False,whole_operation_engagement_verified=False)
    for evidence in pins:check(evidence)
    out.write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n',encoding='utf-8');return result,pin(out)

def load_qualified(path,sha):
    value=read(path,sha)
    require(value['scope']==SCOPE and value['status']=='qualified_saved_input'and value['producer_terminal_semantics_independently_revalidated']is True,'Exact qualified generation geometry input required')
    require(value['qualifier_pin']['sha256']==pin(__file__)['sha256']and value['generation_producer_pin']['sha256']==PRODUCER_SHA and value['historical_context_producer_pin']['sha256']==CONTEXT_SHA,'Qualified producer lineage differs')
    require(value['prior_authority_pin']['sha256']==PRIOR_AUTHORITY_SHA and value['historical_configuration_current_hash_required']is False,'Historical prior authority policy differs')
    require(value['counts']==dict(operations=21,parameters=12,paths=18,protected_paths=14),'Exact18 input required')
    require(value['terminal_verification']['status']=='saved_generation_native_facts_reconciled_offline'and value['terminal_verification']['source_sha256']==value['source_pin']['sha256'],'Saved terminal/source proof differs')
    deps=value['direct_dependency_pins'];require(type(deps)is list and 1<=len(deps)<=32,'Bounded direct dependencies required')
    got={(str(Path(p['path']).resolve()).casefold(),p['sha256'])for p in deps}
    for named in ['qualifier_pin','generation_receipt_pin','configuration_receipt_pin','generation_producer_pin','historical_context_producer_pin','prior_authority_pin','source_pin','source_backup_pin','reconciliation_contract_pin','extended_parser_pin']:
        p=value[named];require((str(Path(p['path']).resolve()).casefold(),p['sha256'])in got,'Required direct pin omitted: '+named)
    for cl in [value['saved_cl'],value['prior_cl']]:
        p=cl['output'];require((str(Path(p['path']).resolve()).casefold(),p['sha256'])in got,'Required CL pin omitted')
    require(value['source_sha256']==value['source_pin']['sha256'] and value['receipt_pin']==value['generation_receipt_pin'] and value['producer_pin']==value['generation_producer_pin'],'Convenience authority projection differs')
    frame=value['frame'];require(frame['qualification_verified']is True and frame['xy_identity']is True and frame['z_offset_mm']==26,'Qualified CL frame differs')
    require(value['prefix_check']['protected14_full_streams_unchanged']is True,'Protected14 full signatures required')
    require(len(value['learned_targets'])==4 and len(value['saved_cl']['expected_generated_operations'])==18 and len(value['prior_cl']['expected_generated_operations'])==14,'Complete native target/count projection required')
    t=value['tool_profile_authority'];require(t['receipt_pin']==value['receipt_pin'] and type(t['tool_native_id'])is int and t['tool_native_id']==342 and t['native_saved_profile_verified']is True and t['physical_tool_identity_qualified']is False,'Native saved tool profile authority differs')
    for p in deps:check(p)
    require(value['reconciliation_contract_pin']['sha256']==CONTRACT_SHA and value['extended_parser_pin']['sha256']==PARSER_SHA and value['original_receipt_status']=='uncertain' and value['original_receipt_modified']is False and value['offline_postcleanup_proof_closure_verified']is True,'Reconciliation scope differs')
    require(value['production_qualified']is False and value['whole_operation_engagement_verified']is False,'Input qualification is not machining acceptance')
    return value


ACTION='offline_reconcile_local_generation'
PARAMS={'process_id','module_sha256','receipt_path','receipt_sha256','prior_authority_path','prior_authority_sha256','archived_cl_path','archived_cl_sha256','source_backup_path','source_backup_sha256','expected_source_sha256','reuse_root','output_path'}

def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'} and request['action']==ACTION,'Exact offline reconciliation action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact sealed reconciliation fields required')
    require(type(p['process_id'])is int and 0<p['process_id']<2**31,'Exact historical owner PID required')
    require(p['module_sha256']==pin(__file__)['sha256'],'Reconciliation module differs')
    for key in ['receipt','prior_authority','archived_cl','source_backup']:
        require(Path(p[key+'_path']).is_absolute(),'Explicit absolute evidence required')
        check(dict(path=p[key+'_path'],sha256=p[key+'_sha256']))
    require(p['prior_authority_sha256']==PRIOR_AUTHORITY_SHA,'Prior14 authority differs')
    out=Path(p['output_path']);require(out.is_absolute() and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh explicit authority output required')
    require(Path(p['reuse_root']).is_absolute() and Path(p['reuse_root']).is_dir(),'Explicit frozen reuse directory required')
    r=read(p['receipt_path'],p['receipt_sha256'])
    require(r['request']['process_id']==p['process_id'] and r['saved_source_sha256']==p['expected_source_sha256']==p['source_backup_sha256'],'Actual owner/saved source differs')
    require(pin(r['source_path'])['sha256']==p['expected_source_sha256'],'Current saved source differs')
    require(str(out.resolve()).casefold() not in {str(Path(v).resolve()).casefold()for k,v in p.items()if k.endswith('_path')and k!='output_path'},'Output aliases evidence')
    return p

def dispatch_request(request,*,validate_only=False):
    p=prepare_request(request)
    if validate_only:return dict(status='validated_offline_evidence_fields',native_called=False,full_ancestry_checked=False,output_created=False)
    root=Path(__file__).resolve().parents[1]
    value,out=qualify(p['receipt_path'],p['receipt_sha256'],p['prior_authority_path'],p['prior_authority_sha256'],p['output_path'],skill_root=root,reuse_root=p['reuse_root'],archived_cl_pin=dict(path=p['archived_cl_path'],sha256=p['archived_cl_sha256']),source_backup_pin=dict(path=p['source_backup_path'],sha256=p['source_backup_sha256']))
    return dict(status=value['status'],authority_pin=out,source_sha256=value['source_sha256'],counts=value['counts'],original_receipt_status=value['original_receipt_status'],original_receipt_modified=False,native_called=False,geometry_accepted=False,persistence_after_reopen_verified=False,production_qualified=False)


def parse_qualified(value):
    """Parse only the pinned current export after load_qualified; no ancestry walk."""
    from scripts import sw_cam_generic_cl_reader_bounded as parser
    require(pin(parser.__file__)['sha256']==value['extended_parser_pin']['sha256']==PARSER_SHA,'Qualified parser differs')
    parsed=parse_cl(value['saved_cl'],parser)
    require(parsed['parse_complete']is True and parsed['native_count_matches']is True and len(parsed['operation_blocks'])==18 and parsed['declared_units']==['MM'],'Complete metric eighteen-stream parse required')
    return parsed
