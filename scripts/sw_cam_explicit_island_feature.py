"""One explicit pocket and four islands, using the caller's guarded CAM context.

Caller owns copy/sketch authority, process lifetime, pinned files, one-use journal,
cleanup and terminal receipt. No Save, GOP/GTP, retries or world-frame inference.
"""
from copy import deepcopy
from ctypes import HRESULT, POINTER
from ctypes.wintypes import VARIANT_BOOL
from comtypes import BSTR
from comtypes.automation import IDispatch
import math
from scripts import sw_cam_autodetected_pocket as factory
from scripts import sw_cam_mill_profile_headers as headers
from scripts import sw_cam_mill_profile_indexed as indexed
from scripts import sw_cam_process_import as shared
from scripts.sw_cam import _member
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_qualification import _vector

SCOPE='ONE_POCKET_FOUR_EXPLICIT_ISLAND_COMPONENT_V1'
require=shared.require


def plan(value):
    keys={'owner_setup_native_id','axis_native','origin_native','outer_sketch_name',
          'island_sketch_names','depth_native','expected_shape','expected_attribute_suffix'}
    require(type(value)is dict and set(value)==keys,'Exact explicit-island plan required')
    v=deepcopy(value)
    require(type(v['owner_setup_native_id'])is int and 0<v['owner_setup_native_id']<2**31,'Actual owner ID required')
    require(type(v['expected_shape'])is int and 0<=v['expected_shape']<2**31,'Explicit Shape, distinct from SubType, required')
    for key in ('axis_native','origin_native'):
        require(type(v[key])is list and len(v[key])==3 and all(type(x)in(int,float)and math.isfinite(x)for x in v[key]),'Finite explicit frame required')
    require(abs(math.dist(v['axis_native'],[0.,0.,0.])-1.)<=1e-12,'Unit setup axis required')
    require(type(v['depth_native'])in(int,float)and math.isfinite(v['depth_native'])and 0<v['depth_native']<=100,'Positive bounded native depth required')
    require(type(v['island_sketch_names'])is list and len(v['island_sketch_names'])==4,'Exactly four explicit sketches required')
    names=[v['outer_sketch_name']]+v['island_sketch_names']
    require(all(type(n)is str and 0<len(n)<=1024 for n in names)and len({n.casefold()for n in names})==5,'Five distinct exact sketch names required')
    suffix=v['expected_attribute_suffix']
    require(type(suffix)is list and len(suffix)<=64,'Bounded declared attribute suffix required')
    require(all(type(r)is dict and set(r)=={'name','type'}and r['type']=='Attribute'and type(r['name'])is str and 0<len(r['name'])<=1024 for r in suffix),'Only predeclared CAD Attribute suffix admitted')
    require(len({r['name']for r in suffix})==len(suffix),'Unique attribute names required')
    return v


def preflight(tlb):
    old=factory.preflight(tlb)
    methods=[m for m in _interface_class('ICWSetup',tlb)._methods_ if m.name=='AddIslandToFeature']
    require(len(methods)==1,'One public AddIslandToFeature required');m=methods[0]
    require(m.restype is HRESULT and m.idlflags[0]==7 and m.argtypes==(POINTER(IDispatch),BSTR,POINTER(VARIANT_BOOL))and tuple(p[0]for p in m.paramflags)==(1,1,10),'Exact public AddIslandToFeature ABI required')
    old=dict(old,auto_detect_islands=False)
    return dict(factory=old,add_island=dict(interface='ICWSetup',method=m.name,dispid=7,return_type='strict bool'),auto_detect_islands=False,native_calls=0)


def empty_baseline(state,v):
    require(state.get('capture_complete')is True,'Complete current inventory required')
    require(all(type(state[k])is int and state[k]==0 for k in ('feature_count','operation_count','generated_operation_count','total_record_count')),'Pilot requires empty initialized CAM, never a second feature beside rejected paths')
    require(state['features']==[]and state['operations']==[],'Empty feature/operation tables required')
    owners=state['feature_setups']
    require(len(owners)==1 and owners[0]['native_id']==v['owner_setup_native_id']and owners[0]['feature_ids']==[]and owners[0]['axis_native']==v['axis_native']and owners[0]['origin_native']==v['origin_native'],'Exact initialized empty owner required')


def verify_header(h,v,count):
    fid=h['native_id']
    require(type(fid)is int and fid>0 and fid!=v['owner_setup_native_id'],'Actual new feature ID required')
    require(h['owner_setup_native_id']==v['owner_setup_native_id']and h['volume_type']==2 and h['shape']==v['expected_shape']and h['suppressed']is False and h['axis_native']==v['axis_native']and factory.native_depth_close(h['depth_native'],v['depth_native'])and h['taper_angle_native']==0. and type(h['island_count'])is int and h['island_count']==count,'Explicit feature scalar readback differs')


def verify_delta(before,after,h,v):
    v=plan(v);empty_baseline(before,v);verify_header(h,v,4)
    require(after.get('capture_complete')is True,'Complete post-creation inventory required')
    actual=deepcopy(after);fid=h['native_id']
    require(actual['feature_count']==1 and len(actual['features'])==1,'Exactly one new feature required')
    row=actual['features'][0]
    require(row['native_id']==fid and row['setup_native_id']==v['owner_setup_native_id']and row['setup_index']==0 and row['feature_index']==0 and row['volume_type']==2 and row['suppressed']is False,'Unexpected new feature membership/classification')
    require(len(actual['feature_setups'])==1 and actual['feature_setups'][0]['feature_ids']==[fid],'Exact owner membership required')
    actual['features']=[];actual['feature_count']=0;actual['feature_setups'][0]['feature_ids']=[]
    old_tree=before['sw_reference']['feature_tree'];observed=actual['sw_reference']['feature_tree']
    require(observed==old_tree+v['expected_attribute_suffix'],'Unrequested CAD tree delta')
    actual['sw_reference']['feature_tree']=deepcopy(old_tree)
    require(factory.same_inventory(before,actual),'Unrequested inventory/body/setup/operation/path delta')
    return dict(new_feature_native_id=fid,island_count=4,prior_inventory_preserved=True,exact_declared_attribute_suffix=deepcopy(v['expected_attribute_suffix']),physical_depth_verified=False,world_profile_placement_verified=False,machining_eligible=False,production_qualified=False)


class Backend:
    """Reuse an existing guarded ImportContext; no new application/document binding."""
    def __init__(self,context):self.ctx=context
    def boundary(self):self.ctx.verify_files();self.ctx.verify_owned()
    def capture(self,label):return self.ctx.capture(label,empty=False)
    def _owner(self,g,v):
        doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3')
        machine=g.typed(g.read(g.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
        rows=shared._items(g.read(machine,'IGetEnumSetups'),g.typed,g.read,8)
        require(len(rows)==1 and _object_id(doc,rows[0],g.read)==v['owner_setup_native_id'],'Exact single setup required')
        return doc,g.typed(rows[0],'ICWSetup')
    def _feature(self,g,doc,fid):
        value=g.read(doc,'GetCWObjectFromID',headers.CW_OBJ_FEAT,fid)
        require(type(value)in(list,tuple)and len(value)==2 and value[1]is True,'Exact feature lookup requires object and strict true')
        raw=value[0];base=g.typed(raw,'ICWFeature')
        require(_object_id(doc,base,g.read)==fid,'Feature lookup identity differs');return raw,base
    def adopt(self):
        self.ctx.check_events();actual=self.ctx.identity();a,b=deepcopy(actual),deepcopy(self.ctx.expected)
        require(type(a.pop('needs_save'))is bool and type(b.pop('needs_save'))is bool and a==b,'Mutation changed owned document identity')
        self.ctx.expected=actual;self.ctx.verify_files();self.ctx.verify_owned()
    def create(self,v,pending,returned):
        with self.ctx.guard()as g:
            doc,setup=self._owner(g,v)
            def invoke():
                value=_member(setup,'CreateMillFeature2',0,v['outer_sketch_name'],False,float(v['depth_native']),False,False,False,False,0.,-1,False,0,0)
                returned(dict(native_return_type=type(value).__name__,native_return_is_object=value is not None and type(value)not in(int,float,bool,str,bytes,list,tuple)))
                return value
            raw=g.dispatch_once(invoke,persist_pending=pending)
        require(raw is not None and type(raw)not in(int,float,bool,str,bytes,list,tuple),'Native factory must return an object')
        self.adopt()
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');fid=_object_id(doc,g.typed(raw,'ICWFeature'),g.read)
            require(type(fid)is int and fid>0,'Actual returned feature ID required');g._boundary()
        return fid
    def add(self,v,fid,name,pending,returned):
        with self.ctx.guard()as g:
            doc,setup=self._owner(g,v);raw,base=self._feature(g,doc,fid)
            require(_object_id(doc,g.read(base,'GetOwner'),g.read)==v['owner_setup_native_id'],'AddIsland target owner differs')
            def invoke():
                value=_member(setup,'AddIslandToFeature',raw,name)
                returned(dict(native_return_type=type(value).__name__,native_return_value=value if type(value)in(bool,int,float,str,type(None))else None))
                return value
            value=g.dispatch_once(invoke,persist_pending=pending)
        require(type(value)is bool and value is True,'Strict native true required; no retry');self.adopt()
    def read_header(self,v,fid,count,diagnostic,persist):
        with self.ctx.guard()as g:
            doc,_=self._owner(g,v);selected=dict(feature_native_id=fid,owner_setup_native_id=v['owner_setup_native_id'],volume_type=2,shape=v['expected_shape'],island_count=count)
            observed=headers.read_profile_feature_headers(doc,selected=selected,read=g.read,typed=g.typed,diagnostic=diagnostic,progress=persist)
            raw,base=self._feature(g,doc,fid);mill=g.typed(raw,'ICWMillFeature')
            scalar=dict(native_id=fid,owner_setup_native_id=observed['owner_setup_native_id'],suppressed=observed['suppressed'],volume_type=observed['volume_type'],shape=observed['shape'],island_count=observed['island_count'],axis_native=_vector(g.read(base,'Axis')),depth_native=factory.number(g.read(mill,'Depth')),taper_angle_native=factory.number(g.read(mill,'IGetTaperAngle')))
            g._boundary()
        wanted=[v['outer_sketch_name']]+v['island_sketch_names'][:count]
        require(observed['sketch_count']==len(wanted)and observed['sketch_names']['value']==wanted,'Exact ordered outer/island names required')
        return dict(scalars=scalar,headers=observed)
    def read_indexed(self,v,fid,anchored,diagnostic,persist):
        names=[v['outer_sketch_name']]+v['island_sketch_names']
        mapping=[dict(native_index=i,expected_sketch_name=n)for i,n in enumerate(names)]
        selected=dict(feature_native_id=fid,owner_setup_native_id=v['owner_setup_native_id'],volume_type=2,shape=v['expected_shape'],island_count=4)
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3')
            value=indexed.read_profile_indexed_chains(doc,selected=selected,index_mapping=mapping,anchor={'headers':anchored},read=g.read,typed=g.typed,boundary=lambda _:g._boundary(),diagnostic=diagnostic,progress=persist)
            g._boundary()
        return value


def create_one(backend,request_plan,*,claim,persist,report,verify_chains):
    """claim(action) must fsync never-reusable target intent before each dispatch.
    verify_chains binds the readback to pinned signed-sketch proofs. Native world
    placement/height and machining remain unqualified even after this succeeds.
    """
    v=plan(request_plan);require(type(report)is dict and not report,'Fresh component report required')
    require(all(callable(x)for x in(claim,persist,verify_chains)),'Explicit durable caller callbacks required')
    report.update(scope=SCOPE,status='running',plan=v,actions=[],native_call_attempted=False,auto_detect_islands=False,Save_attempted=False,GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,model_saved=False,automatic_retry=False,definition_readback_verified=False,island_geometry_verified=False,physical_depth_verified=False,machining_eligible=False,production_qualified=False)
    def dispatch(name,fn):
        action=dict(name=name,pending=False,attempted=False,returned=False);report['actions'].append(action);persist()
        def pending():
            claim(name);action.update(pending=True,attempted=True);report['native_call_attempted']=True;persist()
        def returned(value):action.update(value,pending=False,returned=True);persist()
        return fn(pending,returned)
    try:
        backend.boundary();before=backend.capture('explicit_feature_before');report['before']=deepcopy(before);persist();empty_baseline(before,v)
        fid=dispatch('CreateMillFeature2',lambda pending,returned:backend.create(v,pending,returned));report['new_feature_native_id']=fid;persist()
        for count in range(5):
            if count:
                name=v['island_sketch_names'][count-1]
                dispatch('AddIslandToFeature:'+name,lambda pending,returned:backend.add(v,fid,name,pending,returned))
            diagnostic={};report['current_header_diagnostic']=diagnostic
            observed=backend.read_header(v,fid,count,diagnostic,persist)
            report.setdefault('header_readbacks',[]).append(deepcopy(observed));persist();verify_header(observed['scalars'],v,count)
        diagnostic={};report['indexed_diagnostic']=diagnostic
        chains=backend.read_indexed(v,fid,observed['headers'],diagnostic,persist);report['indexed_readback']=deepcopy(chains);persist()
        proof=verify_chains(chains);require(type(proof)is dict and proof.get('indexed_chain_binding_verified')is True,'Explicit signed-sketch/chain binding proof required')
        report['chain_proof']=proof;persist()
        after=backend.capture('explicit_feature_after');report['after']=deepcopy(after);persist()
        report['delta_proof']=verify_delta(before,after,observed['scalars'],v);backend.boundary()
        report.update(status='definition_observed',definition_readback_verified=True,indexed_readback_complete=True,inventory_delta_verified=True)
        return report
    except Exception:
        report.update(status='uncertain'if report['native_call_attempted']else'error',definition_readback_verified=False,inventory_delta_verified=False);raise
    finally:
        try:persist()
        except Exception:
            report.update(status='uncertain'if report['native_call_attempted']else'error',
                          definition_readback_verified=False,inventory_delta_verified=False,
                          indexed_readback_complete=False,receipt_write_failed=True)
            raise