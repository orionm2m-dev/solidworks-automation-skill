"""Bounded adapter tests: recorded R115 state/CL and one synthetic new route."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_pocket_finish_exports as m
from test_pocket_rough_exports import make_loaded as rough_loaded, NEW as PRIOR_FIVE
from scripts import sw_cam_mill_generic_cl as core
from scripts import sw_cam_events
from test_chamfer_exports import Session

FINISH=('CUTTER/ 2,0,1,0,0,0,55,\nTLAXIS/ 0,0,1\nOPFEATSTART/F144\n'
       'RAPID/\nGOTO/ 0,15,3\nFEDRAT/ MMPM,24\nGOTO/ 0,15,-18.5\nRAPID/\nGOTO/ 0,15,3\nOPFEATEND/F144\nFINI\n').encode('ascii')
BINDING=json.loads((Path(__file__).parent/'fixtures/pocket_finish_exports/observed_tool_binding.json').read_text(encoding='utf-8'))
BASE=PRIOR_FIVE
NEW=BASE[:BASE.rindex(b'FINI')]+FINISH


def make_loaded(tmp_path):
    loaded,source=rough_loaded(tmp_path)
    before=deepcopy(loaded['state'])
    tid=500;row=dict(native_id=tid,tool_type_raw=1,CutDiameter=2.,Protrusion=26.000000000000004,StnNo=19.)
    full=dict(tool_native_id=tid,tool_type_raw=1,cut_diameter_native=2.,tool_protrusion_native=26.000000000000004,
        geometry_read_complete=True,profile_complete=True)
    loaded['neck_tool_candidate']=dict(native_id=tid,full_tool=full,identity={})
    loaded['neck_tool_checkpoint']=dict(catalogue=m.cl.validate_catalogue_authority(loaded)+[row],profile_qualification={'profile_verified':True})
    loaded['state']['operations'][7].update(toolpath_generated=True,toolpath_record_counts=[6],assigned_tool=dict(deepcopy(BINDING['prior_assignment']),native_id=tid,tool_type_raw=row['tool_type_raw'],cut_diameter_native=row['CutDiameter'],protrusion_native=row['Protrusion']))
    loaded.update(authority_kind=m.AUTHORITY,generated_pocket_finish=dict(native_id=144,feature_native_id=79,tool_native_id=tid,record_counts=[6],geometry_acceptance_complete=False))
    loaded['current_context_sha256']=m._digest(m.group.current_projection(loaded))
    path=tmp_path/'prior.cl';path.write_bytes(BASE);pin=m.common._pin(path)
    marker=tmp_path/'prior-marker.json';marker.write_text('{}')
    prior=dict(scope='SAVED_ROUGH_POCKET_CL_EXPORT_V1',phase='finished',native_call_attempted=True,native_call_returned=True,
        native_dispatch_pending=False,native_hresult=0,post_cleanup_document_file_verified=True,
        before=dict(mill_state=before,expected_generated_operations=m.operation_contract(loaded)[:5]),
        output=dict(path=str(path),sha256=pin['sha256'],bytes=path.stat().st_size),saved_checkpoint_pin=loaded['parent_pin'])
    prior['after']=deepcopy(prior['before']);receipt=tmp_path/'prior-export.json';receipt.write_text(json.dumps(prior))
    archive=tmp_path/'historical_parser.py';archive.write_text('historical parser fixture')
    module=tmp_path/'recovery_module.py';module.write_text('recovery module fixture')
    parser=importlib.import_module('scripts.sw_cam_generic_cl_reader')
    recovery=dict(scope='SAVED_ROUGH_CL_OFFLINE_EXPORT_RECONCILIATION_V1',status='export_reconciled_geometry_review_pending',native_calls=0,
        original_export_receipt_pin=m.common._pin(receipt),original_export_marker_pin=m.common._pin(marker),saved_checkpoint_pin=loaded['parent_pin'],
        CL_pin=pin,parser_pin=m.common._pin(parser.__file__),recovery_module_pin=m.common._pin(module),
        historical_parser=dict(original_parser_pin=m.common._pin(archive),historical_parser_archive_pin=m.common._pin(archive)),
        expected_generated_operations=deepcopy(prior['before']['expected_generated_operations']),
        **{k:True for k in ('saved_checkpoint_readback_verified','output_verified','protected_streams_verified','parse_complete','native_count_matches')},
        **{k:False for k in ('original_receipt_rewritten','original_marker_rewritten','reexport_attempted','generation_attempted','model_saved','automatic_replay')})
    recoveryfile=tmp_path/'recovery.json';recoveryfile.write_text(json.dumps(recovery))
    loaded.update(m.protected_reference(str(recoveryfile),m._file_hash(recoveryfile),loaded))
    return loaded,source


@pytest.fixture
def case(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    loaded,source=make_loaded(tmp_path)
    args=dict(process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),
        receipt_path=str(tmp_path/'export.json'),qualification_only=True,acknowledge_disposable_copy=True,message_policy='vendor_default')
    control=SimpleNamespace(calls=0,labels=[],result=0,fail=None,drift=None,output=NEW,event=False,after_native=None)
    class Machine:
        def GetController2(self):return [False,'fixture-controller',True]
        def SaveCLFile(self,path):
            control.calls+=1
            assert json.loads(Path(args['receipt_path']).read_text(encoding='utf-8'))['native_dispatch_pending'] is True
            marker=m.marker_path(source,args['expected_source_sha256'])
            assert json.loads(marker.read_text(encoding='utf-8'))['native_dispatch_pending'] is True
            Path(path).write_bytes(control.output)
            if control.fail:raise RuntimeError(control.fail)
            if control.after_native:control.after_native()
            return control.result
    machine=Machine()
    class Backend:
        def __init__(self,loaded,args,sw,clsid,tlb,report,persist,external_events):
            self.loaded,self.args,self.report,self.persist=loaded,args,report,persist
            self.native={'machine':machine};self.external_events=external_events
            self.ctx=SimpleNamespace(app=None,files=self.files,identity=self.identity)
        def files(self):m.common._check(self.loaded['pins'])
        def identity(self):
            if m._file_hash(source)!=self.args['expected_source_sha256']:raise ValueError('Changed source')
            return deepcopy(loaded['state']['document'])
        def boundary(self):self.files();self.identity();self.external_events(True)
        def capture_export(self,label):
            self.boundary();control.labels.append(label)
            observed=dict(state=deepcopy(loaded['state']),catalogue=m.validate_catalogue_authority(loaded),
                selected_defaults=deepcopy(loaded['configured_contour']['defaults']),selected_feature=deepcopy(loaded['cone_observation']['feature']),
                settings=deepcopy(loaded['settings']),units=deepcopy(loaded['finish_payload']['unit_record']),
                binding=deepcopy(next(r['assigned_tool'] for r in loaded['state']['operations'] if r['native_id']==267)))
            if control.drift:control.drift(label,observed)
            return observed
    monkeypatch.setattr(m.cl,'ReadBackend',Backend)
    monkeypatch.setattr(core,'_bootstrap',lambda *a:object());monkeypatch.setattr(core,'_typed',lambda obj,*a:obj)
    class BoundSession(Session):
        def summary(self):
            r=super().summary();r['event_count']=1 if control.event else 0;return r
    monkeypatch.setattr(sw_cam_events,'CamMessageSession',BoundSession)
    return SimpleNamespace(loaded=loaded,source=source,args=args,root=tmp_path,control=control)


def run(f):
    return m.export_cl(object(),'fixture','fixture.tlb',loaded=f.loaded,args=f.args,output_path=str(f.root/'cl_output/out.cl'))


def test_one_native_export_preserves_five_streams(case):
    r=run(case)
    assert r['readback_verified'] is True,r
    assert r['checkpoint_export_readback_verified'] is True and r['protected_streams_verified'] is True
    assert r['protected_stream_association']['added_operation_native_id']==144
    assert case.control.calls==1 and len(case.control.labels)==3
    assert r['before']==r['after'] and r['before']['selected_operation_native_id']==144
    assert r['before']['expected_ungenerated_operation_ids']==[195,196]
    assert [v['operation_native_id'] for v in r['before']['expected_generated_operations']]==[267,247,248,271,143,144]
    assert all(r[k] is False for k in ('GTP_attempted','GOP_attempted','model_saved','assignment_attempted','setter_attempted','geometry_verified'))
    assert r['full_tool_profile_capture_count']==0


@pytest.mark.parametrize('kind',['order','counts','tool','dirty','catalogue','defaults'])
def test_actual_shape_observation_drift_blocks_native(case,kind):
    def drift(label,obs):
        if kind=='order':obs['state']['operations'][0:2]=reversed(obs['state']['operations'][0:2])
        elif kind=='counts':obs['state']['operations'][6]['toolpath_record_counts']=[7]
        elif kind=='tool':obs['state']['operations'][6]['assigned_tool']['native_id']=249
        elif kind=='dirty':obs['state']['document']['needs_save']=True
        elif kind=='catalogue':obs['catalogue'][0]['CutDiameter']+=1
        elif kind=='defaults':obs['selected_defaults']['finish']['GetChamferLength']+=.1
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is False and case.control.calls==0


@pytest.mark.parametrize('value',[False,True,0,-1,6.0])
def test_actual_target_count_strict(case,value):
    case.loaded['generated_pocket_finish']['record_counts']=[value]
    case.loaded['state']['operations'][7]['toolpath_record_counts']=[value]
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


@pytest.mark.parametrize('value',[None,False,True,1])
def test_once_native_return_no_retry(case,value):
    case.control.result=value;r=run(case)
    assert case.control.calls==1 and r['readback_verified'] is False
    case.args['receipt_path']=str(case.root/'retry.json')
    with pytest.raises(ValueError):run(case)
    assert case.control.calls==1


def test_native_exception_keeps_pending(case):
    case.control.fail='injected';r=run(case)
    assert case.control.calls==1 and r['native_dispatch_pending'] is True and r['readback_verified'] is False


def test_changed_prior_feed_fails_after_single_export(case):
    case.control.output=NEW.replace(b'MMPM,500.000000',b'MMPM,499.000000',1)
    r=run(case)
    assert case.control.calls==1 and r['protected_streams_verified'] is False and r['readback_verified'] is False
    assert r['status']=='uncertain'


def test_changed_prior_tool_cannot_hide_outside_block(case):
    case.control.output=NEW.replace(b'CUTTER/ 8.000000,0.000000,4.000000',b'CUTTER/ 8.000000,0.000000,3.900000',1)
    r=run(case)
    assert case.control.calls==1 and r['protected_streams_verified'] is False


def test_mass_only_roundoff_accepted_raw_preserved(case):
    def drift(label,obs):obs['state']['sw_reference']['solids'][0]['mass_raw'][0]*=1+1e-13
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is True,r
    raw=json.loads(Path(r['observations_path']).read_text(encoding='utf-8'))
    assert raw['observations'][0]['state']['sw_reference']['solids'][0]['mass_raw']!=case.loaded['state']['sw_reference']['solids'][0]['mass_raw']


def test_prior_recovery_and_bytes_pinned(case):
    p=case.loaded['protected_cl_recovery_pin']
    with pytest.raises(ValueError):m.protected_reference(p['path'],'0'*64,case.loaded)


def test_terminal_source_drift_invalidates(case):
    case.control.after_native=lambda:case.source.write_bytes(b'changed')
    r=run(case)
    assert r['readback_verified'] is False and case.control.calls==1


def test_all_current_positions_required(case):
    case.loaded['state']['operations'][6]['operation_index']=0
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


def test_old_fixed_order_rejected(case):
    byid={r['native_id']:r for r in case.loaded['state']['operations']}
    case.loaded['state']['operations']=[byid[n] for n in [143,144,195,196,267,247,248,271]]
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


@pytest.mark.parametrize('change',[(b'UNITS/ MM',b'UNITS/ INCH'),(b'BOX/ -1.592082',b'BOX/ -1.592083')])
def test_global_cl_declarations_protected(case,change):
    case.control.output=NEW.replace(*change,1);r=run(case)
    assert case.control.calls==1 and r['protected_streams_verified'] is False


@pytest.mark.parametrize('scope',list(m.PARENT_LOADERS))
def test_future_flat_loader_and_bounded_phase_retirement(case,monkeypatch,scope):
    inherited=deepcopy(case.loaded)
    module_name=m.PARENT_LOADERS[scope];writer_name=module_name.split('.')[-1]+'.py'
    retired_names=set(m.RETIRED)
    if scope=='PARTIAL_POCKET_FINISH_CONTINUATION_V1':retired_names.add(writer_name)
    writer=case.root/writer_name;writer.write_text('completed writer fixture')
    checkpoint=case.root/'actual_completed_parent.json';checkpoint.write_text(json.dumps({'scope':scope}))
    inherited['parent_pin']=m.common._pin(checkpoint);inherited['pins']=[inherited['parent_pin']]
    names=('sw_cam_chamfer_exports','sw_cam_cl_inventory')
    inherited['pins'] += [m.common._pin(importlib.import_module('scripts.'+n).__file__) for n in names]
    for name in sorted(retired_names)+['active_'+str(i)+'.py' for i in range(61-len(retired_names))]:
        p=case.root/name
        if not p.exists():p.write_text('immutable phase fixture')
        inherited['pins'].append(m.common._pin(p))
    assert len(inherited['pins'])==64
    calls=[]
    def load(path,digest,**kwargs):
        calls.append((path,digest));return deepcopy(inherited)
    module=SimpleNamespace(__file__=str(writer),SCOPE=scope,load_completed=load)
    monkeypatch.setitem(sys.modules,module_name,module)
    ref=case.loaded['protected_cl_recovery_pin'];parentpin=inherited['parent_pin']
    result=m.load_checkpoint(parentpin['path'],parentpin['sha256'],process_id=123,
        expected_document_path=str(case.source),expected_source_sha256=m._file_hash(case.source),
        protected_cl_recovery_path=ref['path'],protected_cl_recovery_sha256=ref['sha256'])
    assert len(result['pins'])==(63 if 'CONTINUATION' in scope else 64)
    assert m.operation_contract(result)[-1]['toolpath_record_counts']==[6]
    assert len(result['export_phase_retired_pins'])==len(retired_names)
    assert any(p['path']==str(writer.resolve()) for p in result['offline_export_proof_pins'])
    assert result['state']==case.loaded['state'] and result['parent_pin']==parentpin
    assert result['export_parent_scope']==scope and calls==[(parentpin['path'],parentpin['sha256'])]
    assert case.control.calls==0


@pytest.mark.parametrize('mode',['unsupported','module_scope','fake_parent'])
def test_loader_scope_dispatch_rejects_substitution(case,monkeypatch,mode):
    scope='PARTIAL_POCKET_FINISH_CONTINUATION_V1';module_name=m.PARENT_LOADERS[scope]
    checkpoint=case.root/'scope-parent.json';checkpoint.write_text(json.dumps({'scope':'UNKNOWN' if mode=='unsupported' else scope}))
    parentpin=m.common._pin(checkpoint);inherited=deepcopy(case.loaded)
    if mode!='fake_parent':inherited['parent_pin']=parentpin
    module=SimpleNamespace(__file__=str(case.root/'sw_cam_pocket_finish_continuation.py'),
        SCOPE='WRONG' if mode=='module_scope' else scope,load_completed=lambda *a,**kw:deepcopy(inherited))
    monkeypatch.setitem(sys.modules,module_name,module)
    ref=case.loaded['protected_cl_recovery_pin']
    with pytest.raises(ValueError):m.load_checkpoint(parentpin['path'],parentpin['sha256'],process_id=123,
        expected_document_path=str(case.source),expected_source_sha256=m._file_hash(case.source),
        protected_cl_recovery_path=ref['path'],protected_cl_recovery_sha256=ref['sha256'])
    assert case.control.calls==0


def test_preservation_is_not_geometry_acceptance(case):
    result=m.preserved_streams(NEW,case.loaded)
    assert result['prior_five_complete_streams_unchanged'] is True
    assert result['new_finish_geometry_verified'] is False


@pytest.mark.parametrize('mode',['old18','new_profile','missing19','duplicate','assignment'])
def test_separate19_tool_catalogue_not_historical18(case,mode):
    if mode=='old18':case.loaded['neck_tool_checkpoint']['catalogue'][0]['CutDiameter']+=.1
    elif mode=='new_profile':case.loaded['neck_tool_candidate']['full_tool']['tool_protrusion_native']=26.
    elif mode=='missing19':case.loaded['neck_tool_checkpoint']['catalogue'].pop()
    elif mode=='duplicate':case.loaded['neck_tool_checkpoint']['catalogue'][-1]['native_id']=145
    elif mode=='assignment':case.loaded['state']['operations'][7]['assigned_tool']['protrusion_native']=26.
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


def test_recovered_uncertain_native_export_not_reexecuted(case):
    result=m.preserved_streams(NEW,case.loaded)
    assert result['added_block']==5 and result['added_operation_native_id']==144
    assert [v['native_id'] for v in result['unchanged']]==[267,247,248,271,143]
    assert case.control.calls==0


@pytest.mark.parametrize('result,expected',[
    ({'status':'validated_offline','native_called':False},0),
    ({'status':'review_required','readback_verified':True},0),
    ({'status':'error','readback_verified':False},1),
    ({'status':'uncertain','readback_verified':False},1)])
def test_permanent_cli_status_exit_code(tmp_path,monkeypatch,capsys,result,expected):
    path=tmp_path/'request.json';path.write_text('{"action":"export_cl","params":{}}')
    calls=[]
    def dispatch(request,*,validate_only):
        calls.append((request,validate_only));return deepcopy(result)
    monkeypatch.setattr(m,'dispatch_request',dispatch)
    assert m.main(['--request',str(path),'--validate-only'])==expected
    assert calls==[({'action':'export_cl','params':{}},True)]
    out=capsys.readouterr().out
    assert json.loads(out)['status']==result['status'] and len(out)<1000


def test_permanent_module_entrypoint_help_runs_without_dispatch(tmp_path):
    import subprocess
    # Exercise the real __main__ branch in a fresh process with the same package
    # path overlay used by staging. Installed use is `python -m scripts.<name>`.
    code=('import sys,runpy;sys.path.insert(0,'+repr(str(ROOT))+');import scripts;'
        'scripts.__path__.insert(0,'+repr(str(STAGE/'scripts'))+');'
        'sys.argv=["sw_cam_pocket_finish_exports","--help"];'
        'runpy.run_module("scripts.sw_cam_pocket_finish_exports",run_name="__main__")')
    completed=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert completed.returncode==0,completed.stderr
    assert '--request' in completed.stdout and '--validate-only' in completed.stdout



def test_actual_catalogue_and_assignment_are_distinct_native_schemas(case):
    row=deepcopy(BINDING['catalogue_row']);expected=dict(deepcopy(BINDING['prior_assignment']),
        native_id=row['native_id'],tool_type_raw=row['tool_type_raw'],cut_diameter_native=row['CutDiameter'],protrusion_native=row['Protrusion'])
    assert m.assignment_from_catalogue(row)==expected
    assert expected['protrusion_native']==26.000000000000004
    assert 'StnNo' not in expected and 'CutDiameter' not in expected
    assert 'is_mill_tool' not in row and 'cut_diameter_native' not in row


@pytest.mark.parametrize('mode',['raw_catalogue','read_incomplete','not_mill','qualification_flags','extra_field'])
def test_actual_assignment_flags_and_schema_remain_strict(case,mode):
    selected=case.loaded['state']['operations'][7]
    if mode=='raw_catalogue':selected['assigned_tool']=deepcopy(case.loaded['neck_tool_checkpoint']['catalogue'][-1])
    elif mode=='read_incomplete':selected['assigned_tool']['native_read_complete']=False
    elif mode=='not_mill':selected['assigned_tool']['is_mill_tool']=False
    elif mode=='qualification_flags':selected['assigned_tool']['units_verified']=True
    elif mode=='extra_field':selected['assigned_tool']['StnNo']=19.
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


@pytest.mark.parametrize('key,value',[('native_id',True),('tool_type_raw',True),('CutDiameter',True),('Protrusion',float('nan'))])
def test_actual_binding_projection_rejects_wrong_native_scalar_types(key,value):
    row=deepcopy(BINDING['catalogue_row']);row[key]=value
    with pytest.raises(ValueError):m.assignment_from_catalogue(row)
