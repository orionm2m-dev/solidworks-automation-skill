from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,sys
import pytest
import scripts
from optimization_fixture import fixture
from scripts import sw_cam_local_serial_optimization as m

def fixture_prepare(tmp_path,monkeypatch):
    base,snap,targets,plan=fixture()
    def file(name,text):p=tmp_path/name;p.write_text(text);return p
    doc=file('part.sldprt','part');qp=file('qualified.json','{}');rp=file('rebind.json','{}');recipe=file('recipe.json',json.dumps(plan));producer=file('rebind.py','# synthetic provider');tlb=file('camworks.tlb','metadata')
    sha=m.prior._file_hash(doc);q=dict(source_sha256=sha,prior_cl={})
    registration=dict(clsid='synthetic',addin_path=str(tmp_path/'addin.dll'))
    l=dict(source_sha256=sha,ownership=dict(process_id=77),guide_parameters=dict(document=dict(path=str(doc),type=1,needs_save=True),configuration=dict(sw_configuration_name='Default'),expected_parameters=base),current_snapshot=snap,deep_targets=targets,qualified_authority_pin=m.common._pin(qp),pins=[m.common._pin(tlb)],registration=registration,generated_pin=m.common._pin(producer))
    fake=SimpleNamespace(__file__=str(producer),load_completed_rebind=lambda *a,**k:(deepcopy(l),deepcopy(q),{},[]))
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_saved18_serial_completed',fake);monkeypatch.setattr(scripts,'sw_cam_saved18_serial_completed',fake,raising=False)
    def partition(loaded,extra):loaded['phase_proof_pins']=extra;loaded['pin_partition']=dict(maximum_with_source=2)
    monkeypatch.setattr(m,'partition_pins',partition)
    monkeypatch.setattr(m.common,'discover_export_registration',lambda *a:registration)
    monkeypatch.setattr(m.prior.guard_reuse,'guard_constructor_preflight',lambda *a:dict(status='synthetic'))
    monkeypatch.setattr(m.native,'audit_final_depth',lambda *a:dict(native_called=False))
    monkeypatch.setattr(m.common,'_local_receipt',lambda p:Path(p))
    # Local-drive export rules are reused unchanged; this unit tests sealed authority on any host filesystem.
    monkeypatch.setattr(m.cl,'_fresh_path',lambda p:Path(p))
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p=dict(process_id=77,expected_document_path=str(doc),expected_source_sha256=sha,qualified_receipt_path=str(qp),qualified_receipt_sha256=m.prior._file_hash(qp),rebind_receipt_path=str(rp),rebind_receipt_sha256=m.prior._file_hash(rp),recipe_path=str(recipe),recipe_sha256=m.prior._file_hash(recipe),module_sha256=m.prior._file_hash(m.__file__),receipt_path=str(tmp_path/'new.json'),progress_path=str(tmp_path/'progress.json'),saved_cl_path=str(tmp_path/'cl-new'/'route.cl'),acknowledgement=m.ACK)
    return dict(action=m.ACTION,params=p),l,q

def test_rebind_source_selected_plan_prepared(tmp_path,monkeypatch):
    req,_,_=fixture_prepare(tmp_path,monkeypatch);original=deepcopy(req)
    p,l,reg,tlb,out,mark=m.prepare_request(req)
    assert req==original and l['optimization']['snapshot']['binding']['operations'][-1]['toolpath_generated']is True
    assert len(l['optimization_plan']['rows'])==4 and p['expected_configuration']=='Default'

@pytest.mark.parametrize('damage',['pid','source','qualifiedpin','module','ack','extra','alias','marker'])
def test_prepare_fail_closed(tmp_path,monkeypatch,damage):
    req,l,q=fixture_prepare(tmp_path,monkeypatch);p=req['params']
    if damage=='pid':p['process_id']=78
    elif damage=='source':p['expected_source_sha256']='f'*64
    elif damage=='qualifiedpin':p['qualified_receipt_sha256']='d'*64
    elif damage=='module':p['module_sha256']='e'*64
    elif damage=='ack':p['acknowledgement']='yes'
    elif damage=='extra':p['accept_feed_drift']=True
    elif damage=='alias':p['receipt_path']=p['recipe_path']
    else:m.marker_path(p).write_text('pending')
    with pytest.raises(ValueError):m.prepare_request(req)
