"""Offline save-only regression tests; AST-loaded helpers never import COM packages."""
import ast
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import io
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[1]


def load_definitions(path, namespace, names=None):
    tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))
             and (names is None or getattr(n, 'name', None) in names)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)


def module_fixture():
    ns = dict(Path=Path, json=json, re=re, deepcopy=deepcopy, monotonic=time.monotonic,
        hashlib=hashlib, os=os, tempfile=tempfile, time=time, ntpath=ntpath, stat=stat, ExitStack=ExitStack)
    for file, names in (
        ('sw_operation_guard.py', {'absolute_document_path', '_path_identity', 'check_document_target', 'SolidWorksDocumentMismatch'}),
        ('sw_cam_generation.py', {'_write_receipt'}), ('sw_cam_thread.py', {'_file_hash'}),
        ('sw_cam_turn_tool.py', {'_digest'}), ('sw_cam_mill_inventory.py', {'validate_inventory_request'}),
        ('sw_cam_mill_feature_context.py', {'_capture_file_stamp', '_CaptureReadFiles'})):
        load_definitions(RUNTIME/'scripts'/file, ns, names)
    load_definitions(STAGE/'scripts/sw_cam_ud14_probe_core.py', ns, {'verify_one_new_tool'})
    load_definitions(STAGE/'scripts/sw_cam_ud14_qualification.py', ns, {'ud14_attempt_marker'})
    load_definitions(STAGE/'scripts/sw_cam_ud14_save.py', ns)
    return ns


class CoreFixture:
    def __init__(self, ns):
        self.ns=ns; self.report={}; self.log=[]; self.n=0; self.fail=None; self.ret=0
    def capture(self, label):
        self.n+=1; self.log.append('capture:'+label)
        if self.fail=='capture:'+label: raise RuntimeError('capture failure')
        return {'same':False if self.fail=='changed_after' and label=='after' else True}
    def verify(self, value):
        if value!={'same':True}:raise ValueError('changed')
    def guard(self):self.log.append('guard')
    def persist(self):
        self.log.append('persist:'+self.report.get('phase',''))
        if self.fail=='persist_pending' and self.report.get('save_pending'):raise OSError('durable report fail')
    def claim(self):
        self.log.append('claim')
        if self.fail=='claim':raise FileExistsError('existing marker')
    def save(self):
        self.log.append('SAVE')
        if self.fail=='save_unknown':raise RuntimeError('lost return')
        return self.ret
    def saved_hash(self):self.log.append('hash_after');return 'f'*64
    def run(self):
        self.ns['run_one_existing_save'](self.report,capture=self.capture,verify=self.verify,
            guard=self.guard,claim=self.claim,persist=self.persist,save=self.save,saved_hash=self.saved_hash)


class SaveCoreTests(unittest.TestCase):
    def setUp(self):self.ns=module_fixture()
    def test_one_save_two_captures_claim_before_save(self):
        f=CoreFixture(self.ns);f.run()
        self.assertEqual(f.n,2);self.assertEqual(f.log.count('SAVE'),1)
        self.assertLess(f.log.index('claim'),f.log.index('SAVE'))
        self.assertLess(f.log.index('SAVE'),f.log.index('hash_after'))
        self.assertTrue(f.report['save_readback_verified'])
    def test_before_mismatch_prevents_save(self):
        f=CoreFixture(self.ns);f.fail='capture:before'
        with self.assertRaises(RuntimeError):f.run()
        self.assertNotIn('SAVE',f.log)
    def test_exclusive_claim_failure_prevents_save(self):
        f=CoreFixture(self.ns);f.fail='claim'
        with self.assertRaises(FileExistsError):f.run()
        self.assertNotIn('SAVE',f.log)
    def test_pending_report_failure_prevents_save(self):
        f=CoreFixture(self.ns);f.fail='persist_pending'
        with self.assertRaises(OSError):f.run()
        self.assertNotIn('SAVE',f.log)
    def test_unknown_save_is_pending_and_not_replayed(self):
        f=CoreFixture(self.ns);f.fail='save_unknown'
        with self.assertRaises(RuntimeError):f.run()
        self.assertTrue(f.report['save_pending']);self.assertEqual(f.log.count('SAVE'),1);self.assertEqual(f.n,1)
    def test_non_hresult_zero_does_not_read_after(self):
        for ret in (None,True,1):
            f=CoreFixture(self.ns);f.ret=ret
            with self.assertRaises(ValueError):f.run()
            self.assertEqual(f.n,1);self.assertEqual(f.log.count('SAVE'),1)
    def test_changed_after_never_repeats_save(self):
        f=CoreFixture(self.ns);f.fail='changed_after'
        with self.assertRaises(ValueError):f.run()
        self.assertEqual(f.log.count('SAVE'),1);self.assertNotIn('save_readback_verified',f.report)


class NativeWrapperFixture:
    def __init__(self, ns, folder):
        self.ns=ns; self.folder=Path(folder); self.calls=[]; self.open_count=0; self.dirty=False;self.unknown=False
        self.source=self.folder/'qualification.SLDPRT';self.source.write_bytes(b'old source')
        self.mt=self.folder/'sample.mt';self.mt.write_bytes(b'Version Clouds\nline 0 0 1 1\n')
        self.source_sha=ns['_file_hash'](self.source);mt_sha=ns['_file_hash'](self.mt)
        self.identity={'path':str(self.source),'title':self.source.name,'type':1,'needs_save':False}
        self.metric={'SW_document_units_raw':[0,1,0,2,0],'CAM_use_document_units_raw':True,
            'metric_document_scope_observed':True,'MT_units_verified':False,'native_CAM_geometry_units_verified':False}
        self.tool={'native_id':213,'tool_type_raw':14,'profile_complete':True,'parameters':{'CutLength':0},
            'profiles':{'tool':{'status':'observed'},'shank':{'status':'observed'}},'mt_path_raw':str(self.mt)}
        self.tools=[{'native_id':7,'tool_type_raw':1},{'native_id':213,'tool_type_raw':14}]
        self.context={'feature_setups':[{'native_id':1,'feature_ids':[2,3]}],'operation_setups':[]}
        self.probe=self.folder/'probe.json';self.output=self.folder/'save.json'
        e=dict(scope='isolated_ud14_specimen',status='review_required',phase='finished',process_id=1,
            new_tool_native_id=213,expected_source_sha256=self.source_sha,expected_document_path=str(self.source),
            tool_reads=[deepcopy(self.tool),deepcopy(self.tool)],before_tools=self.tools[:1],after_tools=self.tools,
            before_context=self.context,after_metric_scope=self.metric,after_cleanup_document=self.identity,
            specimen={'path':str(self.mt),'sha256':mt_sha})
        for k in ('raw_readback_stable','exact_one_tool_created','protected_context_unchanged','full_profiles_complete','creation_returned','load_returned'):e[k]=True
        for k in ('creation_pending','load_pending','operation_assignment_attempted','GTP_attempted','GOP_attempted','TechDB_write_attempted','model_saved','post_cleanup_CAM_getters'):e[k]=False
        e['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
        ns['_write_receipt'](self.probe,e,create=True);self.probe_sha=ns['_file_hash'](self.probe)
        self.creation=ns['ud14_attempt_marker'](self.source,self.source_sha,mt_sha)
        ns['_write_receipt'](self.creation,dict(new_tool_native_id=213,creation_pending=False,load_pending=False,
            creation_returned=True,load_returned=True,receipt_path=str(self.probe)),create=True)
        self.marker=ns['ud14_save_marker'](self.source,self.probe_sha,213)
        self.args=dict(process_id=1,expected_document_path=str(self.source),expected_source_sha256=self.source_sha,
            expected_tool_native_id=213,probe_receipt_path=str(self.probe),probe_receipt_sha256=self.probe_sha,
            qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(self.output))
        parent=self
        class Session:
            def __init__(self,*args):self.active=False;self.done=False
            def __enter__(self):self.active=True;return self
            def __exit__(self,*args):self.active=False;self.done=True
            def summary(self):return dict(subscribed=True,active=self.active,disconnected=self.done,event_count=0)
        self.events=SimpleNamespace(CamMessageSession=Session)
        original_capture=ns['_CaptureReadFiles']
        class TrackedCapture(original_capture):
            def __enter__(self):
                result=super().__enter__();parent.open_count+=1;return result
            def __exit__(self,*args):
                try:return super().__exit__(*args)
                finally:parent.open_count-=1
        ns['_CaptureReadFiles']=TrackedCapture
        self.rawtool=SimpleNamespace(native_id=213)
        crib=SimpleNamespace(GetAllTools=lambda:[self.rawtool])
        machine=SimpleNamespace(MachType=1,IGetToolcrib=lambda:crib)
        doc=SimpleNamespace(GetDocType=lambda:1,IGetMachine=lambda:machine)
        app=SimpleNamespace(IGetActiveDoc=lambda:doc,SaveActiveDocument=self.save)
        self.sw=SimpleNamespace(GetProcessID=lambda:1,ActiveDoc=object())
        def member(obj,name,*args):
            value=getattr(obj,name);return value(*args) if callable(value) else value
        ns.update(_member=member,_error=lambda exc:{'type':type(exc).__name__},
            _typed=lambda obj,name,tlb:obj,_bootstrap=lambda *a:app,
            raw_part_identity=lambda sw:dict(self.identity,needs_save=self.dirty),
            _check_capture_document=lambda *a:None,_items=lambda raw,*a:raw,
            _object_id=lambda doc,obj,read:obj.native_id,
            capture_local_tools=lambda *a:deepcopy(self.tools),
            capture_protected_context=lambda *a:deepcopy(self.context),
            read_ud14_tool=lambda *a,**kw:deepcopy(self.tool),
            read_document_cam_unit_scope=lambda *a,**kw:deepcopy(self.metric))
    def save(self):
        self.calls.append('SAVE')
        assert self.open_count==0,'read handles still open'
        state=json.loads(self.marker.read_text());assert state['save_pending'] is True
        if self.unknown:raise RuntimeError('transport loss')
        self.source.write_bytes(b'new source with CAM')
        return 0
    def run(self):
        package=ModuleType('scripts');package.__path__=[]
        with patch.dict(sys.modules,{'scripts':package,'scripts.sw_cam_events':self.events}):
            return self.ns['save_existing_ud14'](self.sw,'fixture-clsid','fixture.tlb',**self.args)


class SaveWrapperTests(unittest.TestCase):
    def setUp(self):
        self.ns=module_fixture();self.temp=tempfile.TemporaryDirectory(dir=STAGE/'tests')
        self.addCleanup(self.temp.cleanup);self.f=NativeWrapperFixture(self.ns,self.temp.name)
    def test_wrapper_save_closes_files_preserves_context_and_records_new_hash(self):
        original_marker=self.f.creation.read_bytes();result=self.f.run()
        self.assertEqual(result['status'],'review_required',result)
        self.assertTrue(result['model_saved']);self.assertTrue(result['save_readback_verified'])
        self.assertEqual(result['capture_count'],2);self.assertEqual(self.f.calls,['SAVE'])
        self.assertEqual(result['before'],result['after'])
        self.assertNotEqual(result['saved_file_sha256'],self.f.source_sha)
        self.assertEqual(original_marker,self.f.creation.read_bytes())
        self.assertEqual(self.f.open_count,0)
    def test_dirty_or_changed_identity_rejected_before_cam_save(self):
        self.f.dirty=True;result=self.f.run()
        self.assertEqual(result['status'],'error');self.assertEqual(self.f.calls,[])
        self.assertFalse(self.f.marker.exists())
    def test_unknown_save_new_receipt_is_blocked_by_independent_marker(self):
        self.f.unknown=True;result=self.f.run()
        self.assertEqual(result['status'],'uncertain');self.assertEqual(self.f.calls,['SAVE'])
        self.assertTrue(json.loads(self.f.marker.read_text())['save_pending'])
        values=dict(self.f.args,receipt_path=str(self.f.folder/'other.json'))
        with self.assertRaisesRegex(ValueError,'Prior save attempt'):
            self.ns['validate_ud14_save_request'](**values)
    def test_prior_marker_exclusive_claim_cannot_be_replaced(self):
        self.ns['_write_receipt'](self.f.marker,{'prior':True},create=True)
        with self.assertRaisesRegex(ValueError,'Prior save attempt'):
            self.ns['validate_ud14_save_request'](**self.f.args)
        self.assertEqual(self.f.calls,[])
    def test_incomplete_probe_rejected(self):
        data=json.loads(self.f.probe.read_text());data['full_profiles_complete']=False
        self.f.probe.write_text(json.dumps(data));self.f.args['probe_receipt_sha256']=self.ns['_file_hash'](self.f.probe)
        with self.assertRaisesRegex(ValueError,'Incomplete successful'):
            self.ns['validate_ud14_save_request'](**self.f.args)
    def test_changed_profile_before_save_rejected(self):
        self.f.tool['parameters']['CutLength']=19
        result=self.f.run();self.assertEqual(result['status'],'error');self.assertEqual(self.f.calls,[])
        self.assertFalse(self.f.marker.exists())
    def test_source_contains_only_save_native_mutation_and_no_close(self):
        text=(STAGE/'scripts/sw_cam_ud14_save.py').read_text(encoding='utf-8')
        tree=ast.parse(text)
        direct=[x.args[1].value for x in ast.walk(tree) if isinstance(x,ast.Call)
            and isinstance(x.func,ast.Name) and x.func.id=='_member' and len(x.args)>1
            and isinstance(x.args[1],ast.Constant)]
        self.assertEqual(direct.count('SaveActiveDocument'),1)
        self.assertFalse(set(direct)&{'AddNewTool3','SetToolName','SetTool','GenerateOpPlan','GenerateToolpath','CloseActiveDocument','CloseDoc'})
