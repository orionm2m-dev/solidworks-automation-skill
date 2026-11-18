"""Portable fixed-scope orchestration tests, with native and pure-proof seams."""
import ast,copy,os,sys,hashlib
from pathlib import Path
from enum import Enum
from typing import Literal
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_generate as c


def request(tmp_path):
    r=dict(process_id=51,expected_process_create_time=123.5,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,expected_feature_native_id=77,expected_operation_native_ids=[501,502],selected_operation_native_id=501,receipt_path=str(tmp_path/'receipt.json'),saved_cl_path=str(tmp_path/'fresh'/'one.cl'),qualification_only=True,acknowledge_settings_generation_save_export=True,message_policy='vendor_default')
    for key in ('current_context_receipt','recipe'):r[key+'_path']=str(tmp_path/(key+'.json'));r[key+'_sha256']='b'*64
    return r


def schema():
    p=ROOT/'server.fragment.py'
    if not p.exists():p=RUNTIME/'mcp-server/server.py'
    node=next(n for n in ast.parse(p.read_text(encoding='utf-8-sig')).body if isinstance(n,ast.ClassDef)and n.name=='SolidWorksCamCurrentPocketGenerateInput')
    class Target(BaseModel):
        model_config=ConfigDict(extra='forbid')
        addin_clsid:str
        expected_document_title:str|None=None
    class ResponseFormat(str,Enum):JSON='json'
    env=dict(SolidWorksCamTargetInput=Target,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal,ResponseFormat=ResponseFormat)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),env);return env['SolidWorksCamCurrentPocketGenerateInput']


def transform():
    return dict(setup_transform_complete=True,transform_components=dict(scale_raw=1.,rotate_raw=False,vectors={n:dict(coordinates_raw=a)for n,a in [('x_axis',[1.,0.,0.]),('y_axis',[0.,1.,0.]),('z_axis',[0.,0.,1.]),('translation',[0.,0.,-.026])]}),origin=dict(coordinates_raw=[0.,0.,26.]),axis=dict(coordinates_raw=[0.,0.,-1.]))


def test_actual_metadata_no_application():
    tlb=os.environ.get('SWMCP_CAM_TYPELIB_PATH');assert tlb
    r=c.preflight(tlb)
    assert r['native_calls']==0 and r['setup_transform']['native_calls']==0
    assert r['fixed_fields_abi_verified'] and r['generation_save_export_abi_verified']


@pytest.mark.parametrize('patch',[dict(selected_operation_native_id=502),dict(expected_operation_native_ids=[501.,502]),dict(expected_operation_native_ids=[True,502]),dict(expected_operation_native_ids=[501,501]),dict(acknowledge_settings_generation_save_export=False),dict(unrequested_setter='Save3')])
def test_schema_rejects_outside_scope(tmp_path,patch):
    r=request(tmp_path);r.update(patch);r['addin_clsid']='{00000000-0000-0000-0000-000000000000}'
    with pytest.raises(ValueError):schema()(**r)


def test_schema_generic_and_no_application_constructor(tmp_path):
    r=request(tmp_path);assert schema()(**dict(r,addin_clsid='x')).selected_operation_native_id==501
    class NoApplication:
        def __getattr__(self,name):raise AssertionError(name)
    b=c.Backend(NoApplication(),'x','tlb',r,{'bundle':{'context':{'pins':[]}}},{},lambda:None,lambda:None,{'generated_pin':{}})
    assert b.attempted==[] and b.loaded['selected_ids']==[501]
    assert c.Backend.generate is c.generation.NativeGenerationContext.generate
    assert c.Backend.export_cl is c.generation.NativeGenerationContext.export_cl


@pytest.mark.parametrize('kind',['incomplete','nan','zero_scale','nonorthogonal','left_handed','origin_drift','axis_drift'])
def test_transform_rejects_bad_components_without_world_inference(kind):
    r=transform();levels={'setup':{'origin_native':[0.,0.,26.],'axis_native':[0.,0.,-1.]}}
    if kind=='incomplete':r['setup_transform_complete']=False
    elif kind=='nan':r['transform_components']['scale_raw']=float('nan')
    elif kind=='zero_scale':r['transform_components']['scale_raw']=0.
    elif kind=='nonorthogonal':r['transform_components']['vectors']['y_axis']['coordinates_raw']=[1.,0.,0.]
    elif kind=='left_handed':r['transform_components']['vectors']['z_axis']['coordinates_raw']=[0.,0.,-1.]
    elif kind=='origin_drift':r['origin']['coordinates_raw'][2]=0.
    elif kind=='axis_drift':r['axis']['coordinates_raw'][2]=1.
    with pytest.raises(ValueError):c.verify_transform(r,levels)


def test_transform_preserves_distinct_raw_translation_and_operation_origin():
    r=transform();proof=c.verify_transform(r,{'setup':{'origin_native':[0.,0.,26.],'axis_native':[0.,0.,-1.]}})
    assert proof['finite_orthonormal_positive_scale']is True and proof['CL_world_mapping_verified']is False
    assert r['transform_components']['vectors']['translation']['coordinates_raw'][2]==-.026


@pytest.fixture
def flow(tmp_path,monkeypatch):
    v=request(tmp_path);levels={'setup':{'origin_native':[0.,0.,26.],'axis_native':[0.,0.,-1.]}}
    base=dict(inventory=dict(document=dict(path=v['expected_document_path'],title='part.sldprt',type=1,needs_save=False),saved_file_sha256='a'*64,operations=[dict(native_id=501,toolpath_generated=False,toolpath_record_counts=[]),dict(native_id=502,toolpath_generated=False,toolpath_record_counts=[])]),parameters=[dict(operation_native_id=501,read_complete=True,levels=levels),dict(operation_native_id=502,read_complete=True,levels=levels)])
    changes=[dict(field=n,expected=[False,10.]if 'depth'in n else 0 if n=='entry_type'else .25 if n=='side_allowance'else 10.,new=[False,.3]if 'depth'in n else 4 if n=='entry_type'else .25 if n=='side_allowance'else 0. if n=='floor_allowance'else .1)for n in c.FIELD_NAMES]
    row=dict(operation_native_id=501,feature_native_id=77,operation_type=0,expected_tool_native_id=91,existing_tool_native_id=None,fields=changes)
    data=dict(request=v,plan=dict(rows=[row]),recipe={},bundle=dict(state=base['inventory'],parameters=base['parameters'],receipt_pin={'path':str(tmp_path/'baseline.json'),'sha256':'b'*64}),receipt=Path(v['receipt_path']),marker=tmp_path/'once.json')
    r=dict(scope=c.SCOPE,status='prepared',phase='prepared',selected_operation_native_ids=[501],configuration_receipt_pin=data['bundle']['receipt_pin'],current_baseline_receipt_pin=data['bundle']['receipt_pin'],actions={},field_readbacks=[],mutation_attempted=False,CL_export_attempted=False,model_saved=False,save_readback_verified=False,**{k:False for k in c.FLAGS})
    journal=c.Journal(data['receipt'],data['marker'],r)
    monkeypatch.setattr(c.delta,'flatten',lambda s:dict(copy.deepcopy(s['inventory']),operation_parameters=copy.deepcopy(s['parameters'])))
    monkeypatch.setattr(c.fields,'verify_final',lambda before,after,plan,candidates,observed_floor_alias:None)
    def genproof(before,after,oid,native):
        assert native['native_return_type']=='int'and type(native['native_return_value'])is int and native['native_return_value']==0
        assert before['inventory']['operations'][0]['toolpath_record_counts']==[]
        assert after['inventory']['operations'][0]['toolpath_record_counts']==[8]
        assert after['inventory']['operations'][1]==before['inventory']['operations'][1]
        if backend.fail=='post_gtp_delta':raise ValueError('unexpected generated state')
        return {'verified':True}
    monkeypatch.setattr(c.delta,'verify_generation',genproof)
    monkeypatch.setattr(c.delta,'verify_first_cl',lambda parsed,oid,count:{'verified':True,'selected':oid,'count':count})
    monkeypatch.setattr(c,'parse_generic_cl_bytes',lambda raw,expected_block_record_counts:{'fake_parser':True})
    monkeypatch.setattr(c.reader.shared,'event_health',lambda *a,**k:0)
    class B:
        fail=None
        def __init__(self):self.values={x['field']:copy.deepcopy(x['expected'])for x in changes};self.calls=[];self.generated=False;self.source='a'*64;self.expected_document=copy.deepcopy(base['inventory']['document'])
        def start(self):self.calls.append('start')
        def capture_current(self,label):
            self.calls.append(label);s=copy.deepcopy(base);s['inventory']['saved_file_sha256']=self.source
            if self.generated:s['inventory']['operations'][0].update(toolpath_generated=True,toolpath_record_counts=[8])
            return s
        def setup_transform(self,oid):self.calls.append('transform');return transform()
        def boundary(self):return self.expected_document
        def read_field(self,row,change):return copy.deepcopy(self.values[change['field']])
        def set_field(self,row,change,pending,returned):
            pending();self.calls.append('set:'+change['field'])
            if self.fail=='setter':raise RuntimeError('native setter failure')
            returned(0);self.values[change['field']]=copy.deepcopy(change['new'])
        def refresh_dirty(self):pass
        def generate(self,oid,state,*,pending,returned):
            pending();self.calls.append('GTP')
            if self.fail=='gtp_exception':raise RuntimeError('GTP interrupted')
            returned(True if self.fail=='gtp_bool'else 0);self.generated=True
        def save(self):self.calls.append('Save');return 0
        def adopt_context(self,d):self.source='c'*64
        def export_cl(self,label,state,rows,diagnostic,*,pending,returned):
            pending();self.calls.append('CL')
            if self.fail=='CL':raise RuntimeError('CL failure')
            p=Path(v['saved_cl_path']);p.parent.mkdir();p.write_bytes(b'fake export');returned(0)
            diagnostic.update(output={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size},output_verified=True,readback_verified=True)
        def parse_cl(self,result):return {'fake_parser':True}
        def close(self):
            self.calls.append('close');r['messages']={}
            if self.fail=='cleanup':raise RuntimeError('cleanup failed')
        def runtime_check(self):
            if self.fail=='runtime':raise RuntimeError('runtime changed')
        def identity(self):return self.expected_document
        def files(self):pass
    backend=B()
    def save(report,bundle,expected_after,*,capture,guard,claim,persist,save,adopt_context):
        report['save_snapshots']={'before':capture('before_save')};claim();value=save();report['native_save']={'native_return_value':value,'native_return_type':'int','native_call_returned':True};report['saved_file_sha256_after_native_return']='c'*64;report['model_saved']=True;persist();adopt_context({})
        if backend.fail=='post_save':raise ValueError('saved but postcheck failed')
        report['save_readback_verified']=True;after=capture('after_save');report['save_snapshots']['after']=after
        return {'payload':{'scope':'CURRENT_SAVED_POCKET_CONTEXT_V1'},'state':after['inventory'],'parameters':after['parameters']}
    monkeypatch.setattr(c.current,'save_current_baseline',save)
    return backend,journal,data,r


def test_actual_orchestrator_success_has_one_gtp_one_save_first_cl(flow):
    b,j,d,r=flow;out=c.run_backend(b,j,d)
    assert out['status']=='review_required'and all(out[k]is True for k in c.FLAGS)
    assert b.calls.count('GTP')==b.calls.count('Save')==b.calls.count('CL')==1
    assert not any('preCL'in name for name in b.calls)
    assert len([x for x in b.calls if x.startswith('set:')])==6
    assert out['generated']['inventory']['operations'][0]['toolpath_record_counts']==[8]
    assert j.marker.is_file()


@pytest.mark.parametrize('failure',['setter','gtp_exception','gtp_bool','post_gtp_delta','post_save','CL','cleanup','runtime'])
def test_uncertain_stops_without_replay_and_preserves_actual_facts(flow,failure):
    b,j,d,r=flow;b.fail=failure;out=c.run_backend(b,j,d)
    assert out['status']=='uncertain'and all(out[k]is False for k in c.FLAGS)
    assert b.calls.count('GTP')<=1 and b.calls.count('Save')<=1 and b.calls.count('CL')<=1
    if failure in ('post_save','CL','cleanup','runtime'):
        assert out['model_saved']is True and out['native_save']['native_return_value']==0 and out['saved_file_sha256_after_native_return']=='c'*64
    if failure=='post_gtp_delta':assert out['generated']['inventory']['operations'][0]['toolpath_record_counts']==[8]and 'Save'not in b.calls
    if failure=='setter':assert 'GTP'not in b.calls
    with pytest.raises(ValueError):c.Journal(j.receipt,j.marker,r).create()


def test_reused_parse_cl_rejects_changed_raw_buffer_even_when_disk_hash_matches(tmp_path,monkeypatch):
    p=tmp_path/'path.cl';p.write_bytes(b'original');digest=hashlib.sha256(b'original').hexdigest()
    result={'output':{'path':str(p),'sha256':digest,'bytes':8},'expected_generated_operations':[{'operation_native_id':501,'toolpath_record_counts':[8]}]}
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda self:b'mutated!'if self==p else original(self))
    monkeypatch.setattr(c.generation,'parse_generic_cl_bytes',lambda *a,**k:pytest.fail('Parser must not receive unpinned bytes'))
    assert c.Backend.parse_cl is c.generation.NativeGenerationContext.parse_cl
    with pytest.raises(ValueError,match='CL changed during read'):c.Backend.parse_cl(object.__new__(c.Backend),result)
