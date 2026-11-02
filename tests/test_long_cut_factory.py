"""Portable current-catalogue and once-only tool-definition regressions."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os,sys,json
import pytest
STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import scripts
if not (ROOT/'scripts/sw_cam_long_cut_tool_definition.py').is_file(): scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_long_cut_tool_definition as m
from test_pocket_rough_exports import make_loaded
TARGET=dict(m.geometry.TARGET)
IDENTITY=dict(ToolIdentifier='OSG 3130520',ToolVendor='OSG',ToolDescription='WXL-EMS')

@pytest.fixture
def batch(tmp_path,monkeypatch):
    loaded,source=make_loaded(tmp_path)
    loaded['generated_face_operation_id']=267
    loaded['long_cut_registration']={'clsid':'fixture'}
    loaded['state']['operations'][6]['toolpath_record_counts']=[31196]
    loaded['generated_pocket']['record_counts']=[31196]
    evidence=tmp_path/'manufacturer.json';evidence.write_text('{}')
    recipe=dict(target=deepcopy(TARGET),identity=deepcopy(IDENTITY),
        profile_basis='nominal_manufacturer_body_requires_native_readback',source_pins=[m.common._pin(evidence)])
    holder=dict(file_path=str(tmp_path/'holder.mh'),pins=[])
    before=m.factory.rough.cl.validate_catalogue_authority(loaded)
    before.append(dict(native_id=273,tool_type_raw=1,CutDiameter=2.,Protrusion=26.,StnNo=19.))
    loaded['long_cut_initial_catalogue']=deepcopy(before)
    loaded['long_cut_requested_diameter']=2.
    loaded['fresh_finish_result']=dict(generated=True,tool_native_id=273)
    loaded['deep_loaded']={'guide_parameters':{'expected_parameters':{'binding':{'ops':'protected17'},'parameters':['protected8']},'document':{}},'generated':{}}
    loaded['neck_tool_candidate']=dict(native_id=273,full_tool={'protected':'oldD2'})
    loaded['neck_tool_checkpoint']=dict(protected='original273')
    control=SimpleNamespace(created=0,saved=0,props=[],closed=0,fail=None,drift=None)
    class Backend:
        def __init__(self):
            self.new_id=None;self.values={k:0 if type(v) is not str else 'unconfigured' for k,v in dict(TARGET,**IDENTITY).items()}
            self.current_state=deepcopy(loaded['state'])
        def start(self):pass
        def close(self):control.closed+=1
        def boundary(self):pass
        def finish(self):
            journal.report['protected_fourteen_cl_verified']=True
            journal.report['saved_cl']={'test':'fourteen complete streams'}
        def refresh_dirty(self):pass
        def snapshot(self,label):
            out=dict(route=m.prior.expected_route(loaded),tools=self.catalogue(),guide_snapshot=deepcopy(loaded['deep_loaded']['guide_parameters']['expected_parameters']))
            if control.drift:control.drift(label,out)
            return out
        def catalogue(self):
            out=deepcopy(before)
            if self.new_id is not None:out.append(dict(native_id=self.new_id,tool_type_raw=1,CutDiameter=2.,Protrusion=22.,StnNo=20.))
            return out
        def duplicate_candidates(self,recipe):return []
        def create(self,pending,returned):
            pending();control.created+=1
            if control.fail=='create':raise RuntimeError('unknown factory outcome')
            self.new_id=500;returned(object());return self.new_id
        def created_classification(self):return dict(MillToolType=1,MillToolSubType=3,EndRadius=0.)
        def field(self,name):return self.values[name]
        def property(self,name,value,pending):
            pending();control.props.append(name)
            if control.fail==name:raise RuntimeError('injected field failure')
            self.values[name]=value;return None
        def attach_holder(self,path,pending):
            pending()
            if control.fail=='holder':raise ValueError('holder alias')
            return 0
        def candidate(self,label):
            return dict(full_tool={'values':deepcopy(self.values),'tool_native_id':500},identity=deepcopy(IDENTITY))
        def save(self):
            control.saved+=1
            if control.fail=='save':return False
            return 0
        def saved_hash(self,report):
            source.write_bytes(b'Synthetic saved new neck tool, no native execution')
            digest=m.common._pin(source)['sha256']
            journal.report['source_transition']={'document':deepcopy(loaded['state']['document'])}
            self.current_state['saved_file_sha256']=digest
            return digest
    def verify(observed,recipe,holder_recipe):
        full=observed['full_tool']
        assert {k:full['values'][k] for k in TARGET}==TARGET
        if control.fail=='profile':raise ValueError('native profile does not implement the proposal')
        return dict(profile_verified=True,conservative_envelope_only=True,production_qualified=False)
    monkeypatch.setattr(m,'verify_candidate',verify)
    monkeypatch.setattr(m.reuse,'require_new_exact_cutter',lambda *a,**kw:{'verified':'test_double'})
    report=dict(scope=m.SCOPE,source_path=str(source),initial_source_sha256=m.common._pin(source)['sha256'],
        initial_catalogue=deepcopy(before),actions={},mutation_attempted=False,phase='prepared',status='error')
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'once.json')
    return SimpleNamespace(loaded=loaded,recipe=recipe,holder=holder,backend=Backend(),journal=journal,control=control,source=source,root=tmp_path)

def run(b):return m.run_backend(b.backend,b.journal,b.loaded,b.recipe,b.holder)

def test_current_nineteen_and_old_neck_preserved_after_one_save(batch):
    r=run(batch)
    assert r['readback_verified'] is True,r.get('issue')
    assert batch.control.created==batch.control.saved==1
    assert len(r['final_observation']['tools'])==20
    assert r['final_observation']['tools'][-2]['native_id']==273
    checkpoint=m.make_checkpoint(r,batch.loaded,batch.recipe)['context']
    assert checkpoint['neck_tool_candidate']==batch.loaded['neck_tool_candidate']
    assert checkpoint['neck_tool_checkpoint']==batch.loaded['neck_tool_checkpoint']
    assert checkpoint['long_cut_tool_candidate']['native_id']==500
    assert checkpoint['fresh_finish_result']==batch.loaded['fresh_finish_result']
    assert r['GTP_attempted'] is r['assignment_attempted'] is False
    assert batch.control.props==list(m.FIELD_ORDER)

def test_stale_eighteen_catalogue_without_current_tool_rejected_before_native(batch):
    batch.loaded['long_cut_initial_catalogue'].pop()
    with pytest.raises(ValueError,match='finish tool'):run(batch)
    assert batch.control.created==batch.control.saved==0

def test_duplicate_policy_rejection_prevents_factory(batch,monkeypatch):
    def reject(*a,**kw):raise ValueError('duplicate exact identity')
    monkeypatch.setattr(m.reuse,'require_new_exact_cutter',reject)
    r=run(batch)
    assert r['status']=='error'and batch.control.created==0


@pytest.mark.parametrize('fail',['create','holder','ShankLength','profile','save'])
def test_partial_result_never_replayed_or_reported_saved(batch,fail):
    batch.control.fail=fail;r=run(batch)
    assert r['readback_verified'] is False and r['status']=='uncertain'
    assert batch.control.created==1
    assert batch.control.saved==(1 if fail=='save' else 0)
    with pytest.raises(ValueError,match='Fresh exact attempt'):run(batch)
    assert batch.control.created==1

@pytest.mark.parametrize('change',['old_tool','route'])
def test_protected_actual_change_blocks_save(batch,change):
    def drift(label,out):
        if label!='configured':return
        if change=='old_tool':out['tools'][-2]['Protrusion']=99.
        else:out['route']['operation_counts'][0]+=1
    batch.control.drift=drift;r=run(batch)
    assert r['readback_verified'] is False and batch.control.saved==0


def test_actual_initial_catalogue_drift_fails_before_creation(batch):
    batch.control.drift=lambda label,out:out['tools'][-1].update(Protrusion=25.)
    r=run(batch);assert r['status']=='error' and batch.control.created==batch.control.saved==0

@pytest.mark.parametrize('fail',[False,True])
def test_compact_reader_preserves_full_boundaries_and_failure(tmp_path,monkeypatch,fail):
    calls=[];obj=object.__new__(m.NativeBackend)
    obj.report=dict(actions={},receipt_path=str(tmp_path/'owner.json'),source_path=str(tmp_path/'part.SLDPRT'))
    obj.loaded=dict(pins=[]);obj.persist=lambda:calls.append('full')
    durable=obj.persist
    def read(self,label):
        for _ in range(30):self.persist()
        if fail:raise ValueError('read failure')
        return {'value':1}
    monkeypatch.setattr(m.factory.NativeBackend,'read_settings',read)
    if fail:
        with pytest.raises(ValueError,match='read failure'):obj.read_settings('test')
    else:assert obj.read_settings('test')=={'value':1}
    assert obj.persist is durable and calls==['full','full']
    progress=json.loads(Path(obj.report['long_cut_read_progress'][0]).read_text())
    assert progress['status']==('failed' if fail else 'completed') and progress['read_updates']==30
    assert obj.report['actions']=={}


def test_actual_backend_constructor_keeps_capture_module_and_all_calls(batch):
    import ast,inspect,types
    b=m.NativeBackend(batch.loaded,{},None,'clsid','typelib',{},lambda:None)
    assert isinstance(b.capture,types.ModuleType)
    assert callable(b.capture.cone._bootstrap)
    names={node.func.attr for node in ast.walk(ast.parse(inspect.getsource(m.run_backend)))
        if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)
        and isinstance(node.func.value,ast.Name)and node.func.value.id=='backend'}
    assert names and all(callable(getattr(b,name))for name in names)
    for name,value in vars(b).items():
        assert not(callable(getattr(type(b),name,None))and not callable(value)),name
    assert b.guide_reader is None


def test_shared_view_has_one_context_and_session(batch,monkeypatch):
    from types import SimpleNamespace
    b=m.NativeBackend(batch.loaded,{},None,'clsid','typelib',{},lambda:None)
    token=object();context=object()
    def start(self):self.ctx=context;self.session=token;self.session_active=True
    monkeypatch.setattr(m.factory.NativeBackend,'start',start)
    monkeypatch.setattr(m.deep,'ParameterBackend',lambda *a:SimpleNamespace())
    b.start()
    assert b.guide_reader.ctx is context and b.guide_reader.session is token
    assert b.guide_reader.session_active is True


def test_changed_guide_parameters_stop_before_create(batch):
    batch.control.drift=lambda label,out:out['guide_snapshot']['parameters'].append('unrequested')
    result=run(batch)
    assert result['status']=='error'and batch.control.created==batch.control.saved==0


def test_changed_guide_after_create_stops_before_save(batch):
    def drift(label,out):
        if label=='configured':out['guide_snapshot']['parameters'].append('unrequested')
    batch.control.drift=drift;result=run(batch)
    assert result['status']=='uncertain'and batch.control.created==1 and batch.control.saved==0
