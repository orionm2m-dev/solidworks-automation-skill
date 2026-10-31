"""Contract tests for the bounded existing start-point reader."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import unittest

STAGED=Path(__file__).resolve().parents[1]/'scripts'/'sw_cam_rough_startpoint_read.py'
spec=importlib.util.spec_from_file_location('startpoint_reader_under_test',STAGED)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Owner:
    def __init__(self,**values):self.__dict__.update(values)

class StartPointTests(unittest.TestCase):
    def graph(self,kind=3,coords=(0.,0.,0.)):
        position=Owner(GetCoordinates=lambda:coords)
        point=Owner(StartPointType=kind,Position=position)
        coll=Owner(Count=1,Item=lambda index:point)
        op=Owner(GetHoleCentreEntry=lambda feature:True,GetEntryExitType=lambda feature:0,GetStartPointList=lambda feature:coll)
        return op,coll,point
    def execute(self,op,metadata=None,typed=None):
        self.trace=[]
        def read(obj,name,*args):
            self.trace.append(name)
            # Use the permanent shared COM member helper, not a duplicated mock dispatcher.
            return m._member(obj,name,*args)
        def query(obj,name):self.trace.append('QI '+name);return obj
        self.diag={}
        return m.read_startpoints(op,Owner(),read=read,typed=typed or query,
            metadata=metadata or (lambda _:dict(guid=m.COLLECTION_IID,name='ICWDispatchCollection')),diagnostic=self.diag)
    def test_hole_center_actual_native_shape(self):
        op,_,_=self.graph();r=self.execute(op)
        self.assertEqual(r['rows'],[dict(index=0,type_raw=3,type_name='CW_HOLECENTER',position_native=[0.,0.,0.],position_is_null=False)])
        self.assertTrue(r['read_complete']);self.assertTrue(r['collection_interface_verified'])
        self.assertFalse(r['position_frame_qualified'])
    def test_user_defined_shape(self):
        op,_,_=self.graph(1,(10.,0.,0.));self.assertEqual(self.execute(op)['rows'][0]['type_name'],'CW_USERDEFINED')
    def test_null_list_does_not_query_collection(self):
        op,_,_=self.graph();op.GetStartPointList=lambda feature:None
        r=self.execute(op);self.assertTrue(r['list_is_null']);self.assertNotIn('QI ICWDispatchCollection',self.trace)
    def test_empty_collection(self):
        op,c,_=self.graph();c.Count=0;self.assertEqual(self.execute(op)['rows'],[])
    def test_null_position_is_explicit(self):
        op,_,p=self.graph();p.Position=None;self.assertTrue(self.execute(op)['rows'][0]['position_is_null'])
    def test_foreign_type_stops_before_qi(self):
        op,_,_=self.graph()
        with self.assertRaisesRegex(ValueError,'metadata'):self.execute(op,metadata=lambda _:dict(guid='{OTHER}',name='Different'))
        self.assertNotIn('QI ICWDispatchCollection',self.trace)
        self.assertEqual(self.diag['observation']['collection_type_info']['name'],'Different')
    def test_count_bound_and_strict_bool(self):
        for value in (-1,9,True,1.0):
            op,c,_=self.graph();c.Count=value
            with self.assertRaisesRegex(ValueError,'count'):self.execute(op)
    def test_unknown_type(self):
        op,_,_=self.graph(7)
        with self.assertRaisesRegex(ValueError,'type'):self.execute(op)
    def test_nonfinite_coordinate(self):
        op,_,_=self.graph(coords=(float('nan'),0.,0.))
        with self.assertRaisesRegex(ValueError,'Finite'):self.execute(op)
    def test_three_coordinates_required(self):
        op,_,_=self.graph(coords=(10.,0.))
        with self.assertRaisesRegex(ValueError,'Finite'):self.execute(op)
    def test_count_stability(self):
        op,c,_=self.graph();calls=iter((1,2));c.Count=lambda:next(calls)
        with self.assertRaisesRegex(ValueError,'size changed'):self.execute(op)
    def test_read_scope_cannot_mutate(self):
        self.assertNotIn('CreateStartPointInstance',m.GETTERS);self.assertNotIn('SetStartPointList',m.GETTERS)
        self.assertNotIn('SetCoordinates',m.GETTERS);self.assertNotIn('Add',m.GETTERS)
    def test_qi_failure_keeps_type_info(self):
        op,_,_=self.graph()
        def query(obj,name):
            if name=='ICWDispatchCollection':raise ValueError('QI refused')
            return obj
        with self.assertRaisesRegex(ValueError,'QI refused'):self.execute(op,typed=query)
        self.assertEqual(self.diag['observation']['collection_type_info']['guid'],m.COLLECTION_IID)
    def test_installed_metadata_accessor_shape(self):
        from comtypes.typeinfo import TYPEATTR
        from comtypes import GUID
        a=TYPEATTR();a.guid=GUID(m.COLLECTION_IID);a.typekind=4;a.cFuncs=5
        info=Owner(GetTypeAttr=lambda:a,GetDocumentation=lambda n:('ICWDispatchCollection',None,0,None))
        raw=Owner(GetTypeInfo=lambda index:info)
        batch=object.__new__(m.StartPointReadBatch)
        batch.observed=lambda owner,label,name,invoke:invoke()
        self.assertEqual(batch.metadata(raw),dict(guid=m.COLLECTION_IID,typekind=4,member_count=5,name='ICWDispatchCollection'))

if __name__=='__main__':unittest.main()
