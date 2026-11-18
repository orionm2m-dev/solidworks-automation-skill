from copy import deepcopy
from pathlib import Path
import importlib.util,json,sys,hashlib,os
import pytest

RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path.home()/'.codex'/'skills'/'solidworks-automation'))
sys.path.insert(0,str(RUNTIME));sys.path.insert(0,str(RUNTIME/'tests'))
from test_circular_gtp_save import states
from scripts import sw_cam_completed_gtp_wip as core
MODULE=Path(__file__).parents[1]/'scripts'/'sw_cam_current_circular_wip_binding.py'
spec=importlib.util.spec_from_file_location('staged_circular_wip_binding',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def pin(path):
    raw=Path(path).read_bytes();return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))


def write(path,value):
    path.write_text(json.dumps(value),encoding='utf8');return pin(path)


def cl_bytes(rows):
    lines=['UNITS/MM','BOX/0,0,0,65,65,60']
    for row in rows:
        oid=row['operation_native_id'];n=row['toolpath_record_counts'][0]
        lines+=['CUTTER/8,0,4,0,0,0,64,','TLAXIS/0,0,1','OPFEATSTART/op'+str(oid),
                'RAPID/','GOTO/'+str(oid)+',0,10','FEDRAT/MMPM,100']
        lines+=['GOTO/'+str(oid)+',0,'+str(-i) for i in range(n-3)]
        lines+=['OPFEATEND/op'+str(oid)]
    return ('\n'.join(lines+['FINI'])+'\n').encode()


def fixture(tmp_path,count=31):
    before,generated=states()
    for fam in ('candidate_consumers','target_nc'):
        before['parameter_batch'][fam]['13']['feeds_compensation']['XYFeed']=1000.
    source=tmp_path/'part.sldprt';source.write_bytes(b'new-saved-part');newsha=pin(source)['sha256'];oldsha=hashlib.sha256(b'old-saved-part').hexdigest()
    generated['operations'][2]['toolpath_record_counts']=[count]
    for state in (before,generated):
        state['document']['path']=str(source);state['sketch_state']['saved_file_sha256']=oldsha
    saved=deepcopy(generated);saved['document']['needs_save']=False;saved['sketch_state'].update(needs_save=False,saved_file_sha256=newsha)
    old=m.delta.inventory(before)['generated'];new=m.delta.inventory(saved)['generated']
    prefile=tmp_path/'before.cl';prefile.write_bytes(cl_bytes(old));postfile=tmp_path/'after.cl';postfile.write_bytes(cl_bytes(new))
    receipt=tmp_path/'saved.json';marker=tmp_path/'once.json';config=write(tmp_path/'config.json',dict(synthetic=True))
    params=dict(process_id=123,expected_process_create_time=100.25,expected_document_path=str(source),expected_source_sha256=oldsha,
                generation_mode='current_saved_circular',selected_operation_native_ids=[13],receipt_path=str(receipt),attempt_registry_path=str(marker))
    req=dict(action='generate_configured_local_group',params=params)
    r=dict(scope=m.generation.SCOPE,status='review_required',phase='finished',request=req,request_sha256=m._digest(req),
           source_before_sha256=oldsha,source_after_sha256=newsha,saved_file_sha256=newsha,selected_operation_native_ids=[13],
           configuration_receipt_pin=config,dispatch_marker_path=str(marker),messages=dict(subscribed=True,active=False,disconnected=True,event_count=0))
    for key in ('model_saved','save_readback_verified','source_update_verified','readback_verified','runtime_unchanged','GTP_attempted','save_attempted','CL_export_attempted','receipt_created','marker_created'):r[key]=True
    for key in ('GOP_attempted','AFR_attempted','operation_creation_attempted','tool_assignment_attempted','parameter_setter_attempted','automatic_replay','automatic_rollback','native_dispatch_pending'):r[key]=False
    returned=dict(attempted=True,returned=True,native_dispatch_pending=False,native_return_type='int',native_return_value=0)
    r['actions']={k:deepcopy(returned)for k in ('preCL','GTP:13','SaveActiveDocument','postCL')}
    r['save_stage']=dict(save_readback_verified=True,native_return_type='int',native_return_value=0)
    for key in ('before','confirm_before','after_preCL','before_GTP_13'):r[key]=deepcopy(before)
    for key in ('generated','after_GTP_13','confirm_GTP_13','before_save'):r[key]=deepcopy(generated)
    for key in ('saved','confirm_saved','after_postCL'):r[key]=deepcopy(saved)
    for key,state,sha,rows,path in [('preCL',before,oldsha,old,prefile),('postCL',saved,newsha,new,postfile)]:
        r[key]=dict(output_verified=True,readback_verified=True,source_sha256=sha,expected_generated_operations=rows,
            before=deepcopy(state),after=deepcopy(state),output=pin(path))
    parsed=[m.parse_generic_cl_bytes(p.read_bytes(),expected_block_record_counts=[x['toolpath_record_counts'][0]for x in rows])for p,rows in ((prefile,old),(postfile,new))]
    r['CL_preservation']=m.delta.compare_cl(*parsed,old,new,[13])
    rp=write(receipt,r)
    mark=dict(scope=m.generation.SCOPE,receipt_path=rp['path'],receipt_sha256=rp['sha256'],configuration_receipt_pin=config,
        selected_operation_native_ids=[13],status='review_required',phase='finished',automatic_replay=False)
    mp=write(marker,mark)
    kw=dict(process_id=123,process_create_time=100.25,source_path=str(source),source_sha256=newsha,selected_operation_ids=[13],
        protected_operation_ids=[x['operation_native_id']for x in old],expected_generated_operations=new,marker_pin=mp)
    return r,rp,kw


def test_real_parser_binding_variable_count_and_no_mutation(tmp_path):
    r,p,kw=fixture(tmp_path,47);original=deepcopy(r)
    result=m.bind_completed_receipt(p,**kw)
    assert result['expected_generated_operations'][-1]['toolpath_record_counts']==[47]
    assert result['protected_operation_ids']==[11] and result['snapshot']==r['saved'] and r==original
    assert result['total_native_records']==64 and result['producer_terminal_revalidated']


@pytest.mark.parametrize('change',[
 lambda r,k:r.update(status='uncertain'),
 lambda r,k:r.update(verified=True,status='prepared'),
 lambda r,k:r.update(cleanup_error={'reason':'event'}),
 lambda r,k:r.update(native_dispatch_pending=True),
 lambda r,k:r['actions']['SaveActiveDocument'].update(native_return_value=True),
 lambda r,k:r['saved']['document'].update(needs_save=True),
 lambda r,k:r['saved']['sketch_state'].update(needs_save=True),
 lambda r,k:r['postCL'].update(source_sha256='0'*64),
 lambda r,k:r['confirm_saved']['operations'][0].update(toolpath_record_counts=[18]),
 lambda r,k:k.update(process_id=124),
 lambda r,k:k.update(process_create_time=100.5),
 lambda r,k:k.update(source_sha256='0'*64),
 lambda r,k:k.update(protected_operation_ids=[12]),
 lambda r,k:k['expected_generated_operations'][-1].update(toolpath_record_counts=[32]),
 lambda r,k:k['expected_generated_operations'][-1].update(toolpath_record_counts=[True]),
 lambda r,k:r['messages'].update(event_count=1),
 lambda r,k:r['postCL'].update(readback_verified=False),
])
def test_untrusted_uncertain_dirty_drift_mapping_rejected(tmp_path,change):
    r,p,k=fixture(tmp_path);change(r,k)
    with pytest.raises(ValueError):m.validate_terminal(r,p,**k)


def test_changed_protected_stream_rejected_even_with_rehashed_file(tmp_path):
    r,p,k=fixture(tmp_path);f=Path(r['postCL']['output']['path']);f.write_bytes(f.read_bytes().replace(b'GOTO/11,0,10',b'GOTO/12,0,10'));r['postCL']['output']=pin(f)
    with pytest.raises(ValueError,match='CL block'):m.validate_terminal(r,p,**k)


def test_source_bytes_changed_blocks_current_binding(tmp_path):
    r,p,k=fixture(tmp_path);Path(k['source_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='evidence changed'):m.bind_completed_receipt(p,**k)


def test_stale_consumed_marker_cannot_rebind(tmp_path):
    r,p,k=fixture(tmp_path);marker=json.loads(Path(k['marker_pin']['path']).read_text());marker['receipt_sha256']='0'*64
    k['marker_pin']=write(Path(k['marker_pin']['path']),marker)
    with pytest.raises(ValueError,match='marker differs'):m.validate_terminal(r,p,**k)


class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def typed(self,x,*args):return x
    def dispatch_once(self,call,persist_pending):persist_pending();return call()
    def summary(self):return dict(mock_guard=True)


def test_reuses_actual_existing_wip_core_once_and_preserves_whole_model_limits(tmp_path):
    r,p,k=fixture(tmp_path);b=m.bind_completed_receipt(p,**k);report=m.new_report(b,output_dir=tmp_path/'wip',implementation_pin=pin(MODULE));calls=[]
    def capture(label):calls.append('capture:'+label);return deepcopy(b['document']),deepcopy(b['snapshot']),dict(machine=object())
    def invoke(machine):calls.append('WIP');return True
    files=[dict(stl_extension=True,bytes=12,sha256='a'*64,path='synthetic.stl')]
    m.run_existing_core(core,b,report,capture_existing=capture,guard_factory=Guard,persist=lambda:None,
        claim=lambda:calls.append('claim'),invoke=invoke,collect=lambda:deepcopy(files))
    assert calls==['capture:before','claim','WIP','capture:after']
    assert report['binding_readback_verified'] and report['outer_cleanup_still_required']
    assert not report['whole_R25_geometry_verified'] and not report['geometry_verified'] and not report['production_qualified']
    assert report['status']=='prepared'
    with pytest.raises(ValueError,match='Fresh bound'):
        m.run_existing_core(core,b,report,capture_existing=capture,guard_factory=Guard,persist=lambda:None,claim=lambda:None,invoke=invoke,collect=lambda:files)


def test_dirty_capture_prevents_native_export(tmp_path):
    r,p,k=fixture(tmp_path);b=m.bind_completed_receipt(p,**k);report=m.new_report(b,output_dir=tmp_path/'wip',implementation_pin=pin(MODULE));calls=[]
    def capture(label):
        doc=deepcopy(b['document']);doc['needs_save']=True
        return doc,deepcopy(b['snapshot']),dict(machine=object())
    with pytest.raises(ValueError,match='Clean saved'):
        m.run_existing_core(core,b,report,capture_existing=capture,guard_factory=Guard,persist=lambda:None,
            claim=lambda:calls.append('claim'),invoke=lambda x:calls.append('WIP'),collect=lambda:[])
    assert not calls


def test_verified_receipt_path_alias_preserves_marker_identity(tmp_path):
    r,p,k=fixture(tmp_path);(tmp_path/'alias_parent').mkdir()
    alias=deepcopy(p);alias['path']=str(tmp_path/'alias_parent'/'..'/'saved.json')
    bound=m.bind_completed_receipt(alias,**k)
    assert bound['receipt_pin']['path']==alias['path']
    assert bound['producer_terminal_revalidated']
