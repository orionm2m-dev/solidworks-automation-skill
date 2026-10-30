"""Resume terminal binding over the shared real flow and actual saved file hashes.

The separately tested historical/evidence loader is mocked at its boundary.
No synthetic result in these tests is claimed as a native CAM qualification.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import MethodType
import pytest

STAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('resume_terminal_flow_fixture',STAGE/'tests/test_taper_tool_resume_flow.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
m=w.m
case=w.case


@pytest.fixture
def terminal(case,monkeypatch):
    c=case;root=c.j.receipt.parent
    source=Path(c.r['source_path']);source.write_bytes(b'accepted historical source fixture')
    oldsha=m._file_hash(source)
    archive=root/'historical.SLDPRT';archive.write_bytes(source.read_bytes())
    c.source,c.archive,c.oldsha=source,archive,oldsha
    monkeypatch.setattr(m.exports,'local_evidence_root',lambda:root)
    state=c.loaded['state'];state.update(document=dict(path=str(source),title=source.name,type=1,needs_save=False),saved_file_sha256=oldsha)
    state['operations']=[dict(native_id=i,assigned_tool={'native_id':249},toolpath_record_counts=[n]) for i,n in ((267,760),(247,191),(248,74))]
    state['operation_counts']=[3]
    before={key:deepcopy(c.loaded.get(key,{})) for key in m.group.CURRENT_KEYS}
    before.update(state=deepcopy(state),source_sha256=oldsha)
    c.loaded.update(before,toolpath_record_counts=[760])
    c.b.current_state=deepcopy(state)
    initial=dict(route=m.base.expected_route(c.loaded),units=deepcopy(c.loaded['finish_payload']['unit_record']),
        protected_tools={'249':deepcopy(c.loaded['finish_payload']['full_tool'])},tools=deepcopy(c.b.old))
    creator=dict(attempted=True,returned=True,pending=False,native_return_type='pointer',returned_interface_pointer=True)
    c.failed=dict(initial_observation=deepcopy(initial),scalar_catalogue_reads=[dict(rows=deepcopy(c.b.tools()))],
        actions={'AddNewTool3':creator},new_tool_native_id=900)
    def saved_hash(self,stage):
        self.call('saved_hash');source.write_bytes(b'newly saved resumed tool-only source fixture')
        digest=m._file_hash(source);self.current_state['saved_file_sha256']=digest
        self.current_state['document']['needs_save']=False
        self.report['source_transition']=dict(source_before_sha256=oldsha,source_after_sha256=digest,
            strict_save_return=0,document=deepcopy(self.current_state['document']))
        return digest
    c.b.saved_hash=MethodType(saved_hash,c.b)
    def pin(path):return dict(path=str(path),sha256=m._file_hash(path))
    def jsonfile(name,value):
        path=root/name;path.write_text(json.dumps(value));return pin(path)
    parentpin=jsonfile('historical_parent.json',{})
    recipepin=jsonfile('recipe.json',c.recipe);cataloguepin=jsonfile('catalogue.json',{})
    failurepin=jsonfile('failed_creation.json',c.failed);creationpin=jsonfile('original_creation_marker.json',{'created_id':900})
    live=[failurepin,creationpin]
    for i in range(62):live.append(jsonfile('live_%02d.json'%i,{'fixture':i}))
    offline=[pin(archive),parentpin,recipepin,cataloguepin]
    for i in range(10):offline.append(jsonfile('offline_%02d.json'%i,{'historical':i}))
    retired=offline[4:8]
    c.parent=dict(c.loaded,pins=live,offline_export_proof_pins=offline,resume_retired_pins=retired,
        parent_pin=parentpin,historical_source_pin=pin(archive),recipe=deepcopy(c.recipe),
        group_marker_pin=cataloguepin,generated_pin=live[-1],bootstrap_export_pins=[],
        failed_attempt=deepcopy(c.failed),failure_pin=failurepin,creation_marker_pin=creationpin)
    c.r.update(scope=m.SCOPE,module_pin=m.exports._pin(m.__file__),process_id=123,
        receipt_path=str(c.j.receipt),initial_source_sha256=oldsha,initial_observation=deepcopy(initial),
        current_before=deepcopy(before),current_before_sha256=m._digest(before),settings_before=deepcopy(c.loaded['settings']),
        generated_face_operation_id=267,toolpath_record_counts=[760],recipe=deepcopy(c.recipe),
        recipe_pin=recipepin,catalogue_pin=cataloguepin,parent_pin=parentpin,historical_source_pin=pin(archive),
        failure_pin=failurepin,creation_marker_pin=creationpin,inherited_creation_action=deepcopy(creator),
        inherited_created_catalogue=deepcopy(c.b.tools()),baseline_origin='inherited_failed_attempt_before_creation',
        creation_attempted=False,live_pins=deepcopy(live),offline_proof_pins=deepcopy(offline),phase_retired_pins=deepcopy(retired),
        interface_audit=dict(all_resolved=True,property_signatures_verified=True,native_query_interface_calls=0),
        automatic_retry=False,automatic_replay=False,phase_proofs_verified_after_native=False)
    c.j.marker=m.marker_path(source,oldsha,900,creationpin['sha256'])
    result=w.run(c);assert result['readback_verified'],result
    result['phase_proofs_verified_after_native']=True
    result['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
    result['checkpoint']=m.base.make_checkpoint(result);result['checkpoint_sha256']=m._digest(result['checkpoint'])
    m.validate_terminal(result,c.failed)
    c.j.persist();result['marker_pin']=pin(c.j.marker);c.j.persist()
    c.newsha=m._file_hash(source);assert c.newsha!=oldsha
    def historical(params,*,check_current=True):
        assert check_current is False and params['expected_source_sha256']==oldsha
        assert m._file_hash(archive)==oldsha and m._file_hash(source)==c.newsha
        assert params['failed_receipt_path']==failurepin['path'] and params['failed_receipt_sha256']==failurepin['sha256']
        assert params['creation_marker_path']==creationpin['path'] and params['creation_marker_sha256']==creationpin['sha256']
        m.exports._check([failurepin,creationpin])
        return deepcopy(c.parent)
    monkeypatch.setattr(m,'load_inputs',historical)
    monkeypatch.setattr(m.exports,'operation_contract',lambda value:None)
    return c


def load(c):
    return m.load_completed(str(c.j.receipt),m._file_hash(c.j.receipt),process_id=123,
        expected_document_path=str(c.source),expected_source_sha256=c.newsha)


def rewrite(c,modify,*,rebuild=False):
    data=json.loads(c.j.receipt.read_text());modify(data)
    if rebuild:
        data['checkpoint']=m.base.make_checkpoint(data);data['checkpoint_sha256']=m._digest(data['checkpoint'])
    c.j.receipt.write_text(json.dumps(data))


def test_completed_resume_loads_new_source_and_retires_only_reconciled_creation(terminal):
    c=terminal;value=load(c)
    assert value['source_sha256']==c.newsha!=c.oldsha
    assert value['local_tool_candidate']['native_id']==900
    assert value['authority_kind']=='resumed_saved_taper_candidate'
    assert len(c.parent['pins'])==64 and len(c.parent['offline_export_proof_pins'])==14
    assert len(value['pins'])==63 and len(value['offline_export_proof_pins'])==17
    for oldpin in (c.r['failure_pin'],c.r['creation_marker_pin']):
        assert oldpin not in value['pins'] and oldpin in value['offline_export_proof_pins']
    assert value['parent_pin'] in value['pins']
    assert c.r['full_tool_snapshot_count']==2 and c.r['inherited_full_tool_snapshot_count']==1
    assert 'AddNewTool3' not in c.r['actions'] and 'create' not in c.b.calls
    assert c.b.calls.count('save')==1


@pytest.mark.parametrize('field,value', [('full_tool_snapshot_count',3),('inherited_full_tool_snapshot_count',True),
    ('creation_attempted',True),('baseline_origin','fresh_native_capture')])
def test_composite_split_cannot_invent_work(terminal,field,value):
    c=terminal;rewrite(c,lambda d:d.update({field:value}))
    with pytest.raises(ValueError):load(c)


def test_historical_creator_cannot_be_claimed_as_current_action(terminal):
    c=terminal;rewrite(c,lambda d:d['actions'].update(AddNewTool3=deepcopy(d['inherited_creation_action'])))
    with pytest.raises(ValueError,match='historical'):load(c)


def test_inherited_baseline_is_exact(terminal):
    c=terminal;rewrite(c,lambda d:d['initial_observation']['tools'][0].update(Protrusion=999.))
    with pytest.raises(ValueError,match='historical'):load(c)


def test_metadata_native_qi_count_rejects_bool(terminal):
    c=terminal;rewrite(c,lambda d:d['interface_audit'].update(native_query_interface_calls=False))
    with pytest.raises(ValueError):load(c)


@pytest.mark.parametrize('field',['live_pins','offline_proof_pins','phase_retired_pins'])
def test_derived_closure_must_equal_loaded_parent(terminal,field):
    c=terminal;rewrite(c,lambda d:d[field].pop())
    with pytest.raises(ValueError,match='inherited authority'):load(c)


@pytest.mark.parametrize('pin_name',['failure_pin','creation_marker_pin'])
def test_original_failed_creator_bytes_stay_pinned(terminal,pin_name):
    c=terminal;Path(c.r[pin_name]['path']).write_bytes(b'changed previous attempt')
    with pytest.raises(ValueError):load(c)


def test_actual_new_source_bytes_are_required(terminal):
    c=terminal;c.source.write_bytes(b'changed after Save')
    with pytest.raises(ValueError,match='Current resumed source'):load(c)


def test_new_source_cannot_be_replaced_by_historical_hash(terminal):
    c=terminal;rewrite(c,lambda d:d.update(saved_source_sha256=c.oldsha))
    with pytest.raises(ValueError,match='Current resumed source'):load(c)


def test_completed_resume_marker_bytes_stay_pinned(terminal):
    c=terminal;c.j.marker.write_bytes(b'changed completed marker')
    with pytest.raises(ValueError):load(c)


def test_candidate_checkpoint_must_match_saved_tool(terminal):
    c=terminal;rewrite(c,lambda d:d['checkpoint']['local_tool_candidate'].update(native_id=901))
    with pytest.raises(ValueError,match='checkpoint'):load(c)


def test_exact_parent_counts_and_identity_are_bound(terminal):
    c=terminal;rewrite(c,lambda d:d.update(toolpath_record_counts=[74]),rebuild=True)
    with pytest.raises(ValueError,match='inherited authority'):load(c)


def test_noninteger_save_success_cannot_be_reused(terminal):
    c=terminal;rewrite(c,lambda d:d['source_transition'].update(strict_save_return=False))
    with pytest.raises(ValueError,match='Save transition'):load(c)
