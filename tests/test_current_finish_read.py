from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_current_finish_read as m


def graph():
    cutting=dict(GetSpndlSpeed=200.,GetCNCComp=0,GetTlpComp=1,XYFeed=500.,GetSpeedFeedMethod=0,LinkToTool=True,GetIsLockSpindleSpeed=False,GetZFeedrate2=(2.,False),GetLeadinFeedratePercent=30.)
    lead=dict(LeadType=1,LeadAngle=0.,ArcAngle=90.,SidePassType=0,CutDepthType=0,StartAngle=0.,GetArcRadius2=(10.,True,0.),GetLeadOverlap2=(1.,False,0.),GetLeadAmt2=(1.,False,0.),GetIsSameLeadinout=False,GetFeedRate=(2.,False))
    feature=dict(native_id=70);feature['QueryInterface']=lambda cls:feature
    ops=[];expected=[]
    for i in range(26):
        oid=358 if i==24 else 361 if i==25 else 100+i;kind=1 if oid==358 else 0;counts=[500 if i==25 else 10] if i<18 or i==25 else [];tid=252 if oid==358 else 249
        ops.append(dict(native_id=oid,OpernType=kind,Suppressed=False,GetIsToolpathGenerated=bool(counts),IGetEnumToolpaths=[dict(RecordCount=x) for x in counts],IGetTool=dict(native_id=tid)))
        expected.append(dict(native_id=oid,setup_native_id=94,mill_operation_type=kind,suppressed=False,toolpath_generated=bool(counts),toolpath_record_counts=counts,assigned_tool=dict(native_id=tid)))
    target=ops[-2];target.update(IGetAllFeatures=[feature],IGetNCParam=cutting,GetFirstDepthCut=(1.,False),GetMaxDepthCut=(1.,True),GetSideCutAmt=(10.,True),GougeCheck=True,GetIsSingleCutDepth=False,GetToolRadiusLeadInLeadOut=False,LeadInOutApplyToAll=True,DepthProcessOpt=0,IGetLeadin=lambda f:lead,IGetLeadout=lambda f:deepcopy(lead))
    setup=dict(native_id=94,IGetEnumOperations=ops);doc=dict(IGetMachine=dict(MachType=1,IGetEnumOpSetups=[setup]));doc['GetCWObjectID']=lambda x:(x['native_id'],True);doc['GetCWObjectFromID']=lambda kind,oid:(feature,True)
    app=dict(IGetActiveDoc=doc);loaded=dict(state=dict(operations=expected));v=dict(operation_native_id=358,expected_feature_native_id=70,expected_tool_native_id=252)
    count=[0];calls=[]
    def read(obj,name,*args):
        count[0]+=1;calls.append(name)
        if name=='Count':return len(obj)
        if name=='Item':return obj[args[0]]
        value=obj[name];return value(*args) if callable(value) else value
    def typed(obj,name):count[0]+=1;return obj
    def pointer(obj,detail):count[0]+=1;detail['returned']=True;return dict(value_native=2.,is_percent=False,physical_units_verified=False)
    return app,loaded,v,read,typed,pointer,lambda:None,count,ops,target,cutting,lead,calls


def test_actual_26_operation_graph_two_reads_preserves_modes_and_19paths():
    g=graph();a=m.capture(*g[:7]);b=m.capture(*g[:7]);assert a==b
    assert len(a['inventory'])==26 and sum(x['toolpath_generated'] for x in a['inventory'])==19
    assert a['depth_and_side_pairs']=={'GetFirstDepthCut':[1.,False],'GetMaxDepthCut':[1.,True],'GetSideCutAmt':[10.,True]}
    assert a['leads']['lead_in']['GetArcRadius2']['decoded']['percent'] is True
    assert a['nc']['LinkToTool'] is True and a['nc']['leadin_feed']['is_percent'] is False
    assert g[7][0]<m.MAX_READS and set(g[-1])<=m.GETTERS
    assert not any(x.startswith('Set') or x in ('GenerateToolpath','SaveActiveDocument') for x in g[-1])


@pytest.mark.parametrize('mutate',[lambda g:g[8][0].update(GetIsToolpathGenerated=False),lambda g:g[8][0]['IGetTool'].update(native_id=999),lambda g:g[9].update(OpernType=0),lambda g:g[9].update(IGetAllFeatures=[dict(native_id=71)]),lambda g:g[9].update(GetFirstDepthCut=(False,1.)),lambda g:g[9].update(GetMaxDepthCut=(1.,1)),lambda g:g[9].update(GetSideCutAmt=(float('nan'),False)),lambda g:g[9].update(GougeCheck=1),lambda g:g[10].update(GetSpeedFeedMethod=3),lambda g:g[10].update(LinkToTool=1),lambda g:g[10].update(GetZFeedrate2=(1.,1)),lambda g:g[11].update(GetArcRadius2=(1.,False)),lambda g:g[11].update(GetFeedRate=(2.,1))])
def test_actual_capture_rejects_table_identity_and_wrong_output_modes(mutate):
    g=graph();mutate(g)
    with pytest.raises(ValueError):m.capture(*g[:7])


def test_installed_type_metadata_preflight_no_application_calls():
    classes,proof=m.preflight(Path('D:/Program Files/SOLIDWORKS Corp/SOLIDWORKS CAM/camworks.tlb'))
    assert proof['native_calls']==proof['application_connections']==0 and proof['getters_only']
    assert 'ICWFinishMillOp3' in classes and 'ICWLeadInOut' in classes


@pytest.fixture
def lifecycle(tmp_path,monkeypatch):
    v=dict(process_id=123,expected_process_create_time=1.25,expected_document_path=str(tmp_path/'p.sldprt'),expected_source_sha256='a'*64,revision_receipt_path='r.json',revision_receipt_sha256='b'*64,revision_marker_path='m.json',revision_marker_sha256='c'*64,operation_native_id=358,expected_feature_native_id=70,expected_tool_native_id=252,receipt_path=str(tmp_path/'out.json'),qualification_only=True,message_policy='vendor_default')
    doc=dict(path=v['expected_document_path'],title='p',type=1,needs_save=False);loaded=dict(state={'document':doc},pins=[],receipt=Path(v['receipt_path']),bound={'binding_sha256':'d'*64})
    monkeypatch.setattr(m,'validate',lambda values:loaded);monkeypatch.setattr(m,'preflight',lambda tlb:({},{}));monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kw:nullcontext());monkeypatch.setattr(m,'_process_identity',lambda pid:dict(alive=True,process_id=123,create_time=1.25,executable='C:/sldworks.exe'));monkeypatch.setattr(m,'document_snapshot',lambda sw:deepcopy(doc));monkeypatch.setattr(m,'_file_hash',lambda p:'a'*64);monkeypatch.setattr(m,'_typed',lambda obj,*x:obj)
    state=dict(mode=None,captures=0,native=[])
    def member(obj,name,*args):
        state['native'].append(name)
        if name=='GetProcessID':return 123
        if name in ('GetAddInObject','GetCWApp'):return object()
        raise AssertionError('Unexpected native member '+name)
    monkeypatch.setattr(m,'_member',member)
    class Session:
        def __init__(self,*args):self.active=False;self.closed=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*args):self.active=False;self.closed=True
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=self.closed,event_count=1 if state['mode']=='event' else 0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=['bad'] if self.closed and state['mode']=='cleanup' else [])
    monkeypatch.setattr(m,'CamMessageSession',Session)
    def capture(app,loaded,v,read,typed,pointer,boundary,progress=None):
        boundary();state['captures']+=1
        if state['mode']=='source' and state['captures']==2:monkeypatch.setattr(m,'_file_hash',lambda p:'x'*64)
        boundary();return dict(capture_complete=True,value=3 if state['mode']=='mismatch' and state['captures']==2 else 2)
    monkeypatch.setattr(m,'capture',capture)
    return v,state


def test_read_only_lifecycle_durable_and_no_mutation(lifecycle):
    v,s=lifecycle;r=m.dispatch(object(),'cls','tlb',runtime_check=lambda:None,**v)
    assert r['readback_verified'] and r['source_unchanged'] and s['captures']==2 and r['before']==r['after']
    assert not any(r[k] for k in ('mutation_attempted','save_attempted','GTP_attempted','GOP_attempted','parameter_setter_attempted'))
    assert json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))==r


@pytest.mark.parametrize('mode',['event','cleanup','source','mismatch'])
def test_read_failure_never_promotes_or_mutates(lifecycle,mode):
    v,s=lifecycle;s['mode']=mode;r=m.dispatch(object(),'cls','tlb',runtime_check=lambda:None,**v)
    assert r['status']=='error' and not r['readback_verified'] and not r['source_unchanged'] and not r['mutation_attempted']
    assert 'failed_read' not in r


def test_runtime_revocation_durable(lifecycle):
    v,s=lifecycle;r=m.dispatch(object(),'cls','tlb',runtime_check=lambda:None,**v);m.finalize_runtime_failure(r,ValueError('changed'))
    assert json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))==r and not r['readback_verified']


@pytest.fixture
def loader(tmp_path,monkeypatch):
    source=tmp_path/'source.sldprt';source.write_bytes(b'saved part');sha=m._file_hash(source)
    receipt=tmp_path/'revision.json';parent=dict(scope=m.writer.SCOPE,status='review_required',phase='finished',operation_native_id=361,postCL=dict(expected_generated_operations=[dict(operation_native_id=100,toolpath_record_counts=[10]),dict(operation_native_id=361,toolpath_record_counts=[500])]))
    receipt.write_text(json.dumps(parent),encoding='utf-8')
    state=dict(operations=[dict(native_id=358,mill_operation_type=1,suppressed=False,linked_feature_ids=[70],assigned_tool=dict(native_id=252))])
    bound=dict(snapshot=state,pins=[],binding_sha256='d'*64);seen=[]
    def bind(pin,**kw):seen.append((pin,kw));return deepcopy(bound)
    monkeypatch.setattr(m.revision,'bind_completed_revision',bind)
    v=dict(process_id=123,expected_process_create_time=1.25,expected_document_path=str(source),expected_source_sha256=sha,revision_receipt_path=str(receipt),revision_receipt_sha256=m._file_hash(receipt),revision_marker_path=str(tmp_path/'marker.json'),revision_marker_sha256='a'*64,operation_native_id=358,expected_feature_native_id=70,expected_tool_native_id=252,receipt_path=str(tmp_path/'read.json'),qualification_only=True,message_policy='vendor_default')
    return v,bound,seen,source,receipt,parent


def test_loader_separates_finished_producer361_from_read_target358(loader):
    v,bound,seen,*_=loader;data=m.validate(v)
    assert data['target']['native_id']==358 and seen[0][1]['selected_operation_ids']==[361]
    assert seen[0][1]['protected_operation_ids']==[100]
    assert seen[0][1]['writer_pin']['path']==m.writer.__file__
    assert all(Path(p['path']).is_file() for p in data['pins'])


@pytest.mark.parametrize('defect',['bool_pid','source','target_type','tool','feature','suppression','unfinished_parent','receipt_exists','bad_marker_sha'])
def test_loader_rejects_stale_or_wrong_finish_authority(loader,defect):
    v,bound,seen,source,receipt,parent=loader
    if defect=='bool_pid':v['process_id']=True
    elif defect=='source':source.write_bytes(b'changed')
    elif defect=='target_type':bound['snapshot']['operations'][0]['mill_operation_type']=0
    elif defect=='tool':v['expected_tool_native_id']=249
    elif defect=='feature':v['expected_feature_native_id']=71
    elif defect=='suppression':bound['snapshot']['operations'][0]['suppressed']=True
    elif defect=='unfinished_parent':parent['status']='running';receipt.write_text(json.dumps(parent),encoding='utf-8');v['revision_receipt_sha256']=m._file_hash(receipt)
    elif defect=='receipt_exists':Path(v['receipt_path']).write_text('{}',encoding='utf-8')
    else:v['revision_marker_sha256']='not-a-hash'
    with pytest.raises(ValueError):m.validate(v)
    if defect in ('bool_pid','source','unfinished_parent','bad_marker_sha'):assert not seen


def test_modes_nc_scope_never_requests_lead_objects_and_keeps_pairs():
    g=graph();g[2]['read_scope']='modes_nc_only'
    def fail(*args):raise AssertionError('Lead getter must not be called')
    g[9]['IGetLeadin']=g[9]['IGetLeadout']=fail
    observations=[];a=m.capture(*g[:7],progress=observations.append);b=m.capture(*g[:7])
    assert a==b and a['capture_complete'] and a['leads']['status']=='not_observed'
    assert a['observation_groups']==['inventory','depth_and_side_pairs','finish_scope','nc']
    assert a['depth_and_side_pairs']['GetFirstDepthCut']==[1.,False]
    assert a['nc']['LinkToTool'] is True
    assert not {'IGetLeadin','IGetLeadout','GetCWObjectFromID'} & set(g[-1])
    assert len(observations)==4 and all(not x['capture_complete'] for x in observations)


def test_full_scope_failure_retains_complete_prior_groups():
    g=graph();observations=[]
    def fail(*args):raise RuntimeError('observed lead-object failure')
    g[9]['IGetLeadin']=fail
    with pytest.raises(RuntimeError,match='lead-object'):m.capture(*g[:7],progress=observations.append)
    assert observations[-1]['observation_groups']==['inventory','depth_and_side_pairs','finish_scope','nc']
    assert observations[-1]['depth_and_side_pairs']['GetSideCutAmt']==[10.,True]
    assert observations[-1]['nc']['XYFeed']==500.
    assert not observations[-1]['capture_complete'] and observations[-1]['leads']['status']=='not_observed'


def test_dispatch_failure_durably_retains_partial_group(lifecycle,monkeypatch):
    v,state=lifecycle
    def capture(app,loaded,v,read,typed,pointer,boundary,progress=None):
        boundary();progress(dict(capture_complete=False,depth_and_side_pairs={'GetFirstDepthCut':[1.,False]},observation_groups=['depth_and_side_pairs']))
        read(object(),'IGetLeadin')
    monkeypatch.setattr(m,'capture',capture)
    result=m.dispatch(object(),'cls','tlb',runtime_check=lambda:None,**v)
    assert result['status']=='error' and not result['readback_verified'] and not result['mutation_attempted']
    assert result['before']['depth_and_side_pairs']=={'GetFirstDepthCut':[1.,False]}
    assert result['failed_phase']==result['failed_read']=='IGetLeadin'
    assert json.loads(Path(v['receipt_path']).read_text(encoding='utf-8'))==result


def prior_failure(v):
    return dict(scope=m.SCOPE,status='error',phase='finished',read_only=True,request=deepcopy(v),mutation_attempted=False,save_attempted=False,GTP_attempted=False,GOP_attempted=False,parameter_setter_attempted=False,issue=dict(hresult=-2147220990,locations=[dict(file='sw_cam_finish_lead_observation.py',function='read_lead_details',line=111)]),messages=dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]))


def test_modes_loader_binds_actual_failure_separately_without_rewriting(loader):
    v,*_=loader;prior=prior_failure(v);path=Path(v['receipt_path']).with_name('failed.json');path.write_text(json.dumps(prior),encoding='utf-8');before=path.read_bytes()
    v.update(read_scope='modes_nc_only',prior_read_receipt_path=str(path),prior_read_receipt_sha256=m._file_hash(path))
    loaded=m.validate(v)
    assert loaded['prior_limitation']==prior and path.read_bytes()==before
    assert any(x['path']==str(path) for x in loaded['pins'])


@pytest.mark.parametrize('defect',['missing','wrong_source','wrong_pid','mutation','event','other_hresult','other_failure','not_finished','pair','full'])
def test_modes_loader_rejects_unrelated_or_unsafe_prior(loader,defect):
    v,*_=loader;prior=prior_failure(v);path=Path(v['receipt_path']).with_name('failed.json')
    if defect=='wrong_source':prior['request']['expected_source_sha256']='f'*64
    elif defect=='wrong_pid':prior['request']['process_id']=456
    elif defect=='mutation':prior['save_attempted']=True
    elif defect=='event':prior['messages']['event_count']=1
    elif defect=='other_hresult':prior['issue']['hresult']=-1
    elif defect=='other_failure':prior['issue']['locations'][0]['function']='other'
    elif defect=='not_finished':prior['phase']='running'
    path.write_text(json.dumps(prior),encoding='utf-8');v.update(read_scope='modes_nc_only',prior_read_receipt_path=str(path),prior_read_receipt_sha256=m._file_hash(path))
    if defect=='missing':v.pop('prior_read_receipt_path');v.pop('prior_read_receipt_sha256')
    elif defect=='pair':v.pop('prior_read_receipt_sha256')
    elif defect=='full':v['read_scope']='full'
    with pytest.raises(ValueError):m.validate(v)
