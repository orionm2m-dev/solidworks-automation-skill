import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1])))
spec=importlib.util.spec_from_file_location('guide_parameters',ROOT/'scripts/sw_cam_guide_group_parameters.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def completed():
    old=[dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=i,
        mill_operation_type=1,base_operation_type=9,suppressed=False,toolpath_generated=True,
        toolpath_record_counts=[40+i],linked_feature_ids=[79],
        assigned_tool=dict(native_id=273,native_read_complete=True))
        for i,oid in enumerate(m.guide.ORDER)]
    baseline=dict(features={'82':{'native_id':82},'83':{'native_id':83}},
        operations=old,operation_setups=[dict(index=0,native_id=93,operation_count=9)])
    rows=[dict(key=key,feature_native_id=fid,operation_type=kind,operation_setup_native_id=93)
        for key,fid,kind in m.definitions.ROWS]
    config=dict(sw_configuration_name='Default',cam_active_configuration_name='Mill - Metric - 0',
        cam_configuration_name='Mill - Metric - 0',cam_sw_configuration_name='Default',
        binding_verified=True)
    r=dict(scope=m.definitions.SCOPE,status='observed',phase='finished',readback_verified=True,
        plan=dict(rows=rows,baseline=deepcopy(baseline),configuration=config),
        before=deepcopy(baseline),actual_new_ids=[901,902,903,904],actions={},
        captures=[dict(label='before',binding=deepcopy(baseline))],
        current_document=dict(path='C:/model.SLDPRT',title='model.SLDPRT',type=1,needs_save=True))
    for k in ('save_attempted','model_saved','GTP_attempted','tool_assignment_attempted',
        'parameter_setter_attempted','automatic_retry','native_dispatch_pending'):r[k]=False
    for row,oid in zip(rows,r['actual_new_ids']):
        current=deepcopy(baseline);current['operation_setups'][0]['operation_count']+=1
        target=dict(old[0],native_id=oid,operation_index=len(current['operations']),
            mill_operation_type=row['operation_type'],toolpath_generated=False,toolpath_record_counts=[],
            linked_feature_ids=[row['feature_native_id']])
        current['operations'].append(target);nc=dict(read_complete=True,spindle_speed_native=1000.,xy_feed_native=100.)
        r['actions'][row['key']]=dict(status='verified',attempted=True,returned=True,readback_verified=True,
            native_dispatch_pending=False,actual_native_id=oid,observed=dict(operation=deepcopy(target),nc=deepcopy(nc)))
        r['captures'].append(dict(label='after_'+row['key'],new_operation_native_id=oid,binding=deepcopy(current),nc=nc))
        baseline=current
    r['after']=deepcopy(baseline)
    return r


def test_successful_receipt_selects_returned_ids_not_guessed_ids(completed,monkeypatch):
    monkeypatch.setattr(m,'clean_events',lambda r:None)
    monkeypatch.setattr(m.guide.configuration_binding,'require_binding',lambda r:None)
    out=m.completed_definitions(completed)
    assert [v['operation_native_id'] for v in out['targets']]==[901,902,903,904]
    assert out['document']['needs_save'] is True and len(out['baseline']['operations'])==13


@pytest.mark.parametrize('kind',['partial','pending','nc','order','protected','duplicate','save','issue','capture'])
def test_incomplete_or_changed_definition_receipt_rejected(completed,monkeypatch,kind):
    monkeypatch.setattr(m,'clean_events',lambda r:None)
    monkeypatch.setattr(m.guide.configuration_binding,'require_binding',lambda r:None)
    if kind=='partial':completed['status']='uncertain'
    if kind=='pending':completed['native_dispatch_pending']=True
    if kind=='nc':completed['captures'][2]['nc']['read_complete']=False
    if kind=='order':completed['plan']['rows'][0]['operation_type']=1
    if kind=='protected':completed['captures'][2]['binding']['operations'][0]['toolpath_record_counts']=[999]
    if kind=='duplicate':completed['actual_new_ids'][2]=901
    if kind=='save':completed['save_attempted']=True
    if kind=='issue':completed['issue']={}
    if kind=='capture':completed['captures'].pop()
    with pytest.raises(ValueError):m.completed_definitions(completed)


def test_real_constructor_chain_receives_progress_and_state(tmp_path):
    # Actual constructor chain down through ScopedCamDispatchGuard; no __enter__,
    # application handle, COM getter or monkeypatched constructor is used.
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'part')
    pin=tmp_path/'dependency.py';pin.write_bytes(b'pass')
    identity=dict(path=str(source),title=source.name,type=1,needs_save=True)
    progress=lambda:None;state={};events=lambda:None
    backend=SimpleNamespace(sw=object(),typelib_path=str(tmp_path/'camworks.tlb'),
        loaded={'generated_pin':{'path':str(pin),'sha256':m._file_hash(pin)},
                'pins':[{'path':str(pin),'sha256':m._file_hash(pin)}]},
        args={'process_id':52,'expected_source_sha256':m._file_hash(source)},
        ctx=SimpleNamespace(identity=lambda:identity,files=lambda:None,owned=lambda:None),events=events)
    b=m.make_batch(backend,object(),progress,state,lambda:None)
    assert isinstance(b,m.ParameterReadBatch) and b.progress is progress and b.progress_state is state
    assert b._budget==1900 and not b._entered and b._read_calls==b._qi_calls==0


def test_parameter_whitelist_rejects_mutation_before_native_call():
    b=object.__new__(m.ParameterReadBatch);b._known_objects=set();b._invalid=False
    with pytest.raises(ValueError):b.read(object(),'InsertOperation',0,79)
    assert b._invalid


def test_fixed_helpers_shared_tool_read_once_and_stop_on_error(monkeypatch):
    calls=[];doc=object();setup=object();feature=object();ops={i:object() for i in (901,902,903,904)}
    generic=dict(native_id=273,native_read_complete=True);tool=object()
    class Batch:
        def read(self,obj,name,*args):
            if name=='GetCWObjectFromID':return (feature,True)
            return setup
        def typed(self,obj,name):return obj
        def feature_dispatch(self,obj):return obj
        def metadata(self,obj):return {}
        def plane(self,*args):return {}
    batch=Batch()
    monkeypatch.setattr(m,'_items',lambda *a:[setup])
    monkeypatch.setattr(m,'_object_id',lambda d,o,r:93 if o is setup else active[0])
    monkeypatch.setattr(m,'read_generic_tool',lambda *a:(generic,tool))
    monkeypatch.setattr(m,'read_tool_dimensions',lambda *a:(calls.append('tool') or {'generic':deepcopy(generic)}))
    def hook(label):
        def run(*a,**kw):calls.append(label);return {'ok':True}
        return run
    monkeypatch.setattr(m.pocket,'read_levels',hook('levels'))
    monkeypatch.setattr(m.pocket.rough,'read_rough_entry_parameters',hook('rough'))
    monkeypatch.setattr(m.guide.start,'read_startpoints',hook('start'))
    monkeypatch.setattr(m.pocket,'read_finish_parameters',hook('finish'))
    monkeypatch.setattr(m.fields,'read_cached_fields',hook('20fields'))
    monkeypatch.setattr(m.protected,'read_protected',hook('protected'))
    monkeypatch.setattr(m.pocket.leads,'read_lead_details',hook('leads'))
    monkeypatch.setattr(m.pocket,'read_nc_settings',hook('nc'))
    targets=[dict(operation_native_id=i,feature_native_id=fid,operation_type=kind,assigned_tool=generic)
        for i,(_,fid,kind) in zip(ops,m.definitions.ROWS)]
    # Advance exact resolved feature ID using the selected target phase.
    report={};active=[82]
    def persist():
        if 'phase' in report:active[0]=82 if int(report['phase'].rsplit('_',1)[1])<903 else 83
    m.read_parameters(doc,ops,targets,batch,report,persist)
    assert calls.count('tool')==1 and report['unique_tool_dimension_reads']==1
    assert calls.count('rough')==calls.count('finish')==calls.count('20fields')==2
    assert calls.count('nc')==4 and all(v['read_complete'] for v in report['parameters'])
    def fail(*args,**kwargs):raise RuntimeError('native getter failure')
    monkeypatch.setattr(m.pocket.rough,'read_rough_entry_parameters',fail)
    report={}
    with pytest.raises(RuntimeError):m.read_parameters(doc,ops,targets,batch,report,persist)
    assert len(report['parameters'])==1 and not report['parameters'][0]['read_complete']


@pytest.mark.parametrize('failure',[None,'observe','finish','close'])
def test_read_lifecycle_never_reports_complete_on_failed_boundary(failure):
    r={};trace=[]
    class Backend:
        ctx=SimpleNamespace(identity=lambda:{'path':'x','needs_save':True})
        def start(self):trace.append('start')
        def observe(self):
            trace.append('observe')
            if failure=='observe':raise ValueError('bad read')
        def finish(self):
            trace.append('finish')
            if failure=='finish':raise ValueError('event')
        def close(self):
            trace.append('close')
            if failure=='close':raise ValueError('cleanup')
    m.run_backend(Backend(),r,lambda:None)
    assert r['parameter_read_complete'] is (failure is None)
    assert r['status']==('observed' if failure is None else 'error')
    assert not r['mutation_attempted'] and not r['save_attempted'] and not r['GTP_attempted']
    assert trace.count('observe')==1 and trace[-1]=='close'

