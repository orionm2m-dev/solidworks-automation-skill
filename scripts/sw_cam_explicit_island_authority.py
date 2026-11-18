"""Durable four-sketch + outer-circle + existing Save admission for explicit islands.
Historical mutable target hashes are never checked as live. Only the exact recorded
Save transition admits the current hash; every other protected pin remains live.
"""
from copy import deepcopy
from pathlib import Path
import math,re,os
from scripts import sw_cam_process_import as shared
from scripts import sw_cam_profile_sketch as circle
from scripts import sw_cam_explicit_island_sketch as sketches
from scripts import sw_cam_explicit_island_feature as feature
from scripts.sw_cam_current_pocket_saved_context import merge_pins
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest

SCOPE='SAVED_FIVE_SKETCH_EXPLICIT_POCKET_AUTHORITY_V1'
BATCH_SCOPE='EXCLUSIVE_EMPTY_CAM_FOUR_ISLAND_SKETCH_BATCH_V1'
FLAGS=('readback_verified','CAD_body_fingerprint_unchanged','empty_CAM_unchanged','protected_files_unchanged','runtime_unchanged','model_saved','save_readback_verified')
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
      'expected_sw_configuration','expected_cam_configuration','batch_receipt_path','batch_receipt_sha256',
      'circle_receipt_path','circle_receipt_sha256','circle_save_receipt_path','circle_save_receipt_sha256',
      'feature_plan_path','feature_plan_sha256','receipt_path','qualification_only','acknowledge_definition_only','message_policy'}
require=shared.require

def same_path(a,b):
    return type(a)is str and type(b)is str and str(Path(a).resolve()).casefold()==str(Path(b).resolve()).casefold()

def clean(r):
    require(shared.event_health(r['messages'],active=False)==0,'Closed zero-event transport required')
    require(not any(k in r for k in ('issue','runtime_error','cleanup_error','receipt_write_error','failed_phase')),'Unresolved receipt is not authority')

def same_cad(a,b,*,ignore_spec=False):
    a,b=deepcopy(a),deepcopy(b)
    sa,sb=a.pop('solids'),b.pop('solids')
    if ignore_spec:a.pop('spec');b.pop('spec')
    return a==b and circle._same_bodies(sa,sb)

def same_saved(a,b):
    a,b=deepcopy(a),deepcopy(b)
    for x in (a,b):x['cad'].pop('saved_file_sha256');x['cad'].pop('needs_save')
    if a['inventory']!=b['inventory'] or not same_cad(a['cad'],b['cad']):return False
    left,right=a.get('sketches'),b.get('sketches')
    if type(left)is not list or type(right)is not list or len(left)!=4 or len(right)!=4:return False
    for x,y in zip(left,right):
        if set(x)!={'spec','sketch_readback'}or set(y)!=set(x)or x['spec']!=y['spec']:return False
        sketches.verify_readback(x['spec'],x['sketch_readback'])
        sketches.verify_readback(y['spec'],y['sketch_readback'])
    return True

def exact_save(r):
    require(r.get('native_call_returned')is True and r.get('native_return_type')=='int'
            and type(r.get('native_return_value'))is int and r['native_return_value']==0
            and r.get('save_readback_verified')is True,'Completed exact Save int0 plus readback required')

def verify_completed_receipt(path,sha):
    """Pure durable proof; does not pretend the old saved target is still current."""
    r,pin=read_pin(path,sha)
    require(r.get('scope')==BATCH_SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished','Successful four-sketch producer required')
    require(all(r.get(k)is True for k in FLAGS),'Four-sketch producer verification incomplete')
    require(r.get('native_dispatch_pending')is False,'Pending producer cannot authorize next step')
    clean(r);v=r['request'];require(v['save_after_creation']is True,'Saved sketch batch required')
    for key in ('GOP_attempted','GTP_attempted','CAM_feature_creation_attempted','AddIsland_attempted','import_attempted','explicit_rebuild_attempted','tool_mutation_attempted','stock_edit_attempted'):
        require(r.get(key)is False,'Unexpected producer mutation: '+key)
    exact_save(r['native_save'])
    snaps=r['save_snapshots'];before,after=snaps['before'],snaps['after']
    require(same_saved(before,after)and r['after']==after,'Complete unchanged Save snapshots required')
    require(after['cad']['needs_save']is False and before['cad']['needs_save']is True,'Observed sketch Save dirty transition required')
    require(before['cad']['saved_file_sha256']==r['source_before_sha256']==v['expected_source_sha256']
            and after['cad']['saved_file_sha256']==r['source_after_sha256']
            and r['source_before_sha256']!=r['source_after_sha256'],'Exact producer source transition required')
    require(r['native_save']['saved_file_sha256']==r['source_after_sha256'],'Native Save hash differs')
    require(r['before']['inventory']==before['inventory']==after['inventory'],'Sketch batch changed CAM')
    specs=r['specs'];require(type(specs)is list and len(specs)==len(r['sketches'])==4,'Four actual native sketches required')
    require(len(after['sketches'])==4,'Four fresh saved sketch readbacks required')
    for spec,item,confirmed in zip(specs,r['sketches'],after['sketches']):
        require(item.get('status')=='sketch_observed'and item.get('native_readback_verified')is True
                and item['before']['spec']==spec and confirmed['spec']==spec,'Native sketch binding differs')
        sketches.verify_readback(spec,item['sketch_readback']);sketches.verify_readback(spec,confirmed['sketch_readback'])
        require(item.get('Save_attempted')is False and item.get('CAM_feature_creation_attempted')is False
                and item.get('AddIsland_attempted')is False and item.get('GOP_attempted')is False
                and item.get('GTP_attempted')is False,'Sketch component performed another action')
    actions=r['actions'];wanted=['CreateSketch:'+str(i)for i in range(4)]+['SaveActiveDocument']
    require(type(actions)is dict and list(actions)==wanted,'Exactly four sketch actions and one Save required')
    require(all(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False for a in actions.values()),'All native actions must have completed')
    require(actions['SaveActiveDocument'].get('native_return_type')=='int'and type(actions['SaveActiveDocument'].get('native_return_value'))is int and actions['SaveActiveDocument']['native_return_value']==0,'Exact journal Save return required')
    doc=r['after_cleanup_document'];require(doc['needs_save']is False and same_path(doc['path'],v['expected_document_path']),'Clean producer cleanup document required')
    old,new=r['initial_pins'],r['current_pins']
    require(type(old)is list and type(new)is list and len(old)==len(new),'Exact pin transition required')
    hits=0
    for a,b in zip(old,new):
        if same_path(a['path'],v['expected_document_path']):
            aa,bb=deepcopy(a),deepcopy(b);require(aa.pop('sha256')==r['source_before_sha256']and bb.pop('sha256')==r['source_after_sha256']and aa==bb,'Only target SHA may change');hits+=1
        else:require(a==b,'Immutable pin changed during Save')
    require(hits==1,'Exactly one mutable target pin required')
    marker,mp=read_pin(r['marker_path'],_file_hash(r['marker_path']))
    require(marker['scope']==BATCH_SCOPE and same_path(marker['target'],v['expected_document_path'])
            and same_path(marker['receipt_path'],path)and marker['actions']==actions and marker['status']==r['status']
            and marker['phase']=='finished','Exact consumed producer marker required')
    return dict(receipt=r,pin=pin,marker_pin=mp,specs=deepcopy(specs),expected_inventory=deepcopy(after['inventory']),
                saved_cad=deepcopy(after['cad']),root_pins=deepcopy(new),source_sha256=r['source_after_sha256'],document=deepcopy(doc))

def verify_circle_save(batch,c,s,v):
    require(c.get('status')=='ok'and c.get('phase')=='finished'and c.get('native_readback_verified')is True
            and c.get('saved')is False and c.get('CAD_solid_edit_attempted')is False and type(c.get('CAM_calls'))is int and c['CAM_calls']==0,'Successful existing circle-only creator required')
    require(not any(k in c for k in ('issue','failed_phase','receipt_write_error')),'Failed circle creator')
    spec=circle._input(c['after']['spec']);require(spec['profile']['kind']=='circle'and spec['plane_axis']=='Z','Model-Z outer circle required')
    for state in (c['before'],c['after']):
        require(state['pid']==v['process_id']and same_path(state['path'],v['expected_document_path'])
                and state['saved_file_sha256']==batch['source_sha256']and state['spec']==spec,'Exact circle identity/source required')
    require(c['before']['needs_save']is False and c['after']['needs_save']is True,'Circle dirty transition required')
    require(same_cad(batch['saved_cad'],c['before'],ignore_spec=True),'Circle must start from saved four-sketch CAD')
    names=[x['name']for x in c['created_features']]
    require(len(names)==len(set(names))and [x for x in c['after']['features']if x['name']not in names]==c['before']['features']
            and [x for x in c['after']['features']if x['name']in names]==c['created_features']
            and circle._same_bodies(c['before']['solids'],c['after']['solids']),'Circle CAD delta differs')
    require(s.get('status')=='review_required'and s.get('phase')=='finished'and s.get('action')=='save'
            and s.get('machine_kind')=='mill_qualification'and s.get('process_id')==v['process_id'],'Existing zero-operation lifecycle Save required')
    clean(s);exact_save(s)
    for key in ('GOP_attempted','GTP_attempted','AFR_attempted','generation_attempted','native_dispatch_pending'):
        require(s.get(key)is False,'Unexpected Save continuation: '+key)
    a,b=deepcopy(s['before']),deepcopy(s['final_state'])
    require(s['after']==s['final_state'],'Exact final Save readback required')
    require(a['document']['needs_save']is True and b['document']['needs_save']is False,'Exact outer-circle Save dirty transition')
    require(a.pop('saved_file_sha256')==batch['source_sha256']and b.pop('saved_file_sha256')==v['expected_source_sha256']
            and v['expected_source_sha256']!=batch['source_sha256'],'Exact outer-circle Save source transition required')
    for x in (a,b):
        require(same_path(x['document']['path'],v['expected_document_path']),'Save target differs')
        x['document'].pop('needs_save')
        require(all(type(n)is int and n==0 for n in x['operation_counts'])
                and len(x['feature_setups'])==1 and x['feature_setups'][0]['feature_count']==0,'Save must retain empty initialized CAM')
    require(a==b,'Save changed setup/settings')
    expected=deepcopy(c['after']);expected.update(saved_file_sha256=v['expected_source_sha256'],needs_save=False)
    return spec,expected

def prepare(v):
    require(type(v)is dict and set(v)==KEYS,'Exact explicit-feature authority request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owned PID/lifetime required')
    require(v['qualification_only']is True and v['acknowledge_definition_only']is True and v['message_policy']=='vendor_default','Explicit definition-only qualification required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute paths required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
    batch=verify_completed_receipt(v['batch_receipt_path'],v['batch_receipt_sha256'])
    old=batch['receipt']['request']
    for key in ('process_id','expected_process_create_time','expected_sw_configuration','expected_cam_configuration'):
        require(old[key]==v[key]and type(old[key])is type(v[key]),'Producer identity/configuration differs: '+key)
    require(same_path(old['expected_document_path'],v['expected_document_path']),'Producer target differs')
    c,cp=read_pin(v['circle_receipt_path'],v['circle_receipt_sha256']);s,sp=read_pin(v['circle_save_receipt_path'],v['circle_save_receipt_sha256'])
    outer,cad=verify_circle_save(batch,c,s,v)
    p,pp=read_pin(v['feature_plan_path'],v['feature_plan_sha256']);p=feature.plan(p)
    require(p['outer_sketch_name']==outer['sketch_name']and p['island_sketch_names']==[x['sketch_name']for x in batch['specs']],'Feature plan sketch names differ')
    require(p['owner_setup_native_id']==old['expected_setup_native_id']and p['axis_native']==old['expected_setup_axis_native']and p['origin_native']==old['expected_setup_origin_native'],'Feature owner/frame differs')
    feature.empty_baseline(batch['expected_inventory'],p)
    roots=[x for x in batch['root_pins']if not same_path(x['path'],v['expected_document_path'])]
    roots+= [batch['pin'],batch['marker_pin'],cp,sp,pp,shared.file_pin(v['expected_document_path'],v['expected_source_sha256'])]
    for mod in (feature,sketches,circle,shared):roots.append(shared.file_pin(mod.__file__,_file_hash(mod.__file__)))
    roots.append(shared.file_pin(__file__,_file_hash(__file__)))
    for name in ('sw_cam_explicit_island_chain_proof.py','sw_cam_explicit_island_create.py'):
        dep=Path(__file__).with_name(name);roots.append(shared.file_pin(str(dep),_file_hash(dep)))
    roots=merge_pins(roots,[])
    for item in roots:shared.file_pin(item['path'],item['sha256'])
    receipt=Path(v['receipt_path']);marker=Path(v['expected_document_path']).parent/('explicit_island_feature_once_'+_digest(dict(scope=SCOPE,target=str(Path(v['expected_document_path']).resolve()).casefold()))+'.json')
    require(receipt.suffix.lower()=='.json'and receipt.parent.is_dir()and not receipt.exists()and not receipt.is_symlink()
            and not marker.exists()and not marker.is_symlink(),'Fresh receipt and unused target marker required')
    require(not same_path(receipt,marker)and all(not same_path(receipt,x['path'])and not same_path(marker,x['path'])for x in roots),'Output aliases protected evidence')
    copy_record,_=read_pin(batch['receipt']['copy_pin']['path'],batch['receipt']['copy_pin']['sha256'])
    original=Path(copy_record['source']['path']);target=Path(v['expected_document_path'])
    require(copy_record.get('scope')=='EXCLUSIVE_INITIALIZED_CAM_SKETCH_COPY_V1'
            and copy_record.get('exclusive_creation_verified')is True and copy_record.get('source_unchanged')is True
            and same_path(copy_record['target']['path'],v['expected_document_path'])
            and copy_record['target']['sha256']==copy_record['source']['sha256']==batch['receipt']['source_before_sha256'],
            'Exact original exclusive initialized copy required')
    require(not os.path.samefile(original,target)and original.parent.resolve()!=target.parent.resolve(),'Separate physical copy required')
    require(_file_hash(original)==copy_record['source']['sha256'],'Protected initialized source changed')
    return dict(copy=target,original=original,scope=SCOPE,request=deepcopy(v),batch=batch,outer_circle=c,outer_spec=outer,island_specs=batch['specs'],
        expected_cad=cad,expected_inventory=batch['expected_inventory'],feature_plan=p,pins=roots,receipt=receipt,marker=marker,consumed=False)