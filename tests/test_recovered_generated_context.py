"""Synthetic completed-recovery admission; no native calls or actual pending receipt."""
from copy import deepcopy
from pathlib import Path
import ast,hashlib,json,os,sys
import pytest
STAGE=Path(__file__).resolve().parents[1]
RT=Path(os.environ['SWMCP_RUNTIME_ROOT'])
sys.dont_write_bytecode=True
sys.path[:0]=[str(RT),str(RT/'tests')]
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_recovered_generated_context as m
from test_current_pocket_generation_delta import snapshot,generated,native
from test_current_pocket_generate import transform

def pin(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def write(p,r):
    p.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return m.definition.read_pin(str(p),pin(p)['sha256'])[1]

def clean():return dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])

def saved_receipt(before,after,context,identity,roots,predecessor,scope):
    value=deepcopy(context);new=after['inventory']['saved_file_sha256']
    value['expected_source_sha256']=new;value['current_sketch_baseline']['saved_file_sha256']=new
    payload=dict(scope=scope,identity=deepcopy(identity),capture_context=value,snapshot=deepcopy(after),state_sha256=m.producer._digest(after),root_pins=deepcopy(roots),predecessor_pin=deepcopy(predecessor),limitations=deepcopy(m.current.LIMITS),source_transition=dict(before_sha256=before['inventory']['saved_file_sha256'],after_sha256=new,native_return_value=0))
    norm=m.current._without_save_fields(after)
    return dict(status='review_required',phase='finished',current_context_verified=True,save_readback_verified=True,inventory_delta_verified=True,parameter_delta_verified=True,runtime_unchanged=True,model_saved=True,
        current_context=payload,current_baseline_receipt_pin=deepcopy(predecessor),save_snapshots=dict(before=deepcopy(before),after=deepcopy(after)),native_save=dict(native_call_returned=True,save_pending=False,native_return_type='int',native_return_value=0,save_readback_verified=True,before=deepcopy(norm),after=deepcopy(norm),saved_file_sha256=new),
        saved_file_sha256_after_native_return=new,after_cleanup_identity=dict(document=deepcopy(after['inventory']['document']),saved_file_sha256=new),messages=clean(),GTP_attempted=False,GOP_attempted=False,Import_attempted=False,automatic_replay=False,production_qualified=False)

def synthetic_producer(tmp_path):
    target=tmp_path/'synthetic.sldprt';target.write_bytes(b'synthetic current saved generation')
    new=pin(target)['sha256'];old=hashlib.sha256(b'synthetic predecessor').hexdigest()
    before=snapshot();before['inventory']['saved_file_sha256']=old
    before['inventory']['document'].update(path=str(target),title='synthetic.sldprt')
    observed=json.loads((RT/'tests/fixtures/rough_parameter_row.json').read_text(encoding='utf-8'))['row']
    before['parameters'][0]['rough']=deepcopy(observed['rough']);before['parameters'][0]['rough_diagnostic']=deepcopy(observed['rough_diagnostic'])
    levels=dict(setup=dict(origin_native=[0.,0.,26.],axis_native=[0.,0.,-1.]))
    for row in before['parameters']:
        row['levels']=deepcopy(levels);row['nc']['feeds_compensation']={'XYFeed':700.0}
    fid=53;ids=[31,48];identity=dict(process_id=123,expected_process_create_time=123.5,expected_document_path=str(target),expected_source_sha256=old,expected_feature_native_id=fid,expected_operation_native_ids=ids)
    header=before['inventory']['selected_feature']
    context=dict(process_id=123,expected_document_path=str(target),expected_source_sha256=old,expected_feature_native_id=fid,current_sketch_baseline=dict(saved_file_sha256=old,needs_save=False,features=['synthetic'],solids=[]),
        request=dict(process_id=123,expected_process_create_time=123.5,expected_document_path=str(target),expected_sw_configuration='Default',expected_cam_configuration='Mill',owner_setup_native_id=7),creator=dict(status='uncertain',feature_header=deepcopy(header)),spec={'synthetic':True})
    modules=[m.producer,m.delta,m.fields,m.producer.engine,m.producer.generation,m.producer.transforms,m.producer.transforms.metadata_reader,m.current,m.producer.tool,m.delta.existing,m.producer.cl_reader,m.producer.cl_bounded,m.producer.definition_capture,m.producer.guard_module]
    root=tmp_path/'immutable.bin';root.write_bytes(b'root');roots=[pin(root)]+[pin(Path(x.__file__))for x in modules]
    older=deepcopy(before);older['inventory']['saved_file_sha256']='c'*64
    ancestor=write(tmp_path/'ancestor.json',{'synthetic':True})
    previous=saved_receipt(older,before,context,identity,roots,ancestor,m.current.legacy.SCOPE)
    previous['scope']='CURRENT_POCKET_EXISTING_ASSIGNED_TOOL_RECOVERY_V1'
    pp=write(tmp_path/'previous.json',previous)
    flat=m.delta.flatten(before);row=before['parameters'][0]
    changes=[dict(field=name,expected=m.fields.field_value(row,name),new=m.fields.field_value(row,name))for name in m.producer.FIELD_NAMES]
    recipe=dict(schema_version=1,rows=[dict(operation_native_id=31,feature_native_id=53,operation_type=0,expected_tool_native_id=81,existing_tool_native_id=None,fields=changes)])
    rp=write(tmp_path/'recipe.json',recipe);roots+= [rp]
    raw_cl=b'UNITS/MM\nOPFEATSTART/SYNTHETIC\nCUTTER/8,0,0,0,0,0,40\nTLAXIS/0,0,1\nRAPID/\nRAPID/\nGOTO/0,0,10\nOPFEATEND/SYNTHETIC\nFINI\n'
    cl=tmp_path/'synthetic.cl';cl.write_bytes(raw_cl);cp=pin(cl);parsed=m.parse_generic_cl_bytes(raw_cl,expected_block_record_counts=[5])
    gen=generated(before,count=5,dirty=True);saved=deepcopy(gen);saved['inventory']['saved_file_sha256']=new;saved['inventory']['document']['needs_save']=False
    current_identity=dict(identity,expected_source_sha256=new)
    report=saved_receipt(gen,saved,context,current_identity,roots,pp,m.current.SCOPE)
    request=dict(identity,selected_operation_native_id=31,current_context_receipt_path=pp['path'],current_context_receipt_sha256=pp['sha256'],recipe_path=rp['path'],recipe_sha256=rp['sha256'],receipt_path=str(tmp_path/'terminal.json'),saved_cl_path=str(cl),qualification_only=True,acknowledge_settings_generation_save_export=True,message_policy='vendor_default')
    report.update(scope=m.producer.SCOPE,evidence_pin_limit=128,request=request,configuration_receipt_pin=pp,recipe=recipe,recipe_pin=rp,before=deepcopy(before),configured=deepcopy(before),generated=deepcopy(gen),saved=deepcopy(saved),
        selected_operation_native_ids=[31],actions={name:native()for name in ['GTP:31','SaveActiveDocument','postCL']},field_readbacks=[dict(field=c['field'],before=c['expected'],requested=c['new'],setter_attempted=False,readback_verified=True,actual=c['new'])for c in changes],
        generation_proof=m.delta.verify_generation(before,gen,31,native()),setup_transform=transform(),setup_transform_proof=m.producer.verify_transform(transform(),levels),
        first_CL_proof=m.delta.verify_first_cl(parsed,31,5),postCL=dict(output_verified=True,readback_verified=True,output=dict(cp,bytes=len(raw_cl))),
        evidence_pins=roots+[pp,dict(path=str(target),sha256=old)],GTP_attempted=True,Save_attempted=True,save_attempted=True,CL_export_attempted=True,receipt_created=True,marker_created=True,native_call_attempted=True,native_call_returned=True,
        physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,island_geometry_verified=False,geometry_sweep_verified=False,native_dispatch_pending=False,**{k:True for k in m.producer.FLAGS})
    labels=['before','configured','generated','confirm_generated','before','after'];values=[before,before,gen,gen,gen,saved]
    report['captures']=[dict(label=label,diagnostic=dict(capture_complete=True,state=deepcopy(x['inventory'])),observation=deepcopy(x))for label,x in zip(labels,values)]
    receipt=write(Path(request['receipt_path']),report)
    marker=dict(scope=m.producer.SCOPE,receipt_path=receipt['path'],receipt_sha256=receipt['sha256'],configuration_receipt_pin=pp,selected_operation_native_ids=[31],status='review_required',phase='finished',automatic_replay=False)
    marker_pin=write(m.producer.marker_path(request),marker)
    v=dict(current_identity,generated_receipt_path=receipt['path'],generated_receipt_sha256=receipt['sha256'])
    return dict(r=report,previous=previous,recipe=recipe,marker=marker,parsed=parsed,pin=receipt,v=v,cl=cl,marker_pin=marker_pin,root=root)


@pytest.fixture
def packet(tmp_path):
    p=synthetic_producer(tmp_path);old=p['r'];previous=p['previous'];pp=old['configuration_receipt_pin'];q=deepcopy(old['request']);q['receipt_path']=str(tmp_path/'failed_gtp.json')
    before=deepcopy(old['before']);gen=deepcopy(old['generated']);gen['parameters'][0]['nc']['feeds_compensation']['XYFeed']=1400.0
    raw=deepcopy(old)
    for key in ('current_context','current_baseline_receipt_pin','save_snapshots','native_save','saved_file_sha256_after_native_return','after_cleanup_identity','saved','postCL','first_CL_proof','generation_proof'):
        raw.pop(key,None)
    raw.update(request=q,status='uncertain',phase='finished',failed_phase='generated',reason=m.recovery.REASON,issue=dict(type='ValueError',hresult=None,locations=[dict(file=f,function=n)for f,n in [('sw_cam_current_pocket_generation_delta.py','verify_generation'),('sw_cam_current_saved_generation_delta.py','verify_generation'),('sw_cam_current_saved_generation_delta.py','require')]]),generated=gen,
        actions={'GTP:31':native()},Save_attempted=False,save_attempted=False,save_readback_verified=False,model_saved=False,CL_export_attempted=False,**{k:False for k in m.producer.FLAGS})
    raw['captures']=[dict(label=l,diagnostic=dict(capture_complete=True,state=deepcopy(v['inventory'])),observation=deepcopy(v))for l,v in [('before',before),('configured',before),('generated',gen)]]
    raw_pin=write(Path(q['receipt_path']),raw)
    old_marker=dict(scope=m.producer.SCOPE,receipt_path=str(Path(q['receipt_path'])),receipt_sha256=raw_pin['sha256'],configuration_receipt_pin=pp,selected_operation_native_ids=[31],status='uncertain',phase='finished',automatic_replay=False)
    marker_pin=write(m.producer.marker_path(q),old_marker)
    rq={k:deepcopy(q[k])for k in m.recovery.IDENTITY}
    rq.update(failed_generation_receipt_path=raw_pin['path'],failed_generation_receipt_sha256=raw_pin['sha256'],observed_xy_feed_before=700.0,observed_xy_feed_after=1400.0,receipt_path=str(tmp_path/'recovery.json'),saved_cl_path=str(p['cl']),qualification_only=True,acknowledge_observed_feed_save_export=True,message_policy='vendor_default')
    prior_bundle=dict(context=previous['current_context']['capture_context'],state=before['inventory'],parameters=before['parameters'],receipt_pin=pp)
    proof=m.recovery.verify_partial(raw,rq,prior_bundle,p['recipe'])
    saved=deepcopy(gen);saved['inventory']['saved_file_sha256']=p['v']['expected_source_sha256'];saved['inventory']['document']['needs_save']=False
    roots=m.current.pin_union(old['current_context']['root_pins'],[raw_pin,marker_pin,pin(Path(m.recovery.__file__))])
    context=deepcopy(previous['current_context']['capture_context']);identity={k:p['v'][k]for k in m.current.IDENTITY_KEYS}
    r=saved_receipt(gen,saved,context,identity,roots,pp,m.recovery.GENERATED_SCOPE)
    r['current_context'].update(historical_generation_receipt_pin=raw_pin,observed_feed_delta=proof['feed_delta'])
    r['native_save'].update(phase='after_capture',save_attempted=True,mutation_attempted=True,native_call_attempted=True)
    r.update(scope=m.recovery.SCOPE,evidence_pin_limit=128,request=rq,configuration_receipt_pin=raw_pin,historical_GTP_receipt_pin=raw_pin,historical_marker_pin=marker_pin,historical_status='uncertain',historical_runtime_unchanged=False,
        selected_operation_native_ids=[31],recipe=deepcopy(p['recipe']),recipe_pin=raw['recipe_pin'],observed_feed_delta=proof['feed_delta'],historical_generation_proof=proof['generation_proof'],setup_transform=raw['setup_transform'],setup_transform_proof=raw['setup_transform_proof'],
        before=gen,confirm_before=deepcopy(gen),second_capture_roles=['generated_state_confirmation','save_before'],saved=saved,baseline_generated_operation_count=1,
        actions={n:native()for n in ['SaveActiveDocument','postCL']},Save_attempted=True,save_attempted=True,CL_export_attempted=True,receipt_created=True,marker_created=True,native_call_attempted=True,native_call_returned=True,mutation_attempted=True,feed_unqualified=True,
        operation_parameter_setters_attempted=False,setters_replayed=False,GTP_replayed=False,preCL_exported=False,native_dispatch_pending=False,feed_change_cause_verified=False,physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,island_geometry_verified=False,geometry_sweep_verified=False,reopen_persistence_verified=False,
        evidence_pins=m.current.pin_union(raw['evidence_pins'],[raw_pin,marker_pin,pin(Path(m.recovery.__file__))]),**{k:True for k in m.recovery.FLAGS})
    r['captures']=[dict(label=l,diagnostic=dict(capture_complete=True,state=deepcopy(v['inventory'])),observation=deepcopy(v))for l,v in [('recovery_current',gen),('before',gen),('after',saved),('postCL_before',saved),('postCL_after',saved)]]
    flat=m.delta.flatten(saved);rows=[dict(operation_native_id=31,toolpath_record_counts=[5])]
    r['postCL']=dict(output_verified=True,readback_verified=True,native_call_returned=True,native_dispatch_pending=False,output_directory_created=True,source_sha256=identity['expected_source_sha256'],document=saved['inventory']['document'],before=flat,after=deepcopy(flat),expected_generated_operations=rows,output_path=str(p['cl']),output=dict(pin(p['cl']),bytes=p['cl'].stat().st_size),parse_summary=dict(parse_complete=True,native_count_matches=True,blocks=1,declared_units=['MM']))
    r['first_CL_proof']=m.delta.verify_first_cl(p['parsed'],31,5)
    rp=write(Path(rq['receipt_path']),r)
    marker=dict(scope=m.recovery.SCOPE,receipt_path=str(Path(rq['receipt_path'])),receipt_sha256=rp['sha256'],configuration_receipt_pin=raw_pin,selected_operation_native_ids=[31],status='review_required',phase='finished',automatic_replay=False)
    recovery_marker_pin=write(m.recovery.marker_path(rq),marker)
    return dict(r=r,raw=raw,previous=previous,recipe=p['recipe'],markers=dict(original=old_marker,recovery=marker),pin=rp,raw_pin=raw_pin,previous_pin=pp,v=dict(identity,recovered_receipt_path=rp['path'],recovered_receipt_sha256=rp['sha256']),cl=p['cl'],parsed=p['parsed'],root=p['root'],marker_pins=[marker_pin,recovery_marker_pin])


def verify(p):return m.verify_terminal(p['r'],p['raw'],p['previous'],p['recipe'],p['markers'],p['pin'],p['raw_pin'],p['previous_pin'],p['v'])


def test_genuine_recovery_load_preserves_every_immutable_pin_and_history(packet):
    p=packet;before={str(x):x.read_bytes()for x in [Path(p['pin']['path']),Path(p['raw_pin']['path']),Path(p['previous_pin']['path']),p['cl']]}
    b=m.load(p['v']);assert b['protected_generated']=={31:[5]} and b['state']==p['r']['saved']['inventory'] and b['parameters']==p['r']['saved']['parameters']
    assert b['context']['saved_plan_inventory']==b['state'] and b['feed_delta']['feed_unqualified']is True and b['live_capture_verified']is False and b['native_calls']==0
    immutable=[x for x in p['r']['evidence_pins']if not m.definition.creator.same_path(x['path'],p['v']['expected_document_path'])]
    assert m._pin_keys(immutable)<=m._pin_keys(b['pins'])
    assert all(Path(path).read_bytes()==data for path,data in before.items()) and m.verify_files(b)
    assert m.verify_protected_cl(b['protected_cl'],p['parsed'],b['protected_cl']['rows'])['protected_complete_streams_verified']


@pytest.mark.parametrize('change',[
 lambda p:p['r'].update(status='uncertain'),lambda p:p['r'].update(phase='postCL'),lambda p:p['r'].update(scope=m.producer.SCOPE),
 lambda p:p['r'].update(readback_verified=False),lambda p:p['r'].update(native_dispatch_pending=True),lambda p:p['r'].update(GTP_replayed=True),lambda p:p['r'].update(setters_replayed=True),lambda p:p['r'].update(feed_unqualified=False),
 lambda p:p['r']['actions'].update(unrequested=native()),lambda p:p['r']['actions']['SaveActiveDocument'].update(native_return_value=True),lambda p:p['r']['native_save'].update(save_pending=True),
 lambda p:p['r']['captures'].pop(),lambda p:p['r']['captures'][4]['observation']['parameters'][1]['nc'].update(feed=999),
 lambda p:p['r']['observed_feed_delta'].update(after=777),lambda p:p['raw']['generated']['parameters'][1]['nc'].update(feed=999),
 lambda p:p['r']['current_context']['capture_context'].update(expected_source_sha256='f'*64),lambda p:p['r']['current_context']['source_transition'].update(before_sha256='f'*64),lambda p:p['r']['current_context']['capture_context']['creator'].update(status='success'),
 lambda p:p['r']['current_context']['limitations'].update(production_qualified=True),lambda p:p['r']['postCL'].update(readback_verified=False),lambda p:p['r']['postCL']['before'].update(total_record_count=999),
 lambda p:p['markers']['original'].update(extra=True),lambda p:p['markers']['recovery'].update(receipt_path='C:/foreign/receipt.json'),lambda p:p['markers']['recovery'].update(receipt_sha256='f'*64),
 lambda p:p['v'].update(process_id=124),lambda p:p['v'].update(expected_source_sha256='f'*64),lambda p:p['r'].update(selected_operation_native_ids=[48]),
])
def test_terminal_semantic_drift_rejected(packet,change):
    change(packet)
    with pytest.raises((ValueError,KeyError,IndexError)):verify(packet)


@pytest.mark.parametrize('changed',['label','whitespace','payload'])
def test_actual_raw_cl_changed_rejected(packet,changed):
    p=packet;raw=p['cl'].read_bytes();p['cl'].write_bytes(raw.replace(b'SYNTHETIC',b'OTHER')if changed=='label'else raw+bytes([10])if changed=='whitespace'else raw.replace(b'GOTO/0,0,10',b'GOTO/0,0,11'))
    with pytest.raises(ValueError):m.load(p['v'])


def test_verify_files_accepts_added_dependency_but_rejects_loss_or_change(packet,tmp_path):
    b=m.load(packet['v']);extra=tmp_path/'new-reader.py';extra.write_text('# new authority dependency',encoding='utf-8')
    b['pins']=m.current.pin_union(b['pins'],[pin(extra)]);b['context']['pins']=deepcopy(b['pins']);assert m.verify_files(b)
    b['pins']=b['pins'][1:];b['context']['pins']=deepcopy(b['pins'])
    with pytest.raises(ValueError,match='dropped or replaced'):m.verify_files(b)


@pytest.mark.parametrize('which',['canonical_path','bytes','identity'])
def test_real_rich_pin_metadata_rejected(packet,which):
    p=packet;rich=deepcopy(p['previous_pin']);rich[which]='C:/foreign'if which=='canonical_path'else 0 if which=='bytes'else[0]*6
    with pytest.raises(ValueError):m._bytes(rich)


def test_capacity_128_accepts_129_conflict_rejects(packet,tmp_path):
    b=m.load(packet['v']);pins=deepcopy(b['pins'])
    while len(pins)<128:
        p=tmp_path/f'capacity-{len(pins)}.txt';p.write_text('proof',encoding='utf-8');pins.append(pin(p))
    b['pins']=m.current.pin_union(pins);b['context']['pins']=deepcopy(b['pins']);assert m.verify_files(b)
    p=tmp_path/'overflow.txt';p.write_text('proof',encoding='utf-8')
    with pytest.raises(ValueError):m.current.pin_union(pins,[pin(p)])
    with pytest.raises(ValueError):m.current.pin_union(pins,[dict(pins[0],sha256='f'*64)])


def test_source_has_no_dispatch_mutation_or_scope_rewrite():
    tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr in ('dispatch_once','SaveActiveDocument','GenerateToolpath','GetAddInObject','IGetActiveDoc')for n in ast.walk(tree))


def resign_terminal(p):
    rp=write(Path(p['pin']['path']),p['r']);p['pin']=rp;p['v']['recovered_receipt_sha256']=rp['sha256']
    p['markers']['recovery']['receipt_sha256']=rp['sha256']
    write(m.recovery.marker_path(p['r']['request']),p['markers']['recovery'])


@pytest.mark.parametrize('location,expected',[('evidence_pins','dropped original evidence'),('root_pins','dropped saved predecessor roots')])
def test_load_rejects_deleted_immutable_history_even_if_receipt_and_marker_rehashed(packet,location,expected):
    p=packet;key=m.definition.creator.canonical(str(p['root']))
    target=p['r'] if location=='evidence_pins' else p['r']['current_context']
    target[location]=[x for x in target[location]if m.definition.creator.canonical(x['path'])!=key]
    resign_terminal(p)
    with pytest.raises(ValueError,match=expected):m.load(p['v'])


@pytest.mark.parametrize('location',['original','recovery'])
def test_changed_consumed_marker_bytes_rejected(packet,location):
    p=packet;index=0 if location=='original'else 1;path=Path(p['marker_pins'][index]['path']);marker=json.loads(path.read_bytes());marker['extra']=True;write(path,marker)
    with pytest.raises(ValueError):m.load(p['v'])
