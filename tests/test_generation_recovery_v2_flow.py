"""Portable recovery orchestration with the real existing Save helper."""
import ast,copy,hashlib,os,sys
from enum import Enum
from pathlib import Path
from typing import Literal
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
ROOT=Path(__file__).resolve().parents[1];RT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RT))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_generation_recovery_v2 as c


def request(tmp_path):
    return dict(process_id=51,expected_process_create_time=123.5,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=77,expected_operation_native_ids=[501,502],selected_operation_native_id=501,failed_generation_receipt_path=str(tmp_path/'old.json'),failed_generation_receipt_sha256='b'*64,observed_xy_feed_before=700.,observed_xy_feed_after=1400.,receipt_path=str(tmp_path/'receipt.json'),saved_cl_path=str(tmp_path/'fresh'/'one.cl'),qualification_only=True,acknowledge_observed_feed_save_export=True,message_policy='vendor_default')


def schema():
    p=ROOT/'server.fragment.py'
    if not p.exists():p=RT/'mcp-server/server.py'
    node=next(n for n in ast.parse(p.read_text('utf-8-sig')).body if isinstance(n,ast.ClassDef)and n.name=='SolidWorksCamCurrentPocketGenerationRecoveryInput')
    class Target(BaseModel):
        model_config=ConfigDict(extra='forbid')
        addin_clsid:str
        expected_document_title:str|None=None
    class ResponseFormat(str,Enum):JSON='json'
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,ResponseFormat=ResponseFormat)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),env);return env[node.name]


@pytest.mark.parametrize('patch',[dict(selected_operation_native_id=502),dict(expected_operation_native_ids=[501.,502]),dict(observed_xy_feed_before=True),dict(observed_xy_feed_after=float('nan')),dict(acknowledge_observed_feed_save_export=False),dict(unrequested_setter=True)])
def test_schema_rejects_outside_scope(tmp_path,patch):
    v=request(tmp_path);v.update(patch)
    with pytest.raises(ValueError):schema()(**dict(v,addin_clsid='x'))


def test_generic_schema_noapplication_and_no_mutators(tmp_path):
    v=request(tmp_path);schema()(**dict(v,addin_clsid='x'))
    class NoApp:
        def __getattr__(self,name):raise AssertionError(name)
    b=c.Backend(NoApp(),'x','tlb',v,dict(bundle=dict(context=dict(pins=[]))),{},lambda:None,lambda:None,dict(generated_pin={}))
    assert b.attempted==[501] and b.loaded['selected_ids']==[501]
    for name in ('generate','set_field','read_field','create','field','property','assign_selected','attach_holder'):
        with pytest.raises(ValueError,match='forbids'):getattr(b,name)()
    assert c.Backend.export_cl is c.prior.Backend.export_cl and c.Backend.parse_cl is c.prior.Backend.parse_cl


@pytest.fixture
def flow(tmp_path,monkeypatch):
    v=request(tmp_path);source=Path(v['expected_document_path']);source.write_bytes(b'before');v['expected_source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    base=dict(inventory=dict(document=dict(path=str(source),title=source.name,type=1,needs_save=False),saved_file_sha256=v['expected_source_sha256'],operations=[dict(native_id=501,toolpath_generated=True,toolpath_record_counts=[8]),dict(native_id=502,toolpath_generated=False,toolpath_record_counts=[])]),parameters=[dict(operation_native_id=501,feed=1400.),dict(operation_native_id=502,feed=700.)])
    pin=dict(path=str(tmp_path/'old.json'),sha256='b'*64);rootpin=dict(path=str(tmp_path/'root.json'),sha256='d'*64)
    context=dict(expected_source_sha256=v['expected_source_sha256'],expected_document_path=str(source),expected_feature_native_id=77,pins=[rootpin],request={k:v[k]for k in ('process_id','expected_process_create_time','expected_document_path')},saved_transition={})
    bundle=dict(context=context,state=base['inventory'],parameters=base['parameters'],receipt_pin=pin,root_pins=[rootpin],lineage_pins=[pin])
    data=dict(request=v,bundle=bundle,save_bundle=c.current.save_bundle_for_context(bundle),expected_state=copy.deepcopy(base),raw_pin=pin,feed_delta={'feed_unqualified':True},receipt=Path(v['receipt_path']),marker=tmp_path/'once.json')
    r=dict(scope=c.SCOPE,status='prepared',phase='prepared',selected_operation_native_ids=[501],configuration_receipt_pin=pin,actions={},mutation_attempted=False,CL_export_attempted=False,model_saved=False,save_readback_verified=False,GTP_attempted=False,GOP_attempted=False,Import_attempted=False,automatic_replay=False,production_qualified=False,**{k:False for k in c.FLAGS})
    j=c.Journal(data['receipt'],data['marker'],r)
    # Keep the actual Save sequence/claim/raw-return/source transition/capture comparisons.
    monkeypatch.setattr(c.current,'_snapshot',lambda a,b:dict(inventory=copy.deepcopy(a),parameters=copy.deepcopy(b)))
    monkeypatch.setattr(c.current,'_compact',copy.deepcopy)
    def transition(d,sha,native_return_value):
        assert type(native_return_value)is int and native_return_value==0 and sha!=d['expected_source_sha256']
        d=copy.deepcopy(d);d['expected_source_sha256']=sha;return d
    monkeypatch.setattr(c.current.definition,'after_native_save_source',transition)
    monkeypatch.setattr(c.delta,'flatten',lambda s:dict(copy.deepcopy(s['inventory']),operation_parameters=copy.deepcopy(s['parameters'])))
    monkeypatch.setattr(c.delta,'verify_first_cl',lambda parsed,oid,count:dict(verified=True,operation=oid,count=count))
    monkeypatch.setattr(c.reader.shared,'event_health',lambda *a,**k:0)
    class B:
        fail=None
        def __init__(self):self.calls=[];self.source=v['expected_source_sha256'];self.expected_document=copy.deepcopy(base['inventory']['document'])
        def start(self):self.calls.append('start')
        def capture_current(self,label):
            self.calls.append(label);s=copy.deepcopy(base);s['inventory']['saved_file_sha256']=self.source
            if self.fail==label:s['parameters'][1]['feed']+=1
            if self.fail=='after_exception'and label=='after':raise ValueError('post-Save read failed')
            return s
        def boundary(self):return self.expected_document
        def save(self):
            self.calls.append('Save');source.write_bytes(b'after')
            return True if self.fail=='save_bool'else 0
        def adopt_context(self,d):self.source=d['expected_source_sha256']
        def export_cl(self,label,state,rows,diagnostic,*,pending,returned):
            self.capture_current(label+'_before');pending();self.calls.append('CL')
            if self.fail=='CL':raise ValueError('export failed')
            returned(0);self.capture_current(label+'_after');diagnostic.update(output_verified=True,readback_verified=True)
        def parse_cl(self,export):return {'parsed':True}
        def close(self):
            self.calls.append('close');r['messages']={}
            if self.fail=='cleanup':raise ValueError('cleanup failed')
        def runtime_check(self):
            if self.fail=='runtime':raise ValueError('runtime changed')
        def identity(self):return self.expected_document
        def files(self):pass
    return B(),j,data,r


def test_five_fresh_captures_one_save_export_with_real_save_helper(flow,monkeypatch):
    b,j,d,r=flow;out=c.run_backend(b,j,d)
    assert out['status']=='review_required'and all(out[k]is True for k in c.FLAGS)
    assert [x for x in b.calls if x in ('recovery_current','before','after','postCL_before','postCL_after')]==['recovery_current','before','after','postCL_before','postCL_after']
    assert b.calls.count('Save')==b.calls.count('CL')==1
    assert set(r['actions'])=={'SaveActiveDocument','postCL'} and r['GTP_attempted']is False
    assert out['confirm_before']==out['before']==out['save_snapshots']['before']
    assert out['second_capture_roles']==['generated_state_confirmation','save_before']
    assert out['native_save']['native_return_value']==0 and out['model_saved']is True
    assert out['current_context']['scope']==c.GENERATED_SCOPE!=c.current.SCOPE
    monkeypatch.setattr(c.current.definition.creator,'clean',lambda _:None)
    with pytest.raises(ValueError,match='scope'):c.current._load_current_receipt(out,{},d['request'])


@pytest.mark.parametrize('failure',['recovery_current','before','save_bool','after_exception','CL','cleanup','runtime'])
def test_failure_preserves_raw_save_facts_no_replay(flow,failure):
    b,j,d,r=flow;b.fail=failure;out=c.run_backend(b,j,d)
    assert all(out[k]is False for k in c.FLAGS)
    assert b.calls.count('Save')<=1 and b.calls.count('CL')<=1
    if failure in ('recovery_current','before'):assert 'Save'not in b.calls
    if failure in ('after_exception','CL','cleanup','runtime'):
        assert out['native_save']['native_return_value']==0 and out['model_saved']is True
        assert out['saved_file_sha256_after_native_return']==b.source!=d['request']['expected_source_sha256']
    with pytest.raises(ValueError):c.Journal(j.receipt,j.marker,out).create()


@pytest.mark.parametrize('action',['GTP:501','field:entry_type','Save3','ImportCAMData'])
def test_journal_rejects_mutation_replay(tmp_path,action):
    j=c.Journal(tmp_path/'r.json',tmp_path/'m.json',{'actions':{}})
    with pytest.raises(ValueError):j.action(action)


def test_mcp_envelope_connect_and_bound_operation(tmp_path):
    import json
    configured=os.environ.get('SWMCP_REQUEST_ENVELOPE_PATH')
    envelope=json.loads(Path(configured).read_text('utf-8')) if configured else {'requests':[{'name':'solidworks_connect','arguments':{'params':{'process_id':51}}},{'name':'solidworks_cam_recover_generated_current_pocket','arguments':{'params':dict(request(tmp_path),addin_clsid='x')}}]}
    connect,operation=envelope['requests']
    assert connect['name']=='solidworks_connect' and set(connect['arguments'])=={'params'}
    assert set(connect['arguments']['params'])=={'process_id'} and type(connect['arguments']['params']['process_id'])is int
    assert operation['name']=='solidworks_cam_recover_generated_current_pocket' and set(operation['arguments'])=={'params'}
    parsed=schema()(**operation['arguments']['params'])
    assert connect['arguments']['params']['process_id']==parsed.process_id
