"""Portable protocol tests. Synthetic objects never connect to a CAD process."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import os
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', ROOT))
sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location('catalogue_preflight_test', ROOT/'scripts/sw_cam_chamfer_catalogue_preflight.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.fixture
def case(tmp_path):
    geo = dict(native_id=11, volume_type=2, subtype_raw=0, shape_raw=2, suppressed=False,
        name='Existing circle', axis_native=[0., 0., -1.], depth_native=.2,
        bounds_native=[4., 4., .2], start_native=[0., 0., 6.])
    tool = dict(native_id=21, is_mill_tool=True, native_read_complete=True,
        units_verified=False, holder_geometry_verified=False, tool_type_raw=1,
        cut_diameter_native=2., protrusion_native=10.)
    anchor = dict(setup_index=0, setup_native_id=61, operation_index=1,
        native_id=13, mill_operation_type=1, base_operation_type=0, suppressed=False,
        toolpath_generated=True, linked_feature_ids=[12], toolpath_record_counts=[9], assigned_tool=tool)
    first = dict(anchor, native_id=14, operation_index=0)
    saved = dict(geo, taper_enabled=True, taper_angle_readback=45.,
        top_curves_native=[dict(radius_native=2.)], bottom_curves_native=[dict(radius_native=1.8)])
    state = dict(document=dict(needs_save=False), features=[dict(setup_index=0, feature_index=1,
        setup_native_id=51, geometry=geo)], operations=[first, anchor],
        operation_setups=[dict(index=0, native_id=61, operation_count=2)])
    source=tmp_path/'part.sldprt';source.write_bytes(b'saved part')
    authority=tmp_path/'saved.json';authority.write_text('{}')
    save=tmp_path/'sw_cam_ud14_save.py';save.write_text('# completed writer')
    loaded=dict(state=state, cone_feature_native_id=11, cone_observation=dict(feature=saved),
        pins=[m.exports._pin(save),m.exports._pin(authority)], parent_pin=m.exports._pin(authority),
        current_context_sha256='a'*64, offline_export_proof_pins=[], bootstrap_export_pins=[])
    params=dict(process_id=123,expected_document_path=str(source),
        expected_source_sha256=m._file_hash(source),checkpoint_receipt_path=str(authority),
        checkpoint_receipt_sha256=m._file_hash(authority),module_sha256=m._file_hash(m.__file__),
        addin_clsid='{11111111-2222-3333-4444-555555555555}',feature_native_id=11,
        anchor_operation_native_id=13,receipt_path=str(tmp_path/'out.json'))
    binding=m.expected_binding(loaded,params)
    return SimpleNamespace(loaded=loaded,params=params,binding=binding,save=save,source=source)


def request(c):return dict(action='inspect_chamfer_catalogue',params=deepcopy(c.params))


@pytest.mark.parametrize('raw',[None,True,7,[],[''],['a','a'],['a']*33,['a\0b'],['x',2]])
def test_invalid_catalogue_never_looks_up(raw):
    calls=[]
    with pytest.raises(ValueError):m.decode_catalogue(raw,lambda name:calls.append(name))
    assert not calls


@pytest.mark.parametrize('value',[True,False,None,0,-1,2**31,1.0,'1'])
def test_catalogue_id_requires_positive_strict_long(value):
    with pytest.raises(ValueError):m.decode_catalogue(' exact ',lambda name:value)


def test_catalogue_preserves_name_and_does_not_choose():
    seen=[]
    r=m.decode_catalogue((' A ', 'B'),lambda name:seen.append(name) or len(seen))
    assert seen==[' A ','B']
    assert r['entries']==[dict(name=' A ',default_operation_id=1),dict(name='B',default_operation_id=2)]
    assert r['operation_type']==1 and not r['selection_performed']
    assert r['selected_default_operation_id'] is None and not r['unique_default_available']


@pytest.mark.parametrize('field,value',[
    ('feature_native_id',True),('anchor_operation_native_id',0),('process_id',False),
    ('module_sha256','0'*64),('expected_source_sha256','short'),('addin_clsid','bad')])
def test_invalid_request(case,field,value):
    q=request(case);q['params'][field]=value
    with pytest.raises(ValueError):m.validate_request(q)


def test_request_cannot_request_write(case):
    for action in ('create','generate','save'):
        q=request(case);q['action']=action
        with pytest.raises(ValueError):m.validate_request(q)
    q=request(case);q['params']['setter']='SetChamferLength'
    with pytest.raises(ValueError):m.validate_request(q)


@pytest.mark.parametrize('change',[
    lambda c:c.params.update(feature_native_id=12),
    lambda c:c.params.update(anchor_operation_native_id=14),
    lambda c:c.loaded['state']['document'].update(needs_save=True),
    lambda c:c.loaded['cone_observation']['feature'].update(taper_enabled=False),
    lambda c:c.loaded['cone_observation']['feature'].update(depth_native=.3),
    lambda c:c.loaded['state']['operations'][-1].update(mill_operation_type=9),
])
def test_wrong_checkpoint_binding(case,change):
    change(case)
    with pytest.raises(ValueError):m.expected_binding(case.loaded,case.params)


class Protocol:
    def __init__(self,case):
        self.expected=deepcopy(case.binding)
        self.calls=[];self.fail=None;self.drift=None
    def call(self,name):
        self.calls.append(name)
        if self.fail==name:raise RuntimeError(name)
    def start(self):self.call('start')
    def observe(self):
        self.call('observe')
        r={k:deepcopy(v) for k,v in self.expected.items() if not k.startswith('saved_contours')}
        if self.drift and self.calls.count('observe')==2:self.drift(r)
        return r
    def catalogue(self):
        self.call('catalogue')
        return m.decode_catalogue('Exact default',lambda name:5)
    def finish(self):self.call('finish')
    def close(self):self.call('close')


def test_bounded_success_reuses_contours(case):
    backend=Protocol(case);report=dict(phase='prepared');seen=[]
    result=m.run_backend(backend,case.binding,report,lambda:seen.append(deepcopy(report)))
    assert result['readback_verified'] and result['saved_contours_reused']
    assert result['full_capture_count']==result['contour_native_reads']==0
    assert backend.calls==['start','observe','catalogue','observe','finish','close']
    assert result['ready_for_mutation'] is False


@pytest.mark.parametrize('failure',['start','observe','catalogue','finish','close'])
def test_failure_never_replays(case,failure):
    b=Protocol(case);b.fail=failure;r=dict(phase='prepared')
    m.run_backend(b,case.binding,r,lambda:None)
    assert not r['readback_verified']
    assert b.calls.count('catalogue')<=1
    assert b.calls.count('close')==1


@pytest.mark.parametrize('change',[
    lambda r:r['feature']['geometry'].update(depth_native=.3),
    lambda r:r['anchor']['toolpath_record_counts'].append(10),
    lambda r:r['order'].reverse(),
    lambda r:r.update(taper_enabled=1),
])
def test_after_read_state_drift_blocks_acceptance(case,change):
    b=Protocol(case);b.drift=change;r=dict(phase='prepared')
    m.run_backend(b,case.binding,r,lambda:None)
    assert not r['readback_verified'] and b.calls.count('catalogue')==1


def test_prepare_retires_only_completed_save_code(case,monkeypatch):
    monkeypatch.setattr(m.checkpoint,'load_completed',lambda *a,**kw:deepcopy(case.loaded))
    monkeypatch.setattr(m.exports,'_local_receipt',lambda path:None)
    loaded,binding,report=m.prepare(case.params)
    assert loaded['preflight_retired_pins']==[m.exports._pin(case.save)]
    assert m.exports._pin(m.__file__) in loaded['pins']
    assert report['native_mutation_calls']==0 and report['read_only']
    assert binding['saved_contours']==case.loaded['cone_observation']['feature']


def test_changed_retired_proof_rejected_before_connection(case,monkeypatch):
    monkeypatch.setattr(m.checkpoint,'load_completed',lambda *a,**kw:deepcopy(case.loaded))
    case.save.write_text('# changed completed writer')
    with pytest.raises(ValueError):m.prepare(case.params)


def test_receipt_replay_rejected(case,monkeypatch):
    monkeypatch.setattr(m.checkpoint,'load_completed',lambda *a,**kw:deepcopy(case.loaded))
    monkeypatch.setattr(m.exports,'_local_receipt',lambda path:None)
    Path(case.params['receipt_path']).write_text('{}')
    with pytest.raises(ValueError):m.prepare(case.params)


class Node:
    def __init__(self,native_id=0,**values):self.id=native_id;self.values=values


class Guard:
    def __init__(self):self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def typed(self,obj,name):return (obj,name)
    def read(self,obj,name,*args):
        interface=''
        if isinstance(obj,tuple):obj,interface=obj
        self.calls.append((name,args))
        if name=='GetCWObjectID':
            item=args[0][0] if isinstance(args[0],tuple) else args[0]
            return item.id,True
        if name=='Count':return len(obj)
        if name=='Item':return obj[args[0]]
        if name=='OpernType' and interface=='ICWMillOperation':return obj.values['mill_type']
        value=obj.values[name]
        return value(*args) if callable(value) else value


def native_backend(c):
    geo=c.binding['feature']['geometry'];a=c.binding['anchor']
    owner=Node(51)
    feature=Node(11,VolumeType=2,SubType=0,Shape=2,Suppressed=False,FeatureName=geo['name'],
        Axis=geo['axis_native'],Depth=.2,GetBoundParams=geo['bounds_native'],
        GetStartPosition=geo['start_native'],GetOwner=owner,Taper=True,IGetTaperAngle=45.,
        IGetAllDefaultOperations=lambda kind:[' Exact '],
        GetTdbIdForDefaultOperation=lambda kind,name:7)
    tool=Node(21,IsMillTool=True,ToolType=1,CutDiameter=2.,Protrusion=10.)
    anchor=Node(13,mill_type=1,OpernType=0,Suppressed=False,GetIsToolpathGenerated=True,
        IGetAllFeatures=[Node(12)],IGetEnumToolpaths=[Node(RecordCount=9)],IGetTool=tool)
    setup=Node(61,IGetEnumOperations=[Node(14),anchor])
    machine=Node(MachType=1,IGetEnumOpSetups=[setup])
    doc=Node(GetDocType=1,IGetMachine=machine,GetCWObjectFromID=lambda kind,n:(feature,True))
    app=Node(IGetActiveDoc=doc);g=Guard()
    b=m.NativeBackend.__new__(m.NativeBackend)
    b.args=c.params;b.loaded=c.loaded;b.report=dict(native_read_calls=[]);b.reads=0
    b.persist=lambda:None;b.boundary=lambda:None;b.ctx=SimpleNamespace(app=app,guard=lambda:g);b.native=None
    return b,g,feature,anchor


def test_real_reader_uses_exact_catalogue_namespace_and_saved_binding(case):
    b,g,feature,anchor=native_backend(case)
    before=b.observe();m.verify_binding(case.binding,before)
    r=b.catalogue();after=b.observe();m.verify_binding(case.binding,after)
    assert r['entries']==[dict(name=' Exact ',default_operation_id=7)]
    assert ('IGetAllDefaultOperations',(1,)) in g.calls
    assert ('GetTdbIdForDefaultOperation',(1,' Exact ')) in g.calls
    assert b.reads<128
    assert not any(name.startswith('Set') or name in ('InsertOperation','GenerateToolpath','SaveActiveDocument',
        'IGetTopSegChain','IGetBottomSegChain') for name,_ in g.calls)


@pytest.mark.parametrize('method',['SetTool','InsertOperation','GenerateToolpath','SaveActiveDocument','IGetTopSegChain'])
def test_native_reader_rejects_unscoped_calls(case,method):
    b,g,_,_=native_backend(case)
    with pytest.raises(ValueError):b.read(g,Node(),method)
    assert not g.calls


def test_native_reader_budget_fails_before_getter(case):
    b,g,_,_=native_backend(case);b.reads=m.MAX_READS
    with pytest.raises(ValueError):b.read(g,Node(),'GetDocType')
    assert not g.calls


def test_invalid_native_default_id_is_preserved_without_retry(case):
    b,g,feature,anchor=native_backend(case)
    feature.values['GetTdbIdForDefaultOperation']=lambda kind,name:-1
    b.observe()
    with pytest.raises(ValueError):b.catalogue()
    assert b.report['catalogue_observation']['lookups']==[dict(name=' Exact ',python_type='int',value=-1)]
    assert sum(name=='GetTdbIdForDefaultOperation' for name,_ in g.calls)==1
