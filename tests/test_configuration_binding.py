import importlib.util, json, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'scripts/sw_cam_configuration_binding.py'
s=importlib.util.spec_from_file_location('binding_reader',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Tests(unittest.TestCase):
    def binding(self,own='Mill - Metric - 0',sw='По умолчанию'):
        c={'ConfigurationName':own,'SWConfigurationName':sw};d={'GetActiveConfigurationName':'Mill - Metric - 0','GetActiveConfiguration':c}
        return m.config_binding(d,'По умолчанию',read=lambda o,n:o[n],typed=lambda o,n:o)
    def test_separate_cam_and_sw_names(self):
        row=self.binding();m.require_binding(row);self.assertNotEqual(row['cam_configuration_name'],row['sw_configuration_name'])
    def test_wrong_sw_owner_rejected(self):
        with self.assertRaises(ValueError):m.require_binding(self.binding(sw='Other'))
    def test_stale_cam_configuration_object_rejected(self):
        with self.assertRaises(ValueError):m.require_binding(self.binding(own='Turn - Metric - 1'))
    def test_blank_mapping_rejected(self):
        with self.assertRaises(ValueError):self.binding(sw='')
    def test_nc_rows_and_bounded_getters(self):
        calls=[]
        def read(o,n):calls.append(n);return o[n]
        handles={322:{'IGetTurnNCParam':{'GetSpndlSpeed':1200.,'GetFeedRateIPM':12.}},129:{'IGetTurnNCParam':{'GetSpndlSpeed':800.,'GetFeedRateIPM':8.}}}
        rows=m.read_nc([322,129],handles,read=read,typed=lambda o,n:o)
        self.assertTrue(all(r['status']=='observed' for r in rows));self.assertEqual(calls.count('IGetTurnNCParam'),2);self.assertNotIn('IGetTool',calls)
    def test_nc_null_error_preserved_and_second_read(self):
        handles={322:{'IGetTurnNCParam':None},129:{'IGetTurnNCParam':{'GetSpndlSpeed':800.,'GetFeedRateIPM':8.}}}
        rows=m.read_nc([322,129],handles,read=lambda o,n:o[n],typed=lambda o,n:o)
        self.assertEqual(rows[0]['status'],'error');self.assertEqual(rows[0]['stage'],'IGetTurnNCParam');self.assertIn('issue',rows[0]);self.assertEqual(rows[1]['status'],'observed')
    def test_nc_second_getter_error_retains_first(self):
        rows=m.read_nc([322],{322:{'IGetTurnNCParam':{'GetSpndlSpeed':1200.}}},read=lambda o,n:o[n],typed=lambda o,n:o)
        self.assertEqual(rows[0]['spindle_speed_native'],1200.);self.assertEqual(rows[0]['stage'],'GetFeedRateIPM');self.assertEqual(rows[0]['status'],'error')
    def test_nonfinite_nc_rejected(self):
        rows=m.read_nc([322],{322:{'IGetTurnNCParam':{'GetSpndlSpeed':float('nan')}}},read=lambda o,n:o[n],typed=lambda o,n:o)
        self.assertEqual(rows[0]['status'],'error')
    def test_inventory_protects_ids_order_generated_records(self):
        features=[{'id':74},{'id':76}]
        ops=[{'id':127,'OpernType':7,'GetIsToolpathGenerated':True,'IGetEnumToolpaths':[{'RecordCount':40}],'IGetAllFeatures':[features[0]],'Suppressed':False},
             {'id':322,'OpernType':5,'GetIsToolpathGenerated':False,'IGetAllFeatures':[features[1]],'Suppressed':False}]
        machine={'IGetEnumSetups':[{'IGetEnumFeatures':features}],'IGetEnumOpSetups':[{'IGetEnumOperations':ops}],'IGetWorkpiece':{'GetTurnWorkpieceType':3}}
        def read(o,n,*args):
            if n=='Count':return len(o)
            if n=='Item':return o[args[0]]
            if n=='GetCWObjectID':return(args[0]['id'],True)
            return o[n]
        state,handles=m.read_inventory({},machine,read=read,typed=lambda o,n:o)
        self.assertEqual([o['native_id'] for o in state['operations']],[127,322]);self.assertEqual(state['inventory']['operations'][0]['toolpath_record_counts'],[40]);self.assertFalse(state['inventory']['operations'][1]['toolpath_generated']);self.assertEqual(set(handles),{127,322})
    def test_mutation_and_tool_members_absent(self):
        for name in ('IGetTool','SetTool','GenerateToolpath','SaveActiveDocument','ActivateConfiguration','ActivateConfiguration2'):
            self.assertNotIn(name,m.GETTERS)
    def test_reader_rejects_unknown_interface_and_unretained_owner(self):
        r=m.NativeReader(None,{}, {},{},lambda:None)
        with self.assertRaises(ValueError):r.read(object(),'MachType')
        with self.assertRaises(ValueError):r.typed(object(),'ICWUnknown')
if __name__=='__main__':unittest.main(verbosity=2)
