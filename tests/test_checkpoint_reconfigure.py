"""Protocol tests use synthetic CAM state and never connect to a CAD application."""
from copy import deepcopy
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import os
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
REPO=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT)).resolve()
sys.path.insert(0,str(REPO));sys.path.insert(0,str(REPO/'tests'))
from test_checkpoint_exports import fixture,Session
spec=importlib.util.spec_from_file_location('checkpoint_reconfigure_test',ROOT/'scripts/sw_cam_checkpoint_reconfigure.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Backend:
    def __init__(self,f,journal):
        self.f,self.loaded,self.journal=f,deepcopy(f.loaded),journal
        self.state=deepcopy(f.loaded['state']);self.settings=deepcopy(f.loaded['settings'])
        self.calls=Counter();self.returns={};self.fail={};self.drift={};self.labels=[]
        self.invalidate=False;self.event=False;self.process_changed=False;self.session=None
        self.expected_tool=deepcopy(next(v['assigned_tool'] for v in self.state['operations'] if v['native_id']==267))
    def boundary(self):
        assert not self.event and not self.process_changed
        m.check(self.loaded['pins'])
        assert m._file_hash(self.f.source)==self.state['saved_file_sha256']
    def start(self):self.calls['start']+=1;self.boundary();self.session=Session();self.session.__enter__()
    def finish(self):self.boundary();self.session.__exit__();self.journal.report['messages']=self.session.summary()
    def close(self):
        if self.session and self.session.active:self.session.__exit__()
        if self.session:self.journal.report['messages']=self.session.summary()
    def refresh_dirty(self):self.boundary()
    def observe(self,label,full=False):
        self.boundary();self.labels.append(label)
        r=dict(state=deepcopy(self.state),settings=deepcopy(self.settings),binding=deepcopy(self.expected_tool),
            units=deepcopy(self.loaded['finish_payload']['unit_record']))
        if full:r.update(payload=dict(rough=deepcopy(self.loaded['payload']),finish=deepcopy(self.loaded['finish_payload'])),
            cone_observation=deepcopy(self.loaded['cone_observation']),face_observation=deepcopy(self.loaded['face_observation']))
        if label in self.drift:self.drift[label](r)
        return r
    def capture_full(self,label):return self.observe(label,True)
    def read_narrow(self,label):return self.observe(label)
    def read_field(self,name):self.boundary();return deepcopy(self.settings['face'][name])
    def native(self,name,pending,mutate):
        self.boundary();pending()
        a=json.loads(self.journal.receipt.read_text())['actions'][name]
        b=json.loads(self.journal.marker.read_text())['actions'][name]
        assert a['native_dispatch_pending'] and b['native_dispatch_pending']
        self.calls[name]+=1
        if name in self.fail:raise RuntimeError(self.fail[name])
        mutate();return self.returns.get(name,0)
    def write_lead(self,pending):
        def mutate():
            self.settings['face'][m.GETTER]=deepcopy(m.TARGET)
            if self.invalidate:
                r=next(v for v in self.state['operations'] if v['native_id']==267)
                r.update(toolpath_generated=False,toolpath_record_counts=[])
        return self.native(m.MEMBER,pending,mutate)
    def generate(self,pending):
        def mutate():
            r=next(v for v in self.state['operations'] if v['native_id']==267)
            r.update(toolpath_generated=True,toolpath_record_counts=[101])
        return self.native('GenerateToolpath',pending,mutate)
    def save_projection(self,observed):return m.group.NativeBackend.save_projection(None,observed)
    def save(self):
        return self.native('SaveActiveDocument',lambda:None,lambda:None)
    def saved_hash(self,report):
        assert report['native_return_type']=='int' and type(report['native_return_value']) is int and report['native_return_value']==0
        before=self.state['saved_file_sha256'];self.f.source.write_bytes(b'new saved source')
        digest=m._file_hash(self.f.source);self.state['saved_file_sha256']=digest;self.state['document']['needs_save']=False
        self.journal.report['source_transition']=dict(source_before_sha256=before,source_after_sha256=digest,
            strict_save_return=0,document=deepcopy(self.state['document']))
        return digest
    def checkpoint(self,final):
        current=m.group.current_projection(self.loaded)
        current.update(state=deepcopy(final['state']),source_sha256=final['state']['saved_file_sha256'])
        return dict(current=current,settings=deepcopy(final['settings']),generated_face_operation_id=267,
                    toolpath_record_counts=deepcopy(next(v['toolpath_record_counts'] for v in final['state']['operations'] if v['native_id']==267)))


@pytest.fixture
def case(fixture):
    f=fixture
    report=dict(scope=m.SCOPE,source_path=str(f.source),source_sha256=f.args['expected_source_sha256'],recipe_sha256='b'*64,
        current_before=m.group.current_projection(f.loaded),current_before_sha256=f.loaded['current_context_sha256'],
        settings_before=deepcopy(f.loaded['settings']),module_pin=m.pin(m.__file__),process_id=f.args['process_id'])
    j=m.Journal(report,f.root/'correction.json',m.marker_path(f.source,f.args['expected_source_sha256']))
    report['receipt_path']=str(j.receipt)
    b=Backend(f,j)
    return SimpleNamespace(f=f,b=b,j=j)


def run(case):return m.run_backend(case.b,case.j,case.f.loaded)


@pytest.mark.parametrize('invalidate',[True,False])
def test_intentional_new_generation_accepts_old_or_invalidated_path(case,invalidate):
    case.b.invalidate=invalidate;r=run(case)
    assert r['readback_verified'],r
    assert r['full_capture_count']==2 and case.b.labels==['baseline','configured','generated','before_save','final']
    assert all(case.b.calls[name]==1 for name in m.ACTIONS)
    assert r['checkpoint']['settings']['face'][m.GETTER]==[8.0,False]
    assert r['checkpoint']['current']['source_sha256']!=r['source_sha256']
    assert m.validate_terminal(r)==r['checkpoint']


@pytest.mark.parametrize('name',m.ACTIONS)
@pytest.mark.parametrize('value',[None,False,True,1,-1,0.0,'0',float('nan'),float('inf'),2**100])
def test_bad_return_is_durable_and_stops_following_actions(case,name,value):
    case.b.returns[name]=value;r=run(case)
    assert not r['readback_verified'] and r['status']=='uncertain'
    a=json.loads(case.j.receipt.read_text())['actions'][name]
    assert a['returned'] and a['native_return']['python_type']==type(value).__name__
    assert case.b.calls[name]==1
    assert all(case.b.calls[v]==0 for v in m.ACTIONS[m.ACTIONS.index(name)+1:])


@pytest.mark.parametrize('name',m.ACTIONS)
def test_native_exception_keeps_pending_and_cannot_replay(case,name):
    case.b.fail[name]='native failed';r=run(case)
    assert not r['readback_verified'] and r['actions'][name]['native_dispatch_pending']
    raw=case.j.marker.read_bytes()
    replacement=m.Journal(dict(case.j.report,actions={}),case.f.root/'renamed.json',case.j.marker)
    other=Backend(case.f,replacement);again=m.run_backend(other,replacement,case.f.loaded)
    assert not again['readback_verified'] and other.calls['start']==0 and case.j.marker.read_bytes()==raw


@pytest.mark.parametrize('label',['baseline','configured','generated','before_save','final'])
def test_unrelated_settings_drift_stops(case,label):
    case.b.drift[label]=lambda row:row['settings']['nc'].__setitem__('XYFeed',999.0)
    r=run(case);assert not r['readback_verified']
    if label in ('baseline','configured'):assert case.b.calls['GenerateToolpath']==0
    if label!='final':assert case.b.calls['SaveActiveDocument']==0


@pytest.mark.parametrize('field',['assigned_tool','linked_feature_ids','setup_native_id','suppressed','operation_index'])
def test_configured_identity_drift_stops_before_gtp(case,field):
    def drift(row):next(v for v in row['state']['operations'] if v['native_id']==267)[field]='bad'
    case.b.drift['configured']=drift;r=run(case)
    assert not r['readback_verified'] and case.b.calls['GenerateToolpath']==0


@pytest.mark.parametrize('oid',[247,248])
def test_other_toolpath_cannot_change(case,oid):
    def drift(row):next(v for v in row['state']['operations'] if v['native_id']==oid)['toolpath_record_counts']=[1]
    case.b.drift['generated']=drift;r=run(case)
    assert not r['readback_verified'] and case.b.calls['SaveActiveDocument']==0


@pytest.mark.parametrize('value',[True,False,0,-1,2**31,1.0,'1'])
def test_derived_automatic_count_strict_type_and_bounds(case,value):
    case.b.drift['generated']=lambda row:row['settings']['face'].__setitem__('NumberOfCuts',value)
    r=run(case);assert not r['readback_verified'] and case.b.calls['SaveActiveDocument']==0


def test_derived_count_must_freeze_through_save(case):
    case.b.drift['before_save']=lambda row:row['settings']['face'].__setitem__('NumberOfCuts',2)
    assert not run(case)['readback_verified'] and case.b.calls['SaveActiveDocument']==0


@pytest.mark.parametrize('attribute',['event','process_changed'])
def test_boundary_failure_before_native(case,attribute):
    setattr(case.b,attribute,True);r=run(case)
    assert not r['readback_verified'] and all(case.b.calls[n]==0 for n in m.ACTIONS)


def test_source_drift_before_native(case):
    case.f.source.write_bytes(b'changed by other owner');r=run(case)
    assert not r['readback_verified'] and case.b.calls[m.MEMBER]==0


def test_live_pin_change_stops_before_native(case):
    Path(case.f.loaded['pins'][0]['path']).write_bytes(b'changed');r=run(case)
    assert not r['readback_verified'] and case.b.calls[m.MEMBER]==0


def test_marker_does_not_depend_on_target_recipe_or_receipt(case):
    path=m.marker_path(case.f.source,case.f.args['expected_source_sha256'])
    assert path==m.marker_path(case.f.source.parent/'.'/case.f.source.name,case.f.args['expected_source_sha256'])
    assert path!=m.marker_path(case.f.source,'c'*64)


def test_terminal_tamper_rejected(case):
    r=run(case);assert r['readback_verified']
    for mutate in [lambda x:x['checkpoint']['settings']['face'].__setitem__(m.GETTER,[2.0,False]),
        lambda x:x['actions']['GenerateToolpath']['native_return'].__setitem__('value',True),
        lambda x:x['source_transition'].__setitem__('source_before_sha256','f'*64),
        lambda x:x['final']['state']['operations'].reverse()]:
        bad=deepcopy(r);mutate(bad)
        with pytest.raises((ValueError,StopIteration)):m.validate_terminal(bad)


@pytest.fixture
def terminal(case,monkeypatch):
    c=case;f=c.f
    runtime=f.root/'runtime';runtime.mkdir()
    def file(name,text='fixture'):
        p=runtime/name;p.write_text(text);return m.pin(p)
    fake_group=file('sw_cam_grouped_face_recipe.py')
    monkeypatch.setattr(m,'group',SimpleNamespace(**{k:getattr(m.group,k) for k in dir(m.group) if not k.startswith('__')},__file__=fake_group['path']))
    stock=file('sw_cam_mill_stock_export_evidence.py');install=file('sw_cam_installation.py');save=file('sw_cam_ud14_save.py');shared=file('sw_cam_shared_holder_geometry.py')
    holder=file('holder.json','{}');failed=file('failed.json','{}');recovery_marker=file('recovery_marker.json','{}')
    generated=file('_FE488661_fixture.py')
    owned=dict(process_id=f.args['process_id'],create_time=100.0,executable='fixture.exe',alive=True)
    startup=file('startup.json',json.dumps(dict(status='ok',phase='connected',new_process_verified=True,process_id=f.args['process_id'],process_identity=owned)))
    f.loaded.update(ownership=owned,holder_recipe=dict(pins=[holder],records=[]))
    initial=[f.loaded['group_marker_pin'],failed,stock,install,holder,shared,generated,startup,m.pin(m.exports.__file__),m.pin(REPO/'scripts/sw_cam_sandvik_phase1.py')]
    initial += [file('evidence%d.txt'%i) for i in range(64-len(initial))]
    before=m.group.current_projection(f.loaded)
    cp=dict(current=deepcopy(before),settings=deepcopy(f.loaded['settings']),generated_face_operation_id=267,toolpath_record_counts=[83])
    parent=dict(scope=m.exports.RECOVERY_SCOPE,status='observed',phase='finished',read_only=True,read_pending=False,
        readback_verified=True,state_reconciled=True,original_group_completion_claimed=False,
        full_capture_count=1,native_mutation_calls=0,module_pin=m.pin(m.exports.__file__),process_id=f.args['process_id'],
        source_path=str(f.source),source_sha256=f.args['expected_source_sha256'],GTP_attempted=False,model_saved=False,
        setter_attempted=False,automatic_replay=False,checkpoint=cp,checkpoint_sha256=m._digest(cp),
        live_pins=initial,failed_group_pin=failed,messages=Session().summary())
    parent['messages']['subscribed']=True;parent['messages']['disconnected']=True
    parent_path=Path(f.loaded['parent_pin']['path']);parent_path.write_text(json.dumps(parent));from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    _,parentpin=read_pin(str(parent_path),m._file_hash(parent_path))
    parent_live=m.merge([p for p in initial if m.key(p['path'])!=m.key(failed['path'])],[parentpin])
    retired=m._retirements(dict(f.loaded,pins=parent_live));keys={m.key(p['path']) for p in retired}
    live=m.merge([p for p in parent_live if m.key(p['path']) not in keys],[m.pin(m.__file__),save]);assert len(live)==63
    f.loaded.update(pins=live,parent_pin=parentpin,reconfigure_retired_pins=retired,current_context_sha256=m._digest(before))
    plan=dict(scope='FACE267_SINGLE_PARAMETER_LEADIN_CORRECTION_V1',operation_native_id=267,feature_native_id=265,
        assigned_tool_native_id=249,all_other_settings_protected=True,only_parameter_change=dict(interface='ICWFaceMillOp',setter=m.MEMBER,getter=m.GETTER,expected_old=deepcopy(m.OLD),target=deepcopy(m.TARGET)),
        baseline_settings=deepcopy(f.loaded['settings']),source_sha256=f.args['expected_source_sha256'],source_authority=parentpin,
        protected_operations={'247':[191],'248':[74]},source_evidence=[])
    planpin=file('plan.json',json.dumps(plan))
    r=c.j.report;r.update(current_before=before,current_before_sha256=m._digest(before),parent_pin=parentpin,
        recipe_pin=planpin,recipe_sha256=planpin['sha256'],plan=plan,live_pins=live,retired_offline=retired,
        previous_recovery_marker_pin=recovery_marker,previous_group_marker_pin=f.loaded['group_marker_pin'],
        historical_move_marker_pin=f.loaded['group_marker_pin'])
    c.b=Backend(f,c.j);result=run(c);assert result['readback_verified'],result
    result['marker_pin']=m.pin(c.j.marker);c.j.persist()
    c.digest=m._file_hash(c.j.receipt);c.identity=dict(process_id=f.args['process_id'],expected_document_path=str(f.source),expected_source_sha256=result['saved_source_sha256'])
    c.retired=retired;c.startup=startup;c.parent_path=parent_path;c.parent=parent
    return c


def load_terminal(c):return m.load_completed(str(c.j.receipt),m._file_hash(c.j.receipt),**c.identity)


def test_flat_terminal_loads_new_source_without_old_source_check(terminal):
    c=terminal;loaded=load_terminal(c)
    assert loaded['settings']['face'][m.GETTER]==[8.,False] and len(loaded['pins'])==64
    assert loaded['source_sha256']==m._file_hash(c.f.source)!=c.j.report['source_sha256']
    assert loaded['toolpath_record_counts']==[101]


@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_terminal_can_build_bounded_export_context(terminal,action):
    c=terminal
    loaded=m.load_export(str(c.j.receipt),m._file_hash(c.j.receipt),action=action,**c.identity)
    assert len(loaded['pins'])<=64 and loaded['settings']['face'][m.GETTER]==[8.,False]
    assert any(m.key(p['path'])==m.key(m.__file__) for p in loaded['pins'])
    assert not any(m.key(p['path'])==m.key(c.j.marker) for p in loaded['pins'])
    assert m.exports.operation_contract(loaded)[0]['toolpath_record_counts']==[101]


@pytest.mark.parametrize('slot',[0,1,2])
def test_changed_retired_evidence_blocks_terminal_before_native(terminal,slot):
    c=terminal;Path(c.retired[slot]['path']).write_bytes(b'one changed byte')
    with pytest.raises(ValueError):load_terminal(c)


def test_changed_saved_source_rejected(terminal):
    c=terminal;c.f.source.write_bytes(b'wrong current source')
    with pytest.raises(ValueError):load_terminal(c)


def test_unrelated_valid_live_pin_substitution_rejected(terminal):
    c=terminal;r=json.loads(c.j.receipt.read_text());p=c.f.root/'unrelated.txt';p.write_text('valid hash wrong role')
    index=next(i for i,p in enumerate(r['live_pins']) if Path(p['path']).name=='evidence0.txt')
    r['live_pins'][index]=m.pin(p);c.j.receipt.write_text(json.dumps(r))
    with pytest.raises(ValueError,match='derived'):load_terminal(c)


@pytest.mark.parametrize('field,value',[('read_only',False),('native_mutation_calls',True),('status','uncertain'),('process_id',999)])
def test_parent_completed_proof_flags_are_strict(terminal,field,value):
    c=terminal;p=deepcopy(c.parent);p[field]=value;c.parent_path.write_text(json.dumps(p))
    r=json.loads(c.j.receipt.read_text());newpin=m.pin(c.parent_path);r['parent_pin']=newpin
    for row in r['live_pins']:
        if m.key(row['path'])==m.key(c.parent_path):row.update(newpin)
    c.j.receipt.write_text(json.dumps(r))
    with pytest.raises(ValueError):load_terminal(c)


def test_startup_provenance_change_rejected_before_export(terminal):
    c=terminal;Path(c.startup['path']).write_bytes(b'changed ownership record')
    with pytest.raises(ValueError):m.load_export(str(c.j.receipt),m._file_hash(c.j.receipt),action='export_cl',**c.identity)


def test_save_same_bytes_is_not_accepted_and_not_repeated(case):
    case.b.saved_hash=lambda report:case.f.args['expected_source_sha256']
    r=run(case)
    assert not r['readback_verified'] and r['status']=='uncertain'
    assert case.b.calls['SaveActiveDocument']==1 and case.b.labels[-1]=='before_save'


def test_nonprimitive_save_return_original_type_retained(case):
    case.b.returns['SaveActiveDocument']=object()
    r=run(case);row=r['actions']['SaveActiveDocument']['native_return']
    assert not r['readback_verified'] and row['python_type']=='object' and row['value_recorded'] is False
