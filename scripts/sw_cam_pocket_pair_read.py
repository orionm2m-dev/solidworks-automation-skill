"""Read missing settings of an existing pocket pair and its named face associations.

Existing indexed CAM chains and tool profiles are pinned and reused. This module
cannot set parameters, generate, export, or save. One retained read batch uses a
compact progress journal; complete observations are flushed only at boundaries.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import inspect
import math
from scripts import sw_cam_chamfer_receipt as receipt_loader
from scripts import sw_cam_chamfer_nc_planes as nc
from scripts import sw_cam_chamfer_clearance_read as planes
from scripts import sw_cam_rough_entry_parameters as rough
from scripts import sw_cam_finish_observation as finish
from scripts import sw_cam_finish_lead_observation as leads
from scripts import sw_cam_mill_levels as levels
from scripts import sw_cam_mill_profile_headers as profile
from scripts import sw_cam_mill_selected_plan_context as selected
from scripts import sw_cam_read_progress_journal as journal
from scripts.sw_cam_face_interfaces import FACE_IIDS,face_interface_class,_verify_generated_class
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require

common,group=nc.common,nc.group
SCOPE='SAVED_POCKET_PAIR_MISSING_PARAMETERS_READ_V1'
FEATURE=79
OPERATIONS=(143,144)
TOOL=145
MAX_CALLS=1900
PARAMS=nc.PARAMS|{'reuse_manifest_path','reuse_manifest_sha256','progress_path'}
CAM_INTERFACES=planes.INTERFACES|nc.INTERFACES|{'ICWMillFeature','ICWProfileFeature',
    'ICWRghMillOp','ICWMillOperation3','ICWToolpathParam','ICWPosition','ICWUnitVector',
    'ICWFinishMillOp2','ICWFinishMillOp3','ICWNCParam2'}
LEVEL_GETTERS={'GetMachiningDepth','GetOverrideMachiningDepth','GetToolpathParam','GetToolpathParameters',
    'GetSetupParameters','GetCoordinates'}
HEADER_GETTERS={'GetOwner','VolumeType','SubType','Shape','FeatureName','Axis','Depth','GetBoundParams',
    'GetStartPosition','IGetIslandCount','GetSketchCount','GetSketchNameList','GetEndCondition1','GetEndCondition2'}
CAM_GETTERS=planes.GETTERS|nc.GETTERS|LEVEL_GETTERS|HEADER_GETTERS|set(finish.FINISH_BASE_FIELDS)|set(finish.FINISH_V3_FIELDS)|{
    n for fields in (rough.ENTRY_FIELDS,rough.DEPTH_FIELDS,rough.BOUNDARY_FIELDS,rough.NC_FIELDS) for n,_ in fields}|{
    'GetPreviousAllowance','GetSpndlSpeed','GetTlpComp','GetCNCComp','XYFeed','GetZFeedrate2'}
SW_IIDS={
    'IPartDoc':'{83A33D32-27C5-11CE-BFD4-00400513BB57}',
    'IFeature':'{83A33D38-27C5-11CE-BFD4-00400513BB57}',
    'IAttribute':'{83A33D71-27C5-11CE-BFD4-00400513BB57}',
    'IEntity':'{83A33D65-27C5-11CE-BFD4-00400513BB57}',
    'IFace2':'{4A8BA4D8-DA25-4B75-8E2D-4922B74D81ED}',
    'ISurface':'{83A33D40-27C5-11CE-BFD4-00400513BB57}',
    'ILoop2':'{9350CA6E-0ADB-485A-8941-9407DD7B3B8E}',
    'IEdge':'{83A33D42-27C5-11CE-BFD4-00400513BB57}',
    'ICurve':'{83A33D44-27C5-11CE-BFD4-00400513BB57}',
    'ICurveParamData':'{03DFD291-2C77-494F-A81A-8C3653BAB985}',
}
SW_GETTERS={'FeatureByName','Name','GetTypeName2','GetSpecificFeature2','GetEntityState','GetEntity','GetType',
    'GetSurface','IsPlane','PlaneParams','GetBox','GetLoops','GetEdges','IsOuter','GetCurve','GetCurveParams3',
    'StartPoint','EndPoint','UMinValue','UMaxValue','Sense','IsLine','IsCircle','LineParams','CircleParams'}
ATTRIBUTE_STATES={'invalid':0,'suppressed':1,'ambiguous':2,'deleted':3}
RETIRED_NAMES={'sw_cam_chamfer_approach_correction.py','sw_cam_chamfer_generate.py','sw_cam_ud14_save.py',
    'sw_cam_finish_read_batch.py','sw_cam_cl_inventory.py'}


def cam_class(name,typelib,generated):
    require(name in CAM_INTERFACES|{'ICWDoc3'},'Interface outside pocket reader')
    if name in nc.EXTENSION_IIDS:return nc.interface_class(name,typelib,generated)
    if name in FACE_IIDS:return face_interface_class(name,typelib,generated_pin=generated)
    if name=='ICWOpSetup3':return planes.interface_class(name,typelib,generated)
    from scripts.sw_cam_comtypes import _interface_class,_INTERFACES
    return _verify_generated_class(_interface_class(name,str(typelib)),_INTERFACES[name],generated)


def sw_class(name):
    from win32com.client import gencache
    require(name in SW_IIDS,'SW interface outside face-association scope')
    cls=gencache.GetClassForCLSID(SW_IIDS[name])
    require(cls is not None and str(cls.CLSID).upper()==SW_IIDS[name],'Installed generated SW interface differs')
    return cls


def audit_interfaces(typelib,generated):
    rows=[]
    for name in sorted(CAM_INTERFACES):
        cls=cam_class(name,typelib,generated)
        rows.append(dict(interface=name,iid=str(cls._iid_).upper()))
    from ctypes import HRESULT,POINTER,c_double
    from ctypes.wintypes import VARIANT_BOOL
    z=cam_class('ICWNCParam4',typelib,generated)
    methods=[v for v in z._methods_ if v.name=='GetZFeedrate2']
    require(len(methods)==1 and methods[0].restype is HRESULT and int(methods[0].idlflags[0])==50
        and methods[0].argtypes==(POINTER(c_double),POINTER(VARIANT_BOOL))
        and tuple(v[0] for v in methods[0].paramflags)==(2,2),'Exact documented Z-feed output pair required')
    sw_pins=[]
    for name in SW_IIDS:sw_pins=common._merge(sw_pins,[common._pin(inspect.getfile(sw_class(name)))])
    return dict(cam_interfaces=rows,sw_generated_pins=sw_pins,
        nc=nc.audit_interfaces(typelib,generated),planes=planes.audit_interfaces(typelib,generated),
        z_feed_abi=dict(interface='ICWNCParam4',member='GetZFeedrate2',dispid=50,paramflags=[2,2],input_count=0),
        application_connections=0,native_calls=0,native_support_qualified=False)


def target_rows(loaded):
    rows=[r for r in loaded['state']['operations'] if r['native_id'] in OPERATIONS]
    require(len(rows)==2 and [r['native_id'] for r in rows]==list(OPERATIONS),'Exact ordered pocket pair required')
    for r,t in zip(rows,(0,1)):
        require(r['linked_feature_ids']==[FEATURE] and r['assigned_tool']['native_id']==TOOL
            and r['mill_operation_type']==t and r['base_operation_type']==0
            and r['suppressed'] is False and r['toolpath_generated'] is False and r['toolpath_record_counts']==[]
            and r['setup_native_id']==93,'Saved ungenerated pocket pair differs')
    return deepcopy(rows)


def read_binding(doc,loaded,*,read,typed):
    rows=target_rows(loaded);result=[];handles={}
    for expected in rows:
        found=read(doc,'GetCWObjectFromID',3,expected['native_id'])
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact operation lookup required')
        raw=found[0];op=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation')
        ident=_object_id(doc,op,read)
        links=[_object_id(doc,f,read) for f in _items(read(op,'IGetAllFeatures'),typed,read,2)]
        tool,tool_raw=read_generic_tool(raw,doc,read,typed)
        counts=[read(typed(p,'ICWToolpath'),'RecordCount') for p in _items(read(op,'IGetEnumToolpaths'),typed,read,2)]
        actual=dict(native_id=ident,linked_feature_ids=links,assigned_tool=tool,
            mill_operation_type=read(mill,'OpernType'),base_operation_type=read(op,'OpernType'),
            suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'),
            toolpath_record_counts=counts)
        require(group.exact(actual,{k:expected[k] for k in nc.TARGET_KEYS}),'Pocket operation/tool/generated binding changed')
        result.append(actual);handles[ident]=raw
    found=read(doc,'GetCWObjectFromID',1,FEATURE)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact pocket feature lookup required')
    expected=next(r for r in loaded['state']['features'] if r['geometry']['native_id']==FEATURE)
    header,feature=selected.read_header(found[0],doc,read,typed,expected['setup_native_id'])
    require(group.exact(header,expected['geometry']),'Pocket feature geometry header changed')
    handles.update(feature=feature,feature_dispatch=found[0])
    setup,raw_setup=planes.read_setup_binding(doc,loaded,read=read,typed=typed)
    require(setup['setup_native_id']==rows[0]['setup_native_id']==rows[1]['setup_native_id'],'Shared selected setup differs')
    handles['setup']=raw_setup
    return dict(operations=result,feature=header,setup=setup),handles


def read_levels(op,feature,*,read,typed,feature_dispatch):
    out={}
    def native_read(label,invoke,decoder=None,interface=False,validator=None):
        value=feature_dispatch(feature) if label=='QueryInterface.IDispatch.feature' else invoke()
        if interface:require(value is not None and bool(value),'Non-null level interface required')
        if validator:validator(value)
        return decoder(value) if decoder else value
    def getter(obj,interface_name,name,*args,**kwargs):
        return native_read(interface_name+'.'+name,lambda:read(obj,name,*args),**kwargs)
    levels.read_mill_level_values(feature,op,native_read=native_read,typed=typed,getter=getter,report=out)
    return out


def read_finish_parameters(op,feature,*,read,typed):
    result={};one=typed(op,'ICWFinishMillOp')
    for name in finish.FINISH_BASE_FIELDS:result[name]=rough.bounded_raw_observation(read(one,name))
    two=typed(op,'ICWFinishMillOp2')
    result['GetPreviousAllowance']=rough.bounded_raw_observation(read(two,'GetPreviousAllowance',feature))
    three=typed(op,'ICWFinishMillOp3')
    for name in finish.FINISH_V3_FIELDS:result[name]=rough.bounded_raw_observation(read(three,name))
    return result


def read_nc_settings(op,setup,*,read,typed,pointer_read,diagnostic,persist):
    result=dict(feed_planes=nc.read_planes(op,read=read,typed=typed,diagnostic=diagnostic.setdefault('feed',{})))
    result['clearance_rapid']=planes.read_plane_parameters(op,setup,read=read,typed=typed,pointer_read=pointer_read,
        diagnostic=diagnostic.setdefault('clearance_rapid',{}),persist=persist)
    raw=read(typed(op,'ICWMillOperation'),'IGetNCParam');owner=typed(raw,'ICWNCParam');owner2=typed(raw,'ICWNCParam2')
    result['feeds_compensation']={name:nc.scalar(kind,read(owner2 if name=='XYFeed' else owner,name))
        for name,kind in {'GetSpndlSpeed':'double','GetTlpComp':'long','GetCNCComp':'long',
            'GetRetractType':'long','XYFeed':'double'}.items()}
    z=read(typed(raw,'ICWNCParam4'),'GetZFeedrate2')
    require(type(z) in (tuple,list) and len(z)==2,'Exact Z-feed value/percentage pair required')
    result['z_feed']=dict(value_native=nc.scalar('double',z[0]),percentage=nc.scalar('bool',z[1]),
        physical_feed_units_verified=False,percentage_basis_verified=False)
    result['unread_feed_fields']=['Per-link feed and cutting ratings not qualified by this scalar observation']
    return result


def vector(value,length):
    require(type(value) in (tuple,list) and len(value)==length and all(type(v) in (int,float)
        and math.isfinite(v) for v in value),'Finite native vector of exact size required')
    return list(value)


def objects(value,maximum):
    require(type(value) in (tuple,list) and 1<=len(value)<=maximum and all(v is not None for v in value),
        'Bounded nonempty native object array required')
    return value


def read_face_associations(part,names,*,read,typed,diagnostic):
    require(type(names) is list and len(names)==6 and len(set(names))==6,'Six exact saved Attribute names required')
    result=[];diagnostic['rows']=result;edge_total=0
    for name in names:
        row=dict(name=name,status='reading',model_space_geometry_complete=False);result.append(row)
        raw=read(part,'FeatureByName',name)
        if raw is None:row.update(status='unresolved',reason='exact_named_feature_absent');continue
        feat=typed(raw,'IFeature')
        require(read(feat,'Name')==name,'Named feature lookup returned another feature')
        row['feature_type']=read(feat,'GetTypeName2')
        if row['feature_type']!='Attribute':row.update(status='unresolved',reason='not_Attribute');continue
        attr=typed(read(feat,'GetSpecificFeature2'),'IAttribute')
        row['entity_states']={k:nc.scalar('bool',read(attr,'GetEntityState',v)) for k,v in ATTRIBUTE_STATES.items()}
        if any(row['entity_states'].values()):row.update(status='unresolved',reason='invalid_association_state');continue
        entity_raw=read(attr,'GetEntity')
        if entity_raw is None:row.update(status='unresolved',reason='entity_null_or_document_association');continue
        ent=typed(entity_raw,'IEntity');kind=read(ent,'GetType');row['entity_type']=nc.scalar('long',kind)
        if kind!=2:row.update(status='unresolved',reason='associated_entity_not_face');continue
        face=typed(entity_raw,'IFace2');surface=typed(read(face,'GetSurface'),'ISurface')
        row['is_plane']=nc.scalar('bool',read(surface,'IsPlane'))
        if not row['is_plane']:row.update(status='unresolved',reason='associated_face_not_planar');continue
        row['plane_model_native']=vector(read(surface,'PlaneParams'),6)
        row['box_model_native']=vector(read(face,'GetBox'),6);row['box_is_approximate']=True
        row['loops']=[]
        for loop_raw in objects(read(face,'GetLoops'),16):
            loop=typed(loop_raw,'ILoop2');entry=dict(is_outer=nc.scalar('bool',read(loop,'IsOuter')),edges=[]);row['loops'].append(entry)
            for edge_raw in objects(read(loop,'GetEdges'),128):
                edge_total+=1;require(edge_total<=128,'Six-face total edge budget exceeded')
                edge=typed(edge_raw,'IEdge');param=typed(read(edge,'GetCurveParams3'),'ICurveParamData')
                curve=typed(read(edge,'GetCurve'),'ICurve')
                e=dict(start_model_native=vector(read(param,'StartPoint'),3),end_model_native=vector(read(param,'EndPoint'),3),
                    parameter_range=[nc.scalar('double',read(param,'UMinValue')),nc.scalar('double',read(param,'UMaxValue'))],
                    curve_sense=nc.scalar('bool',read(param,'Sense')))
                entry['edges'].append(e)
                line=nc.scalar('bool',read(curve,'IsLine'));circle=nc.scalar('bool',read(curve,'IsCircle'))
                require(not (line and circle),'Curve cannot be both line and circle')
                if line:e.update(kind='line',line_params_model_native=vector(read(curve,'LineParams'),6))
                elif circle:e.update(kind='circle',circle_params_model_native=vector(read(curve,'CircleParams'),7))
                else:e.update(kind='other',analytic_geometry_complete=False)
        complete=all(e['kind'] in ('line','circle') for l in row['loops'] for e in l['edges'])
        row.update(status='observed',model_space_geometry_complete=complete,model_coordinate_units='metre',
            cam_chain_transform_inferred=False,retained_side_qualified=False)
    diagnostic['complete']=True
    return dict(rows=result,all_six_faces_observed=all(r['status']=='observed' for r in result),
        all_six_analytic_geometry_complete=all(r['model_space_geometry_complete'] for r in result),
        total_edges=edge_total,geometric_role_mapping_verified=False,production_qualified=False)


class PocketReadBatch(planes.ReadBatch):
    def __init__(self,*args,progress,progress_state,**kwargs):
        self.progress=progress;self.progress_state=progress_state
        super().__init__(*args,**kwargs)
    def reject(self,condition,message):
        if not condition:
            self._invalid=True;self._completed=False
            raise ValueError(message)
    def observed(self,obj,label,member,invoke):
        self.progress_state.update(member=member,returned=False)
        self.progress()
        value=self._observe_read(obj,label,invoke)
        self.progress_state.update(returned=True,read_index=self._read_calls+self._qi_calls)
        self.progress();return value
    def read(self,obj,name,*args):
        self.reject(name in CAM_GETTERS|SW_GETTERS,'Getter outside exact pocket read scope')
        for arg in args:self.reject(type(arg) is int or (type(arg) is str and len(arg)<=128) or id(arg) in self._known_objects,
            'Argument outside retained graph')
        return self.observed(obj,'getter',name,lambda:_member(obj,name,*args))
    def typed(self,obj,name):
        self.reject(name in CAM_INTERFACES,'Interface outside exact pocket read scope')
        cls=cam_class(name,self.typelib_path,self.generated_pin)
        def query():
            value=obj.QueryInterface(cls)
            require(value is not None and bool(value) and isinstance(value,cls),'Exact non-null CAM interface required')
            return value
        return self.observed(obj,'qi',name,query)
    def sw_typed(self,obj,name):
        self.reject(name in SW_IIDS,'SW interface outside exact association scope')
        cls=sw_class(name)
        return self.observed(obj,'qi',name,lambda:cls(obj._oleobj_))
    def feature_dispatch(self,obj):
        from comtypes.automation import IDispatch
        return self.observed(obj,'qi','IDispatch',lambda:obj.QueryInterface(IDispatch))
    def plane(self,obj,name,diagnostic):
        self.reject(name in planes.POINTER_FIELDS,'Pointer getter outside qualified pair')
        return self.observed(obj,'getter',name,lambda:planes.pointer_value(obj,name,diagnostic))


class NativeBackend(nc.NativeBackend):
    def observe(self):
        r=self.report;handles={};state=dict(phase='binding',member='',returned=False,read_index=0)
        with self.ctx.guard() as g:swdoc=g.read(self.sw,'ActiveDoc')
        def binding():
            self.events();require(_member(self.doc,'GetDocType')==1,'Retained CAM part changed')
            for key in OPERATIONS:
                if key in handles:require(_object_id(self.doc,handles[key],_member)==key,'Retained pocket identity changed')
            self.events()
        protected=[self.args['expected_document_path'],self.args['receipt_path']]+[p['path'] for p in self.loaded['pins']]
        with journal.ReadProgressJournal(full_persist=self.persist,progress_path=self.args['progress_path'],
                describe=lambda:dict(state,phase=r['phase']),max_updates=4096,protected_paths=protected) as progress:
            b=PocketReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
                process_id=self.args['process_id'],expected_document=self.ctx.identity(),source_sha256=self.args['expected_source_sha256'],
                evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,
                check_events=self.events,retained_objects=(self.doc,swdoc),verify_retained_binding=binding,
                max_native_calls=MAX_CALLS,progress=progress.read,progress_state=state)
            try:
                with b:
                    r['before_binding'],h=read_binding(self.doc,self.loaded,read=b.read,typed=b.typed);handles.update(h)
                    r['phase']='profile_headers'
                    r['profile_headers']=profile.read_profile_feature_headers(self.doc,selected=self.loaded['reuse_selected'],
                        read=b.read,typed=b.typed,diagnostic=r.setdefault('profile_diagnostic',{}),progress=progress.read)
                    require(group.exact(r['profile_headers'],self.loaded['reuse_profile_headers']),'Saved six-chain metadata changed')
                    r['parameters']={}
                    for oid in OPERATIONS:
                        r['phase']='parameters_'+str(oid);out={};r['parameters'][str(oid)]=out
                        out['levels']=read_levels(handles[oid],handles['feature'],read=b.read,typed=b.typed,feature_dispatch=b.feature_dispatch)
                        if oid==143:
                            out['rough']=rough.read_rough_entry_parameters(handles[oid],handles['feature_dispatch'],read=b.read,typed=b.typed,
                                diagnostic=out.setdefault('rough_diagnostic',{}))
                        else:
                            out['finish']=read_finish_parameters(handles[oid],handles['feature_dispatch'],read=b.read,typed=b.typed)
                            out['leads']=leads.read_lead_details(handles[oid],handles['feature_dispatch'],read=b.read,typed=b.typed,
                                lead_typed=lambda o:b.typed(o,'ICWLeadInOut'))
                        out['nc']=read_nc_settings(handles[oid],handles['setup'],read=b.read,typed=b.typed,pointer_read=b.plane,
                            diagnostic=out.setdefault('nc_diagnostic',{}),persist=progress.read)
                    r['parameter_read_complete']=True;r['phase']='attribute_face_associations'
                    part=b.sw_typed(swdoc,'IPartDoc')
                    r['face_associations']=read_face_associations(part,self.loaded['reuse_names'],read=b.read,typed=b.sw_typed,
                        diagnostic=r.setdefault('association_diagnostic',{}))
                    r['phase']='after_binding'
                    r['after_binding'],_=read_binding(self.doc,self.loaded,read=b.read,typed=b.typed)
                    require(group.exact(r['before_binding'],r['after_binding']),'Selected route binding changed during reading')
                b.require_complete();progress.complete()
            finally:r['read_batch']=b.summary()


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_pocket_pair',
        'Exact read-only pocket action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact pocket reader fields required')
    base={k:v for k,v in p.items() if k in nc.PARAMS};base['module_sha256']=_file_hash(nc.__file__)
    nc.validate_request(dict(action='read_nc_planes_and_leads',params=base))
    require(p['module_sha256']==_file_hash(__file__),'Exact pocket reader module required')
    for key in ('reuse_manifest_path','progress_path'):require(type(p[key]) is str and Path(p[key]).is_absolute(),'Absolute scoped path required')
    require(type(p['reuse_manifest_sha256']) is str and nc.re.fullmatch('[0-9a-f]{64}',p['reuse_manifest_sha256']),'Exact reuse manifest SHA required')
    return deepcopy(p)


def load_inputs(p):
    loaded=receipt_loader.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],
        **{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    target_rows(loaded)
    require(_digest(group.current_projection(loaded))==loaded['current_context_sha256'],'Current saved context digest differs')
    manifest,manifest_pin=read_pin(p['reuse_manifest_path'],p['reuse_manifest_sha256'])
    require(manifest.get('scope')==SCOPE and set(manifest['evidence'])=={'indexed_profile','tool_profile','world_face_loops','primary_association_docs'},
        'Exact bounded reuse manifest required')
    docs={};pins=[]
    for name,pin in manifest['evidence'].items():docs[name],actual=read_pin(pin['path'],pin['sha256']);pins.append(actual)
    old=docs['indexed_profile']
    require(old.get('readback_verified') is True and old.get('selected_chains_read_complete') is True and
        group.exact(old['before'],old['after']) and old['before']['headers']['native_id']==FEATURE,
        'Completed unchanged six-chain observation required')
    tool=docs['tool_profile']
    require(tool.get('readback_verified') is True and tool.get('cutter_profile_readback_verified') is True
        and tool.get('holder_profile_readback_verified') is True and tool.get('save_after_verified') is True
        and tool['selected']['feature_native_id']==FEATURE,'Completed saved shared-tool profile evidence required')
    items=tool['saved_tool_details']['items']
    require({v['operation_native_id'] for v in items}==set(OPERATIONS) and all(
        v['full_tool']['geometry_read_complete'] is True and v['full_tool']['profile_complete'] is True for v in items),
        'Both existing pocket operations require completed saved tool-profile evidence')
    hdr=old['before']['headers'];names=hdr['sketch_names']['value']
    require(hdr['island_count']==5 and hdr['sketch_count']==6 and len(names)==6 and len(set(names))==6,'Exact six indexed contours required')
    retired=[v for v in loaded['pins'] if Path(v['path']).name in RETIRED_NAMES]
    added=[common._pin(__file__),common._pin(journal.__file__)]
    live=common._merge([v for v in loaded['pins'] if v not in retired],added)
    offline=common._merge(loaded['offline_export_proof_pins'],retired,pins,[manifest_pin])
    require(len(live)<=64,'Bounded pocket reader dependency closure required')
    common._check(live);common._check(offline)
    return dict(loaded,pins=live,offline_export_proof_pins=offline,reuse_manifest_pin=manifest_pin,reuse_evidence=pins,
        reuse_names=names,reuse_profile_headers=hdr,reuse_selected=dict(feature_native_id=FEATURE,
            owner_setup_native_id=hdr['owner_setup_native_id'],volume_type=hdr['volume_type'],shape=hdr['shape'],island_count=hdr['island_count']))


def run(sw,clsid,typelib,*,loaded,args,audit):
    receipt=common._local_receipt(args['receipt_path'])
    r=dict(schema_version=1,scope=SCOPE,status='reading',phase='preflight',read_only=True,
        process_id=args['process_id'],process_ownership=deepcopy(loaded['ownership']),
        expected_document_path=args['expected_document_path'],expected_source_sha256=args['expected_source_sha256'],
        checkpoint_pin=loaded['parent_pin'],reuse_manifest_pin=loaded['reuse_manifest_pin'],reuse_evidence=loaded['reuse_evidence'],
        interface_audit=audit,evidence_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],
        feature_native_id=FEATURE,operation_native_ids=list(OPERATIONS),tool_native_id=TOOL,
        readback_verified=False,parameter_read_complete=False,mutation_attempted=False,save_attempted=False,model_saved=False,
        GTP_attempted=False,export_attempted=False,full_CAD_stock_capture=False,indexed_chains_reread=False,
        full_tool_profile_reread=False,production_qualified=False,automatic_retry=False)
    start=monotonic();backend=None
    def persist():r['elapsed_seconds']=monotonic()-start;_write_receipt(receipt,r)
    _write_receipt(receipt,r,create=True)
    try:
        backend=NativeBackend(loaded,args,sw,clsid,typelib,r,persist)
        backend.start();r['before_document']=backend.ctx.identity();persist()
        backend.observe();backend.finish();r['after_document']=backend.ctx.identity()
        require(r['before_document']==r['after_document']==loaded['state']['document'],'Document or saved-state binding changed')
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins'])
        r.update(status='observed',phase='finished',readback_verified=True,phase_proofs_verified_after_read=True)
    except Exception as exc:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        if backend:
            try:backend.close()
            except Exception as exc:r.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    registration=common.discover_export_registration(loaded,p['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_interfaces(typelib,loaded['generated_pin'])
    loaded['pins']=common._merge(loaded['pins'],audit['sw_generated_pins'],[common._pin(typelib)])
    require(len(loaded['pins'])<=64,'Bounded qualified native dependency closure required')
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    protected=[p['expected_document_path']]+[v['path'] for v in loaded['pins']+loaded['offline_export_proof_pins']]
    keys={common._key(v) for v in protected}
    require(common._key(receipt) not in keys and common._key(progress) not in keys and common._key(receipt)!=common._key(progress)
        and progress.suffix.lower()=='.json' and progress.parent.is_dir() and not progress.exists() and not progress.is_symlink(),
        'Fresh distinct outputs outside every protected input required')
    if validate_only:return dict(status='validated_offline',native_called=False,interface_audit=audit,
        selected=target_rows(loaded),reuse_names=loaded['reuse_names'],live_pin_count=len(loaded['pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return run(sw,registration['clsid'],typelib,loaded=loaded,args=p,audit=audit)