from copy import deepcopy
import json
import pytest
from scripts import sw_cam_current_saved_generation as g
from test_current_saved_generation_delta import state

class Backend:
    def __init__(self,mode=None):self.value=state();self.mode=mode;self.calls=[];self.events=False;self.source='a'*64;self.parsed={};self.closed=False
    def start(self):self.calls.append('start')
    def boundary(self):
        if self.events:raise ValueError('event stop')
    def capture(self,label,partial):
        self.boundary();self.calls.append(label);partial.update(deepcopy(self.value))
        if self.mode=='partial_capture'and label.startswith('after_GTP'):
            partial['capture_complete']=False;raise ValueError('capture incomplete')
        return deepcopy(self.value)
    def generate(self,oid,prior,*,pending,returned):
        self.calls.append('gtp');pending();row=next(r for r in self.value['operations']if r['native_id']==oid);row.update(toolpath_generated=True,toolpath_record_counts=[31]);self.value['document']['needs_save']=True
        if self.mode=='native_exception':raise RuntimeError('native failure after side effect')
        returned(None if self.mode=='unexpected_gtp_return'else 0)
        if self.mode=='event_after_return':self.events=True;self.boundary()
        if self.mode=='changed_other_nc':self.value['operation_parameters'][1]['nc']['feed']=101.0
    def save(self,*,returned):
        self.calls.append('save');self.value['document']['needs_save']=False
        if self.mode=='partial_save':self.source='b'*64;raise RuntimeError('Save failed after file change')
        value=None if self.mode=='unexpected_save_return'else 0;returned(value);return value
    def adopt_saved_source(self,report):
        assert report['native_return_type']=='int' and report['native_return_value']==0
        self.source='b'*64;return self.source
    def export_cl(self,label,value,rows,detail,*,pending,returned):
        self.calls.append(label);pending();returned(0)
        p=dict(parse_complete=True,native_count_matches=True,declared_units=['MM'],operation_blocks=[],commands=[dict(name='BOX',raw='BOX/stock',line=1)],motions=[],circle_records=[])
        for i,row in enumerate(rows):
            start=10+i*10;p['operation_blocks'].append(dict(start_line=start,end_line=start+9));p['commands'].append(dict(name='GOTO',raw='GOTO/'+str(row['operation_native_id']),line=start+1))
        if self.mode=='changed_old_CL'and label=='postCL':p['commands'][1]['raw']='GOTO/changed'
        self.parsed[label]=p
        return dict(output_verified=True,readback_verified=True,expected_generated_operations=deepcopy(rows),label=label)
    def parse_cl(self,result):return deepcopy(self.parsed[result['label']])
    def may_capture_failure(self):return not self.events and self.source=='a'*64
    def finish(self):self.boundary();self.calls.append('finish')
    def close(self):self.closed=True

def run(tmp_path,mode=None):
    b=Backend(mode);loaded=dict(state=state(),selected_ids=[13],pin=dict(path='configuration.json',sha256='c'*64),source_sha256='a'*64)
    r={};j=g.Journal(tmp_path/'receipt.json',tmp_path/'once.json',r);result=g.run_once(b,j,loaded)
    actual=json.loads((tmp_path/'receipt.json').read_text(encoding='utf-8'));assert actual==result
    return b,j,result

def test_success_single_gtp_save_two_exports(tmp_path):
    b,j,r=run(tmp_path)
    assert r['status']=='review_required'and r['readback_verified']and r['save_readback_verified']
    assert b.calls.count('gtp')==b.calls.count('save')==b.calls.count('preCL')==b.calls.count('postCL')==1
    assert r['CL_preservation']['protected_operation_native_ids']==[11]
    assert r['source_after_sha256']=='b'*64 and b.closed
    assert r['saved']==r['confirm_saved'] and r['saved']['operations'][1]['suppressed']is True
    assert j.marker.exists()

@pytest.mark.parametrize('mode',['native_exception','unexpected_gtp_return','changed_other_nc','partial_capture','event_after_return'])
def test_gtp_failures_preserve_attempt_no_save_or_replay(tmp_path,mode):
    b,j,r=run(tmp_path,mode)
    assert r['status']=='uncertain' and not r['readback_verified']
    assert b.calls.count('gtp')==1 and 'save'not in b.calls and 'postCL'not in b.calls
    assert j.marker.exists() and r['actions']['GTP:13']['attempted']
    if mode=='event_after_return':assert r['actions']['GTP:13']['returned'] and 'failure_actual'not in r
    elif mode=='partial_capture':assert any(x['label'].startswith('after_GTP')and x['capture_complete']is False and x['state']['operations'][2]['toolpath_generated']for x in r['captures'])
    else:assert r['failure_actual']['operations'][2]['toolpath_generated']is True

@pytest.mark.parametrize('mode',['unexpected_save_return','partial_save'])
def test_save_failures_no_postexport_no_source_success(tmp_path,mode):
    b,j,r=run(tmp_path,mode)
    assert r['status']=='uncertain'and not r['save_readback_verified']and not r['source_update_verified']
    assert b.calls.count('save')==1 and b.calls.count('gtp')==1 and 'postCL'not in b.calls
    assert 'source_after_sha256'not in r
    if mode=='unexpected_save_return':assert r['save_stage']['native_return_type']=='NoneType'
    else:assert r['actions']['SaveActiveDocument']['native_dispatch_pending']is True

def test_cl_failure_retains_successful_save_evidence(tmp_path):
    b,j,r=run(tmp_path,'changed_old_CL')
    assert r['status']=='uncertain'and not r['readback_verified']
    assert r['save_stage']['save_readback_verified']is True and r['saved']==r['confirm_saved']
    assert r['source_after_sha256']=='b'*64 and r['postCL']['output_verified']
    assert b.calls.count('gtp')==b.calls.count('save')==1

def test_consumed_once_marker_blocks_replay(tmp_path):
    b,j,r=run(tmp_path);b2=Backend();loaded=dict(state=state(),selected_ids=[13],pin=dict(path='configuration.json',sha256='c'*64),source_sha256='a'*64)
    r2={};j2=g.Journal(tmp_path/'second.json',tmp_path/'once.json',r2);g.run_once(b2,j2,loaded)
    assert not b2.calls and r2['status']=='error'and not(tmp_path/'second.json').exists()
