from copy import deepcopy
from types import SimpleNamespace
import pytest
from optimization_fixture import fixture
from scripts import sw_cam_local_serial_optimization as m
from scripts import sw_cam_local_optimization_fields as f

def workflow(tmp_path,monkeypatch,fail=None,drift=None,bad_before=False,skip=False):
    baseline,snapshot,targets,plan=fixture()
    if skip:snapshot['parameters'][8]['rough']['depth']['FinCutAmt']['raw']=0.
    pins={k:dict(path=k,sha256='c'*64)for k in ['qualified_receipt_pin','rebind_receipt_pin','recipe_pin']}
    r=dict(scope=m.SCOPE,source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64,phase_proof_checks=[dict(phase=k,verified=True)for k in ['before_native_start','before_save','after_export_and_cleanup']],ownership=dict(process_id=77),request=dict(process_id=77),**pins)
    j=m.Journal(r,tmp_path/'receipt.json',tmp_path/'marker.json')
    l=dict(source_sha256='a'*64,ownership=dict(process_id=77),guide_parameters=dict(expected_parameters=baseline,document=dict(path=r['source_path'],needs_save=True)),optimization=dict(snapshot=deepcopy(snapshot),targets=targets,prior_cl={}),optimization_plan=plan,**pins)
    class Backend:
        def __init__(self):self.value=deepcopy(snapshot);self.calls=[];self.learned=[];self.n=0
        def start(self):self.calls.append('start')
        def boundary(self):pass
        def refresh_dirty(self):pass
        def capture_snapshot(self,label,**kw):return deepcopy(self.value)
        def field(self,t,spec):return deepcopy(f.field_value(next(p for p in self.value['parameters']if p['operation_native_id']==t['operation_native_id']),spec))
        def set_field(self,t,spec,value,pending):
            self.calls.append('set:'+spec[0]);pending()
            if fail==spec[0]:raise RuntimeError('unknown setter outcome')
            p=next(p for p in self.value['parameters']if p['operation_native_id']==t['operation_native_id']);key=spec[0]
            if t['operation_type']==0:
                if key=='spiral_pitch':p['rough']['entry'][spec[2]]['raw']=value
                elif key=='rough_final_depth':p['rough']['depth']['FinCutAmt']['raw']=value
                else:
                    d=p['rough']['depth'];d[spec[2]].update(raw=deepcopy(value),is_percent=value[0],value_native=value[1]);d['FirstDepthAmt'if key=='first_depth'else'SbsqDepthAmt']['raw']=value[1]
            else:p['finish_fields'][key]=deepcopy(value);p['finish']['FirstDepthCut'if key=='first_depth'else'MaxDepthCut']['raw']=value[0]
            return 0
        def generate(self,t,pending):
            self.calls.append('generate');pending();self.n+=1
            if fail==self.n:raise RuntimeError('unknown GTP outcome')
            op=next(o for o in self.value['binding']['operations']if o['native_id']==t['operation_native_id']);op.update(toolpath_generated=True,toolpath_record_counts=[100])
            if drift:
                p=next(p for p in self.value['parameters']if p['operation_native_id']==t['operation_native_id'])
                if drift=='feed':p['nc']['feeds_compensation']['XYFeed']=70.
                elif drift=='spindle':p['nc']['feeds_compensation']['GetSpndlSpeed']=8000.
                else:p['levels']['levels']['axis']=1
            return 0
        def outcome(self,t):return dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=False,background_over_after=False,generated=True,generated_for_feature=True,record_counts=[100])
        def save(self):self.calls.append('save');return 0
        def saved_hash(self,stage):r['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0,document=dict(path=r['source_path'],needs_save=False));return 'b'*64
        def export(self,*a):self.calls.append('export');return dict(source_sha256='b'*64)
        def finish(self):self.calls.append('finish');r['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
        def close(self):self.calls.append('close')
    b=Backend()
    if bad_before:b.value['parameters'][0]['sentinel']+=1
    monkeypatch.setattr(m.generation,'close_checked',lambda b,r:b.close())
    monkeypatch.setattr(m.cl,'verify_saved',lambda *a:dict(protected14=True))
    return b,j,l

def test_full_once_only_and_terminal(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l)
    assert r['readback_verified'],r.get('issue')
    assert len([x for x in b.calls if x.startswith('set:')])==12
    assert b.calls.count('generate')==4 and b.calls.count('save')==b.calls.count('export')==1
    assert m.validate_completed(r,l)['regenerated_paths']==4
    assert not any(k.startswith(('SetTool:','insert:'))for k in r['actions'])

@pytest.mark.parametrize('failure',[1,2,3,4,'rough_final_depth'])
def test_unknown_outcome_preserved_no_save_or_replay(tmp_path,monkeypatch,failure):
    b,j,l=workflow(tmp_path,monkeypatch,fail=failure);r=m.run_once(b,j,l)
    assert not r['readback_verified']and r['native_dispatch_pending']and 'save'not in b.calls
    frozen=j.receipt.read_bytes(),j.marker.read_bytes(),deepcopy(r),list(b.calls)
    with pytest.raises(ValueError):m.run_once(b,j,l)
    assert frozen==(j.receipt.read_bytes(),j.marker.read_bytes(),r,b.calls)

@pytest.mark.parametrize('drift',['feed','spindle','other'])
def test_unplanned_gtp_change_stops_after_complete4_before_save(tmp_path,monkeypatch,drift):
    b,j,l=workflow(tmp_path,monkeypatch,drift=drift);r=m.run_once(b,j,l)
    assert b.calls.count('generate')==4 and 'save'not in b.calls and len(r['completed_gtp_counts'])==4
    assert not r['readback_verified']and not r['native_dispatch_pending']
    assert r['nc_restore_candidate']['status']==('NOT_PROVEN_NC_ONLY'if drift=='other'else'EXACT_NC_ONLY_DIFFERENCES_REVIEW_REQUIRED')

def test_changed_live_baseline_never_mutates(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch,bad_before=True);r=m.run_once(b,j,l)
    assert b.calls==['start','close']and not r['mutation_attempted']

def test_already_satisfied_field_no_repeat_native_setter(tmp_path,monkeypatch):
    b,j,l=workflow(tmp_path,monkeypatch,skip=True);r=m.run_once(b,j,l)
    assert r['readback_verified']and b.calls.count('set:rough_final_depth')==1
    assert m.validate_completed(r,l)['regenerated_paths']==4

@pytest.mark.parametrize('damage',['setter','NC','target','counts','source','owner','savestage'])
def test_terminal_changed_claim_rejected(tmp_path,monkeypatch,damage):
    b,j,l=workflow(tmp_path,monkeypatch);r=m.run_once(b,j,l);assert r['readback_verified']
    if damage=='setter':r['actions']['101:rough_final_depth']['observed']=.25
    elif damage=='NC':r['generated']['parameters'][8]['nc']['feeds_compensation']['XYFeed']=70.
    elif damage=='target':r['learned_targets'][0]['feature_native_id']=999
    elif damage=='counts':r['completed_gtp_counts'][101]=[99]
    elif damage=='owner':r['ownership']['process_id']=88
    elif damage=='savestage':r['save_stage']['saved_file_sha256']='c'*64
    else:r['source_transition']['source_before_sha256']='d'*64
    with pytest.raises(ValueError):m.validate_completed(r,l)
