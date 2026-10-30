"""Offline failure-ordering, preservation and parser tests; never attach to a CAD process."""
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

STAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE))
import scripts
scripts.__path__.insert(0, str(STAGE / 'scripts'))
from scripts.sw_cam_ud14_probe_core import run_single_probe
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_ud14_specimen import read_mt_specimen
from scripts.sw_cam_ud14_qualification import validate_ud14_request, read_ud14_tool, ud14_attempt_marker, claim_ud14_attempt


class FakeProbe:
    def __init__(self):
        self.report = {}; self.log = []; self.saved = []
        self.local_tools = [dict(native_id=4, tool_type_raw=1, diameter=2)]
        self.protected = dict(operations=[dict(native_id=7, tool_native_id=4)])
        self.raw = object(); self.read_count = 0; self.fail_save = None
        self.fail_create = False; self.fail_load = False; self.change_read = False
        self.change_sibling = False
    def guard(self): self.log.append('guard')
    def persist(self):
        phase = self.report['phase']
        self.log.append('persist:' + phase)
        if self.fail_save == phase: raise OSError('durable publication failed')
        self.saved.append(deepcopy(self.report))
    def create(self):
        self.log.append('create')
        if self.fail_create: raise RuntimeError('constructor transport failed')
        self.local_tools.append(dict(native_id=9, tool_type_raw=14, diameter=12))
        return self.raw
    def load(self, raw, path):
        self.log.append('load')
        if self.fail_load: raise RuntimeError('MT load failed')
        if self.change_sibling: self.local_tools[0]['diameter'] = 99
    def identify(self, raw): return 9
    def read(self, raw, diagnostic):
        self.read_count += 1
        row = dict(native_id=9, tool_type_raw=14, profile=[0, 1])
        if self.change_read and self.read_count == 2: row['profile'] = [0, 2]
        return row
    def run(self):
        return run_single_probe(report=self.report, guard=self.guard, persist=self.persist,
            create=self.create, load=self.load, identify=self.identify, read_tool=self.read,
            context=lambda: deepcopy(self.protected), tools=lambda: deepcopy(self.local_tools),
            specimen_path='pinned.mt')


class ProbeTests(unittest.TestCase):
    def test_single_create_load_and_double_read(self):
        f=FakeProbe(); r=f.run()
        self.assertEqual(f.log.count('create'),1); self.assertEqual(f.log.count('load'),1)
        self.assertEqual(f.read_count,2); self.assertTrue(r['raw_readback_stable'])
        self.assertLess(f.log.index('persist:create_pending'),f.log.index('create'))
        before_load=next(x for x in f.saved if x['phase']=='load_pending')
        self.assertEqual(before_load['new_tool_native_id'],9)
        self.assertFalse(before_load['creation_pending']); self.assertTrue(before_load['load_pending'])
    def test_failed_precreate_publication_does_not_create(self):
        f=FakeProbe();f.fail_save='create_pending'
        with self.assertRaises(OSError):f.run()
        self.assertNotIn('create',f.log);self.assertNotIn('load',f.log)
    def test_constructor_error_keeps_pending_without_replay(self):
        f=FakeProbe();f.fail_create=True
        with self.assertRaises(RuntimeError):f.run()
        self.assertEqual(f.log.count('create'),1);self.assertNotIn('load',f.log)
        self.assertTrue(f.saved[-1]['creation_pending'])
    def test_failed_preload_publication_leaves_identified_new_tool(self):
        f=FakeProbe();f.fail_save='load_pending'
        with self.assertRaises(OSError):f.run()
        self.assertEqual(f.report['new_tool_native_id'],9);self.assertNotIn('load',f.log)
    def test_load_error_has_no_cleanup_retry_or_reads(self):
        f=FakeProbe();f.fail_load=True
        with self.assertRaises(RuntimeError):f.run()
        self.assertEqual(f.log.count('load'),1);self.assertEqual(f.read_count,0)
        self.assertTrue(f.report['load_pending']);self.assertEqual(len(f.local_tools),2)
    def test_readback_difference_rejects(self):
        f=FakeProbe();f.change_read=True
        with self.assertRaisesRegex(ValueError,'Repeated'):f.run()
        self.assertNotIn('raw_readback_stable',f.report)
    def test_sibling_change_rejects(self):
        f=FakeProbe();f.change_sibling=True
        with self.assertRaisesRegex(ValueError,'unchanged siblings'):f.run()
    def test_identity_guard_failure_after_create_prevents_load(self):
        f=FakeProbe()
        def guard():
            if 'create' in f.log: raise ValueError('active document changed')
        f.guard=guard
        with self.assertRaisesRegex(ValueError,'active document'):f.run()
        self.assertEqual(f.log.count('create'),1);self.assertNotIn('load',f.log)
    def test_context_change_during_creation_prevents_load(self):
        f=FakeProbe();original=f.create
        def create():
            value=original();f.protected['operations'][0]['tool_native_id']=99;return value
        f.create=create
        with self.assertRaisesRegex(ValueError,'Protected context'):f.run()
        self.assertNotIn('load',f.log)
    def test_stable_raw_reads_do_not_imply_full_profiles(self):
        f=FakeProbe();r=f.run()
        self.assertTrue(r['raw_readback_stable']);self.assertFalse(r['full_profiles_complete'])
    def test_wrong_new_tool_type_stops_before_loading(self):
        f=FakeProbe();original=f.create
        def wrong():
            value=original();f.local_tools[-1]['tool_type_raw']=9;return value
        f.create=wrong
        with self.assertRaisesRegex(ValueError,'UD14'):f.run()
        self.assertNotIn('load',f.log)


class SpecimenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=STAGE/'tests')
        self.root=Path(self.tmp.name);self.mt=self.root/'sample.mt'
        self.data=b'Version Clouds\n# installed specimen\nline 0 0 1 0\nline 1 0 1 3\n'
        self.mt.write_bytes(self.data);self.sha=hashlib.sha256(self.data).hexdigest()
    def tearDown(self): self.tmp.cleanup()
    def test_raw_units_not_inferred(self):
        row=read_mt_specimen(str(self.mt),self.sha)
        self.assertEqual(row['coordinate_units'],'unqualified')
        self.assertEqual(row['segments'][1]['end_raw'],[1.,3.])
    def test_hash_mismatch(self):
        with self.assertRaisesRegex(ValueError,'hash'):read_mt_specimen(str(self.mt),'0'*64)
    def test_unknown_record_rejected(self):
        self.mt.write_bytes(self.data+b'unit mm\n')
        with self.assertRaisesRegex(ValueError,'Unsupported'):read_mt_specimen(str(self.mt),hashlib.sha256(self.mt.read_bytes()).hexdigest())
    def test_disconnected_profile_rejected(self):
        self.mt.write_bytes(self.data.replace(b'line 1 0 1 3',b'line 2 0 1 3'))
        with self.assertRaisesRegex(ValueError,'Disconnected'):read_mt_specimen(str(self.mt),hashlib.sha256(self.mt.read_bytes()).hexdigest())
    def test_nan_rejected(self):
        self.mt.write_bytes(self.data.replace(b'1 3',b'1 nan'))
        with self.assertRaisesRegex(ValueError,'Finite'):read_mt_specimen(str(self.mt),hashlib.sha256(self.mt.read_bytes()).hexdigest())
    def request(self):
        source=self.root/'isolated.SLDPRT';source.write_bytes(b'isolated')
        return dict(process_id=123,expected_document_path=str(source),expected_source_sha256='a'*64,
            mt_specimen_path=str(self.mt),mt_specimen_sha256=self.sha,
            expected_sw_document_units_raw=[0,0,0,0,0],expected_cam_use_document_units=True,
            qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(self.root/'receipt.json'))
    def test_request_requires_metric_scope(self):
        a=self.request();a['expected_sw_document_units_raw'][0]=3
        with self.assertRaisesRegex(ValueError,'millimetre'):validate_ud14_request(**a)
    def test_existing_receipt_prevents_replay(self):
        a=self.request();Path(a['receipt_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unique'):validate_ud14_request(**a)
    def test_unknown_creation_blocks_new_receipt_name(self):
        a=self.request();specimen=validate_ud14_request(**a)
        marker=ud14_attempt_marker(a['expected_document_path'],a['expected_source_sha256'],a['mt_specimen_sha256'])
        f=FakeProbe();f.fail_create=True;original=f.persist;claimed=False
        f.report.update(expected_document_path=a['expected_document_path'],
            expected_source_sha256=a['expected_source_sha256'],specimen=specimen)
        def persist():
            nonlocal claimed
            if f.report['phase']=='create_pending' and not claimed:
                claim_ud14_attempt(marker,f.report,a['receipt_path']);claimed=True
            original()
        f.persist=persist
        with self.assertRaises(RuntimeError):f.run()
        pending=json.loads(marker.read_text())
        self.assertTrue(pending['creation_pending'])
        a['receipt_path']=str(self.root/'different_receipt.json')
        with self.assertRaisesRegex(ValueError,'Prior UD dispatch marker'):validate_ud14_request(**a)
        self.assertEqual(f.log.count('create'),1)
    def test_unknown_load_blocks_new_receipt_name(self):
        a=self.request();specimen=validate_ud14_request(**a)
        marker=ud14_attempt_marker(a['expected_document_path'],a['expected_source_sha256'],a['mt_specimen_sha256'])
        f=FakeProbe();f.fail_load=True;original=f.persist;claimed=False
        f.report.update(expected_document_path=a['expected_document_path'],
            expected_source_sha256=a['expected_source_sha256'],specimen=specimen)
        def persist():
            nonlocal claimed
            if f.report['phase']=='create_pending' and not claimed:
                claim_ud14_attempt(marker,f.report,a['receipt_path']);claimed=True
            original()
        f.persist=persist
        with self.assertRaises(RuntimeError):f.run()
        pending=json.loads(marker.read_text())
        self.assertTrue(f.report['load_pending']);self.assertEqual(f.report['new_tool_native_id'],9)
        a['receipt_path']=str(self.root/'different_receipt.json')
        with self.assertRaisesRegex(ValueError,'Prior UD dispatch marker'):validate_ud14_request(**a)
        self.assertEqual(f.log.count('create'),1)
    def test_same_mt_bytes_under_another_name_share_attempt_key(self):
        a=self.request();first=ud14_attempt_marker(a['expected_document_path'],a['expected_source_sha256'],a['mt_specimen_sha256'])
        second=self.root/'renamed.mt';second.write_bytes(self.data)
        a['mt_specimen_path']=str(second)
        self.assertEqual(first,ud14_attempt_marker(a['expected_document_path'],a['expected_source_sha256'],a['mt_specimen_sha256']))
    def test_exclusive_attempt_claim(self):
        a=self.request();specimen=validate_ud14_request(**a)
        marker=ud14_attempt_marker(a['expected_document_path'],a['expected_source_sha256'],a['mt_specimen_sha256'])
        report=dict(expected_document_path=a['expected_document_path'],expected_source_sha256=a['expected_source_sha256'],specimen=specimen)
        claim_ud14_attempt(marker,report,a['receipt_path'])
        with self.assertRaises(FileExistsError):claim_ud14_attempt(marker,report,str(self.root/'other.json'))
    def test_strict_boolean_acknowledgement(self):
        a=self.request();a['qualification_only']=1
        with self.assertRaises(ValueError):validate_ud14_request(**a)
    def test_request_validates_without_native_calls(self):
        self.assertEqual(validate_ud14_request(**self.request())['sha256'],self.sha)


class ReaderTests(unittest.TestCase):
    def test_ud_reader_uses_ud_interface_and_both_full_profiles(self):
        tool=object();ud=object();seen=[]
        values={'ToolType':14,'IsMillTool':True,'GetToolName':'specimen.mt','CutDiameter':8.,
                'Protrusion':25.,'ShankDia':8.,'CutLength':19.,'OverallLength':63.,
                'TipOffset':0.,'TipLength':0.,'Flutes':4,'MillUDToolOutputType':1}
        def read(obj,name,*args): seen.append(name);return values[name]
        def typed(raw,name):
            self.assertIn(name,('ICWTool','ICWMillUDTool'))
            return tool if name=='ICWTool' else ud
        def profiles(owner,method,**kw):
            seen.append(method);kw['diagnostic']['state'].update(status='observed',chains=[{'all_segments_retained':True}])
        with patch('scripts.sw_cam_ud14_qualification._object_id',return_value=9),patch('scripts.sw_cam_ud14_qualification.read_segment_chains',side_effect=profiles):
            row=read_ud14_tool(tool,doc=object(),read=read,typed=typed,diagnostic={})
        self.assertEqual(set(row['profiles']),{'tool','shank'})
        self.assertIn('GetToolProfile',seen);self.assertIn('GetShankProfile',seen)
        self.assertNotIn('ShoulderLength',seen);self.assertFalse(row['units_verified'])


class UnitScopeTests(unittest.TestCase):
    def test_exact_known_getter_names(self):
        calls=[]
        def sw_read(obj,name): calls.append(name); return (0,0,2,0,3)
        def cam_read(obj,name): calls.append(name); return True
        row=read_document_cam_unit_scope(object(),object(),sw_read=sw_read,cam_read=cam_read)
        self.assertEqual(calls,['GetUnits','GetUseDocumentUnit'])
        self.assertTrue(row['metric_document_scope_observed']);self.assertFalse(row['MT_units_verified'])
    def test_unknown_cam_scope_is_returned_without_mutation(self):
        row=read_document_cam_unit_scope(object(),object(),sw_read=lambda *a:[0,0,2,0,3],cam_read=lambda *a:False)
        self.assertFalse(row['metric_document_scope_observed'])
    def test_five_strict_integers_required(self):
        for raw in ([0,0,2,0],[False,0,2,0,3],[0.,0,2,0,3]):
            with self.assertRaises(ValueError):read_document_cam_unit_scope(object(),object(),sw_read=lambda *a:raw,cam_read=lambda *a:True)
    def test_strict_native_cam_boolean_required(self):
        with self.assertRaises(ValueError):read_document_cam_unit_scope(object(),object(),sw_read=lambda *a:[0,0,2,0,3],cam_read=lambda *a:1)


if __name__=='__main__': unittest.main(verbosity=2)