import json, unittest, inspect
from unittest.mock import patch
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_finish_diagnostic_read as d

class Contract(unittest.TestCase):
    def request(self):
        p={k:'a'*64 if k.endswith('_sha256') else str(Path('test.json').resolve()) for k in d.PARAMS}
        p.update(process_id=123,addin_clsid='{00000000-0000-0000-0000-000000000000}',module_sha256=d._file_hash(d.__file__))
        return dict(action='read_finish_diagnostics',params=p)
    def test_valid_request(self):self.assertEqual(d.validate_request(self.request())['process_id'],123)
    def test_unknown_action(self):
        r=self.request();r['action']='generate'
        with self.assertRaises(ValueError):d.validate_request(r)
    def test_unknown_field(self):
        r=self.request();r['params']['setter']=True
        with self.assertRaises(ValueError):d.validate_request(r)
    def test_wrong_digest(self):
        r=self.request();r['params']['module_sha256']='0'*64
        with self.assertRaises(ValueError):d.validate_request(r)
    def test_bool_pid(self):
        r=self.request();r['params']['process_id']=True
        with self.assertRaises(ValueError):d.validate_request(r)
    def test_unlisted_getter_invalidates(self):
        b=object.__new__(d.ReadBatch);b._invalid=False
        with self.assertRaises(ValueError):b.read(object(),'GenerateToolpath')
        self.assertTrue(b._invalid)
    def test_unlisted_interface_invalidates(self):
        b=object.__new__(d.ReadBatch);b._invalid=False
        with self.assertRaises(ValueError):b.typed(object(),'ICWUnknown')
        self.assertTrue(b._invalid)
    def test_backend_never_mutates(self):
        text=inspect.getsource(d.dispatch_request)
        for forbidden in ('.generate(','.save(','.set_field(','.assign(','.dispatch_once('):self.assertNotIn(forbidden,text)
    def test_tool_binding_uses_operation_interface(self):
        reference={'operations':[dict(native_id=n,suppressed=False,toolpath_generated=False,linked_feature_ids=[f],assigned_tool={'native_id':t},toolpath_record_counts=[],mill_operation_type=1) for n,f,t in [(144,79,273),(248,244,249)]]}
        def read(obj,name,*args):
            if name=='GetCWObjectFromID':return [('raw',args[1]),True]
            owner,n=obj
            if name=='IGetTool':
                self.assertEqual(owner,'ICWOperation');return ('tool',273 if n==144 else 249)
            if name=='IGetAllFeatures':return [('feature',79 if n==144 else 244)]
            if name=='IGetEnumToolpaths':return []
            if name in ('Suppressed','GetIsToolpathGenerated'):return False
            if name=='OpernType':return 1
            raise AssertionError(name)
        def typed(obj,name):return (name,obj[1])
        with patch.object(d,'_items',side_effect=lambda v,*a:v),patch.object(d,'_object_id',side_effect=lambda doc,obj,*a:obj[1]):
            rows,_=d.binding(('doc',1),reference,read=read,typed=typed)
        self.assertEqual(rows['144']['tool_id'],273)
    def test_read_failure_not_retried(self):
        b=object.__new__(d.ReadBatch);b._invalid=False;b._known_objects=set();b.progress=lambda *a:None
        calls=[]
        def observed(*a):calls.append(1);raise RuntimeError('read failed')
        b._observe_read=observed
        with self.assertRaises(RuntimeError):b.read(object(),'GetText')
        self.assertEqual(calls,[1]);self.assertTrue(b._invalid)

if __name__=='__main__':unittest.main()
