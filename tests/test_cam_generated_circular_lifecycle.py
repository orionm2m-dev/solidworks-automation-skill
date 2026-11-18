from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import sw_cam_circular_reconfigure as m

from test_cam_generated_circular_delta import state_recipe

@pytest.fixture(scope="module")
def evidence():
    state,recipe=state_recipe()
    v=dict(expected_source_sha256='a'*64)
    d=dict(state=state,recipe=recipe,recipe_pin={'path':'synthetic-recipe.json','sha256':'c'*64},cl_pin={'path':'synthetic-old.cl','sha256':'d'*64})
    return v,d


@pytest.fixture
def run(evidence,tmp_path,monkeypatch):
    v,d=evidence;v=deepcopy(v);d=deepcopy(d);v['receipt_path']=str(tmp_path/'receipt.json');d['receipt']=tmp_path/'receipt.json';d['marker']=tmp_path/'marker.json'
    state=d['state'];recipe=d['recipe'];oid=recipe['operation_native_id'];configured=m.expected_configuration(state,recipe);configured['document']['needs_save']=True;configured['sketch_state']['needs_save']=True
    generated=deepcopy(configured);target=m.selected(generated,oid);target['toolpath_generated']=True;target['toolpath_record_counts']=[120]
    saved=deepcopy(generated);saved['document']['needs_save']=False;saved['sketch_state']['needs_save']=False;saved['sketch_state']['saved_file_sha256']='b'*64
    class Backend:
        def __init__(self):self.calls=[];self.source=v['expected_source_sha256'];self.failure=None;self.closed=False
        def start(self):self.calls.append('start')
        def boundary(self):return None
        def capture(self,label,partial):
            self.calls.append(label)
            if self.failure==label:raise ValueError('capture failure '+label)
            value=deepcopy({'before':state,'configured':configured,'generated':generated,'saved':saved,'confirm_saved':saved}[label])
            if self.failure=='before_drift' and label=='before':value['operations'][0]['name']='unexpected'
            if self.failure=='configuration_drift' and label=='configured':value['cutting_context']['nc']['XYFeed']=777.
            if self.failure=='generation_drift' and label=='generated':value['cutting_context']['nc']['XYFeed']=1000.
            partial.update(value);return value
        def set_change(self,kind,change,*,pending,returned):
            name=kind+':'+change['field'];self.calls.append(name);pending()
            if self.failure==name:raise ValueError('unknown setter outcome')
            returned(0);return deepcopy(change['new'])
        def generate(self,oid,state,*,pending,returned):self.calls.append('GTP');pending();returned(0)
        def save(self,*,returned):self.calls.append('Save');returned(0);self.source='b'*64
        def adopt_saved_source(self,stage):return self.source
        def export_cl(self,label,state,rows,detail,*,pending,returned):
            self.calls.append('CL');pending();returned(0)
            if self.failure=='CL':raise ValueError('CL parse failed')
            return dict(output_verified=True,readback_verified=True,output={'path':'new.cl'},expected_generated_operations=rows)
        def parse_cl(self,detail):return detail
        def finish(self):self.calls.append('finish')
        def close(self):self.closed=True
    monkeypatch.setattr(m,'compare_replacement_cl',lambda *a:dict(protected_complete_streams_verified=True,protected_block_count=18))
    def invoke(failure=None):
        report=dict(scope=m.SCOPE,status='error',phase='preflight',recipe_pin=d['recipe_pin'],operation_native_id=oid,source_before_sha256=v['expected_source_sha256'],receipt_path=v['receipt_path'],dispatch_marker_path=str(d['marker']),actions={},captures=[],mutation_attempted=False,native_read_count=0,readback_verified=False,receipt_created=False,marker_created=False)
        journal=m.RevisionJournal(v['receipt_path'],d['marker'],report);backend=Backend();backend.failure=failure;result=m.run_once(backend,journal,d,v);return result,backend,journal
    return invoke


def test_exact_seven_setters_one_gtp_one_save_one_cl(run):
    r,b,j=run();assert r['status']=='review_required',r.get('reason');assert r['continuation_verified']
    assert len([c for c in b.calls if c.startswith(('nc:','rough:'))])==7
    assert b.calls.count('GTP')==b.calls.count('Save')==b.calls.count('CL')==1
    assert b.calls.count('before')==b.calls.count('configured')==b.calls.count('generated')==1
    assert b.calls.count('saved')==b.calls.count('confirm_saved')==1
    assert r['save_stage']['before_state_reused_from']=='generated'
    assert b.closed and json.loads(j.receipt.read_text(encoding='utf-8'))==r
    with pytest.raises(ValueError):j.claim()


@pytest.mark.parametrize('failure',['nc:LinkToTool','nc:GetSpndlSpeed','rough:first_depth','rough:spiral_pitch'])
def test_setter_unknown_outcome_consumes_marker_no_gtp_save(run,failure):
    r,b,j=run(failure);assert r['status']=='uncertain' and r['mutation_attempted']
    assert r['actions'][failure]['native_dispatch_pending'] and not r['actions'][failure]['returned']
    assert 'GTP' not in b.calls and 'Save' not in b.calls and j.marker.exists()


@pytest.mark.parametrize('failure',['before_drift','configuration_drift','generation_drift'])
def test_fresh_or_protected_drift_stops_before_save(run,failure):
    r,b,j=run(failure);assert r['status'] in ('error','uncertain') and 'Save' not in b.calls
    if failure=='before_drift':assert not j.marker.exists() and not any(x.startswith('nc:') for x in b.calls)


@pytest.mark.parametrize('failure',['saved','confirm_saved','CL'])
def test_returned_save_facts_survive_later_failure(run,failure):
    r,b,j=run(failure);assert r['status']=='uncertain' and b.calls.count('Save')==1
    assert r['actions']['SaveActiveDocument']['returned'] and r['actions']['SaveActiveDocument']['native_return_value']==0
    assert r['source_after_sha256']=='b'*64 and r['save_stage']['native_return_value']==0
    assert json.loads(j.receipt.read_text(encoding='utf-8'))==r


def test_runtime_revocation_is_durable_without_erasing_save(run):
    r,b,j=run();m.finalize_runtime_failure(r,ValueError('runtime drift'));disk=json.loads(j.receipt.read_text(encoding='utf-8'))
    assert disk['status']=='uncertain' and not disk['readback_verified'] and not disk['runtime_unchanged']
    assert disk['source_after_sha256']=='b'*64 and disk['actions']['SaveActiveDocument']['native_return_value']==0
    assert json.loads(j.marker.read_text(encoding='utf-8'))['receipt_sha256']==m._file_hash(j.receipt)
