"""Synthetic grouped terminal lifecycle, using real journals and flat loader."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from test_grouped_face_core import Backend
from test_grouped_face_native_boundaries import route, configured
import test_grouped_face_core as core
m=core.m

class FinalBackend(Backend):
    def __init__(self,journal,current,source):
        super().__init__(journal);self.current=current;self.source_path=source
        self.source=current['source_sha256'];self.current['state']['saved_file_sha256']=self.source
    def state(self):
        base=deepcopy(self.current['state'])
        row=base['operations'][4]
        if self.tool==249:row['assigned_tool']=deepcopy(base['operations'][-1]['assigned_tool'])
        row['toolpath_generated']=self.generated;row['toolpath_record_counts']=[83] if self.generated else []
        base['saved_file_sha256']=self.source;base['document']['needs_save']=self.dirty
        return dict(state=base,settings=deepcopy(self.settings),binding=deepcopy(row['assigned_tool']),
            units={'metric':True},payload={'rough':self.current['payload'],'finish':self.current['finish_payload']},
            cone_observation=self.current['cone_observation'],face_observation=self.current['face_observation'])
    def verify_baseline(self,value):pass
    def verify_assignment(self,value):assert value['binding']['native_id']==249
    def verify_configured(self,value):m.verify_route_delta(self.current['state'],value['state'],self.current['state']['operations'][-1]['assigned_tool'])
    def verify_generated(self,value):m.verify_route_delta(self.current['state'],value['state'],self.current['state']['operations'][-1]['assigned_tool'],generated=True)
    def verify_final(self,value):m.verify_route_delta(self.current['state'],value['state'],self.current['state']['operations'][-1]['assigned_tool'],generated=True,saved_sha=self.source)
    def saved_hash(self,report):
        self.source_path.write_bytes(b'synthetic saved generated route')
        self.source=m._file_hash(self.source_path)
        self.journal.report['source_transition']=dict(source_before_sha256=self.current['source_sha256'],source_after_sha256=self.source)
        return self.source
    def save_projection(self,state):return m.NativeBackend.save_projection(self,state)
    def checkpoint(self,final):
        current=deepcopy(self.current);current.update(state=deepcopy(final['state']),source_sha256=self.source)
        return dict(current=current,settings=final['settings'],generated_face_operation_id=267,toolpath_record_counts=[83])

@pytest.fixture
def terminal(route,tmp_path):
    state,_=route;source=Path(state['document']['path']);sha=m._file_hash(source);state['saved_file_sha256']=sha
    current={k:None for k in m.CURRENT_KEYS}
    current.update(state=state,source_sha256=sha,payload={'protected':'rough'},finish_payload={'protected':'finish'},
        cone_observation={'raw':'cone'},face_observation={'raw':'face'})
    parent=tmp_path/'parent.json';parent.write_text(json.dumps(dict(current_after=current,current_after_sha256=m._digest(current),order_verified=True,readback_verified=True)))
    pins=[m._self_pin(),m._pin(parent)]
    for i in range(61):
        dep=tmp_path/('_FE488661_fixture.py' if i==0 else 'original_uncertain_marker.json' if i==1 else f'live{i}.txt')
        dep.write_text('synthetic immutable dependency');pins.append(m._pin(dep))
    retired=[]
    for i in range(5):
        dep=tmp_path/f'checkedhistory{i}.txt';dep.write_text('synthetic checked history');retired.append(dict(pin=m._pin(dep),reason='synthetic history'))
    receipt=tmp_path/'result.json';marker=m.group_marker(source,sha)
    report=dict(scope=m.SCOPE,source_path=str(source),source_sha256=sha,recipe_sha256='c'*64,receipt_path=str(receipt),
        module_pin=m._self_pin(),process_id=101,parent_pin=m._pin(parent),live_pins=pins,retired_offline=retired,
        historical_move_marker_pin=pins[3],current_before=current,current_before_sha256=m._digest(current),
        messages=dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=False,callback_errors=[],callback_error_count=0,disconnect_errors=[]))
    journal=m.GroupJournal(report,receipt,marker);backend=FinalBackend(journal,current,source)
    result=m.run_grouped_backend(backend,journal)
    assert result['readback_verified'],result.get('issue')
    report['compact_checkpoint_sha256']=m._digest(report['compact_checkpoint']);report['group_marker_pin']=m._pin(marker)
    journal.persist()
    return receipt,report,journal,source


def load(terminal):
    receipt,report,journal,source=terminal
    return m.load_completed_group(receipt,m._file_hash(receipt),process_id=101,expected_document_path=str(source),expected_source_sha256=report['save_stage']['saved_file_sha256'])


def test_terminal_flat_load_no_old_loader(terminal,monkeypatch):
    from scripts import sw_cam_current_reconciliation as old
    monkeypatch.setattr(old,'load_completed_reconciliation',lambda *a,**k:pytest.fail('old parent loader replayed'))
    loaded=load(terminal)
    assert len(loaded['pins'])==64 and loaded['toolpath_record_counts']==[83]
    assert loaded['state']['operations'][4]['assigned_tool']['native_id']==249
    assert loaded['state']['operations'][-2]['toolpath_record_counts']==[191]
    assert loaded['state']['operations'][-1]['toolpath_record_counts']==[74]

@pytest.mark.parametrize('kind',['baseline_payload','baseline_state','checkpoint_count','historical_marker','source','module','live','old_history','group_marker'])
def test_terminal_tampering_rejected(terminal,kind):
    receipt,data,journal,source=terminal
    if kind=='baseline_payload':
        data['baseline']['payload']['rough']={'changed':True};data['final']['payload']['rough']={'changed':True}
    elif kind=='baseline_state':data['baseline']['state']['features'][0]['native_id']=900
    elif kind=='checkpoint_count':data['compact_checkpoint']['toolpath_record_counts']=[84];data['compact_checkpoint_sha256']=m._digest(data['compact_checkpoint'])
    elif kind=='historical_marker':data['historical_move_marker_pin']=dict(path=str(source),sha256=m._file_hash(source))
    elif kind=='source':source.write_bytes(b'changed after save')
    elif kind=='module':data['module_pin']['sha256']='0'*64
    elif kind=='live':Path(data['live_pins'][5]['path']).write_text('changed')
    elif kind=='old_history':Path(data['retired_offline'][0]['pin']['path']).write_text('changed')
    elif kind=='group_marker':journal.marker.write_text('changed')
    if kind not in ('source','live','old_history','group_marker'):
        journal.persist();data['group_marker_pin']=m._pin(journal.marker);journal.persist()
    with pytest.raises((ValueError,KeyError)):load(terminal)


def test_existing_receipt_never_overwritten(terminal):
    receipt,data,journal,source=terminal
    before=receipt.read_bytes()
    with pytest.raises(ValueError):m._fresh(dict(pins=data['live_pins'],state=data['current_before']['state']),receipt,journal.marker)
    assert receipt.read_bytes()==before
