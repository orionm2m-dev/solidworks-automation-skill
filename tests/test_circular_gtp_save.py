from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_circular_gtp_save as m
from scripts import sw_cam_current_saved_generation as engine
from test_current_saved_generation_delta import state


def states():
    b=state();b['sketch_state']=dict(pid=123,needs_save=False,saved_file_sha256='a'*64,solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])])
    for k in ('candidate_consumers','target_nc'):
        b['parameter_batch'][k]={'13':dict(operation_native_id=13,read_complete=True,feeds_compensation=dict(XYFeed=500.,GetSpndlSpeed=200.,GetCNCComp=0,GetTlpComp=1))}
    a=deepcopy(b);a['operations'][2].update(toolpath_generated=True,toolpath_record_counts=[31]);a['document']['needs_save']=True;a['sketch_state']['needs_save']=True
    for k in ('candidate_consumers','target_nc'):a['parameter_batch'][k]['13']['feeds_compensation']['XYFeed']=1000.
    return b,a


def history():
    b,a=states();p=dict(process_id=123,expected_process_create_time=100.25,expected_document_path=r'C:\e\part.sldprt',expected_source_sha256='a'*64,generation_mode='current_saved_circular',selected_operation_native_ids=[13])
    req=dict(action='generate_configured_local_group',params=p);pin=dict(path=r'C:\e\failed.json',sha256='d'*64);markerpin=dict(path=r'C:\e\oldmarker.json',sha256='e'*64);cp=dict(path=r'C:\e\config.json',sha256='c'*64)
    returned=dict(attempted=True,returned=True,native_dispatch_pending=False,native_return_type='int',native_return_value=0)
    d=dict(scope=engine.SCOPE,status='uncertain',phase='finished',request=req,request_sha256=m._digest(req),selected_operation_native_ids=[13],source_before_sha256='a'*64,
           reason='GTP changed protected operation, suppression, tool, parameter, feature/setup or source fields',issue=dict(type='ValueError',hresult=None,locations=[dict(function='verify_generation')]),
           receipt_path=pin['path'],dispatch_marker_path=markerpin['path'],configuration_receipt_pin=cp,actions={'preCL':deepcopy(returned),'GTP:13':deepcopy(returned)},
           messages=dict(subscribed=True,disconnected=True,active=False,event_count=0),runtime_unchanged=False)
    for k in ('save_attempted','model_saved','native_dispatch_pending','GOP_attempted','AFR_attempted','operation_creation_attempted','tool_assignment_attempted','parameter_setter_attempted','automatic_replay','automatic_rollback'):d[k]=False
    for k in ('GTP_attempted','native_call_attempted','native_call_returned','marker_created','receipt_created'):d[k]=True
    for k in ('before','confirm_before','preCL_before','preCL_after','after_preCL','before_GTP_13'):d[k]=deepcopy(b)
    d['after_GTP_13']=deepcopy(a);d['failure_actual']=deepcopy(a)
    d['preCL']=dict(output_verified=True,readback_verified=True,source_sha256='a'*64,expected_generated_operations=m.delta.inventory(b)['generated'],label='preCL')
    marker=dict(scope=engine.SCOPE,status='uncertain',phase='finished',automatic_replay=False,receipt_sha256=pin['sha256'],receipt_path=pin['path'],configuration_receipt_pin=cp,selected_operation_native_ids=[13])
    v={k:p[k] for k in ('process_id','expected_process_create_time','expected_document_path','expected_source_sha256')};v.update(operation_native_id=13,expected_xy_feed_before=500.,expected_xy_feed_after=1000.,expected_generated_record_count=31)
    loaded=dict(state=b,pin=cp)
    return d,marker,v,loaded,pin,markerpin


def test_exact_history_accepts_only_explicit_feed_refresh_without_rewriting():
    args=history();old=deepcopy(args);r=m.validate_history(*args)
    assert args==old and r['expected_state']==args[0]['after_GTP_13'] and r['proof']['complete_captured_delta_verified']


@pytest.mark.parametrize('change',[
 lambda d,marker,v,load,p,mp:d['actions']['GTP:13'].update(native_return_value=True),
 lambda d,marker,v,load,p,mp:d.update(save_attempted=True),
 lambda d,marker,v,load,p,mp:d.update(runtime_error={'issue':'drift'}),
 lambda d,marker,v,load,p,mp:d.update(cleanup_error={'issue':'event'}),
 lambda d,marker,v,load,p,mp:marker.update(receipt_sha256='0'*64),
 lambda d,marker,v,load,p,mp:v.update(process_id=124),
 lambda d,marker,v,load,p,mp:v.update(expected_process_create_time=101.),
 lambda d,marker,v,load,p,mp:d['after_GTP_13']['operations'][0].update(toolpath_record_counts=[18]),
 lambda d,marker,v,load,p,mp:d['after_GTP_13']['parameter_batch']['target_nc']['13']['feeds_compensation'].update(XYFeed=999.),
 lambda d,marker,v,load,p,mp:d['after_GTP_13']['parameter_batch']['target_nc']['13']['feeds_compensation'].update(GetSpndlSpeed=300.),
 lambda d,marker,v,load,p,mp:d['failure_actual']['operations'][0].update(suppressed=True),
 lambda d,marker,v,load,p,mp:d['actions'].update({'GTP:14':d['actions']['GTP:13']}),
 lambda d,marker,v,load,p,mp:d['before_GTP_13']['profile']['steps'].append(4),
 lambda d,marker,v,load,p,mp:v.update(expected_generated_record_count=32),
])
def test_history_rejects_other_change_or_unproven_native_outcome(change):
    args=history();change(*args)
    with pytest.raises(ValueError):m.validate_history(*args)


@pytest.mark.parametrize('old,new',[(True,1000.),(500.,float('nan')),(500.,0.),(500.,500.),(500,1000.)])
def test_feed_contract_strict_positive_double_pair(old,new):
    b,a=states()
    with pytest.raises(ValueError):m.verify_feed_delta(b,a,13,old,new,31)


def parsed(rows):
    p=dict(parse_complete=True,native_count_matches=True,declared_units=['MM'],operation_blocks=[],commands=[dict(name='BOX',raw='BOX/stock',line=1)],motions=[],circle_records=[])
    for i,row in enumerate(rows):
        line=10+i*10;p['operation_blocks'].append(dict(start_line=line,end_line=line+9));p['commands'].append(dict(name='GOTO',raw='GOTO/'+str(row['operation_native_id']),line=line+1))
    return p


class Backend:
    def __init__(self,current,mode=None):self.value=deepcopy(current);self.source='a'*64;self.calls=[];self.mode=mode;self.closed=False
    def start(self):self.calls.append('start')
    def boundary(self):
        if self.mode=='event' and 'save' in self.calls:raise ValueError('event')
    def capture(self,label,partial):
        self.calls.append(label)
        if self.mode=='before_drift' and label=='confirm_before':self.value['operations'][0]['toolpath_record_counts']=[18]
        if self.mode=='save_drift' and label=='saved':self.value['parameter_batch']['target_nc']['13']['feeds_compensation']['XYFeed']=999.
        partial.update(deepcopy(self.value));return deepcopy(self.value)
    def generate(self,*a,**kw):raise AssertionError('Never GTP')
    def save(self,*,returned):
        self.calls.append('save')
        if self.mode=='exception':raise RuntimeError('native save failed')
        value=True if self.mode=='bad_return' else 0;returned(value)
        self.value['document']['needs_save']=False;self.value['sketch_state']['needs_save']=False;return value
    def adopt_saved_source(self,report):
        assert report['native_return_type']=='int' and report['native_return_value']==0
        self.source='b'*64;self.value['sketch_state']['saved_file_sha256']=self.source;return self.source
    def export_cl(self,label,value,rows,detail,*,pending,returned):
        self.calls.append(label);pending();returned(0)
        return dict(output_verified=True,readback_verified=True,expected_generated_operations=deepcopy(rows),label=label)
    def parse_cl(self,result):
        p=parsed(result['expected_generated_operations'])
        if self.mode=='old_CL_changed' and result['label']=='postCL':p['commands'][1]['raw']='GOTO/changed'
        return p
    def finish(self):self.calls.append('finish')
    def close(self):self.closed=True


def run(tmp_path,mode=None,marker=None):
    d,old,v,loaded,pin,mp=history();h=m.validate_history(d,old,v,loaded,pin,mp);data=dict(history=h,loaded=loaded)
    backend=Backend(h['expected_state'],mode)
    report=dict(scope=m.SCOPE,status='error',phase='preflight',historical_generation_pin=pin,configuration_receipt_pin=loaded['pin'],selected_operation_native_ids=[13],actions={},captures=[],mutation_attempted=False,CL_export_attempted=False,GTP_attempted=False,GTP_replayed=False,native_dispatch_pending=False,readback_verified=False,continuation_verified=False,save_attempted=False,source_update_verified=False,model_saved=False,save_readback_verified=False,runtime_unchanged=False)
    journal=m.ContinuationJournal(tmp_path/'receipt.json',marker or tmp_path/'once.json',report)
    result=m.run_once(backend,journal,data,v)
    if journal.receipt.exists():assert json.loads(journal.receipt.read_text())==result
    return backend,journal,result


def test_save_once_export_once_protected_CL_no_generation(tmp_path):
    backend,j,r=run(tmp_path)
    assert r['status']=='review_required' and r['continuation_verified'] and r['save_readback_verified'],r
    assert backend.calls.count('save')==backend.calls.count('postCL')==1 and not r['GTP_attempted'] and not r['GTP_replayed']
    assert r['source_after_sha256']=='b'*64 and r['CL_preservation']['protected_operation_native_ids']==[11] and backend.closed
    assert r['saved']==r['confirm_saved'] and j.marker.exists()


@pytest.mark.parametrize('mode',['before_drift','exception','bad_return','event','save_drift','old_CL_changed'])
def test_failure_stops_without_GTP_or_save_replay(tmp_path,mode):
    b,j,r=run(tmp_path,mode)
    assert r['status'] in ('error','uncertain') and not r['continuation_verified'] and not r['readback_verified']
    assert b.calls.count('save')<=1 and not r['GTP_attempted'] and b.closed
    if mode=='before_drift':assert 'save' not in b.calls
    if mode in ('exception','bad_return','event','save_drift'):assert 'postCL' not in b.calls
    if mode in ('event','save_drift'):
        assert r['actions']['SaveActiveDocument']['returned'] is True
        assert r['actions']['SaveActiveDocument']['native_return_value'] == 0
    if mode=='old_CL_changed':assert r['save_stage']['save_readback_verified'] and r['postCL']['output_verified']


def test_once_marker_blocks_new_receipt_replay(tmp_path):
    b,j,r=run(tmp_path);sub=tmp_path/'second';sub.mkdir();b2,j2,r2=run(sub,marker=j.marker)
    assert r2['status']=='error' and not b2.calls and not j2.receipt.exists()


def test_journal_rejects_any_generation_action(tmp_path):
    r=dict(actions={},historical_generation_pin={},status='error',phase='test');j=m.ContinuationJournal(tmp_path/'r.json',tmp_path/'m.json',r);j.create();j.claim();j.action('GTP:13')
    with pytest.raises(ValueError,match='Only Save'):j.pending('GTP:13')
    assert r['actions']['GTP:13']['attempted'] is False


def test_context_denies_mutation_methods_without_dispatch():
    c=m.ContinuationContext.__new__(m.ContinuationContext)
    for name in ('generate','set_tool','set_field'):
        with pytest.raises(ValueError):getattr(c,name)()


def test_inherited_actual_save_callback_durable_return_before_source_read(monkeypatch):
    from scripts import sw_cam_current_saved_parameter_batch as batch
    c=m.ContinuationContext.__new__(m.ContinuationContext);calls=[];r={'actions':{'SaveActiveDocument':{'native_dispatch_pending':True}}}
    c.report=r;c.source='a'*64;c.v={'expected_document_path':'part.sldprt'};c.app={'tag':'existing'}
    c.boundary=lambda:calls.append('boundary');c.typed=lambda obj,name:(calls.append('typed:'+name) or obj)
    c.check=lambda:calls.append('events');c.runtime_check=lambda:calls.append('runtime');c.identity=lambda *a:calls.append('identity');c.persist=lambda:calls.append('persist')
    def member(obj,name,*args):assert obj is c.app and name=='SaveActiveDocument' and not args;calls.append('nativeSave');return 0
    def digest(path):assert 'returned' in calls;calls.append('hash');return 'b'*64
    monkeypatch.setattr(batch,'_member',member);monkeypatch.setattr(batch,'_file_hash',digest)
    result=c.save(returned=lambda value:(calls.append('returned'),r.update(actual_return=value)))
    assert type(result) is int and result==0 and calls.count('nativeSave')==1
    assert calls.index('typed:ICWApp')<calls.index('nativeSave')<calls.index('returned')<calls.index('hash')
    assert c.source=='b'*64 and r['actual_return']==0
