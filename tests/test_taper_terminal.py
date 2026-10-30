"""Independent terminal tests over the real tool-only state machine.

Native tool/holder observations use the existing synthetic writer fixture.
Historical lineage is a separate tested loader; these tests isolate the new
terminal's binding to that loader and hash actual old/new source file bytes.
"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import MethodType
import pytest

STAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('terminal_writer_fixture',STAGE/'tests/test_taper_tool_writer.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
m=w.m
case=w.case

@pytest.fixture
def terminal(case, monkeypatch):
    c=case; root=c.j.receipt.parent
    source=Path(c.r['source_path']);source.write_bytes(b'accepted historical source fixture')
    oldsha=m._file_hash(source)
    archive=root/'historical.SLDPRT';archive.write_bytes(source.read_bytes())
    c.source,c.archive,c.oldsha=source,archive,oldsha
    monkeypatch.setattr(m.exports,'local_evidence_root',lambda:root)
    c.j.marker=m.marker_path(source,oldsha)
    state=c.loaded['state'];state.update(document=dict(path=str(source),title=source.name,type=1,needs_save=False),saved_file_sha256=oldsha)
    state['operations']=[dict(native_id=i,assigned_tool={'native_id':249},toolpath_record_counts=[n]) for i,n in ((267,760),(247,191),(248,74))]
    state['operation_counts']=[3]
    before={key:deepcopy(c.loaded.get(key,{})) for key in m.group.CURRENT_KEYS}
    before.update(state=deepcopy(state),source_sha256=oldsha)
    c.loaded.update(before,toolpath_record_counts=[760])
    c.b.current_state=deepcopy(state)
    def saved_hash(self,stage):
        self.call('saved_hash');source.write_bytes(b'newly saved tool-only source fixture')
        digest=m._file_hash(source)
        self.current_state['saved_file_sha256']=digest
        self.current_state['document']['needs_save']=False
        self.report['source_transition']=dict(source_before_sha256=oldsha,source_after_sha256=digest,
            strict_save_return=0,document=deepcopy(self.current_state['document']))
        return digest
    c.b.saved_hash=MethodType(saved_hash,c.b)
    def pin(path):return dict(path=str(path),sha256=m._file_hash(path))
    parentfile=root/'historical_parent.json';parentfile.write_text('{}')
    recipefile=root/'recipe.json';recipefile.write_text(json.dumps(c.recipe))
    cataloguefile=root/'catalogue.json';cataloguefile.write_text('{}')
    dummycode=root/'phase_code.py';dummycode.write_text('# immutable fixture')
    parentpin=pin(parentfile); live=[parentpin,pin(dummycode)]; offline=[pin(archive),pin(recipefile),pin(cataloguefile)]
    c.parent=dict(c.loaded,pins=live,offline_export_proof_pins=offline,tool_phase_retired=[],
        parent_pin=parentpin,historical_source_pin=pin(archive),recipe=deepcopy(c.recipe),
        group_marker_pin=pin(cataloguefile),generated_pin=pin(dummycode),bootstrap_export_pins=[])
    c.r.update(scope=m.SCOPE,module_pin=m.exports._pin(m.__file__),process_id=123,
        receipt_path=str(c.j.receipt),initial_source_sha256=oldsha,
        current_before=deepcopy(before),current_before_sha256=m._digest(before),settings_before=deepcopy(c.loaded['settings']),
        generated_face_operation_id=267,toolpath_record_counts=[760],recipe=deepcopy(c.recipe),
        recipe_pin=pin(recipefile),catalogue_pin=pin(cataloguefile),parent_pin=parentpin,historical_source_pin=pin(archive),
        live_pins=deepcopy(live),offline_proof_pins=deepcopy(offline),phase_retired_pins=[],
        automatic_retry=False,automatic_replay=False,phase_proofs_verified_after_native=False)
    result=w.run(c);assert result['readback_verified'],result
    result['phase_proofs_verified_after_native']=True
    result['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
    result['checkpoint']=m.make_checkpoint(result);result['checkpoint_sha256']=m._digest(result['checkpoint'])
    m.validate_terminal(result)
    c.j.persist();result['marker_pin']=pin(c.j.marker);c.j.persist()
    c.newsha=m._file_hash(source);assert c.newsha!=oldsha
    def historical(params,*,check_current=True):
        assert check_current is False
        assert params['expected_source_sha256']==oldsha
        assert m._file_hash(archive)==oldsha and m._file_hash(source)==c.newsha
        return deepcopy(c.parent)
    monkeypatch.setattr(m,'load_inputs',historical)
    monkeypatch.setattr(m.exports,'operation_contract',lambda value: None)
    return c

def load(c,**kwargs):
    args=dict(process_id=123,expected_document_path=str(c.source),expected_source_sha256=c.newsha)
    args.update(kwargs)
    return m.load_completed(str(c.j.receipt),m._file_hash(c.j.receipt),**args)

def rewrite(c,modify,*,rebuild=False):
    data=json.loads(c.j.receipt.read_text());modify(data)
    if rebuild:
        data['checkpoint']=m.make_checkpoint(data);data['checkpoint_sha256']=m._digest(data['checkpoint'])
    c.j.receipt.write_text(json.dumps(data))

def test_completed_tool_checkpoint_uses_new_source_and_keeps_old_parent(terminal):
    c=terminal;value=load(c)
    assert value['source_sha256']==c.newsha!=c.oldsha
    assert value['local_tool_candidate']['native_id']==900
    assert value['generated_face_operation_id']==267 and value['toolpath_record_counts']==[760]
    assert value['authority_kind']=='saved_local_taper_candidate'
    assert value['historical_parent_pin']==c.parent['parent_pin']
    assert len(value['pins'])==2
    assert c.b.calls.count('create')==1 and c.b.calls.count('save')==1

@pytest.mark.parametrize('field,value',[('generated_face_operation_id',248),('toolpath_record_counts',[74])])
def test_parent_operation_identity_and_counts_cannot_be_rewritten(terminal,field,value):
    c=terminal;rewrite(c,lambda data:data.update({field:value}),rebuild=True)
    with pytest.raises(ValueError,match='historical parent'):load(c)

def test_recipe_payload_must_equal_loaded_pin_payload(terminal):
    c=terminal;c.parent['recipe']['proposed_fields']['ToolDescription']='different valid pinned description'
    with pytest.raises(ValueError,match='historical parent'):load(c)

def test_historical_archive_pin_payload_cannot_be_changed(terminal):
    c=terminal;rewrite(c,lambda data:data['historical_source_pin'].update(sha256='f'*64))
    with pytest.raises(ValueError,match='historical parent'):load(c)

@pytest.mark.parametrize('field',['live_pins','offline_proof_pins','phase_retired_pins'])
def test_derived_closure_must_match_loaded_parent(terminal,field):
    c=terminal;rewrite(c,lambda data:data[field].append(dict(path=str(c.archive),sha256=c.oldsha)))
    with pytest.raises(ValueError,match='historical parent'):load(c)

def test_actual_current_file_hash_must_match_terminal(terminal):
    c=terminal;c.source.write_bytes(b'changed after verified save')
    with pytest.raises(ValueError,match='Current source'):load(c)

@pytest.mark.parametrize('field,value',[('readback_verified',False),('model_saved',False),('phase_proofs_verified_after_native',False),('production_qualified',True)])
def test_terminal_flags_are_strict(terminal,field,value):
    c=terminal;rewrite(c,lambda data:data.update({field:value}))
    with pytest.raises(ValueError):load(c)

def test_marker_bytes_must_stay_exact(terminal):
    c=terminal;c.j.marker.write_bytes(b'changed marker')
    with pytest.raises(ValueError):load(c)

def test_source_transition_requires_int_zero(terminal):
    c=terminal;rewrite(c,lambda data:data['source_transition'].update(strict_save_return=False))
    with pytest.raises(ValueError,match='Save transition'):load(c)

def test_checkpoint_candidate_tamper_is_rejected(terminal):
    c=terminal;rewrite(c,lambda data:data['checkpoint']['local_tool_candidate'].update(native_id=901))
    with pytest.raises(ValueError,match='checkpoint'):load(c)