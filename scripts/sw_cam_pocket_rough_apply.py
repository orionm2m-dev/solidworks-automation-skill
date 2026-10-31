"""Configure one saved rough pocket, generate it once, and save the current part.

Reuses current checkpoint, retained readers, mutation journal, route captures and
single-save helper. Point coordinates are candidates until the exported CL is
reviewed. No tool/feature creation, global generation, or automatic replay.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_rough_startpoint_read as start
from scripts import sw_cam_pocket_pair_read as pocket
from scripts import sw_cam_taper_tool_candidate as tools
from scripts import sw_cam_read_progress_journal as progress
from scripts import sw_cam_raw_mill_face_move as move
from scripts.sw_cam import _member,_error
from scripts.sw_cam_comtypes import _is_comtypes_pointer
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_upper_cone_feature import require_state_equivalent
from scripts.sw_cam_ud14_save import run_one_existing_save

common,group=start.common,start.group
SCOPE='SAVED_ROUGH_POCKET_GENERATE_V1'
PARAMS=start.PARAMS|{'startpoint_receipt_path','startpoint_receipt_sha256','recipe_path','recipe_sha256'}
OLD_ORDER=[143,144,195,196,267,247,248,271]
MID_ORDER=[144,195,196,267,247,248,271,143]
NEW_ORDER=[195,196,267,247,248,271,143,144]
POINT=[10.,0.,0.]
FIELDS=(
 ('entry_type','ICWRghMillOp','GetEntryExitType','SetEntryExitType','feature',0,4),
 ('spiral_radius','ICWRghMillOp','GetSpiralRadius','SetSpiralRadius','feature',3.,1.),
 ('spiral_pitch','ICWRghMillOp','GetSpiralPitch','SetSpiralPitch','feature',3.,.1),
 ('first_depth','ICWRghMillOp','GetStartDepth','SetStartDepth','pair',[False,10.],[False,.3]),
 ('subsequent_depth','ICWRghMillOp','GetSubsequentDepthAmount','SetSubsequentDepthAmount','pair',[False,10.],[False,.3]),
 ('start_z','ICWMillOperation3','GetStartZ','SetStartZ','scalar',0.,-13.4),
 ('first_z_type','ICWMillOperation3','GetTypeOfFirstCutZ','SetTypeOfFirstCutZ','scalar',1,2),
)
POINT_ACTIONS=('CreateStartPointInstance','CreatePosition','SetPointCoordinates','SetPointPosition','AddStartPoint','SetStartPointList')
ACTIONS=tuple('field:'+x[0] for x in FIELDS)+POINT_ACTIONS+('Move143','Move144','GenerateToolpath','SaveActiveDocument')
FORBIDDEN=('tool_edit_attempted','feature_edit_attempted','assignment_attempted','operation_creation_attempted',
 'global_generation_attempted','GOP_attempted','automatic_retry','automatic_rollback','geometry_acceptance_complete','production_qualified')


def scalar_projection(value):
    if type(value) is dict:
        if 'raw' in value:return deepcopy(value['raw'])
        return {k:scalar_projection(v) for k,v in value.items() if 'diagnostic' not in k}
    if type(value) in (tuple,list):return [scalar_projection(v) for v in value]
    return value


def expected_parameters(before):
    result=scalar_projection(before);r=result['143']
    r['rough']['entry'].update(GetEntryExitType=4,GetSpiralRadius=1.,GetSpiralPitch=.1)
    r['rough']['depth'].update(FirstDepthAmt=.3,SbsqDepthAmt=.3,GetStartDepth=[False,.3],GetSubsequentDepthAmount=[False,.3])
    # Actual aggregate getter has a different raw representation than direct GetStartZ.
    # This exact observed value is scoped to this recipe; no general unit conversion.
    r['levels']['levels']['toolpath_parameters'].update(first_cut_Z_type_raw=2,start_Z_native=-0.0134)
    return result


def verify_parameters(before,actual,*,configured):
    expected=expected_parameters(before) if configured else scalar_projection(before)
    observed=scalar_projection(actual)
    if configured:
        # These three legacy projections are derived from the explicitly verified
        # start-point list. They are retained raw and checked in the later CL gate.
        for name in ('GetHoleCentreEntry','GetEntryStartPtX','GetEntryStartPtY'):
            require(name in observed['143']['rough']['entry'],'Missing derived point field')
            expected['143']['rough']['entry'][name]=deepcopy(observed['143']['rough']['entry'][name])
        require(type(observed['143']['rough']['entry']['GetHoleCentreEntry']) is bool,'Strict derived centre flag required')
    require(group.exact(expected,observed),'Pocket parameters changed outside the seven fields and explicit point projections')
    return observed


def verify_points(value,*,configured):
    require(value.get('read_complete') is True and value.get('collection_interface_verified') is True
        and value.get('list_is_null') is False,'Exact completed native collection required')
    if not configured:require(value['count']==0 and value['rows']==[] and value['hole_center_entry'] is True and value['entry_type']==0,'Initial entry differs')
    else:
        require(value['count']==1 and len(value['rows'])==1 and value['entry_type']==4,'Exactly one helical entry point required')
        point=value['rows'][0]
        require(point['type_raw']==1 and point['position_is_null'] is False and group.exact(point['position_native'],POINT),
            'Exact explicit user-defined raw XYZ required')
    return deepcopy(value)


def verify_route(before,actual,*,order,generated=False,saved_sha=None,diagnostic=None):
    a,b=deepcopy(before),deepcopy(actual)
    require(a['operation_count']==b['operation_count']==8 and len(a['features'])==len(b['features'])==21,'Exact route size required')
    require([v['native_id'] for v in a['operations']]==OLD_ORDER and [v['native_id'] for v in b['operations']]==order,'Exact operation order required')
    wanted={v['native_id']:v for v in a['operations']};rows={v['native_id']:v for v in b['operations']}
    row=rows[143];counts=deepcopy(row['toolpath_record_counts'])
    require(row['toolpath_generated'] is generated,'Rough generation status differs')
    require((not generated and counts==[]) or (generated and len(counts)==1 and type(counts[0]) is int and 0<counts[0]<=100000),
        'Exact empty or bounded generated rough path required')
    for key in ('toolpath_generated','toolpath_record_counts'):row[key]=deepcopy(wanted[143][key])
    for oid,v in rows.items():
        require(v['setup_native_id']==93 and v['setup_index']==0 and v['operation_index']==order.index(oid),'Native operation ordinal differs')
        v['operation_index']=wanted[oid]['operation_index']
    b['operations']=[rows[oid] for oid in OLD_ORDER]
    for setup in b['operation_setups']:
        if setup['native_id']==93:
            # If an order list is present, protect it as well as the per-operation
            # native ordinals; current setup rows contain only counts.
            if 'operation_ids' in setup:
                require(setup['operation_ids']==order,'Setup order differs');setup['operation_ids']=deepcopy(OLD_ORDER)
    require(type(b['document']['needs_save']) is bool,'Strict dirty flag required')
    b['document']['needs_save']=a['document']['needs_save']
    if saved_sha is not None:
        require(actual['document']['needs_save'] is False and actual['saved_file_sha256']==saved_sha,'Saved clean hash required')
        b['saved_file_sha256']=a['saved_file_sha256']
    require_state_equivalent(a,b,diagnostic=diagnostic)
    return counts


def save_projection(value):
    state=deepcopy(value['state']);state.pop('saved_file_sha256',None);state['document'].pop('needs_save',None)
    return dict(state=state,parameters=scalar_projection(value['parameters']),startpoints=deepcopy(value['startpoints']))


def equivalent_projection(reference,observed):
    normalized=deepcopy(observed);normalized['state']=require_state_equivalent(reference['state'],observed['state'])
    require(group.exact(reference,normalized),'Save changed route or configured parameters')
    return normalized


class Journal(tools.Journal):
    def marker_state(self):
        r=self.report
        result=dict(scope=SCOPE,receipt_path=str(self.receipt),source_path=r['source_path'],initial_source_sha256=r['initial_source_sha256'],
            phase=r['phase'],recipe_sha256=r['recipe_pin']['sha256'],actions=deepcopy(r['actions']),readback_verified=r.get('readback_verified',False),
            saved_source_sha256=r.get('saved_source_sha256'),automatic_replay=False)
        if r.get('continuation') is True:result['configured_receipt_sha256']=r['configured_receipt_pin']['sha256']
        return result


class NativeBackend(tools.NativeBackend):
    def target(self,g,oid=143):
        found=g.read(self.native['doc'],'GetCWObjectFromID',3,oid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact existing operation required')
        raw=found[0];op=g.typed(raw,'ICWOperation');mill=g.typed(raw,'ICWMillOperation')
        require(_object_id(self.native['doc'],op,g.read)==oid and g.read(op,'Suppressed') is False,'Current operation binding differs')
        feature_found=g.read(self.native['doc'],'GetCWObjectFromID',1,79)
        require(type(feature_found) in (tuple,list) and len(feature_found)==2 and feature_found[1] is True,'Exact feature79 required')
        feature=feature_found[0]
        links=[_object_id(self.native['doc'],v,g.read) for v in _items(g.read(op,'IGetAllFeatures'),g.typed,g.read,2)]
        require(links==[79] and g.read(mill,'OpernType')==(0 if oid==143 else 1),'Exact pocket operation type required')
        self.native['operations'][oid]=raw
        return raw,feature
    def typed(self,g,obj,name):
        cls=interface_class(name,self.typelib_path,self.loaded['generated_pin'])
        value=g.read(obj,'QueryInterface',cls)
        require(value is not None and bool(value) and isinstance(value,cls),'Exact typed native object required')
        return value
    def field(self,spec):
        _,interface,getter,_,mode,_,_=spec
        with self.ctx.guard() as g:
            raw,feature=self.target(g);owner=self.typed(g,raw,interface)
            value=g.read(owner,getter,*([feature] if mode=='feature' else []))
        return list(value) if type(value) is tuple else value
    def set_field(self,spec,pending):
        _,interface,_,setter,mode,_,value=spec
        with self.ctx.guard() as g:
            raw,feature=self.target(g);owner=self.typed(g,raw,interface)
            args=[feature,value] if mode=='feature' else list(value) if mode=='pair' else [value]
            return g.dispatch_once(lambda:_member(owner,setter,*args),persist_pending=pending)
    def create_point(self,pending):
        from ctypes import c_int,pointer,POINTER,byref
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            raw,_=self.target(g);owner=self.typed(g,raw,'ICWRghMillOp');kind=c_int(1);output=POINTER(IDispatch)()
            method=getattr(owner,'_ICWRghMillOp__com_CreateStartPointInstance')
            result=g.dispatch_once(lambda:method(pointer(kind),byref(output)),persist_pending=pending)
        self.point=output;return result
    def point_state(self):
        with self.ctx.guard() as g:
            self.target(g);point=self.typed(g,self.point,'ICWStartPoint')
            require(g.read(point,'StartPointType')==1,'Created point must remain USERDEFINED')
            raw=g.read(point,'Position');require(raw is not None and bool(raw),'Factory point Position is null; stop without fallback')
            position=self.typed(g,raw,'ICWPosition')
            return pocket.vector(g.read(position,'GetCoordinates'),3)
    def created_type(self):
        with self.ctx.guard() as g:
            self.target(g);point=self.typed(g,self.point,'ICWStartPoint')
            value=g.read(point,'StartPointType');require(type(value) is int and value==1,'Factory type is not USERDEFINED');return value
    def create_position(self,pending):
        from ctypes import POINTER,byref
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            self.target(g);app=g.typed(self.ctx.app,'ICWApp')
            utility=self.typed(g,g.read(app,'GetMathUtility'),'ICWMathUtility');output=POINTER(IDispatch)()
            method=getattr(utility,'_ICWMathUtility__com_CreatePoint')
            result=g.dispatch_once(lambda:method(byref(output)),persist_pending=pending)
        self.position=output;return result
    def position_state(self):
        with self.ctx.guard() as g:
            self.target(g);owner=self.typed(g,self.position,'ICWPosition')
            return pocket.vector(g.read(owner,'GetCoordinates'),3)
    def set_point_coordinates(self,pending):
        with self.ctx.guard() as g:
            self.target(g);owner=self.typed(g,self.position,'ICWPosition')
            return g.dispatch_once(lambda:_member(owner,'SetCoordinates',*POINT),persist_pending=pending)
    def set_point_position(self,pending):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            self.target(g);point=self.typed(g,self.point,'ICWStartPoint')
            require(g.read(point,'StartPointType')==1,'Exact USERDEFINED point required')
            position=g.read(self.position,'QueryInterface',IDispatch)
            setter=getattr(point,'_ICWStartPoint__com__set_Position')
            return g.dispatch_once(lambda:setter(position),persist_pending=pending)
    def collection_state(self):
        with self.ctx.guard() as g:
            self.target(g);coll=self.typed(g,self.entry_collection,'ICWDispatchCollection')
            require(g.read(coll,'Count')==1,'Held new point collection count differs')
            point=self.typed(g,g.read(coll,'Item',0),'ICWStartPoint')
            kind=g.read(point,'StartPointType');position=self.typed(g,g.read(point,'Position'),'ICWPosition')
            xyz=pocket.vector(g.read(position,'GetCoordinates'),3)
            require(kind==1 and group.exact(xyz,POINT),'Held collection must contain the exact user point')
            return dict(count=1,type_raw=kind,position_native=xyz)
    def attach_point(self,member,pending):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            raw,feature=self.target(g);owner=self.typed(g,raw,'ICWRghMillOp')
            if member=='Add':
                collraw=g.read(owner,'GetStartPointList',feature);coll=self.typed(g,collraw,'ICWDispatchCollection')
                require(type(g.read(coll,'Count')) is int and g.read(coll,'Count')==0,'Exact initially empty list required')
                self.entry_collection=collraw
                point=g.read(self.point,'QueryInterface',IDispatch)
                return g.dispatch_once(lambda:_member(coll,'Add',point),persist_pending=pending)
            require(member=='SetStartPointList','Exact list association action required')
            coll=self.typed(g,self.entry_collection,'ICWDispatchCollection')
            require(g.read(coll,'Count')==1,'Exact held point collection required')
            dispatch=g.read(self.entry_collection,'QueryInterface',IDispatch)
            return g.dispatch_once(lambda:_member(owner,'SetStartPointList',feature,dispatch),persist_pending=pending)
    def move_after(self,oid,anchor,pending):
        with self.ctx.guard() as g:
            a=g.read(self.native['doc'],'GetCWObjectFromID',3,oid);b=g.read(self.native['doc'],'GetCWObjectFromID',3,anchor)
            require(a[1] is True and b[1] is True,'Existing move operands required')
            setups=_items(g.read(self.native['machine'],'IGetEnumOpSetups'),g.typed,g.read,8)
            selected=[x for x in setups if _object_id(self.native['doc'],x,g.read)==93]
            require(len(selected)==1,'Exact operation setup93 required')
            setup=g.typed(selected[0],'ICWBaseOpSetup')
            from comtypes.automation import IDispatch
            moving=g.read(a[0],'QueryInterface',IDispatch);anchor_raw=g.read(b[0],'QueryInterface',IDispatch)
            require(_object_id(self.native['doc'],moving,g.read)==oid and _object_id(self.native['doc'],anchor_raw,g.read)==anchor,'Move dispatch identities changed')
            return g.dispatch_once(lambda:_member(setup,'InsertOperationAfter',moving,anchor_raw,False),persist_pending=pending)
    def generate(self,pending):
        with self.ctx.guard() as g:
            raw,_=self.target(g);op=g.typed(raw,'ICWOperation')
            require(g.read(op,'GetIsToolpathGenerated') is False,'Already generated143 forbids replay')
            from scripts.sw_cam_mill_route_context import read_generic_tool
            tool,_=read_generic_tool(raw,self.native['doc'],g.read,g.typed)
            wanted=next(x['assigned_tool'] for x in self.loaded['state']['operations'] if x['native_id']==143)
            require(group.exact(tool,wanted) and tool['native_id']==145,'Exact existing tool145 required before GTP')
            mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)
    def headers(self,label):
        self.boundary();diag=dict(phase=label);self.report.setdefault('header_reads',[]).append(diag)
        state,native=self.capture._capture_headers(self.ctx,self.clsid,self.loaded['state'],21,diag)
        self.native,self.current_state=native,deepcopy(state);self.persist();return state
    def route(self,label):
        self.boundary();state=deepcopy(self.current_state);state['document']=self.ctx.identity();state['saved_file_sha256']=self.ctx.args['expected_source_sha256']
        diag=dict(phase=label);self.report.setdefault('route_reads',[]).append(diag)
        batch=self.capture.cone.ScopedUpperHeaderReadBatch(self.sw,self.typelib_path,native_context=self.native,reference_state=state,
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),source_sha256=self.ctx.args['expected_source_sha256'],
            evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events)
        try:
            with batch:self.capture.read_route_operations(state,self.native,batch.read,batch.typed,diagnostic=diag)
            batch.require_complete()
        finally:diag['batch']=batch.summary();self.persist()
        self.current_state=deepcopy(state);return state
    def parameters(self,label):
        with self.ctx.guard() as g:
            first,feature=self.target(g);second,_=self.target(g,144)
            allsetups=_items(g.read(self.native['machine'],'IGetEnumOpSetups'),g.typed,g.read,8)
            setups=[x for x in allsetups if _object_id(self.native['doc'],x,g.read)==93]
            require(len(setups)==1,'One existing setup93 required');setup=setups[0]
        state=dict(member='',returned=False,read_index=0);diag=dict(label=label);self.report.setdefault('parameter_reads',[]).append(diag)
        path=Path(self.args['progress_path']).with_name(Path(self.args['progress_path']).stem+'.'+label+'.json')
        def binding():
            self.events();require(_object_id(self.native['doc'],first,_member)==143 and _object_id(self.native['doc'],second,_member)==144,'Retained pair changed');self.events()
        with progress.ReadProgressJournal(full_persist=self.persist,progress_path=path,describe=lambda:dict(state,phase=label),
            max_updates=2000,protected_paths=[self.args['expected_document_path'],self.args['receipt_path']]+[v['path'] for v in self.loaded['pins']]) as j:
            b=start.StartPointReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],process_id=self.args['process_id'],
                expected_document=self.ctx.identity(),source_sha256=self.ctx.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
                verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,retained_objects=(self.native['doc'],first,second,feature,setup),
                verify_retained_binding=binding,max_native_calls=900,progress=j.read,progress_state=state)
            try:
                with b:
                    result={}
                    for oid,raw in ((143,first),(144,second)):
                        out={};result[str(oid)]=out
                        out['levels']=pocket.read_levels(raw,feature,read=b.read,typed=b.typed,feature_dispatch=b.feature_dispatch)
                        if oid==143:out['rough']=pocket.rough.read_rough_entry_parameters(raw,feature,read=b.read,typed=b.typed,diagnostic={})
                        else:
                            out['finish']=pocket.read_finish_parameters(raw,feature,read=b.read,typed=b.typed)
                            out['leads']=pocket.leads.read_lead_details(raw,feature,read=b.read,typed=b.typed,lead_typed=lambda v:b.typed(v,'ICWLeadInOut'))
                        out['nc']=pocket.read_nc_settings(raw,setup,read=b.read,typed=b.typed,pointer_read=b.plane,diagnostic={},persist=j.read)
                    points=start.read_startpoints(first,feature,read=b.read,typed=b.typed,metadata=b.metadata,diagnostic={})
                b.require_complete();j.complete()
            finally:diag['batch']=b.summary()
        return dict(parameters=result,startpoints=points)
    def capture_narrow(self,label):return dict(state=self.route(label),**self.parameters(label))
    def capture_full(self,label):return dict(state=self.headers(label),catalogue=self.catalogue(),**self.parameters(label))
    def close(self):
        try:super().close()
        finally:
            if self.session is not None:self.report['messages']=self.session.summary()
            self.persist()


def verify_capture(loaded,value,*,order,generated,saved_sha=None):
    counts=verify_route(loaded['state'],value['state'],order=order,generated=generated,saved_sha=saved_sha)
    verify_parameters(loaded['pocket_parameters'],value['parameters'],configured=True)
    verify_points(value['startpoints'],configured=True)
    if 'catalogue' in value:require(group.exact(value['catalogue'],loaded['operation_checkpoint']['final_observation']['tools']), 'Existing18-tool catalogue changed')
    return counts


def generate_and_save(backend,journal,loaded):
    r=journal.report
    result=backend.generate(lambda:journal.pending('GenerateToolpath'));journal.returned('GenerateToolpath',result)
    require(type(result) is int and result==0,'Strict single-operation GTP HRESULT0 required');backend.refresh_dirty()
    generated=backend.capture_narrow('generated');r['generated']=generated
    r['generated_record_counts']=verify_capture(loaded,generated,order=NEW_ORDER,generated=True)
    r['actions']['GenerateToolpath']['readback_verified']=True;journal.persist()
    expected=save_projection(generated);r['save_stage']={}
    def capture(label):
        if label=='before':backend.boundary();return deepcopy(expected)
        final=backend.capture_full('saved');r['final']=final;r['actual_full_capture_count']=1
        counts=verify_capture(loaded,final,order=NEW_ORDER,generated=True,saved_sha=r['saved_source_sha256'])
        require(group.exact(counts,r['generated_record_counts']),'Saved rough count changed')
        return equivalent_projection(expected,save_projection(final))
    def save():
        result=backend.save();journal.returned('SaveActiveDocument',result);return result
    def saved_hash():
        sha=backend.saved_hash(r['save_stage']);require(sha!=r['initial_source_sha256'],'Save must establish new bytes')
        r['saved_source_sha256']=sha;journal.persist();return sha
    run_one_existing_save(r['save_stage'],capture=capture,verify=lambda v:equivalent_projection(expected,v),guard=backend.boundary,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
    r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True)


def run_backend(backend,journal,loaded):
    r=journal.report
    try:
        backend.start();r['initial_headers']=backend.headers('initial_reconcile')
        verify_route(loaded['state'],r['initial_headers'],order=OLD_ORDER)
        initial=backend.parameters('initial');r['initial_parameters']=initial
        verify_parameters(loaded['pocket_parameters'],initial['parameters'],configured=False);verify_points(initial['startpoints'],configured=False)
        journal.persist()
        for spec in FIELDS:
            label='field:'+spec[0];require(group.exact(backend.field(spec),spec[5]),'Field changed before mutation')
            result=backend.set_field(spec,lambda label=label:journal.pending(label));journal.returned(label,result)
            require(type(result) is int and result==0,'Strict setter HRESULT0 required');backend.refresh_dirty()
            value=backend.field(spec);require(group.exact(value,spec[6]),'Exact scalar readback differs')
            r['actions'][label].update(readback_verified=True,observed=deepcopy(value));journal.persist()
        result=backend.create_point(lambda:journal.pending('CreateStartPointInstance'))
        journal.returned('CreateStartPointInstance',result)
        r['actions']['CreateStartPointInstance'].update(returned_interface_pointer=_is_comtypes_pointer(backend.point),returned_nonnull=_is_comtypes_pointer(backend.point) and bool(backend.point));journal.persist()
        require(type(result) is int and result==0 and r['actions']['CreateStartPointInstance']['returned_nonnull'],'Factory requires HRESULT0 and non-null native interface');backend.refresh_dirty()
        backend.created_type();r['actions']['CreateStartPointInstance']['readback_verified']=True;journal.persist()
        result=backend.create_position(lambda:journal.pending('CreatePosition'))
        journal.returned('CreatePosition',result)
        r['actions']['CreatePosition'].update(returned_interface_pointer=_is_comtypes_pointer(backend.position),returned_nonnull=_is_comtypes_pointer(backend.position) and bool(backend.position));journal.persist()
        require(type(result) is int and result==0 and r['actions']['CreatePosition']['returned_nonnull'],'Math factory requires HRESULT0 and non-null Position');backend.refresh_dirty()
        backend.position_state();r['actions']['CreatePosition']['readback_verified']=True;journal.persist()
        result=backend.set_point_coordinates(lambda:journal.pending('SetPointCoordinates'));journal.returned('SetPointCoordinates',result)
        require(type(result) is int and result==0,'Strict point-coordinate HRESULT0 required');backend.refresh_dirty()
        require(group.exact(backend.position_state(),POINT),'Created Position raw coordinates differ')
        r['actions']['SetPointCoordinates'].update(readback_verified=True,observed=deepcopy(POINT));journal.persist()
        result=backend.set_point_position(lambda:journal.pending('SetPointPosition'));journal.returned('SetPointPosition',result)
        require(type(result) is int and result==0,'Strict raw Position property HRESULT0 required');backend.refresh_dirty()
        require(group.exact(backend.point_state(),POINT),'Associated start-point Position differs')
        r['actions']['SetPointPosition'].update(readback_verified=True,observed=deepcopy(POINT));journal.persist()
        for member,label in (('Add','AddStartPoint'),('SetStartPointList','SetStartPointList')):
            result=backend.attach_point(member,lambda label=label:journal.pending(label));journal.returned(label,result)
            require(type(result) is int and result==0,'Strict collection setter HRESULT0 required');backend.refresh_dirty()
            r['actions'][label].update(readback_verified=True,held_collection=backend.collection_state());journal.persist()
        for oid,anchor,label,order in ((143,271,'Move143',MID_ORDER),(144,143,'Move144',NEW_ORDER)):
            result=backend.move_after(oid,anchor,lambda label=label:journal.pending(label));journal.returned(label,result)
            move.require_move_return(result);backend.refresh_dirty();state=backend.route(label)
            verify_route(loaded['state'],state,order=order);r['actions'][label].update(readback_verified=True,observed_order=order);journal.persist()
        configured=backend.capture_narrow('configured');r['configured']=configured
        verify_capture(loaded,configured,order=NEW_ORDER,generated=False)
        for name in ('AddStartPoint','SetStartPointList'):r['actions'][name].update(readback_verified=True,observed=deepcopy(configured['startpoints']))
        journal.persist()
        generate_and_save(backend,journal,loaded)
    except Exception as exc:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        journal.persist()
    return r


def interface_class(name,typelib,generated):
    extra={'ICWMathUtility':'{3D202A65-9757-45BE-A4A8-7F610EB1D4D4}','ICWApp':'{6015E884-0B0D-11D6-A982-00062999E55F}'}
    if name in extra:
        from scripts.sw_cam_comtypes import _load_type_library
        return pocket._verify_generated_class(getattr(_load_type_library(str(typelib)),name),extra[name],generated)
    return start.interface_class(name,typelib,generated)


def require_abi(member,expected_id,args,flags):
    from ctypes import HRESULT
    require(member.restype is HRESULT and int(member.idlflags[0])==expected_id and member.argtypes==args
        and tuple(x[0] for x in member.paramflags)==flags,'Exact native ABI differs: '+member.name)


def audit_recipe(typelib,generated):
    from ctypes import POINTER,c_int,c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    specs=[]
    setter_ids={'SetEntryExitType':88,'SetSpiralRadius':90,'SetSpiralPitch':91,'SetStartDepth':82,'SetSubsequentDepthAmount':84,'SetStartZ':17,'SetTypeOfFirstCutZ':15}
    getter_ids={'GetEntryExitType':58,'GetSpiralRadius':61,'GetSpiralPitch':62,'GetStartDepth':81,'GetSubsequentDepthAmount':83,'GetStartZ':16,'GetTypeOfFirstCutZ':14}
    for _,owner,getter,setter,mode,_,new in FIELDS:
        scalar=c_int if type(new) is int else c_double
        args=(POINTER(IDispatch),scalar) if mode=='feature' else (VARIANT_BOOL,c_double) if mode=='pair' else (scalar,)
        specs.append((owner,setter,setter_ids[setter],args,(0,) if setter=='SetStartZ' else (1,)*len(args)))
        gargs=(POINTER(IDispatch),POINTER(scalar)) if mode=='feature' else (POINTER(VARIANT_BOOL),POINTER(c_double)) if mode=='pair' else (POINTER(scalar),)
        specs.append((owner,getter,getter_ids[getter],gargs,(1,10) if mode=='feature' else (2,2) if mode=='pair' else (10,)))
    specs += [('ICWApp','GetMathUtility',30,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWMathUtility','CreatePoint',1,(POINTER(POINTER(IDispatch)),),(10,)),
        ('ICWStartPoint','_set_Position',2,(POINTER(IDispatch),),(1,)),
        ('ICWRghMillOp','CreateStartPointInstance',94,(POINTER(c_int),POINTER(POINTER(IDispatch))),(1,10)),
        ('ICWPosition','SetCoordinates',2,(c_double,)*3,(1,1,1)),
        ('ICWDispatchCollection','Add',2,(POINTER(IDispatch),),(1,)),
        ('ICWRghMillOp','SetStartPointList',96,(POINTER(IDispatch),)*2,(1,1)),
        ('ICWBaseOpSetup','InsertOperationAfter',9,(POINTER(IDispatch),POINTER(IDispatch),VARIANT_BOOL),(1,1,1))]
    rows=[]
    for owner,name,dispid,args,flags in specs:
        cls=interface_class(owner,typelib,generated);matches=[v for v in cls._methods_ if v.name==name]
        require(len(matches)==1,'Unique exact native member required');require_abi(matches[0],dispid,args,flags)
        rows.append(dict(interface=owner,name=name,dispid=dispid,paramflags=list(flags),argtypes=[v.__name__ for v in args]))
    for owner,name in [('ICWStartPoint','_ICWStartPoint__com__set_Position'),('ICWRghMillOp','_ICWRghMillOp__com_CreateStartPointInstance'),('ICWMathUtility','_ICWMathUtility__com_CreatePoint')]:
        require(hasattr(POINTER(interface_class(owner,typelib,generated)),name),'Exact raw HRESULT wrapper required')
    return dict(all_resolved=True,native_calls=0,members=rows,point_getters=start.audit_interfaces(typelib,generated))


def validate_apply_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='apply_rough_pocket','Exact rough batch action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact rough batch fields required')
    base={k:v for k,v in p.items() if k in start.PARAMS};base['module_sha256']=_file_hash(start.__file__)
    start.validate_request(dict(action='read_rough_startpoints',params=base))
    require(p['module_sha256']==_file_hash(__file__),'Exact current rough module required')
    for key in ('startpoint_receipt','recipe'):
        require(type(p[key+'_path']) is str and Path(p[key+'_path']).is_absolute(),'Absolute pinned input required')
        require(type(p[key+'_sha256']) is str and start.nc.re.fullmatch('[0-9a-f]{64}',p[key+'_sha256']),'Exact input hash required')
    return deepcopy(p)


def load_inputs(p):
    loaded=start.load_inputs(p)
    old,oldpin=read_pin(p['pocket_receipt_path'],p['pocket_receipt_sha256'])
    point,pointpin=read_pin(p['startpoint_receipt_path'],p['startpoint_receipt_sha256'])
    require(point['scope']==start.SCOPE and point['status']=='observed' and point['readback_verified'] is True
        and point['phase_proofs_verified_after_read'] is True and point['expected_source_sha256']==loaded['source_sha256'], 'Completed current start-point read required')
    clean_events(point);verify_points(point['startpoints'],configured=False)
    require(point['process_id']==p['process_id'] and common._key(point['expected_document_path'])==common._key(p['expected_document_path']), 'Start-point process/source differs')
    require(group.exact(point['before_binding'],point['after_binding']) and group.exact(point['before_binding'],old['before_binding']), 'Start-point binding changed')
    common._check(point['evidence_pins']);common._check(point['offline_proof_pins'])
    recipe,recipepin=read_pin(p['recipe_path'],p['recipe_sha256'])
    require(recipe['scope']=='ROUGH143_BATCH_SETTINGS_CONTRACT' and recipe['source_sha256']==loaded['source_sha256'],'Exact reviewed recipe source required')
    require([(v['key'],v['old'],v['new']) for v in recipe['exact_changes']]==[(v[0],v[5],v[6]) for v in FIELDS], 'Recipe scalar changes differ')
    require(recipe['point_entry']['candidate_position_raw']==POINT and [x['new_order'] for x in recipe['moves']]==[MID_ORDER,NEW_ORDER], 'Recipe point/order differs')
    live=common._merge(loaded['pins'],[common._pin(__file__),common._pin(move.__file__),common._pin(__import__('scripts.sw_cam_ud14_save',fromlist=['__file__']).__file__)])
    offline=common._merge(loaded['offline_export_proof_pins'],[pointpin,recipepin])
    require(len(live)<=64,'Bounded recipe runtime closure exceeded')
    common._check(live);common._check(offline)
    return dict(loaded,pins=live,offline_export_proof_pins=offline,pocket_parameters=deepcopy(old['parameters']),
        initial_startpoints=deepcopy(point['startpoints']),startpoint_read_pin=pointpin,recipe_pin=recipepin,recipe=recipe)


def marker_path(source,sha):
    return common.local_evidence_root()/('pocket_rough_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,operation=143))+'.json')


def make_context(r):
    context=deepcopy(r['loaded_context_before']);final=r['final']
    context.update(state=deepcopy(final['state']),source_sha256=r['saved_source_sha256'],authority_kind='saved_rough_pocket_geometry_review_pending')
    context['pocket_parameters']=deepcopy(final['parameters']);context['pocket_startpoints']=deepcopy(final['startpoints'])
    context['generated_pocket']=dict(native_id=143,feature_native_id=79,tool_native_id=145,record_counts=deepcopy(r['generated_record_counts']),geometry_acceptance_complete=False)
    context['operation_checkpoint']=dict(final_observation={'tools':deepcopy(final['catalogue'])})
    context['current_context_sha256']=_digest(group.current_projection(context))
    return context


def validate_terminal(r):
    require(r['scope']==SCOPE and r['status']=='review_required' and r['phase']=='finished' and r['readback_verified'] is True
        and r['model_saved'] is True and r['phase_proofs_verified'] is True and r['actual_full_capture_count']==1,'Completed saved rough batch required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')),'Uncertain batch cannot become authority')
    require(all(r[k] is False for k in FORBIDDEN),'Unexpected forbidden action')
    actions=terminal_actions(r)
    require(set(actions)==set(ACTIONS),'Unexpected action inventory')
    loaded=r['loaded_context_before']
    verify_route(loaded['state'],r['initial_headers'],order=OLD_ORDER)
    verify_parameters(loaded['pocket_parameters'],r['initial_parameters']['parameters'],configured=False)
    verify_points(r['initial_parameters']['startpoints'],configured=False)
    for key,generated in (('configured',False),('generated',True),('final',True)):
        counts=verify_capture(loaded,r[key],order=NEW_ORDER,generated=generated,saved_sha=r['saved_source_sha256'] if key=='final' else None)
        if generated:require(group.exact(counts,r['generated_record_counts']),'Terminal generated count differs')
    for label,a in actions.items():
        require(a['attempted'] is True and a['returned'] is True and a['pending'] is False and a['readback_verified'] is True,'Unverified action')
        if label in ('CreateStartPointInstance','CreatePosition'):require(a.get('returned_interface_pointer') is True and a.get('returned_nonnull') is True,'Non-null factory result required')
        require(a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0,'Exact integerHRESULT0 required')
    for spec in FIELDS:require(group.exact(actions['field:'+spec[0]]['observed'],spec[6]),'Scalar action readback differs')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Saved source transition incomplete')
    require(r['source_transition']['strict_save_return']==0 and r['source_transition']['source_after_sha256']==r['saved_source_sha256']
        and r['source_transition']['source_before_sha256']==r['initial_source_sha256'],'Source transition differs')
    equivalent_projection(save_projection(r['generated']),save_projection(r['final']));clean_events(r)
    return make_context(r)


def prepare(p,loaded,audit,*,marker_override=None):
    receipt=common._local_receipt(p['receipt_path']);marker=marker_override or marker_path(p['expected_document_path'],p['expected_source_sha256'])
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']}
    protected.add(common._key(p['expected_document_path']))
    paths=[receipt,marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+label+'.json') for label in ('initial','configured','generated','saved')]
    require(len({common._key(v) for v in paths})==len(paths) and not protected.intersection(common._key(v) for v in paths), 'Output aliases protected input')
    require(all(v.is_absolute() and v.parent.is_dir() and not v.exists() and not v.is_symlink() for v in paths), 'Fresh evidence and once-marker required')
    context=deepcopy({k:v for k,v in loaded.items() if k!='recipe'})
    report=dict(schema_version=1,scope=SCOPE,status='prepared',phase='prepared',actions={},process_id=p['process_id'],
        source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],receipt_path=str(receipt),
        module_pin=common._pin(__file__),recipe_pin=loaded['recipe_pin'],parent_pin=loaded['parent_pin'],
        loaded_context_before=context,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],
        setter_interface_audit=audit,mutation_attempted=False,readback_verified=False,model_saved=False,phase_proofs_verified=False,
        reused_full_capture_count=1,actual_full_capture_count=0,**{k:False for k in FORBIDDEN})
    return report,marker


def execute(sw,clsid,typelib,*,loaded,params,report,marker):
    journal=Journal(report,params['receipt_path'],marker);_write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist)
    result=run_continuation(backend,journal,loaded) if report.get('continuation') is True else run_backend(backend,journal,loaded)
    try:
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);result['phase_proofs_verified']=True
        if result.get('readback_verified') is True:
            context=validate_terminal(result);result['checkpoint_digest']=_digest(group.current_projection(context))
            journal.persist();result['marker_pin']=common._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
    except Exception as exc:result.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Current saved source/runtime/process differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    context=validate_terminal(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Saved flat checkpoint digest differs')
    marker=continuation_marker_path(r['source_path'],r['initial_source_sha256'],r['configured_receipt_pin']['sha256']) if r.get('continuation') is True else marker_path(r['source_path'],r['initial_source_sha256'])
    mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()),'Stable terminal once-marker differs')
    live=common._merge([v for v in r['live_pins'] if common._key(v['path'])!=common._key(r['parent_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded completed runtime closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[r['parent_pin'],markpin]),parent_pin=pin,group_marker_pin=markpin)
    return context


CONTINUATION_KEYS={'configured_receipt_path','configured_receipt_sha256','failed_module_archive_path','failed_module_archive_sha256','failed_marker_path','failed_marker_sha256'}
INHERITED_ACTIONS=ACTIONS[:-2]


def validate_request(request):
    if request.get('action')!='continue_configured_rough':return validate_apply_request(request)
    require(set(request)=={'action','params'} and set(request['params'])==PARAMS|CONTINUATION_KEYS,'Exact bounded continuation fields required')
    p=request['params'];validate_apply_request(dict(action='apply_rough_pocket',params={k:p[k] for k in PARAMS}))
    for name in ('configured_receipt','failed_module_archive','failed_marker'):
        require(type(p[name+'_path']) is str and Path(p[name+'_path']).is_absolute(),'Absolute continuation evidence required')
        require(type(p[name+'_sha256']) is str and start.nc.re.fullmatch('[0-9a-f]{64}',p[name+'_sha256']),'Exact continuation evidence hash required')
    return deepcopy(p)


def validate_configured_receipt(failed,*,module_archive_pin,marker_pin):
    require(failed['scope']==SCOPE and failed['status']=='uncertain' and failed['phase']=='finished'
        and failed['readback_verified'] is False and failed['model_saved'] is False
        and failed['phase_proofs_verified'] is True and failed['actual_full_capture_count']==0,'Exact stopped configuration required')
    require(not any(k in failed for k in ('cleanup_issue','phase_proof_error')),'Failed lifecycle cannot resume')
    clean_events(failed)
    issue=failed.get('issue',{});require(issue.get('type')=='ValueError' and any(v.get('function')=='verify_parameters' for v in issue.get('locations',[])), 'Expected aggregate representation mismatch required')
    require(set(failed['actions'])==set(INHERITED_ACTIONS) and not any(k in failed for k in ('generated','final','save_stage','saved_source_sha256')),'No prior generation or save may exist')
    require(module_archive_pin['sha256']==failed['module_pin']['sha256'],'Exact original writer archive required')
    common._check([module_archive_pin,marker_pin]);old_module=failed['module_pin']
    historical=[v for v in failed['live_pins'] if common._key(v['path'])!=common._key(old_module['path'])]
    removed=[v for v in failed['live_pins'] if common._key(v['path'])==common._key(old_module['path'])]
    require(len(removed)==1 and removed[0]['sha256']==old_module['sha256'],'Exactly one archived historical writer pin required')
    common._check(historical);common._check(failed['offline_proof_pins']);common._check(failed['bootstrap_export_pins'])
    old_marker,_=read_pin(marker_pin['path'],marker_pin['sha256'])
    require(group.exact(old_marker,Journal(failed,failed['receipt_path'],Path(marker_pin['path'])).marker_state()),'Original immutable marker differs')
    baseline=failed['loaded_context_before'];verify_route(baseline['state'],failed['initial_headers'],order=OLD_ORDER)
    verify_parameters(baseline['pocket_parameters'],failed['initial_parameters']['parameters'],configured=False)
    verify_points(failed['initial_parameters']['startpoints'],configured=False)
    verify_capture(baseline,failed['configured'],order=NEW_ORDER,generated=False)
    require(group.exact(failed['configured']['parameters']['143']['levels']['levels']['toolpath_parameters']['start_Z_native'],-.0134),'Exact observed aggregate start required')
    for name,action in failed['actions'].items():
        require(action.get('attempted') is True and action.get('returned') is True and action.get('pending') is False
            and action.get('readback_verified') is True and action.get('native_return_type')=='int'
            and type(action.get('native_return_value')) is int and action['native_return_value']==0,'Every inherited action must be fully verified')
        if name in ('CreateStartPointInstance','CreatePosition'):
            require(action.get('returned_interface_pointer') is True and action.get('returned_nonnull') is True,'Inherited factory must have exact non-null result')
    for spec in FIELDS:require(group.exact(failed['actions']['field:'+spec[0]]['observed'],spec[6]),'Inherited direct scalar readback changed')
    for name,order in (('Move143',MID_ORDER),('Move144',NEW_ORDER)):
        require(failed['actions'][name]['observed_order']==order,'Inherited move readback changed')
    require(all(failed[k] is False for k in FORBIDDEN),'Unexpected historical operation')
    return failed


def load_configured_evidence(p):
    failed,pin=read_pin(p['configured_receipt_path'],p['configured_receipt_sha256'])
    module_pin=common._pin(p['failed_module_archive_path']);marker_pin=common._pin(p['failed_marker_path'])
    require(module_pin['sha256']==p['failed_module_archive_sha256'] and marker_pin['sha256']==p['failed_marker_sha256'],'Exact continuation archives required')
    validate_configured_receipt(failed,module_archive_pin=module_pin,marker_pin=marker_pin)
    return failed,pin,module_pin,marker_pin


def continuation_marker_path(source,sha,configured_sha):
    return common.local_evidence_root()/('pocket_rough_continue_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,configured_receipt_sha256=configured_sha))+'.json')


def prepare_continuation(p,baseline,audit):
    failed,failedpin,modulepin,markerpin=load_configured_evidence(p)
    require(failed['process_id']==p['process_id'] and common._key(failed['source_path'])==common._key(p['expected_document_path'])
        and failed['initial_source_sha256']==p['expected_source_sha256'],'Exact same saved source and process required')
    require(group.exact(group.current_projection(failed['loaded_context_before']),group.current_projection(baseline)), 'Saved original context differs')
    require(group.exact(failed['loaded_context_before']['pocket_parameters'],baseline['pocket_parameters'])
        and failed['recipe_pin']['sha256']==baseline['recipe_pin']['sha256'],'Original parameter/recipe evidence differs')
    baseline=deepcopy(baseline)
    baseline['offline_export_proof_pins']=common._merge(baseline['offline_export_proof_pins'],[failedpin,modulepin,markerpin])
    marker=continuation_marker_path(p['expected_document_path'],p['expected_source_sha256'],failedpin['sha256'])
    report,marker=prepare(p,baseline,audit,marker_override=marker)
    report.update(continuation=True,configured_receipt_pin=failedpin,failed_module_archive_pin=modulepin,failed_marker_pin=markerpin,
        inherited_actions=deepcopy(failed['actions']),inherited_action_count=15,new_action_count=0,
        initial_headers=deepcopy(failed['initial_headers']),initial_parameters=deepcopy(failed['initial_parameters']),
        reused_initial_parameter_capture=True,inherited_configured_state_sha256=_digest(failed['configured']))
    runtime=deepcopy(baseline);runtime['state']=deepcopy(failed['configured']['state'])
    runtime['current_context_sha256']=_digest(group.current_projection(runtime))
    return runtime,report,marker


def terminal_actions(r):
    if r.get('continuation') is not True:
        require('inherited_actions' not in r,'Unrecognized inherited actions');return r['actions']
    require(set(r['actions'])==set(ACTIONS[-2:]) and r['inherited_action_count']==15 and r['new_action_count']==2,'Continuation can dispatch only GTP and Save')
    failed,_=read_pin(r['configured_receipt_pin']['path'],r['configured_receipt_pin']['sha256'])
    validate_configured_receipt(failed,module_archive_pin=r['failed_module_archive_pin'],marker_pin=r['failed_marker_pin'])
    require(group.exact(r['inherited_actions'],failed['actions']) and r['inherited_configured_state_sha256']==_digest(failed['configured']),'Inherited evidence altered')
    require(group.exact(r['initial_headers'],failed['initial_headers']) and group.exact(r['initial_parameters'],failed['initial_parameters']), 'Reused captures differ')
    require(group.exact(r['direct_start_z_readback'],-13.4),'Fresh direct StartZ readback differs')
    require_state_equivalent(failed['configured']['state'],r['reconciled_headers'])
    equivalent_projection(save_projection(failed['configured']),save_projection(r['configured']))
    return dict(r['inherited_actions'],**r['actions'])


def run_continuation(backend,journal,runtime):
    r=journal.report;baseline=r['loaded_context_before']
    try:
        backend.start();headers=backend.headers('configured_reconcile');r['reconciled_headers']=headers
        failed,_=read_pin(r['configured_receipt_pin']['path'],r['configured_receipt_pin']['sha256'])
        require_state_equivalent(failed['configured']['state'],headers)
        configured=dict(state=deepcopy(headers),**backend.parameters('configured'));r['configured']=configured
        verify_capture(baseline,configured,order=NEW_ORDER,generated=False)
        equivalent_projection(save_projection(failed['configured']),save_projection(configured))
        r['direct_start_z_readback']=backend.field(FIELDS[5]);require(group.exact(r['direct_start_z_readback'],-13.4),'Fresh direct StartZ differs')
        journal.persist();generate_and_save(backend,journal,baseline)
        r['new_action_count']=len(r['actions']);require(r['new_action_count']==2,'Only GTP and Save may be dispatched')
    except Exception as exc:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        journal.persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    registration=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_recipe(typelib,loaded['generated_pin'])
    if request['action']=='continue_configured_rough':loaded,report,marker=prepare_continuation(p,loaded,audit)
    else:report,marker=prepare(p,loaded,audit)
    if validate_only:return dict(status='validated_offline',native_called=False,setter_interface_audit=audit,live_pin_count=len(loaded['pins']),marker=str(marker))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,loaded=loaded,params=p,report=report,marker=marker)
