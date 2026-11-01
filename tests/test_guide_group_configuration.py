"""Group configuration protocol tests using synthetic parameter shapes; no CAD calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
spec=importlib.util.spec_from_file_location('guide_configuration_test',ROOT/'scripts/sw_cam_guide_group_configuration.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
F=json.loads((Path(__file__).parent/'guide_configuration_shapes.json').read_text(encoding='utf-8'))


def update(row,spec,value):
    key=spec[0]
    if 'rough' in row:
        area={'entry_type':'entry','spiral_radius':'entry','spiral_pitch':'entry','first_depth':'depth','subsequent_depth':'depth'}.get(key,'boundary')
        row['rough'][area][spec[2]]['raw']=deepcopy(value)
        if key=='entry_type':row['startpoints']['entry_type']=value
    elif key in row['finish_fields']:row['finish_fields'][key]=deepcopy(value)
    elif key=='gouge_check':row['protected_finish']['gouge_check']=value
    elif key in ('lead_in_type','lead_out_type'):row['protected_finish']['lead_types'][0 if key=='lead_in_type' else 1]=value
    else:row['finish']['BottomFinOpt']['raw']=value


class Fake:
    def __init__(self,failure=None):
        self.state=deepcopy(F['initial']);self.trace=[];self.failure=failure
    def start(self):self.trace.append('start')
    def capture_parameters(self,label):
        self.trace.append('capture:'+label)
        if self.failure==label:raise ValueError('read failed')
        out=deepcopy(self.state)
        if self.failure=='saved_delta' and label=='saved':out['binding']['operations'][0]['name']='changed'
        self.report.setdefault('captures',[]).append(dict(label=label,**deepcopy(out)))
        return out
    def assign(self,row,pending):
        pending();oid=row['operation_native_id'];self.trace.append(('tool',oid))
        if self.failure=='settool_return':return -1
        op=next(x for x in self.state['binding']['operations']if x['native_id']==oid);op['assigned_tool']=deepcopy(F['wanted'])
        selected=next(x for x in self.state['parameters']if x['operation_native_id']==oid);selected['tool']['generic']=deepcopy(F['wanted'])
        # Native auto-default changes are allowed only for this selected operation.
        if self.failure=='auto_defaults' and 'rough'in selected:selected['rough']['entry']['GetSpiralRadius']['raw']=.2
        if self.failure=='foreign_defaults':self.state['parameters'][-1]['finish_fields']['perimeter']=3
        if self.failure=='nc':selected['nc']['unexpected']=1
        return 0
    def refresh_dirty(self):self.trace.append('dirty')
    def field(self,row,spec):
        if self.failure=='field_read':raise ValueError('field failed')
        return deepcopy(m.field_value(next(x for x in self.state['parameters']if x['operation_native_id']==row['operation_native_id']),spec))
    def set_field(self,row,spec,value,pending):
        pending();self.trace.append(('field',row['operation_native_id'],spec[0]))
        if self.failure=='field_return':return -1
        selected=next(x for x in self.state['parameters']if x['operation_native_id']==row['operation_native_id'])
        update(selected,spec,value)
        if self.failure=='unselected_field':selected['levels']['levels']['minimum_extra']=9
        return 0
    def boundary(self):self.trace.append('guard')
    def save(self):self.trace.append('save');return -1 if self.failure=='save_return' else 0
    def saved_hash(self,r):
        self.trace.append('hash');self.report['source_transition']={'document':{'path':'synthetic.SLDPRT','type':1,'title':'synthetic.SLDPRT','needs_save':False}}
        return 'b'*64
    def finish(self):self.trace.append('finish')
    def close(self):self.trace.append('close')


def setup(tmp_path,failure=None):
    report=dict(scope=m.SCOPE,source_path='synthetic.SLDPRT',source_sha256='a'*64,recipe_sha256='c'*64,
        request={'process_id':52},ownership={'process_id':52})
    journal=m.ConfigurationJournal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    loaded=dict(configuration_recipe=deepcopy(F['recipe']),configuration_initial=deepcopy(F['initial']),configuration_tool=deepcopy(F['wanted']),guide_parameters={'configuration':{'synthetic':True}},
        configuration_pins=[{'path':'synthetic.json','sha256':'d'*64}])
    backend=Fake(failure);backend.report=report
    return backend,journal,loaded


@pytest.mark.parametrize('failure',[None,'auto_defaults','nc'])
def test_four_tools_then_fields_then_one_save(tmp_path,failure):
    b,j,l=setup(tmp_path,failure);r=m.run_backend(b,j,l)
    assert r['status']=='saved_configuration_no_toolpath',r.get('issue')
    assert r['model_saved'] and r['readback_verified'] and not r['GTP_attempted']
    assert r['continuation_ready'] and r['saved_checkpoint_context']['source_sha256']=='b'*64
    assert r['saved_checkpoint_context']['snapshot_sha256']==m.group._digest(r['saved'])
    assert not r['saved_checkpoint_context']['persistence_after_reopen_verified']
    assert b.trace.count('save')==1 and len([x for x in b.trace if isinstance(x,tuple)and x[0]=='tool'])==4
    last_tool=max(i for i,x in enumerate(b.trace)if isinstance(x,tuple)and x[0]=='tool')
    first_field=min(i for i,x in enumerate(b.trace)if isinstance(x,tuple)and x[0]=='field')
    assert last_tool<first_field
    assert r['actions']['322:floor_allowance']['attempted'] is False


@pytest.mark.parametrize('failure',['settool_return','foreign_defaults','field_read','field_return','unselected_field','configured','save_return','saved_delta'])
def test_failure_stops_without_replay(tmp_path,failure):
    b,j,l=setup(tmp_path,failure);r=m.run_backend(b,j,l)
    assert r['status']=='uncertain' and not r['readback_verified']
    assert r['model_saved'] is (failure=='saved_delta')
    assert b.trace.count('save')<=1
    if failure in ('settool_return','foreign_defaults'):
        assert len([x for x in b.trace if isinstance(x,tuple)and x[0]=='tool'])==1
    if failure not in ('save_return','saved_delta'):assert 'save'not in b.trace
    assert b.trace[-1]=='close'


def test_reenter_preserves_original_forensic_bytes(tmp_path):
    b,j,l=setup(tmp_path,'field_return');m.run_backend(b,j,l)
    before=(j.receipt.read_bytes(),j.marker.read_bytes())
    with pytest.raises(ValueError):m.run_backend(b,j,l)
    assert before==(j.receipt.read_bytes(),j.marker.read_bytes())


def test_marker_write_failure_prevents_native_call(tmp_path,monkeypatch):
    b,j,l=setup(tmp_path);original=m.group._write_receipt
    def write(path,*args,**kwargs):
        if Path(path)==j.marker:raise OSError('disk')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(m.group,'_write_receipt',write)
    r=m.run_backend(b,j,l)
    assert not any(isinstance(x,tuple)for x in b.trace) and not r['readback_verified']


def test_real_parameter_constructor_chain(tmp_path):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'part')
    pin=tmp_path/'dependency.py';pin.write_bytes(b'pass')
    identity=dict(path=str(source),title=source.name,type=1,needs_save=True)
    class Trap:
        def __getattr__(self,name):raise AssertionError('Native access: '+name)
    state={};progress=lambda:None
    backend=SimpleNamespace(sw=Trap(),typelib_path=str(tmp_path/'camworks.tlb'),
        loaded={'generated_pin':{'path':str(pin),'sha256':m._file_hash(pin)},'pins':[{'path':str(pin),'sha256':m._file_hash(pin)}]},
        args={'process_id':52},ctx=SimpleNamespace(args={'expected_source_sha256':m._file_hash(source)},
        identity=lambda:identity,files=lambda:None,owned=lambda:None),events=lambda:None)
    batch=m.NativeBackend.batch(backend,Trap(),progress,state,lambda:None)
    assert isinstance(batch,m.reader.ParameterReadBatch) and batch.progress is progress and batch.progress_state is state
    assert not batch._entered and batch._read_calls==batch._qi_calls==0


def test_actual_shapes_map_every_selected_field():
    for row,target in zip(F['initial']['parameters'],F['recipe']['rows']):
        for spec in m.ROUGH_FIELDS if target['operation_type']==0 else m.FINISH_FIELDS:
            assert m.field_value(row,spec) is not None
    assert m.validate_recipe(F['recipe'],{'targets':F['targets']})==F['recipe']


@pytest.mark.parametrize('change',['tool','id','missing','nan','bool_depth'])
def test_recipe_rejects_unqualified_or_ambiguous_values(change):
    recipe=deepcopy(F['recipe'])
    if change=='tool':recipe['tool_native_id']=252
    if change=='id':recipe['rows'][0]['operation_native_id']=143
    if change=='missing':recipe['rows'][0]['fields'].pop('side_step')
    if change=='nan':recipe['rows'][0]['fields']['spiral_radius']=float('nan')
    if change=='bool_depth':recipe['rows'][0]['fields']['first_depth']=[False,True]
    with pytest.raises(ValueError):m.validate_recipe(recipe,{'targets':F['targets']})


def test_protected_projection_keeps_unselected_machining_values():
    before=deepcopy(F['initial']['parameters'][0]);after=deepcopy(before)
    update(after,m.ROUGH_FIELDS[0],4)
    assert m.protected_parameters(before)==m.protected_parameters(after)
    after['rough']['depth']['FinCutAmt']['raw']=.5
    assert m.protected_parameters(before)!=m.protected_parameters(after)


def test_exact_extra_rough_abi_without_cad():
    runtime=RUNTIME
    generated=runtime/'.venv/Lib/site-packages/comtypes/gen/_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0.py'
    tlb=Path('D:/Program Files/SOLIDWORKS Corp/SOLIDWORKS CAM/camworks.tlb')
    if not generated.is_file()or not tlb.is_file():pytest.skip('installed vendor type library unavailable')
    out=m.audit(str(tlb),{'path':str(generated),'sha256':m._file_hash(generated)})
    assert [x['member']for x in out['extra']]==['_get_SideAllow','_set_SideAllow','GetStepOver','SetStepover','GetZAllowance','SetZAllowance']


def test_native_assignment_adapter_exact_factory_and_signature(monkeypatch):
    from contextlib import contextmanager
    trace=[];doc=object();part=object();machine=object();crib=object();tool=object();dispatch=object()
    class Mill:
        def SetTool(self,value):
            assert value is dispatch;trace.append('SetTool');return 0
    mill=Mill()
    class Guard:
        def typed(self,obj,name):trace.append(('QI',name));return obj
        def read(self,obj,name,*args):
            trace.append(name)
            if obj is doc and name=='IGetMachine':return machine
            if obj is machine and name=='IGetToolcrib':return crib
            if obj is crib and name=='GetAllTools':return [tool]
            if obj is tool and name=='ToolType':return F['wanted']['tool_type_raw']
            if obj is tool and name=='CutDiameter':return 2.
            if obj is tool and name=='Protrusion':return F['wanted']['protrusion_native']
            if obj is tool and name=='QueryInterface':return dispatch
            raise AssertionError((obj,name,args))
        def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
    @contextmanager
    def guarded():yield Guard()
    monkeypatch.setattr(m,'_items',lambda value,*args:value)
    monkeypatch.setattr(m,'_object_id',lambda d,o,r:273 if o is tool else -1)
    b=SimpleNamespace(doc=doc,ctx=SimpleNamespace(guard=guarded),
        loaded={'configuration_tool':F['wanted'],'neck_tool_checkpoint':{'catalogue':[{'native_id':273}]}},
        target=lambda g,row:(mill,object()))
    assert m.NativeBackend.assign(b,F['targets'][0],lambda:trace.append('pending'))==0
    assert 'IGetToolcrib'in trace and ('QI','ICWToolcrib4')in trace
    assert trace.index('pending')<trace.index('SetTool') and trace.count('SetTool')==1


def test_save_fact_requires_successful_hash_transition(tmp_path):
    b,j,l=setup(tmp_path)
    def failed_hash(report):raise ValueError('not clean or hash missing')
    b.saved_hash=failed_hash
    r=m.run_backend(b,j,l)
    assert r['status']=='uncertain' and not r['model_saved'] and not r['readback_verified']
    assert b.trace.count('save')==1 and not r['persistence_after_reopen_verified']


def test_automatic_entry_alias_can_change_but_startpoint_list_cannot():
    old=deepcopy(F['initial']['parameters'][0]);new=deepcopy(old)
    new['startpoints']['entry_type']=4
    m.verify_automatic_target(old,new)
    new['startpoints']['rows']=[{'position_native':[1.,2.,3.]}]
    with pytest.raises(ValueError):m.verify_automatic_target(old,new)


def test_automatic_tool_update_cannot_change_levels():
    old=deepcopy(F['initial']['parameters'][0]);new=deepcopy(old)
    new['levels']['levels']['machining_depth_native']=2.
    with pytest.raises(ValueError):m.verify_automatic_target(old,new)


def test_compact_capture_reference_keeps_full_snapshot_once_and_checks_digest():
    snapshot=deepcopy(F['initial']);report={'captures':[dict(label='after_tool_322',**snapshot)]}
    ref=m.capture_reference(report,'after_tool_322',snapshot,322)
    assert set(ref)=={'capture_index','capture_label','snapshot_sha256','operation_native_id'}
    assert m.resolve_capture_reference(report,ref)==snapshot
    report['captures'][0]['parameters'][0]['rough']['boundary']['SideAllow']['raw']=.9
    with pytest.raises(ValueError):m.resolve_capture_reference(report,ref)


@pytest.mark.parametrize('mutation',['index','label','operation','missing'])
def test_compact_capture_reference_rejects_rebinding(mutation):
    snapshot=deepcopy(F['initial']);report={'captures':[dict(label='after_tool_322',**snapshot)]}
    ref=m.capture_reference(report,'after_tool_322',snapshot,322)
    if mutation=='index':ref['capture_index']=True
    if mutation=='label':ref['capture_label']='foreign'
    if mutation=='operation':ref['operation_native_id']=99999
    if mutation=='missing':report['captures']=[]
    with pytest.raises(ValueError):m.resolve_capture_reference(report,ref)


def constructed_native_backend(tmp_path):
    document={'path':str(tmp_path/'synthetic.SLDPRT'),'title':'synthetic.SLDPRT','type':1,'needs_save':True}
    loaded={'state':{'document':document,'operations':[{'native_id':248,'assigned_tool':{'native_id':249}}]},
        'ids':{},'guide_parameters':{'document':document}}
    args={'process_id':52,'expected_document_path':document['path'],'expected_source_sha256':'a'*64}
    class Trap:
        def __getattr__(self,name):raise AssertionError('Unexpected native access: '+name)
    return m.NativeBackend(loaded,args,Trap(),'synthetic-clsid',str(tmp_path/'vendor.tlb'),{},lambda:None)


def test_real_constructed_backend_does_not_shadow_capture_method(tmp_path):
    import types
    backend=constructed_native_backend(tmp_path)
    assert isinstance(backend.capture,types.ModuleType)
    assert backend.capture_parameters.__self__ is backend
    assert backend.capture_parameters.__func__ is m.NativeBackend.capture_parameters
    collisions=[name for name in vars(backend) if callable(getattr(type(backend),name,None))]
    assert collisions==[]
    class Entered(Exception):pass
    def boundary():raise Entered('real capture method entered')
    backend.boundary=boundary
    with pytest.raises(Entered,match='real capture method entered'):
        backend.capture_parameters('preflight_probe')


def test_real_start_invokes_inherited_capture_module_bootstrap(tmp_path,monkeypatch):
    backend=constructed_native_backend(tmp_path);called=[]
    backend.ctx.files=lambda:called.append('files')
    backend.ctx.identity=lambda:called.append('identity')
    class Entered(Exception):pass
    def bootstrap(*args):called.append('bootstrap');raise Entered('native bootstrap boundary')
    monkeypatch.setattr(backend.capture.cone,'_bootstrap',bootstrap)
    with pytest.raises(Entered,match='native bootstrap boundary'):backend.start()
    assert called==['files','identity','bootstrap']
    assert backend.session is None and backend.session_active is False


@pytest.mark.parametrize('failed',[False,True])
def test_prewrite_failure_refreshes_cleanup_summary(tmp_path,failed):
    b,j,l=setup(tmp_path,'before');b.session=object();b.session_active=True
    def close():b.trace.append('close');b.session_active=False
    def events(active):
        assert active is False
        j.report['messages']={'active':failed,'subscribed':True,'disconnected':not failed,
            'disconnect_errors':[{'type':'SyntheticDisconnectError'}] if failed else []}
        if failed:raise ValueError('disconnect failed')
    b.close=close;b.events=events
    r=m.run_backend(b,j,l)
    assert r['mutation_attempted'] is False and r['actions']=={} and not r['readback_verified']
    assert r['messages']['active'] is failed and r['messages']['disconnected'] is not failed
    assert ('cleanup_issue'in r) is failed and not r['continuation_ready']
    if not failed:assert r['cleanup_session_active'] is False


def test_actual_capture_method_happy_path_with_native_transport_stub(tmp_path,monkeypatch):
    from contextlib import contextmanager
    backend=constructed_native_backend(tmp_path);calls=[];doc=object();app=object()
    expected=deepcopy(F['initial']);targets=deepcopy(F['targets'])
    backend.loaded.update(pins=[],configuration_pins=[],guide_parameters={'configuration':{'bound':True},'targets':targets})
    backend.args.update(progress_path=str(tmp_path/'progress.json'),receipt_path=str(tmp_path/'receipt.json'))
    backend.ctx.app=app;backend.boundary=lambda:calls.append('boundary')
    backend.configuration=lambda value:{'bound':True}
    class Guard:
        def typed(self,value,name):return value
        def read(self,value,name):
            assert value is app and name=='IGetActiveDoc';return doc
    @contextmanager
    def guard():yield Guard()
    backend.ctx.guard=guard
    class Batch:
        read=typed=object()
        def __enter__(self):calls.append('batch_enter');return self
        def __exit__(self,*args):calls.append('batch_exit')
        def require_complete(self):calls.append('complete')
        def summary(self):return {'read_scope_complete':True}
    backend.batch=lambda *args:Batch()
    class Progress:
        def __init__(self,**kwargs):assert kwargs['progress_path'].endswith('.probe.json')
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):pass
        def complete(self):calls.append('progress_complete')
    monkeypatch.setattr(m.reader.pocket.journal,'ReadProgressJournal',Progress)
    def binding(*args,**kwargs):calls.append('binding');return deepcopy(expected['binding']),{}
    def parameters(d,handles,rows,batch,report,persist):
        assert d is doc and [r['operation_native_id']for r in rows]==[r['operation_native_id']for r in targets]
        report['parameters']=deepcopy(expected['parameters']);calls.append('parameters')
    monkeypatch.setattr(m.definitions,'read_current_binding',binding)
    monkeypatch.setattr(m.reader,'read_parameters',parameters)
    assert backend.capture_parameters('probe')==expected
    assert backend.report['captures'][0]['label']=='probe'
    assert backend.report['captures'][0]['read_batch']['read_scope_complete'] is True
    assert calls==['boundary','batch_enter','binding','parameters','binding','batch_exit','complete','progress_complete']
