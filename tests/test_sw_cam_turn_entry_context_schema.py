"""Portable schema/ABI boundary tests; no application or native calls.

SWMCP_RUNTIME_ROOT selects the unchanged dependency runtime while testing staging.
SWMCP_CAM_TYPELIB explicitly enables the public ABI metadata test.
"""
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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, ValidationError

STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT', STAGE))
sys.path.insert(0,str(RUNTIME))
from scripts.sw_operation_guard import absolute_document_path


def models():
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
            model_validator=model_validator,Optional=typing.Optional,Literal=typing.Literal,
            Enum=enum.Enum,Path=Path,absolute_document_path=absolute_document_path)
    tree=ast.parse((RUNTIME/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    for name in ('ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput'):
        node=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'existing_server_bases','exec'),ns)
    snippet=STAGE/'SERVER_REGISTRATION_SNIPPET.py'
    scope=ast.parse(snippet.read_text(encoding='utf-8')) if snippet.exists() else tree
    for name in ('SolidWorksCamTurnEntryTargetInput','SolidWorksCamTurnEntryContextInput'):
        node=next(x for x in scope.body if isinstance(x,ast.ClassDef) and x.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'entry_context_schema','exec'),ns)
    return ns


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.schema=models()['SolidWorksCamTurnEntryContextInput']
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'fixture.sldprt';self.source.write_bytes(b'synthetic schema fixture; no CAD document')
    def values(self):
        return dict(addin_clsid='{00000000-0000-0000-0000-000000000001}',response_format='json',
            process_id=12345,expected_process_create_time=1234567890.125,
            expected_document_path=str(self.source),expected_source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            expected_feature_count=3,expected_operation_count=4,expected_operation_setup_count=1,
            expected_generated_operation_count=1,expected_total_record_count=7,
            targets=[dict(operation_native_id=501,feature_native_id=301,setup_index=0,operation_index=0,operation_type=7),
                     dict(operation_native_id=502,feature_native_id=301,setup_index=0,operation_index=1,operation_type=8)],
            receipt_path=str(Path(self.temp.name)/'new_read.json'),qualification_only=True,message_policy='vendor_default',
            post_parameter_index_policy='probe_zero_through_count_inclusive')
    def test_generic_request_accepts_exact_inherited_schema(self):
        self.assertEqual(self.schema.model_validate(self.values()).targets[0].operation_type,7)
    def test_face_kind_float_string_and_bool_refused_before_coercion(self):
        for bad in (7.0,'7',True):
            with self.subTest(bad=bad):
                v=self.values();v['targets'][0]['operation_type']=bad
                with self.assertRaises(ValidationError):self.schema.model_validate(v)
    def test_unknown_target_field_cannot_disappear_in_model_dump(self):
        v=self.values();v['targets'][0]['set_home']=True
        with self.assertRaises(ValidationError):self.schema.model_validate(v)
    def test_unknown_top_field_refused(self):
        v=self.values();v['generate']=True
        with self.assertRaises(ValidationError):self.schema.model_validate(v)


class MetadataTests(unittest.TestCase):
    def test_explicit_public_abi_and_no_application_constructor(self):
        tlb=os.environ.get('SWMCP_CAM_TYPELIB')
        if not tlb:self.skipTest('Set SWMCP_CAM_TYPELIB for the installed public ABI metadata test')
        spec=importlib.util.spec_from_file_location('entry_metadata',STAGE/'scripts/sw_cam_turn_entry_context.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        classes,abi=m.preflight(tlb)
        self.assertEqual(abi['getter_count'],29);self.assertEqual(abi['native_calls'],0)
        class NoApplication:
            def __getattribute__(self,name):raise AssertionError('Application accessed: '+name)
        m.NativeRead(NoApplication(),None,None,{}, {}, classes,[],lambda:None)

if __name__=='__main__':unittest.main()