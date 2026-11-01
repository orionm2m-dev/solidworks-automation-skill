import ast, hashlib, json, os, sys, tempfile, types, unittest
from pathlib import Path
from enum import Enum
from unittest.mock import patch
from pydantic import BaseModel, ConfigDict, Field, model_validator

STAGE=Path(__file__).resolve().parents[1]
def wrapper_source():
    runtime=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
    server=runtime/'mcp-server/server.py'
    source=server if server.is_file() and 'def solidworks_cam_resume_guide_configuration(' in server.read_text(encoding='utf-8-sig') else STAGE/'MCP_SNIPPET.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    names={'SolidWorksCamGuideResumeInput','_cam_guide_resume_sealed_payload','solidworks_cam_resume_guide_configuration'}
    nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
    if {n.name for n in nodes}!=names:raise AssertionError('Configuration MCP wrapper is incomplete')
    return ast.unparse(ast.Module(body=nodes,type_ignores=[]))
class BaseInput(BaseModel):model_config=ConfigDict(extra='forbid')
class ResponseFormat(str,Enum):JSON='json'
class FakeMcp:
    def tool(self,**kwargs):return lambda f:f

class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cam-wrapper-test-');self.root=Path(self.temp.name)
        self.module=self.root/'sw_cam_guide_group_resume.py';self.module.write_bytes(b'# fixed writer\n')
        self.request=self.root/'request.json';self.payload={'action':'resume_partial_guide_configuration','params':{'process_id':52,'module_sha256':self.sha(self.module),'receipt_path':str(self.root/'out.json')}}
        self.write(self.payload);self.dispatched=[];self.locked=[]
        self.fake=types.ModuleType('scripts.sw_cam_guide_group_resume');self.fake.dispatch_request=lambda value:self.dispatched.append(value) or {'status':'observed','native_called':False}
        self.scope=dict(BaseInput=BaseInput,ConfigDict=ConfigDict,Field=Field,model_validator=model_validator,ResponseFormat=ResponseFormat,mcp=FakeMcp(),SCRIPTS_DIR=self.root,_selected_process_id=52)
        def lock(op,fmt,**kwargs):self.locked.append(kwargs);return op()
        self.scope['_run_locked']=lock
        exec(compile(wrapper_source(),'<snippet>','exec'),self.scope)
        self.modules=patch.dict(sys.modules,{'scripts.sw_cam_guide_group_resume':self.fake});self.modules.start()
    def tearDown(self):self.modules.stop();self.temp.cleanup()
    def sha(self,p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def write(self,payload):self.request.write_text(json.dumps(payload),encoding='utf-8')
    def params(self,**kw):
        data=dict(process_id=52,request_path=str(self.request),request_sha256=self.sha(self.request));data.update(kw)
        return self.scope['SolidWorksCamGuideResumeInput'](**data)
    def call(self,**kw):return self.scope['solidworks_cam_resume_guide_configuration'](self.params(**kw))
    def test_exact_payload_dispatch_without_automation(self):
        self.assertEqual(self.call()['status'],'observed');self.assertEqual(self.dispatched,[self.payload]);self.assertEqual(self.locked,[{'load_automation':False,'desktop_guard':True}])
    def test_prepare_action_accepted(self):
        self.payload['action']='prepare_partial_guide_configuration';self.write(self.payload)
        self.assertEqual(self.call()['status'],'observed');self.assertEqual(self.dispatched,[self.payload])
    def test_selected_pid_required(self):
        for value in (None,True,53):
            self.scope['_selected_process_id']=value
            with self.assertRaises(ValueError):self.call()
        self.assertFalse(self.dispatched)
    def test_payload_pid_exact(self):
        for value in (True,'52',53):
            self.payload['params']['process_id']=value;self.write(self.payload)
            with self.assertRaises(ValueError):self.call()
        self.assertFalse(self.dispatched)
    def test_model_strict_pid(self):
        for value in (True,'52',52.,0,-1):
            with self.assertRaises(ValueError):self.params(process_id=value)
    def test_model_extra_forbidden(self):
        with self.assertRaises(ValueError):self.params(arbitrary_method='Save')
    def test_model_relative_path_forbidden(self):
        with self.assertRaises(ValueError):self.params(request_path='relative.json')
    def test_request_digest_required(self):
        with self.assertRaises(ValueError):self.call(request_sha256='0'*64)
        self.assertFalse(self.dispatched)
    def test_writer_digest_required(self):
        self.module.write_bytes(b'# changed\n')
        with self.assertRaises(ValueError):self.call()
        self.assertFalse(self.dispatched)
    def test_wrong_action_rejected(self):
        self.payload['action']='save';self.write(self.payload)
        with self.assertRaises(ValueError):self.call()
    def test_duplicate_json_key_rejected(self):
        self.request.write_text('{"action":"x","action":"resume_partial_guide_configuration","params":{}}',encoding='utf-8')
        with self.assertRaises(ValueError):self.call()
    def test_nonfinite_json_rejected(self):
        self.request.write_text('{"action":"resume_partial_guide_configuration","params":{"process_id":NaN}}',encoding='utf-8')
        with self.assertRaises(ValueError):self.call()
    def test_payload_change_after_dispatch_detected(self):
        def change(value):self.dispatched.append(value);self.request.write_text('{}',encoding='utf-8');return {'status':'observed'}
        self.fake.dispatch_request=change
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(len(self.dispatched),1)
    def test_receipt_cannot_overwrite_request(self):
        self.payload['params']['receipt_path']=str(self.request);self.write(self.payload)
        with self.assertRaises(ValueError):self.call()
    def test_payload_bounded(self):
        self.request.write_bytes(b' '*(1048576+1))
        with self.assertRaises(ValueError):self.call()
    def test_wrapper_declares_mutation_and_nonidempotence(self):
        content=wrapper_source()
        tree=ast.parse(content);call=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='solidworks_cam_resume_guide_configuration').decorator_list[0];annotations=ast.literal_eval(next(k.value for k in call.keywords if k.arg=='annotations'));self.assertIs(annotations['readOnlyHint'],False);self.assertIs(annotations['idempotentHint'],False)
if __name__=='__main__':unittest.main(verbosity=2)
