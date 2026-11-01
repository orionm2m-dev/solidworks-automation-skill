"""Portable contract tests; no CAD, COM package or installed runtime required."""
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('finish_diagnostics', Path(__file__).parents[1] / 'scripts/sw_cam_finish_diagnostics.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Fake:
    def __init__(self, op_id=144, feat_id=79):
        self.op, self.feature, self.doc, self.nc = object(), object(), object(), object()
        self.ids = {self.op: (op_id, True), self.feature: (feat_id, True)}
        self.values = {name: False if kind == 'bool' else [0.3,False] if kind == 'double_bool' else 0 for fields in m.FIELDS.values() for name, kind in fields}
        self.values.update(GetText='raw operation description', GetRebuildOk=True)
        self.areas = {name: (None, False) for name in m.AREA_MEMBERS}
        self.collections = {}
        self.calls, self.qis = [], []
    def typed(self, obj, interface):
        self.qis.append(interface)
        return obj
    def read(self, obj, name, *args):
        self.calls.append((name, args))
        if name == 'GetCWObjectID': return self.ids[args[0]]
        if name == 'IGetNCParam': return self.nc
        if name in self.areas: return self.areas[name]
        if name == 'Count': return len(self.collections[obj])
        if name == 'Item': return self.collections[obj][args[0]]
        return self.values[name]
    def run(self):
        return m.read_finish_diagnostics(self.op, self.feature, self.doc, read=self.read, typed=self.typed)
    def add_areas(self, count, supported=True):
        col = object(); items = [object() for _ in range(count)]
        self.collections[col] = items
        for i, item in enumerate(items): self.ids[item] = (500+i, supported)
        self.areas['IGetAllContainAreas'] = (col, True)


class ReadContracts(unittest.TestCase):
    def test_both_target_pairs_and_json(self):
        for oid, fid in ((144,79),(248,244)):
            f=Fake(oid,fid); r=f.run(); json.dumps(r,allow_nan=False)
            self.assertEqual((r['operation_native_id'],r['feature_native_id']),(oid,fid))
            self.assertFalse(r['read_complete']); self.assertTrue(r['supported_fields_read_complete']); self.assertFalse(r['production_qualified'])
            self.assertFalse(r['text_is_documented_error_message'])
            self.assertEqual(r['native_read_count'],len(f.calls))
    def test_getter_whitelist_contains_no_writes(self):
        self.assertFalse(any(n.startswith(('Set','Put','Generate','Save','Add','Remove')) for n in m.ALLOWED_MEMBERS))
        f=Fake();f.run();self.assertTrue(all(n in m.ALLOWED_MEMBERS for n,_ in f.calls))
    def test_wrong_target_stops_before_settings(self):
        for ids in ((143,79),(144,244),(248,79)):
            f=Fake(*ids)
            with self.assertRaises(ValueError):f.run()
            self.assertEqual([n for n,_ in f.calls],['GetCWObjectID','GetCWObjectID'])
    def test_strict_booleans(self):
        for value in (0,1,'false',None):
            f=Fake();f.values['GougeCheck']=value
            with self.assertRaises(ValueError):f.run()
    def test_strict_longs(self):
        for value in (True,1.0,2**31,-2**31-1):
            f=Fake();f.values['ContourMillRestMachMethod']=value
            with self.assertRaises(ValueError):f.run()
    def test_finite_bounded_scalars(self):
        for value in (True,float('nan'),float('inf'),-float('inf'),1e10,'2'):
            f=Fake();f.values['ContourMillRestMachCutDiameter']=value
            with self.assertRaises(ValueError):f.run()
    def test_text_is_raw_and_bounded(self):
        f=Fake();f.values['GetText']='error-looking text';r=f.run()
        self.assertEqual(r['raw_operation_text'],'error-looking text')
        self.assertFalse(r['text_is_documented_error_message'])
        for value in (None,17,'x'*16385):
            f=Fake();f.values['GetText']=value
            with self.assertRaises(ValueError):f.run()
    def test_exact_area_pair(self):
        for value in (None,False,(None,), (None,False,0),(None,0),(None,True)):
            f=Fake();f.areas['IGetAllContainAreas']=value
            with self.assertRaises(ValueError):f.run()
    def test_empty_collection_supported(self):
        f=Fake();f.add_areas(0);r=f.run()
        self.assertEqual(r['areas']['IGetAllContainAreas']['count'],0)
    def test_maximum_bounded_collection_and_ids(self):
        f=Fake();f.add_areas(16);r=f.run();a=r['areas']['IGetAllContainAreas']
        self.assertEqual(a['count'],16);self.assertEqual(a['items'][-1]['native_id'],515)
        self.assertLessEqual(r['native_read_count'],m.MAX_READS)
    def test_count_bound_before_enumeration(self):
        f=Fake();f.add_areas(17)
        with self.assertRaises(ValueError):f.run()
        self.assertNotIn('Item',[n for n,_ in f.calls])
    def test_unsupported_area_id_is_explicit(self):
        f=Fake();f.add_areas(1,False);r=f.run()
        self.assertEqual(r['areas']['IGetAllContainAreas']['items'][0],{'index':0,'supported':False,'native_id':None})
    def test_undefined_nonempty_collection_rejected(self):
        f=Fake();f.add_areas(1);col,_=f.areas['IGetAllContainAreas'];f.areas['IGetAllContainAreas']=(col,False)
        with self.assertRaises(ValueError):f.run()
    def test_null_item_rejected(self):
        f=Fake();f.add_areas(1);col,_=f.areas['IGetAllContainAreas'];f.collections[col]=[None]
        with self.assertRaises(ValueError):f.run()
    def test_target_id_contract(self):
        for value in ((0,True),(144,False),(144,1),(True,True),(2**32,True),(144,True,1)):
            f=Fake();f.ids[f.op]=value
            with self.assertRaises(ValueError):f.run()
    def test_read_failure_has_no_retry(self):
        f=Fake();reads=[]
        def read(obj,name,*args):
            reads.append(name)
            if name=='GougeCheck':raise RuntimeError('native read failed')
            return f.read(obj,name,*args)
        with self.assertRaisesRegex(RuntimeError,'native read failed'):
            m.read_finish_diagnostics(f.op,f.feature,f.doc,read=read,typed=f.typed)
        self.assertEqual(reads.count('GougeCheck'),1)
    def test_query_failure_has_no_fallback(self):
        f=Fake();qis=[]
        def typed(obj,name):
            qis.append(name)
            if name=='ICWFinishMillOp3':raise RuntimeError('QI failed')
            return obj
        with self.assertRaisesRegex(RuntimeError,'QI failed'):
            m.read_finish_diagnostics(f.op,f.feature,f.doc,read=f.read,typed=typed)
        self.assertEqual(qis.count('ICWFinishMillOp3'),1)
    def test_collection_count_strict(self):
        for invalid in (True,-1,1.5):
            f=Fake();f.add_areas(1);original=f.read
            def read(obj,name,*args):return invalid if name=='Count' else original(obj,name,*args)
            with self.assertRaises(ValueError):
                m.read_finish_diagnostics(f.op,f.feature,f.doc,read=read,typed=f.typed)




    def test_lock_interface_is_explicitly_unobserved(self):
        f=Fake();r=f.run()
        self.assertNotIn('ICWObject',f.qis)
        self.assertNotIn('GetLock',[n for n,_ in f.calls])
        self.assertNotIn('GetLock',m.ALLOWED_MEMBERS)
        self.assertNotIn('ICWObject',m.IIDS)
        self.assertEqual(r['unobserved_fields'][0]['status'],'not_observed_unsupported_interface')
        self.assertFalse(r['read_complete'])
    def test_ctypes_null_collection_is_empty_when_not_defined(self):
        from ctypes import POINTER,c_int
        for member in m.AREA_MEMBERS:
            f=Fake();f.areas[member]=(POINTER(c_int)(),False);r=f.run()
            self.assertEqual(r['areas'][member]['count'],0)
            self.assertFalse(r['areas'][member]['collection_present'])
    def test_defined_null_pointer_fails(self):
        from ctypes import POINTER,c_int
        f=Fake();f.areas['IGetAllContainAreas']=(POINTER(c_int)(),True)
        with self.assertRaisesRegex(ValueError,'null collection'):f.run()
    def test_null_pointer_item_fails(self):
        from ctypes import POINTER,c_int
        f=Fake();f.add_areas(1);col,_=f.areas['IGetAllContainAreas'];f.collections[col]=[POINTER(c_int)()]
        with self.assertRaisesRegex(ValueError,'Null area collection item'):f.run()
    def test_false_scalars_are_not_null_pointers(self):
        for value in (False,0,[],{}):self.assertFalse(m._null_pointer(value))


    def test_depth_pairs_preserve_value_and_percent_flag(self):
        f=Fake()
        for n in ('GetFirstDepthCut','GetMaxDepthCut','GetSideCutAmt'):f.values[n]=(50.0,True)
        f.values['GetIsSingleCutDepth']=True;f.values['DepthProcessOpt']=1
        r=f.run();v=r['values']['ICWFinishMillOp3']
        for n in ('GetFirstDepthCut','GetMaxDepthCut','GetSideCutAmt'):self.assertEqual(v[n],[50.0,True])
        self.assertIs(v['GetIsSingleCutDepth'],True)
        self.assertEqual(r['values']['ICWFinishMillOp']['DepthProcessOpt'],1)
    def test_depth_pair_rejects_wrong_order_shape_or_type(self):
        for invalid in ((False,.3),(.3,0),(float('nan'),False),(.3,),(.3,False,0),.3):
            f=Fake();f.values['GetFirstDepthCut']=invalid
            with self.assertRaises(ValueError):f.run()


class AuditContracts(unittest.TestCase):
    def tables(self):
        from types import SimpleNamespace
        classes = {name: SimpleNamespace(_methods_=[]) for name in m.IIDS}
        for spec in m.ABI_SPECS:
            classes[spec['interface']]._methods_.append(SimpleNamespace(
                name=spec['native_name'], dispid=spec['dispid'], args=tuple(spec['args']),
                flags=tuple(spec['paramflags'])))
        def verifier(member, dispid, args, flags):
            if (member.dispid,member.args,member.flags)!=(dispid,args,flags):
                raise ValueError('ABI differs')
        return classes, verifier
    def test_all_allowed_members_audited(self):
        self.assertEqual({s['member'] for s in m.ABI_SPECS},set(m.ALLOWED_MEMBERS))
        classes,v=self.tables();self.assertEqual(len(m._check_abi_members(classes,m.ABI_SPECS,v,str)),26)
    def test_disps_and_out_order_must_match(self):
        for attr,value in [('dispid',999),('flags',(10,2)),('args',('WRONG',))]:
            classes,v=self.tables();spec=m.ABI_SPECS[0]
            setattr(classes[spec['interface']]._methods_[0],attr,value)
            with self.assertRaisesRegex(ValueError,'ABI differs'):
                m._check_abi_members(classes,m.ABI_SPECS,v,str)
    def test_missing_or_duplicate_member_fails(self):
        for duplicate in (False,True):
            classes,v=self.tables();spec=m.ABI_SPECS[0];lst=classes[spec['interface']]._methods_
            if duplicate:lst.append(lst[0])
            else:lst.pop(0)
            with self.assertRaisesRegex(ValueError,'Unique native getter'):
                m._check_abi_members(classes,m.ABI_SPECS,v,str)
    def test_method_vs_property_name_is_exact(self):
        classes,v=self.tables()
        spec=next(s for s in m.ABI_SPECS if s['native_name'].startswith('_get_'))
        member=next(x for x in classes[spec['interface']]._methods_ if x.name==spec['native_name'])
        member.name=spec['member']
        with self.assertRaisesRegex(ValueError,'Unique native getter'):
            m._check_abi_members(classes,m.ABI_SPECS,v,str)


if __name__=='__main__': unittest.main()
