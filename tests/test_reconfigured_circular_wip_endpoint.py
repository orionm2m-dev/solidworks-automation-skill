from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,pytest
from test_reconfigured_circular_wip_binding import fixture,pin
from test_current_circular_wip_binding import Guard
from scripts import sw_cam_reconfigured_circular_wip as m


@pytest.fixture
def setup(tmp_path,monkeypatch):
    r,rp,kw=fixture(tmp_path)
    v=dict(process_id=kw['process_id'],expected_process_create_time=kw['process_create_time'],
        expected_document_path=kw['source_path'],expected_source_sha256=kw['source_sha256'],
        saved_writer_receipt_path=rp['path'],saved_writer_receipt_sha256=rp['sha256'],
        consumed_writer_marker_sha256=kw['marker_pin']['sha256'],writer_module_sha256=kw['writer_pin']['sha256'],
        module_sha256=pin(Path(m.__file__))['sha256'],operation_native_id=361,project_root=str(tmp_path),
        output_dir=str(tmp_path/'wip'),receipt_path=str(tmp_path/'wip.json'),acknowledge_machine_scope=True,
        qualification_only=True,message_policy='vendor_default')
    monkeypatch.setattr(m,'load_context_lineage',lambda r,b:dict(synthetic=True))
    monkeypatch.setattr(m,'preflight',lambda tlb:dict(native_calls=0))
    mode={'name':None};calls=[];contexts=[]
    class Context:
        def __init__(self,sw,clsid,tlb,v,plan,report,persist,runtime_check):
            self.v=v;self.plan=plan;self.report=report;self.closed=False;self.entered=False;self.session=None;contexts.append(self)
        def start(self):
            calls.append('start');self.entered=True
            self.session=SimpleNamespace(summary=lambda:dict(subscribed=True,active=not self.closed,disconnected=self.closed,event_count=0))
        def capture_existing(self,label):
            calls.append('capture:'+label)
            if mode['name']==label:raise ValueError('capture failed')
            b=self.plan['bound'];doc=deepcopy(b['document']);state=deepcopy(b['snapshot'])
            if mode['name']=='dirty_before' and label=='before':doc['needs_save']=True
            if mode['name']=='changed_after' and label=='after':state['operations'][0]['toolpath_record_counts']=[99]
            return doc,state,dict(machine=object())
        def guard(self):
            class G(Guard):
                def __exit__(inner,*args):
                    if mode['name']=='guard_exit':raise ValueError('guard boundary failed after return')
            return G()
        def finish(self):calls.append('finish')
        def close(self):
            if self.closed:return
            calls.append('close');self.closed=True
            self.report['messages']=self.session.summary()
            if mode['name']=='cleanup':raise ValueError('event disconnect failed')
            if mode['name']=='file_drift':(self.plan['directory']/'part.stl').write_bytes(b'drift')
            if mode['name']=='source_drift':Path(self.v['expected_document_path']).write_bytes(b'drift')
        def identity(self):
            for p in self.plan['bound']['pins']:m.common.direct(p)
            return deepcopy(self.plan['bound']['document'])
    def member(machine,name,*args):
        calls.append(name);assert name=='CreateSTLOfWIPs2' and args[1:]==('wip.stl','',0,0)
        (Path(args[0])/'part.stl').write_bytes(b'synthetic STL bytes')
        if mode['name']=='native_exception':raise RuntimeError('unknown native result')
        return False if mode['name']=='native_false' else True
    monkeypatch.setattr(m,'_member',member)
    def runtime():
        if mode['name']=='runtime_after' and 'close'in calls:raise ValueError('runtime changed')
    def run():return m.dispatch(object(),'cls','tlb',runtime_check=runtime,_context_factory=Context,**v)
    return v,mode,calls,contexts,run


def test_one_existing_core_export_clean_release_and_once_marker(setup):
    v,mode,calls,contexts,run=setup;r=run()
    assert r['status']=='review_required',r.get('issue')
    assert calls==['start','capture:before','CreateSTLOfWIPs2','capture:after','finish','close']
    assert r['cleanup_verified'] and r['source_unchanged'] and r['runtime_unchanged']
    assert not r['outer_cleanup_still_required'] and r['native_call_count']==1
    assert r['expected_generated_operations'][-1]['toolpath_record_counts']==[731]
    assert len(r['expected_generated_operations'])==19 and not r['whole_R25_geometry_verified']
    assert not any(r[k]for k in ('GTP_attempted','GOP_attempted','AFR_attempted','model_saved','setter_attempted','assignment_attempted','production_qualified'))
    assert json.loads(Path(v['receipt_path']).read_bytes())==r
    with pytest.raises(ValueError):run()
    assert calls.count('CreateSTLOfWIPs2')==1


@pytest.mark.parametrize('failure',['dirty_before','before','after','changed_after','cleanup','file_drift','source_drift','runtime_after','native_false','native_exception','guard_exit'])
def test_failure_revokes_and_never_replays_or_skips_close(setup,failure):
    v,mode,calls,contexts,run=setup;mode['name']=failure;r=run()
    assert r['status']in('error','uncertain') and not r['readback_verified'] and not r['export_files_verified']
    assert not r['runtime_unchanged'] and r['outer_cleanup_still_required']
    assert calls.count('close')==1 and contexts[0].closed
    assert calls.count('CreateSTLOfWIPs2')<=(0 if failure in ('dirty_before','before') else 1)
    if failure in ('native_false','native_exception','guard_exit'):assert 'capture:after'not in calls
    if failure=='native_exception':assert r['native_dispatch_pending'] and not r['native_call_returned']
    if failure=='guard_exit':
        disk=json.loads(Path(v['receipt_path']).read_bytes())
        assert disk['native_call_returned'] and disk['native_return_value']is True and not disk['native_dispatch_pending']
    if r['marker_created']:
        with pytest.raises(ValueError):run()


@pytest.mark.parametrize('key,value',[('acknowledge_machine_scope',False),('qualification_only',False),('process_id',True),
 ('expected_process_create_time',True),('operation_native_id',True),('module_sha256','0'*64),('writer_module_sha256','0'*64),
 ('expected_source_sha256','0'*64),('saved_writer_receipt_sha256','0'*64),('consumed_writer_marker_sha256','0'*64)])
def test_public_preflight_rejects_invalid_scope_owner_and_pins_without_native(setup,key,value):
    v,mode,calls,contexts,run=setup;v[key]=value
    with pytest.raises(ValueError):run()
    assert not calls and not contexts


def test_read_context_explicitly_denies_mutation_methods():
    for name in ('set_change','generate','save','set_tool','set_field','create_sketch','create_feature','insert_rough','export_cl','adopt_saved_source'):
        with pytest.raises(ValueError,match='Only one guarded'):getattr(m.ReadContext,name)(object())


def test_runtime_revocation_is_durable_and_preserves_native_return(setup):
    v,mode,calls,contexts,run=setup;r=run();m.finalize_runtime_failure(r,ValueError('late runtime change'))
    disk=json.loads(Path(v['receipt_path']).read_bytes())
    assert disk['status']=='uncertain' and disk['native_call_returned'] and not disk['readback_verified']
    assert not disk['runtime_unchanged'] and calls.count('CreateSTLOfWIPs2')==1


def test_lineage_loader_uses_historical_hash_only_as_metadata(monkeypatch):
    # It does not validate old source bytes and passes only the current owned identity.
    import inspect
    source=inspect.getsource(m.load_context_lineage)
    assert '_file_hash'not in source and 'expected_source_sha256' in source
    values={('nc','n'):dict(request=dict(reconciliation_path='review',reconciliation_sha256='r')),
        ('review','r'):dict(pins=dict(save_receipt=dict(path='save',sha256='s'))),
        ('save','s'):dict(historical_generation_pin=dict(path='history',sha256='h')),
        ('history','h'):dict(request=dict(params=dict(configuration_receipt_path='config',configuration_receipt_sha256='c',expected_source_sha256='oldhash')))}
    monkeypatch.setattr(m.writer,'read_pin',lambda p,h:(deepcopy(values[(p,h)]),dict(path=p,sha256=h)))
    calls=[]
    def load(*args,**kwargs):calls.append((args,kwargs));return dict(mode='current_saved_circular')
    monkeypatch.setattr(m.writer.engine,'load_completed_configuration',load)
    r=dict(request=dict(nc_receipt_path='nc',nc_receipt_sha256='n'),recipe={})
    values[('writer','w')]=deepcopy(r)
    b=dict(process_id=99,source_path='current.sldprt',selected_operation_ids=[7],snapshot={},receipt_pin=dict(path='writer',sha256='w'),saved_CL={},pins=[pin(Path(m.writer.__file__))])
    got=m.load_context_lineage(r,b)
    assert calls[0][1]==dict(process_id=99,source_path='current.sldprt',source_sha256='oldhash',selected_ids=[7])
    assert got['state']=={} and len(got['pins'])==5
    assert got['module_sha256']==pin(Path(m.writer.__file__))['sha256']


def test_actual_revision_context_constructor_and_verify_files_contract(tmp_path,monkeypatch):
    # Keep actual writer.RevisionContext.__init__/verify_files and our subclass.
    # Only its older capture-layout constructor/JSON ancestry checks are synthetic.
    r,rp,kw=fixture(tmp_path);bound=m.binding.bind_completed_revision(rp,**kw)
    args=dict(process_id=kw['process_id'],expected_process_create_time=kw['process_create_time'],
        expected_source_sha256='a'*64,expected_document_path=kw['source_path'],saved_cl_path=r['postCL']['output']['path'])
    data=dict(args=args,loaded=dict(addin_clsid='cls'),recipe=r['recipe'],state=bound['snapshot'],
        pins=[m.writer.read_pin(rp['path'],rp['sha256'])[1]],cl_pin=bound['saved_CL'],module_sha256=kw['writer_pin']['sha256'])
    plan=dict(lineage=data,writer_receipt=r,bound=bound,dependencies=[])
    def prior_init(self,sw,clsid,tlb,args,loaded,report,persist,runtime_check):
        self.source=args['expected_source_sha256'];self.v=deepcopy(args);self.pins=[];self.data={}
        self.report=report;self.persist=persist;self.runtime_check=runtime_check;self.request={}
    monkeypatch.setattr(m.writer.CircularGenerationContext,'__init__',prior_init)
    monkeypatch.setattr(m.writer.nc_read,'preflight',lambda tlb:({},{}))
    class NoApplication:
        def __getattr__(self,key):raise AssertionError('No application access permitted')
    v=dict(expected_source_sha256=kw['source_sha256'],process_id=kw['process_id'],expected_process_create_time=kw['process_create_time'])
    ctx=m.ReadContext(NoApplication(),'cls','tlb',v,plan,{},lambda:None,lambda:None)
    assert ctx.source==kw['source_sha256'] and ctx.revision['module_sha256']==kw['writer_pin']['sha256']
    ctx.verify_files()
    # The inherited guard still rejects missing metadata, identical-hash identity drift, and content drift.
    original=deepcopy(ctx.pins[0])
    ctx.pins[0]={k:original[k]for k in ('path','sha256')}
    with pytest.raises(ValueError,match='Immutable circular authority changed'):ctx.verify_files()
    ctx.pins[0]=deepcopy(original);ctx.pins[0]['identity'][3]+=1
    with pytest.raises(ValueError,match='Immutable circular authority changed'):ctx.verify_files()
    ctx.pins[0]=deepcopy(original);ctx.pins[0]['sha256']='0'*64
    with pytest.raises(ValueError):ctx.verify_files()
    ctx.pins[0]=original;ctx.verify_files()
    ctx.revision['module_sha256']='0'*64
    with pytest.raises(ValueError,match='Revision implementation changed'):ctx.verify_files()
