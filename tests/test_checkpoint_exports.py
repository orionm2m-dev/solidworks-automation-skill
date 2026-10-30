"""合成文件和模拟 COM 的导出边界测试；不读取项目 CAD 或原生收据。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import os
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0,str(REPO))
sys.path.insert(0,str(REPO/'tests'))
from cam_face_test_fixtures import current
from scripts import sw_cam_mill_generic_cl as cl
from scripts import sw_cam_events
from scripts import sw_cam_upper_cone_feature as cone
from scripts import sw_cam_completed_gtp_wip as wip

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value
m=module('checkpoint_export_test',ROOT/'scripts/sw_cam_checkpoint_exports.py')
g=module('grouped_export_dependency',REPO/'scripts/sw_cam_grouped_face_recipe.py')

class Session:
    def __init__(self,*args):self.active=False
    def __enter__(self):self.active=True;return self
    def __exit__(self,*args):self.active=False
    def summary(self):return dict(subscribed=True,active=self.active,disconnected=not self.active,event_count=0,
        overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])

class Guard:
    def __init__(self,backend):self.backend=backend
    def __enter__(self):self.backend.boundary();return self
    def __exit__(self,*args):self.backend.boundary()
    def typed(self,obj,name):assert name=='ICWMachine5';return obj
    def dispatch_once(self,call,*,persist_pending):persist_pending();self.backend.boundary();return call()
    def summary(self):return dict(invalid=False,native_call_attempted=True,native_call_returned=True)

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    source=tmp_path/'fixture.SLDPRT';source.write_bytes(b'synthetic non-CAD source')
    loaded=current();state=loaded['state']
    state['document'].update(path=str(source),title=source.name,needs_save=False)
    state['saved_file_sha256']=m._file_hash(source);loaded['source_sha256']=state['saved_file_sha256']
    byid={r['native_id']:r for r in state['operations']};state['operations']=[byid[n] for n in m.ORDER]
    for index,row in enumerate(state['operations']):row['operation_index']=index
    row=byid[267];row['toolpath_generated']=True;row['toolpath_record_counts']=[83]
    row['assigned_tool']=deepcopy(byid[248]['assigned_tool'])
    loaded.update(settings=g.expected_settings(True),generated_face_operation_id=267,toolpath_record_counts=[83],
        parent_pin={},group_marker_pin={},pins=[],offline_export_proof_pins=[],bootstrap_export_pins=[])
    loaded['finish_payload']['unit_record']={'metric_document_scope_observed':True}
    for key,name in [('parent_pin','saved_group.json'),('group_marker_pin','group_marker.json')]:
        path=tmp_path/name;path.write_text('{}');loaded[key]=m._pin(path);loaded['pins'].append(loaded[key])
    loaded['current_context_sha256']=m._digest(g.current_projection(loaded))
    args=dict(process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),
        receipt_path=str(tmp_path/'export.json'),qualification_only=True,acknowledge_disposable_copy=True,message_policy='vendor_default')
    control=SimpleNamespace(calls=0,labels=[],result=0,drift=None,event=False,fail=None,raw_seen=False,post_boundary_fail=False,after_native=None)
    class Machine:
        def GetController2(self):return [False,'fixture-controller',True]
        def SaveCLFile(self,path):
            control.calls+=1
            receipt=json.loads(Path(args['receipt_path']).read_text())
            marker=m.export_marker('export_cl',source,args['expected_source_sha256'])
            assert receipt['native_dispatch_pending'] is True and json.loads(marker.read_text())['native_dispatch_pending'] is True
            Path(path).write_text('UNITS/MM\nFINI\n')
            if control.fail:raise RuntimeError(control.fail)
            if control.after_native:control.after_native()
            return control.result
        def CreateSTLOfWIPs2(self,directory,name,a,b,c):
            control.calls+=1
            marker=m.export_marker('export_wip',source,args['expected_source_sha256'])
            assert json.loads(marker.read_text())['native_dispatch_pending'] is True
            Path(directory,name).write_text('solid fixture\nendsolid fixture\n')
            if control.fail:raise RuntimeError(control.fail)
            if control.after_native:control.after_native()
            return control.result
    machine=Machine()
    class Backend(g.NativeBackend):
        def __init__(self,loaded,args,sw,clsid,tlb,report,persist):
            self.loaded,self.args,self.report,self.persist=loaded,args,report,persist
            self.expected_tool=deepcopy(next(r['assigned_tool'] for r in loaded['state']['operations'] if r['native_id']==248))
            self.native={'machine':machine};self.capture=SimpleNamespace(cone=cone);self.session=None;self.session_active=False
            self.ctx=SimpleNamespace(app=None,files=self.files,identity=self.identity,guard=lambda:Guard(self),args=args)
        def files(self):m._check(self.loaded['pins'])
        def identity(self):
            assert m._file_hash(source)==self.args['expected_source_sha256']
            return deepcopy(self.loaded['state']['document'])
        def events(self,active=True):
            assert not control.event
            if self.session is not None:
                self.report['messages']=self.session.summary();assert self.session.active is active
        def boundary(self):
            self.files();self.identity();self.events()
            if control.post_boundary_fail and control.calls:raise ValueError('post-dispatch boundary changed')
        def start(self):self.session=Session();self.session.__enter__();self.session_active=True;self.boundary()
        def finish(self):self.session.__exit__();self.session_active=False;self.events(False);self.files();self.identity()
        def close(self):
            if self.session_active:self.session.__exit__();self.session_active=False
        def capture_full(self,label):
            self.boundary();control.labels.append(label)
            observation=dict(state=deepcopy(self.loaded['state']),payload=dict(rough=deepcopy(self.loaded['payload']),finish=deepcopy(self.loaded['finish_payload'])),
                cone_observation=deepcopy(self.loaded['cone_observation']),face_observation=deepcopy(self.loaded['face_observation']),
                settings=deepcopy(self.loaded['settings']),units=deepcopy(self.loaded['finish_payload']['unit_record']),binding=deepcopy(self.expected_tool))
            if control.drift:control.drift(label,observation)
            self.report.setdefault('full_diagnostics',[]).append(deepcopy(observation));self.persist()
            return observation
        def verify_final(self,observed):
            self.verify_assignment(observed)
            g.verify_route_delta(self.loaded['state'],observed['state'],self.expected_tool,generated=True,saved_sha=self.args['expected_source_sha256'])
            assert observed['payload']==dict(rough=self.loaded['payload'],finish=self.loaded['finish_payload'])
            assert observed['cone_observation']==self.loaded['cone_observation'] and observed['face_observation']==self.loaded['face_observation']
    surrogate=SimpleNamespace(**{name:getattr(g,name) for name in ('exact','current_projection','return_observation')},NativeBackend=Backend,__file__=g.__file__)
    monkeypatch.setattr(m,'_group',lambda:surrogate)
    monkeypatch.setattr(cl,'_bootstrap',lambda *a:object())
    monkeypatch.setattr(cl,'_typed',lambda obj,*args:obj)
    class BoundSession(Session):
        def summary(self):
            result=super().summary();result['event_count']=1 if control.event else 0
            return result
    monkeypatch.setattr(sw_cam_events,'CamMessageSession',BoundSession)
    return SimpleNamespace(loaded=loaded,args=args,source=source,control=control,root=tmp_path,group=surrogate)

def run(f,action):
    if action=='export_cl':return m.export_cl(object(),'fixture','fixture.tlb',loaded=f.loaded,args=f.args,output_path=str(f.root/'cl_output'/'out.cl'))
    return m.export_wip(object(),'fixture','fixture.tlb',loaded=f.loaded,args=f.args,project_root=str(f.root),output_dir=str(f.root/'wip_output'))

@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_existing_real_export_core_success(fixture,action):
    f=fixture;f.control.result=0 if action=='export_cl' else True
    result=run(f,action)
    assert result['readback_verified'] is True and result['checkpoint_export_readback_verified'] is True
    assert result['scope']==m.SCOPE
    assert f.control.calls==1 and len(f.control.labels)==(3 if action=='export_cl' else 2)
    assert m._file_hash(f.source)==f.args['expected_source_sha256']
    assert result['GTP_attempted'] is False and result['model_saved'] is False
    assert Path(f.args['receipt_path']).is_file()
    assert Path(f.args['receipt_path']).with_suffix('.observations.json').is_file()
    if action=='export_cl':
        assert result['before']==result['after'] and result['before']['expected_generated_operations']==m.operation_contract(f.loaded)
    else:assert result['export_files_verified'] is True and len(result['files'])==1

@pytest.mark.parametrize('action,result',[('export_cl',v) for v in (None,False,True,1,-1,0.0)] + [('export_wip',v) for v in (None,False,0,1,-1,'true')])
def test_unexpected_return_once_no_postread(fixture,action,result):
    f=fixture;f.control.result=result
    report=run(f,action)
    assert report['status']=='uncertain' and report['readback_verified'] is False and f.control.calls==1
    assert len(f.control.labels)==(2 if action=='export_cl' else 1)
    before={p:p.read_bytes() for p in [Path(f.args['receipt_path']),m.export_marker(action,f.source,f.args['expected_source_sha256'])]}
    f.args['receipt_path']=str(f.root/'renamed.json')
    with pytest.raises(ValueError):run(f,action)
    assert all(p.read_bytes()==raw for p,raw in before.items()) and f.control.calls==1

@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_native_exception_consumes_once(fixture,action):
    f=fixture;f.control.fail='native failure'
    report=run(f,action)
    assert report['status']=='uncertain' and report['native_dispatch_pending'] is True and f.control.calls==1
    assert len(f.control.labels)==(2 if action=='export_cl' else 1)

@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_postread_drift_persisted(fixture,action):
    f=fixture;f.control.result=0 if action=='export_cl' else True
    def drift(label,observed):
        if 'after' in label:observed['settings']['nc']['XYFeed']=1.0
    f.control.drift=drift
    report=run(f,action)
    assert report['status']=='uncertain' and report['readback_verified'] is False and f.control.calls==1
    raw=json.loads(Path(f.args['receipt_path']).with_suffix('.observations.json').read_text())
    assert raw['full_diagnostics'][-1]['settings']['nc']['XYFeed']==1.0

@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_approved_mass_recomputation_keeps_raw(fixture,action):
    f=fixture;f.control.result=0 if action=='export_cl' else True
    def drift(label,observation):observation['state']['sw_reference']['solids'][0]['mass_raw'][0]*=1.+1e-13
    f.control.drift=drift
    report=run(f,action)
    assert report['readback_verified'] is True
    raw=json.loads(Path(f.args['receipt_path']).with_suffix('.observations.json').read_text())
    assert raw['full_diagnostics'][0]['state']['sw_reference']['solids'][0]['mass_raw'][0]!=f.loaded['state']['sw_reference']['solids'][0]['mass_raw'][0]

@pytest.mark.parametrize('action',['export_cl','export_wip'])
@pytest.mark.parametrize('kind',['source','pin','settings','payload','geometry','count','dirty'])
def test_pre_capture_changes_block_dispatch(fixture,action,kind):
    f=fixture
    if kind=='source':f.source.write_bytes(b'changed')
    elif kind=='pin':Path(f.loaded['pins'][0]['path']).write_text('changed')
    else:
        def drift(label,observation):
            if kind=='settings':observation['settings']['face']['CutOrder']=0
            elif kind=='payload':observation['payload']['rough']['extra']=1
            elif kind=='geometry':observation['face_observation']['extra']=1
            elif kind=='count':next(r for r in observation['state']['operations'] if r['native_id']==267)['toolpath_record_counts']=[84]
            elif kind=='dirty':observation['state']['document']['needs_save']=True
        f.control.drift=drift
    report=run(f,action)
    assert report['readback_verified'] is False and f.control.calls==0

@pytest.mark.parametrize('action',['export_cl','export_wip'])
@pytest.mark.parametrize('which',['receipt','observations','marker'])
def test_preexisting_evidence_preserved(fixture,action,which):
    f=fixture;path=Path(f.args['receipt_path'])
    if which=='observations':path=path.with_suffix('.observations.json')
    if which=='marker':path=m.export_marker(action,f.source,f.args['expected_source_sha256'])
    path.write_bytes(b'preserve exact bytes')
    with pytest.raises(ValueError):run(f,action)
    assert path.read_bytes()==b'preserve exact bytes' and f.control.calls==0

@pytest.mark.parametrize('value',[[],[0],[True],[1,2],[-1],[100001]])
def test_invalid_generated_count(fixture,value):
    fixture.loaded['toolpath_record_counts']=value
    with pytest.raises(ValueError):m.operation_contract(fixture.loaded)

def test_independent_stable_export_markers(fixture):
    f=fixture
    first=m.export_marker('export_cl',f.source,f.args['expected_source_sha256'])
    assert first==m.export_marker('export_cl',f.source,f.args['expected_source_sha256'])
    assert first!=m.export_marker('export_wip',f.source,f.args['expected_source_sha256'])

def test_wrong_order_rejected(fixture):
    fixture.loaded['state']['operations'].reverse()
    with pytest.raises(ValueError):m.operation_contract(fixture.loaded)


@pytest.mark.parametrize('action',['export_cl','export_wip'])
@pytest.mark.parametrize('value',[float('nan'),float('inf'),-(10**100),'x'*5000])
def test_bounded_unexpected_return_survives_serialization(fixture,action,value):
    f=fixture;f.control.result=value
    report=run(f,action)
    assert report['readback_verified'] is False and f.control.calls==1
    if action=='export_wip':
        data=json.loads(Path(f.args['receipt_path']).read_text())
        observed=data['bounded_native_return']
    else:
        data=json.loads(Path(f.args['receipt_path']).with_suffix('.observations.json').read_text())
        observed=data['core_return_observation']
    assert observed['value_recorded'] is False and observed['value'] is None
    assert observed['python_type']==type(value).__name__
    json.dumps(report,allow_nan=False)

def checkpoint_pins(f):
    root=f.root/'runtime';root.mkdir()
    f.group.__file__=str(root/'sw_cam_grouped_face_recipe.py')
    files=[]
    for name in ('sw_cam_ud14_save.py','sw_cam_mill_stock_export_evidence.py','sw_cam_shared_holder_geometry.py','sw_cam_existing_sandvik.py','sw_cam_installation.py'):
        p=root/name;p.write_text('pass\n');files.append(m._pin(p))
    nominal=f.root/'installed_profile_nominal.json';nominal.write_text('{"synthetic":true}')
    files.append(m._pin(nominal));f.loaded['holder_recipe']={'pins':[m._pin(nominal)]}
    for name in ('native.mt','native.mh','stock.stl','uncertain_mutation_marker.json'):
        p=f.root/name;p.write_bytes(b'pinned synthetic input');files.append(m._pin(p))
    f.loaded['pins']=f.loaded['pins']+files
    while len(f.loaded['pins'])<64:
        p=f.root/('critical_'+str(len(f.loaded['pins']))+'.json');p.write_text('{}');f.loaded['pins'].append(m._pin(p))
    f.loaded['current_context_sha256']=m._digest(g.current_projection(f.loaded))
    f.group.load_completed_group=lambda *a,**kw:deepcopy(f.loaded)
    return files

def load(f,action):
    return m.load_export_checkpoint(f.loaded['parent_pin']['path'],f.loaded['parent_pin']['sha256'],action=action,
        **{k:f.args[k] for k in ('process_id','expected_document_path','expected_source_sha256')})

@pytest.mark.parametrize('action,retired_count,extra_count',[('export_cl',6,6),('export_wip',4,4)])
def test_exact_action_closure64_and_only_declared_retirements(fixture,action,retired_count,extra_count):
    f=fixture;checkpoint_pins(f)
    result=load(f,action)
    assert len(result['pins'])==64 and len(result['offline_export_proof_pins'])+len(result['bootstrap_export_pins'])==retired_count
    assert len(m.export_runtime_pins(action))==extra_count
    assert m._digest(g.current_projection(result))==f.loaded['current_context_sha256']
    assert {_key['sha256'] for _key in result['offline_export_proof_pins']} <= {x['sha256'] for x in f.loaded['pins']}
    protected=[p for p in f.loaded['pins'] if Path(p['path']).suffix in ('.mt','.mh','.stl') or Path(p['path']).name=='uncertain_mutation_marker.json']
    assert all(p in result['pins'] for p in protected+[f.loaded['parent_pin'],f.loaded['group_marker_pin']])
    assert set(x['path'] for x in result['pins'])==set(x['path'] for x in f.loaded['pins'] if x not in result['offline_export_proof_pins']+result['bootstrap_export_pins']) | set(x['path'] for x in m.export_runtime_pins(action))

@pytest.mark.parametrize('change',['source','retired_hash','missing_bootstrap','missing_runtime','missing_nominal','extra65'])
def test_cutover_rejects_invalid_proof(fixture,change):
    f=fixture;files=checkpoint_pins(f)
    if change=='source':f.source.write_text('changed')
    elif change=='retired_hash':Path(files[0]['path']).write_text('changed')
    elif change=='missing_bootstrap':f.loaded['pins'].remove(files[4])
    elif change=='missing_runtime':f.loaded['pins'].remove(files[0])
    elif change=='missing_nominal':f.loaded['holder_recipe']={'pins':[]}
    elif change=='extra65':
        p=f.root/'extra.json';p.write_text('{}');f.loaded['pins'].append(m._pin(p))
    with pytest.raises(ValueError):load(f,'export_cl')

@pytest.mark.parametrize('action',['generate','save','move','export_nc','arbitrary'])
def test_only_export_actions_allowed(action):
    with pytest.raises(ValueError):m.validate_request({'action':action,'params':{}})


def test_wip_result_persisted_even_if_exit_boundary_fails(fixture):
    f=fixture;f.control.result=True;f.control.post_boundary_fail=True
    report=run(f,'export_wip')
    assert report['status']=='uncertain' and report['readback_verified'] is False and f.control.calls==1
    data=json.loads(Path(f.args['receipt_path']).read_text())
    assert data['immediate_native_return_observation']==g.return_observation(True)
    assert len(f.control.labels)==1


@pytest.mark.parametrize('action',['export_cl','export_wip'])
@pytest.mark.parametrize('kind',['source','pin','event'])
def test_changed_boundary_after_native_stops_readback(fixture,action,kind):
    f=fixture;f.control.result=0 if action=='export_cl' else True
    def change():
        if kind=='source':f.source.write_bytes(b'changed during export')
        elif kind=='pin':Path(f.loaded['pins'][0]['path']).write_text('changed evidence')
        else:f.control.event=True
    f.control.after_native=change
    result=run(f,action)
    assert result['status']=='uncertain' and result['readback_verified'] is False and f.control.calls==1

@pytest.mark.parametrize('action',['export_cl','export_wip'])
def test_event_before_export_blocks_dispatch(fixture,action):
    f=fixture;f.control.event=True
    result=run(f,action)
    assert result['readback_verified'] is False and f.control.calls==0


@pytest.mark.parametrize('when',['before','during'])
def test_bootstrap_module_drift_blocks_connect(fixture,monkeypatch,when):
    from contextlib import nullcontext
    from scripts import sw_cam_installation as installation
    from scripts import sw_connect, sw_operation_guard
    f=fixture;checkpoint_pins(f);loaded=load(f,'export_cl')
    bootstrap=Path(loaded['bootstrap_export_pins'][0]['path'])
    monkeypatch.setattr(installation,'__file__',str(bootstrap))
    calls=[]
    def discover():
        calls.append('discover')
        if when=='during':bootstrap.write_text('changed discovery implementation')
        return {'errors':[]}
    monkeypatch.setattr(installation,'discover_cam_installations',discover)
    monkeypatch.setattr(sw_connect,'connect_solidworks',lambda **kw:calls.append('connect'))
    monkeypatch.setattr(sw_operation_guard,'solidworks_operation_lock',lambda **kw:nullcontext())
    monkeypatch.setattr(m,'load_export_checkpoint',lambda *a,**kw:loaded)
    params=dict(f.args,checkpoint_receipt_path=f.loaded['parent_pin']['path'],checkpoint_receipt_sha256=f.loaded['parent_pin']['sha256'],
        module_sha256=m._file_hash(m.__file__),addin_clsid='{12345678-1234-1234-1234-123456789abc}',
        acknowledge_machine_scope=True,output_path=str(f.root/'clout'/'out.cl'))
    if when=='before':bootstrap.write_text('changed discovery implementation')
    with pytest.raises(ValueError):m.dispatch_request({'action':'export_cl','params':params})
    assert 'connect' not in calls and calls==([] if when=='before' else ['discover'])

def test_bootstrap_success_is_explicit_phase_role(fixture,monkeypatch):
    from scripts import sw_cam_installation as installation
    from scripts import sw_cam
    f=fixture;checkpoint_pins(f);loaded=load(f,'export_cl')
    monkeypatch.setattr(installation,'__file__',loaded['bootstrap_export_pins'][0]['path'])
    monkeypatch.setattr(installation,'discover_cam_installations',lambda:{'errors':[]})
    monkeypatch.setattr(sw_cam,'select_registration',lambda *a:{'fixture':'registration'})
    assert m.discover_export_registration(loaded,'fixture')=={'fixture':'registration'}
    assert loaded['bootstrap_validation']['role']=='bootstrap_checked'
    assert loaded['bootstrap_validation']['checked_before'] and loaded['bootstrap_validation']['checked_after']
    assert loaded['bootstrap_validation']['executes_during_native_capture'] is False
