"""Portable schema and real typelib metadata tests; never activate an application."""
from pathlib import Path
import ast
import enum
import hashlib
import importlib.util
import os
import sys
import tempfile
import typing
import unittest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator,ValidationError
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
from scripts.sw_operation_guard import absolute_document_path


def models():
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
            model_validator=model_validator,Optional=typing.Optional,Literal=typing.Literal,
            Enum=enum.Enum,Path=Path,absolute_document_path=absolute_document_path)
    tree=ast.parse((RUNTIME/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    for name in ('ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamTurnEntryTargetInput'):
        node=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'existing_server','exec'),ns)
    snippet=STAGE/'SERVER_REGISTRATION_SNIPPET.py'
    scope=ast.parse(snippet.read_text(encoding='utf-8')) if snippet.exists() else tree
    node=next(x for x in scope.body if isinstance(x,ast.ClassDef) and x.name=='SolidWorksCamTurnNcHomeContextInput')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'post_option_schema','exec'),ns)
    return ns['SolidWorksCamTurnNcHomeContextInput']


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=models()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'fixture.sldprt';self.source.write_bytes(b'not CAD; schema fixture')
    def values(self):
        return dict(addin_clsid='{00000000-0000-0000-0000-000000000001}',response_format='json',process_id=123,
            expected_process_create_time=1234.25,expected_document_path=str(self.source),
            expected_source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            expected_feature_count=2,expected_operation_count=3,expected_operation_setup_count=1,
            expected_generated_operation_count=1,expected_total_record_count=20,
            targets=[dict(operation_native_id=501,feature_native_id=301,setup_index=0,operation_index=0,operation_type=7)],
            receipt_path=str(Path(self.temp.name)/'new.json'),qualification_only=True,message_policy='vendor_default',
            acknowledge_public_interface_qualification=True)
    def test_generic_exact_request(self):self.model.model_validate(self.values())
    def test_only_one_target(self):
        v=self.values();v['targets']*=2
        with self.assertRaises(ValidationError):self.model.model_validate(v)
    def test_inherited_kind_is_strict(self):
        for kind in (7.0,'7',True):
            v=self.values();v['targets'][0]['operation_type']=kind
            with self.subTest(kind=kind),self.assertRaises(ValidationError):self.model.model_validate(v)
    def test_nested_unknown_field_rejected(self):
        v=self.values();v['targets'][0]['write']=True
        with self.assertRaises(ValidationError):self.model.model_validate(v)
    def test_explicit_public_qualification_is_strict(self):
        for invalid in (False,1,'true'):
            v=self.values();v['acknowledge_public_interface_qualification']=invalid
            with self.subTest(value=invalid),self.assertRaises(ValidationError):self.model.model_validate(v)


class ActualMetadataTests(unittest.TestCase):
    def test_public_two_getter_abi_and_no_application_constructor(self):
        tlb=os.environ.get('SWMCP_CAM_TYPELIB')
        if not tlb:self.skipTest('Set SWMCP_CAM_TYPELIB for the public ABI metadata test')
        spec=importlib.util.spec_from_file_location('nc_home_metadata',STAGE/'scripts/sw_cam_turn_nc_home_context.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        classes,abi=m.preflight(tlb);self.assertEqual(abi['getter_count'],2)
        self.assertEqual(abi['native_calls'],0)
        from ctypes import POINTER
        class NoApplication:
            def __getattribute__(self,name):raise AssertionError('Application accessed: '+name)
        m.NativeHome(NoApplication(),None,tlb,{},dict(native_read_count=0),classes,[],lambda:None)
        self.assertIsInstance(POINTER(classes[m.NC4])(),classes[m.NC4])

if __name__=='__main__':unittest.main()
