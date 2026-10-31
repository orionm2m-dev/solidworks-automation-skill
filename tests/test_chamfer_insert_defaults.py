"""Portable one-insertion protocol and terminal continuation tests."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_chamfer_insert_defaults as m

spec=importlib.util.spec_from_file_location('insert_defaults_graph',ROOT/'tests/test_chamfer_defaults.py')
graph=importlib.util.module_from_spec(spec);spec.loader.exec_module(graph)


class Fake:
    def __init__(self,loaded,report,source):
        self.loaded=loaded;self.report=report;self.source=source
        self.current_state=deepcopy(loaded['state']);self.calls=[];self.new=False
        self.fault=None;self.save_return=0;self.defaults=graph.Graph().run()
    def call(self,name):
        self.calls.append(name)
        if self.fault==name:raise RuntimeError('injected '+name)
    def start(self):
        self.call('start')
        self.report['interface_audit']=dict(all_resolved=True,native_query_interface_calls=0)
    def snapshot(self,label):
        self.call('snapshot:'+label)
        route=m.base.expected_route(self.loaded)
        if self.new:
            row=dict(setup_index=0,setup_native_id=20,operation_index=7,native_id=100,
                mill_operation_type=1,base_operation_type=9,suppressed=False,toolpath_generated=False,
                linked_feature_ids=[70],toolpath_record_counts=[],assigned_tool=None)
            route['operations'].append(row);route['operation_counts'][0]+=1
            route['operation_setups'][0]['operation_count']+=1
        if self.fault=='old_state:'+label:route['operations'][0]['toolpath_record_counts']=[999]
        if self.fault=='new_generated':route['operations'][-1]['toolpath_generated']=True
        tools=deepcopy(self.loaded['tool_checkpoint']['final_observation']['tools'])
        if self.fault=='tools:'+label:tools[0]['CutDiameter']+=1
        for name in ('operations','operation_counts','operation_setups'):self.current_state[name]=deepcopy(route[name])
        self.current_state['operation_count']=len(route['operations'])
        return dict(route=route,tools=tools,feature=deepcopy(self.loaded['cone_observation']['feature']))
    def operation_defaults(self,oid,label,feature_native_id=None):
        self.call('defaults:'+label)
        if label=='anchor_reader_preflight':assert oid==90 and feature_native_id==69
        else:assert oid==100 and feature_native_id is None
        result=deepcopy(self.defaults)
        if self.fault=='defaults_bad:'+label:result['finish']['GetChamferType']=True
        if self.fault=='defaults_drift' and label=='saved_defaults':result['finish']['GetChamferLength']+=.1
        return result
    def insert(self,pending):
        pending();self.call('insert');self.new=True
        return object()
    def refresh_dirty(self):self.call('refresh_dirty')
    def bind_inserted(self,raw):
        self.call('bind')
        return 100 if self.fault!='old_id' else 90
    def boundary(self):self.call('guard')
    def save(self):
        self.call('save')
        if self.fault!='unchanged_source':self.source.write_bytes(b'new-saved-cam')
        return self.save_return
    def saved_hash(self,save):
        self.call('saved_hash')
        sha=m._file_hash(self.source)
        self.current_state['saved_file_sha256']=sha
        self.report['source_transition']=dict(source_before_sha256=self.loaded['source_sha256'],
            source_after_sha256=sha,strict_save_return=0,document=deepcopy(self.current_state['document']))
        return sha
    def finish(self):
        self.call('finish')
        self.report['messages']=dict(subscribed=True,active=False,disconnected=True,event_count=0,
            overflow=False,callback_errors=[],callback_error_count=0)
    def close(self):self.call('close')


@pytest.fixture
def case(tmp_path,monkeypatch):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'old-saved-tool')
    archive=tmp_path/'tool-archive.SLDPRT';archive.write_bytes(source.read_bytes())
    proof=tmp_path/'proof.json';proof.write_text('{}')
    tool=dict(native_id=120,tool_type_raw=8,CutDiameter=2.,Protrusion=20.,StnNo=0)
    old=[dict(setup_index=0,setup_native_id=20,operation_index=i,native_id=84+i,
        mill_operation_type=20 if i==4 else 1,base_operation_type=9,suppressed=False,
        toolpath_generated=i>=4,linked_feature_ids=[69],toolpath_record_counts=[10+i] if i>=4 else [],
        assigned_tool=deepcopy(tool)) for i in range(7)]
    loaded={k:{} for k in m.group.CURRENT_KEYS}
    loaded.update(state=dict(document={'needs_save':False,'path':str(source)},
        saved_file_sha256=m._file_hash(source),features=[dict(setup_native_id=10,geometry={'native_id':70})],
        feature_setups=[dict(native_id=10)],operations=old,operation_counts=[7,0,0],operation_count=7,
        operation_setups=[dict(index=i,native_id=20+i,operation_count=7 if i==0 else 0) for i in range(3)]),
        source_sha256=m._file_hash(source),settings={'LeadInClearance':[8.,False]},
        generated_face_operation_id=88,toolpath_record_counts=[14],
        cone_observation={'feature':{'native_id':70,'taper_enabled':True,'taper_angle_readback':45.}},
        finish_payload={'unit_record':{'metric_document_scope_observed':True}},
        tool_checkpoint={'final_observation':{'tools':[deepcopy(tool)]}},
        local_tool_candidate={'native_id':120,'qualified':True},profile_contract={'review':'fixture'},
        candidate_qualification={'complete_qualified':True},
        pins=[m.exports._pin(proof)],offline_export_proof_pins=[],bootstrap_export_pins=[],
        parent_pin=m.exports._pin(proof),tool_source_archive_pin=m.exports._pin(archive),
        insertion_phase_retired_pins=[],generated_pin=m.exports._pin(proof))
    loaded['current_context_sha256']=m._digest(m.group.current_projection(loaded))
    params=dict(process_id=123,expected_document_path=str(source),expected_source_sha256=loaded['source_sha256'],
        checkpoint_receipt_path=str(proof),checkpoint_receipt_sha256=m._file_hash(proof),
        tool_source_archive_path=str(archive),receipt_path=str(tmp_path/'insert.json'),
        feature_native_id=70,anchor_operation_native_id=90,default_operation_id=145,
        default_operation_name='Contour machining',module_sha256=m._file_hash(m.__file__),
        addin_clsid='{12345678-1234-1234-1234-123456789ABC}',qualification_only=True,
        acknowledge_disposable_copy=True,acknowledge_machine_scope=True,message_policy='vendor_default')
    monkeypatch.setattr(m,'load_inputs',lambda p,check_current=True:deepcopy(loaded))
    monkeypatch.setattr(m,'marker_path',lambda *args:tmp_path/'insert.marker.json')
    _,r,marker=m.prepare(params)
    journal=m.Journal(r,params['receipt_path'],marker)
    return SimpleNamespace(loaded=loaded,p=params,r=r,j=journal,b=Fake(loaded,r,source),source=source)


def run(c):return m.run_backend(c.b,c.j,c.loaded,c.p)


def complete(c):
    result=run(c);assert result['readback_verified'],result.get('issue')
    result['phase_proofs_verified_after_native']=True
    result['checkpoint']=m.make_checkpoint(result);result['checkpoint_sha256']=m._digest(result['checkpoint'])
    m.validate_terminal(result,c.loaded)
    c.j.persist();result['marker_pin']=m.exports._pin(c.j.marker);c.j.persist()
    return result


def test_one_insert_defaults_and_one_save_without_tool_assignment(case):
    r=complete(case)
    assert list(r['actions'])==['InsertOperation','SaveActiveDocument']
    assert case.b.calls.count('insert')==case.b.calls.count('save')==1
    assert [x for x in case.b.calls if x.startswith('snapshot:')]==[
        'snapshot:before','snapshot:inserted','snapshot:saved']
    assert case.b.calls.index('defaults:anchor_reader_preflight')<case.b.calls.index('insert')
    assert r['new_operation_native_id']==100
    assert r['checkpoint']['current']['state']['operation_count']==8
    assert r['new_operation']['assigned_tool'] is None
    assert r['full_tool_profile_capture_count']==0 and r['assignment_attempted'] is False


@pytest.mark.parametrize('fault',['start','snapshot:before','old_state:before',
    'defaults:anchor_reader_preflight','defaults_bad:anchor_reader_preflight','tools:before'])
def test_failure_before_creator_has_no_mutations(case,fault):
    case.b.fault=fault;r=run(case)
    assert r['readback_verified'] is False and r['actions']=={}
    assert 'insert' not in case.b.calls and 'save' not in case.b.calls and not case.j.marker.exists()


@pytest.mark.parametrize('fault',['insert','save'])
def test_native_exception_preserves_pending_and_forbids_replay(case,fault):
    case.b.fault=fault;r=run(case)
    name='InsertOperation' if fault=='insert' else 'SaveActiveDocument'
    assert r['actions'][name]['pending'] is True and case.b.calls.count(fault)==1
    assert r['readback_verified'] is False
    other=m.Journal(r,Path(case.p['receipt_path']).with_name('renamed.json'),case.j.marker)
    with pytest.raises(ValueError):other.claim()


@pytest.mark.parametrize('fault',['bind','old_id','old_state:inserted','tools:inserted',
    'new_generated','defaults:new_defaults','defaults_bad:new_defaults'])
def test_post_insert_failure_keeps_actual_attempt_without_save(case,fault):
    case.b.fault=fault;r=run(case)
    assert r['readback_verified'] is False and case.b.calls.count('insert')==1
    assert 'save' not in case.b.calls
    assert r['actions']['InsertOperation']['returned'] is True


@pytest.mark.parametrize('value',[False,True,None,1,0.,'0'])
def test_non_integer_zero_save_is_not_accepted(case,value):
    case.b.save_return=value;r=run(case)
    assert r['readback_verified'] is False and case.b.calls.count('save')==1
    assert 'saved_hash' not in case.b.calls


@pytest.mark.parametrize('fault',['unchanged_source','defaults_drift','old_state:saved','tools:saved','finish'])
def test_post_save_failure_never_saves_twice(case,fault):
    case.b.fault=fault;r=run(case)
    assert r['readback_verified'] is False and case.b.calls.count('save')==1


def test_loader_accepts_new_bytes_with_historical_parent_only(case):
    r=complete(case)
    loaded=m.load_completed(case.p['receipt_path'],m._file_hash(case.p['receipt_path']),
        process_id=123,expected_document_path=str(case.source),expected_source_sha256=r['saved_source_sha256'])
    assert loaded['state']['operation_count']==8 and loaded['inserted_contour']['native_id']==100
    assert loaded['local_tool_candidate']==case.loaded['local_tool_candidate']
    assert case.source.read_bytes()==b'new-saved-cam'


@pytest.mark.parametrize('field',['actions','counts','candidate','source','marker','defaults','old_op','savebool','status','receipt_error'])
def test_terminal_tampering_rejected(case,field):
    r=complete(case)
    if field=='actions':r['actions']['SetTool']={}
    if field=='counts':r['toolpath_record_counts']=[999]
    if field=='candidate':r['local_tool_candidate']['native_id']+=1
    if field=='source':case.source.write_bytes(b'changed')
    if field=='marker':case.j.marker.write_text('{}')
    if field=='defaults':r['final_defaults']['finish']['GetChamferType']=True
    if field=='old_op':r['final_observation']['route']['operations'][0]['suppressed']=True
    if field=='savebool':r['save_stage']['native_return_value']=False
    if field=='status':r['status']='uncertain'
    if field=='receipt_error':r['receipt_write_error']='storage failure'
    m._write_receipt(case.p['receipt_path'],r)
    with pytest.raises(ValueError):
        m.load_completed(case.p['receipt_path'],m._file_hash(case.p['receipt_path']),
            process_id=123,expected_document_path=str(case.source),expected_source_sha256=r['saved_source_sha256'])


def test_changed_request_filename_or_default_id_cannot_bypass_once_marker(case):
    run(case)
    p=dict(case.p,receipt_path=str(Path(case.p['receipt_path']).with_name('different.json')),default_operation_id=146)
    with pytest.raises(ValueError):m.prepare(p)


class Guard:
    def __init__(self, backend, *, default_id=145):
        self.b=backend;self.default_id=default_id;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,obj,name,*args):
        self.calls.append((name,args))
        if name=='QueryInterface':return self.b.anchor_dispatch
        if name=='GetTdbIdForDefaultOperation':return self.default_id
        raise AssertionError(name)
    def dispatch_once(self,invoke,*,persist_pending):
        persist_pending();self.calls.append(('dispatch',()))
        return invoke()


def native_insert_fixture(case, monkeypatch, *, default_id=145, pointer=True):
    from scripts import sw_cam_comtypes as bridge
    b=object.__new__(m.NativeBackend)
    b.args=case.p;b.report=case.r;b.persist=case.j.persist
    b.feature=object();b.anchor_raw=object();b.anchor_dispatch=object();b.raw_result=object()
    b.native={'doc':object(),'operations':{90:b.anchor_raw}}
    b.selected_feature=lambda:(b.feature,{})
    g=Guard(b,default_id=default_id);b.ctx=SimpleNamespace(guard=lambda:g)
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:90 if obj in (b.anchor_raw,b.anchor_dispatch) else 70)
    monkeypatch.setattr(bridge,'_is_comtypes_pointer',lambda obj:obj is b.raw_result and pointer)
    def member(obj,name,*args):
        assert obj is b.feature and name=='InsertOperation'
        assert args==(1,145,b.anchor_dispatch)
        assert case.r['actions']['InsertOperation']['pending'] is True and case.j.marker.exists()
        g.calls.append(('native',args))
        return b.raw_result
    monkeypatch.setattr(m,'_member',member)
    return b,g


def test_real_adapter_uses_exact_three_arg_overload_with_actual_dispatch(case,monkeypatch):
    b,g=native_insert_fixture(case,monkeypatch)
    assert b.insert(lambda:case.j.pending('InsertOperation')) is b.raw_result
    assert [x[0] for x in g.calls]==['QueryInterface','GetTdbIdForDefaultOperation','dispatch','native']
    assert case.r['actions']['InsertOperation']['returned_interface_pointer'] is True
    assert case.r['actions']['InsertOperation']['pending'] is False


def test_changed_native_default_stops_before_once_claim(case,monkeypatch):
    b,g=native_insert_fixture(case,monkeypatch,default_id=146)
    with pytest.raises(ValueError):b.insert(lambda:case.j.pending('InsertOperation'))
    assert not case.r['actions'] and not case.j.marker.exists()
    assert not any(x[0]=='native' for x in g.calls)


def test_invalid_native_return_preserves_returned_type_and_stops(case,monkeypatch):
    b,g=native_insert_fixture(case,monkeypatch,pointer=False)
    with pytest.raises(ValueError):b.insert(lambda:case.j.pending('InsertOperation'))
    action=case.r['actions']['InsertOperation']
    assert action['returned'] is True and action['pending'] is False
    assert action['returned_interface_pointer'] is False


def test_defaults_batch_rejects_setters_and_converts_only_standard_dispatch(monkeypatch):
    from comtypes.automation import IDispatch
    b=object.__new__(m.DefaultsReadBatch);b._invalid=False;b._completed=False
    calls=[];obj=object()
    b._observe_read=lambda raw,kind,fn:(calls.append((raw,kind)),fn())[1]
    monkeypatch.setattr(m,'_member',lambda raw,name,*args:(name,args))
    assert b.typed(obj,'IDispatch')==('QueryInterface',(IDispatch,))
    assert calls==[(obj,'getter')]
    with pytest.raises(ValueError):b.read(obj,'SetChamferLength',.2)
    assert len(calls)==1
