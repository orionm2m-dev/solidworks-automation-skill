"""Portable scalar regression; all IDs are synthetic fixtures."""
import importlib.util
import math
from pathlib import Path
import unittest
import tempfile
import hashlib
from scripts import sw_cam_current_floor_wall_scalars as reader

class PureReadContractTests(unittest.TestCase):
    def state(self):
        rows=[dict(native_id=1000+i) for i in range(28)]
        for oid,(fid,kind,count) in {101:(301,0,100),102:(302,1,22)}.items():
            rows.append(dict(native_id=oid, setup_native_id=401, linked_feature_ids=[fid],
                mill_operation_type=kind,base_operation_type=0,suppressed=False,
                toolpath_generated=True,toolpath_record_counts=[count],assigned_tool={'native_id':201}))
        return {'operations':rows,'selected_pair_observations':{'targets':[{'operation_native_id':101}]}}
    def fake(self, override=None):
        calls=[]; seen={}; objects={oid:object() for oid in (101,102)}; reverse={id(v):k for k,v in objects.items()}
        def typed(obj,name):
            self.assertIn(name, {'ICWMillOperation','ICWNCParam3','ICWNCParam4'});return obj
        def read(obj,name):
            oid=reverse[id(obj)];calls.append((oid,name));seen[oid,name]=seen.get((oid,name),0)+1
            if name=='IGetNCParam':return obj
            value={'ToolpathFeedLength':31.4,'ToolpathRapidLength':42.0,'ToolpathTotalLength':73.4,
                'FeedPlaneType':1,'FeedPlaneDistance':0.5,'GetUseCurrentMachiningDepthForFeedPlane':False}[name]
            return override(oid,name,seen[oid,name],value) if override else value
        return objects,read,typed,calls
    def runfake(self,override=None):
        handles,read,typed,calls=self.fake(override);progress=[]
        result=reader.observe_values(handles,read=read,typed=typed,progress=progress.append)
        return result,calls,progress
    def test_exact_native_payload_count_and_stable_triples(self):
        result,calls,progress=self.runfake()
        self.assertTrue(result['complete']);self.assertEqual(result['first'],result['second'])
        self.assertEqual(sum(name in {x[1] for x in reader.LENGTHS} for _,name in calls),12)
        self.assertEqual(sum(name in {x[1] for x in reader.PLANES} for _,name in calls),6)
        self.assertEqual(sum(name=='IGetNCParam' for _,name in calls),2)
        self.assertEqual(len(progress),19)
    def test_bad_length_scalars_fail(self):
        for bad in [True,-1.0,float('nan'),float('inf'),1,'1']:
            with self.subTest(bad=repr(bad)),self.assertRaises(ValueError):
                self.runfake(lambda oid,name,n,value:bad if name=='ToolpathFeedLength' else value)
    def test_different_second_read_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'triples differ'):
            self.runfake(lambda oid,name,n,value:value+0.1 if name=='ToolpathFeedLength' and n==2 else value)
    def test_bad_plane_types_fail(self):
        for field,bad in [('FeedPlaneType',True),('FeedPlaneType',2**31),('FeedPlaneDistance',1),('FeedPlaneDistance',float('nan')),('GetUseCurrentMachiningDepthForFeedPlane',0)]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.runfake(lambda oid,name,n,value:bad if name==field else value)
    def test_native_failure_never_replayed(self):
        handles,read,typed,calls=self.fake()
        def fail(obj,name):
            if name=='FeedPlaneDistance':calls.append(('failure',name));raise RuntimeError('native stop')
            return read(obj,name)
        with self.assertRaises(RuntimeError):reader.observe_values(handles,read=fail,typed=typed,progress=lambda _:None)
        self.assertEqual(calls.count(('failure','FeedPlaneDistance')),1)
        self.assertEqual(sum(name=='ToolpathFeedLength' for _,name in calls),2)
    def test_exact_saved_targets(self):
        selected=reader.selected_authority(self.state(),101,102);self.assertEqual(list(selected),[101,102])
        self.assertEqual(selected[101]['mill_operation_type'],0)
    def test_wrong_saved_record_count_and_kind_rejected(self):
        for key,bad in [('toolpath_record_counts',[0]),('mill_operation_type',1),('suppressed',0),('native_id',101.0),('linked_feature_ids',[False])]:
            state=self.state();state['operations'][-2][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):reader.selected_authority(state,101,102)
    def test_incomplete_and_duplicate_authority_rejected(self):
        state=self.state();state['operations'].pop()
        with self.assertRaises(ValueError):reader.selected_authority(state,101,102)
        state=self.state();state['operations'][0]=state['operations'][-2]
        with self.assertRaises(ValueError):reader.selected_authority(state,101,102)
    def test_generic_role_ids_and_saved_expected_rows(self):
        state=self.state();floor,wall=state['operations'][-2:]
        floor.update(native_id=501,setup_native_id=700,linked_feature_ids=[802],toolpath_record_counts=[120],assigned_tool={'native_id':999})
        wall.update(native_id=502,setup_native_id=700,linked_feature_ids=[803],toolpath_record_counts=[30],assigned_tool={'native_id':999})
        state['selected_pair_observations']['targets'][0]['operation_native_id']=501
        selected=reader.selected_authority(state,501,502)
        self.assertEqual(selected[501]['tool_native_id'],999)
        self.assertEqual(selected[502]['toolpath_record_counts'],[30])
    def test_private_bundle_detects_mutation_and_fingerprint_is_stable(self):
        bundle=reader._Prepared({'x':1},{'pins':[],'receipt':Path('receipt.json')})
        self.assertEqual(bundle.digest,bundle.fingerprint())
        bundle.loaded['pins'].append({'path':'changed','sha256':'0'*64})
        self.assertNotEqual(bundle.digest,bundle.fingerprint())
    def test_prepared_bundle_can_only_be_consumed_once(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle=reader._Prepared({'x':1},{'pins':[],'receipt':Path(temp)/'fresh.json'})
            reader._consume(bundle,{'x':1},lambda:None)
            with self.assertRaises(ValueError):reader._consume(bundle,{'x':1},lambda:None)
    def test_prepared_bundle_request_mutation_burns_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle=reader._Prepared({'x':1},{'pins':[],'receipt':Path(temp)/'fresh.json'})
            with self.assertRaises(ValueError):reader._consume(bundle,{'x':2},lambda:None)
            self.assertTrue(bundle.used)
    def test_prepared_bundle_rechecks_file_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=Path(temp)/'pin.txt';evidence.write_text('original')
            pin={'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
            bundle=reader._Prepared({'x':1},{'pins':[pin],'receipt':Path(temp)/'fresh.json'})
            evidence.write_text('changed')
            with self.assertRaises(ValueError):reader._consume(bundle,{'x':1},lambda:None)
    def test_mutating_members_absent(self):
        self.assertFalse(reader.GETTERS & {'Save','Save3','SaveActiveDocument','SaveCLFile','GenerateToolpath','CreateSTLOfWIPs2','SetClrPlanePrms','SetZFeedrate2'})
    def test_typed_comparison_does_not_accept_bool_as_integer(self):
        self.assertFalse(reader.exact({'a':[0]}, {'a':[False]}))

if __name__=='__main__': unittest.main(verbosity=2)
