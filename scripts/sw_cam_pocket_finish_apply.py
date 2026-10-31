"""Bounded finish of one saved pocket using a separately qualified neck tool.

The selected tool is inherited from its saved native authority, never predicted.
No tool creation, Move, global generation, replay or production release.
"""
from copy import deepcopy
from pathlib import Path
import math
from scripts import sw_cam_pocket_rough_apply as prior
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_upper_cone_feature import require_state_equivalent
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events

common,group=prior.common,prior.group
SCOPE='SAVED_POCKET_FINISH_GENERATE_V1'
ORDER=[195,196,267,247,248,271,143,144]
AUTHORITY='saved_pocket_finish_geometry_review_pending'
# key, owner, getter, setter, mode, observed scalar baseline, target
FIELDS=(
 ('out_independent','lead_out','GetIsSameLeadinout','SetIsSameLeadinout','scalar',True,False),
 ('first_depth','ICWFinishMillOp3','GetFirstDepthCut','SetFirstDepthCut','depth_pair',10.,[.3,False]),
 ('max_depth','ICWFinishMillOp3','GetMaxDepthCut','SetMaxDepthCut','depth_pair',10.,[.3,False]),
 ('side_step','ICWFinishMillOp3','GetSideCutAmt','SetSideCutAmt','depth_pair',5.,[.25,False]),
 ('previous_allowance','ICWFinishMillOp2','GetPreviousAllowance','SetPreviousAllowance','feature',.5,.5),
 ('override_previous','ICWFinishMillOp','OverridePrevAllow','OverridePrevAllow','property',False,True),
 ('bottom_finish','ICWFinishMillOp','BottomFinOpt','BottomFinOpt','property',False,True),
)+tuple((side+'_'+key,side,getter,setter,mode,old,new)
 for side in ('lead_in','lead_out')
 for key,getter,setter,mode,old,new in (
 ('angle','ArcAngle','ArcAngle','property',45.,90.),
 ('radius','GetArcRadius2','SetArcRadius2','pair',[10.,True,0.],[.5,False,0.]),
 ('straight','GetLeadAmt2','SetLeadAmt2','pair',[52.,True,0.],[0.,False,0.]),
 ('overlap','GetLeadOverlap2','SetLeadOverlap2','pair',[10.,True,0.],[0.,False,0.])))
ACTIONS=('SetTool',)+tuple('field:'+x[0] for x in FIELDS)+('GenerateToolpath','SaveActiveDocument')
FORBIDDEN=('tool_creation_attempted','tool_edit_attempted','feature_edit_attempted','operation_creation_attempted',
 'move_attempted','global_generation_attempted','GOP_attempted','automatic_retry','automatic_rollback',
 'geometry_acceptance_complete','production_qualified')
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','receipt_path','progress_path',
 'tool_receipt_path','tool_receipt_sha256','recipe_path','recipe_sha256','expected_module_sha256'}


def projected(value):return prior.scalar_projection(value)


def expected_parameters(before):
    result=projected(before);finish=result['144']['finish']
    finish.update(FirstDepthCut=.3,MaxDepthCut=.3,SideCutAmt=.25,GetPreviousAllowance=.5,OverridePrevAllow=True,BottomFinOpt=True)
    for side in ('lead_in','lead_out'):
        result['144']['leads'][side].update(ArcAngle=90.,GetArcRadius2=[.5,False,0.],GetLeadAmt2=[0.,False,0.],
            GetLeadOverlap2=[0.,False,0.],GetIsSameLeadinout=False)
    return result


def normalize_nc_roundoff(reference,actual):
    result=deepcopy(actual)
    for oid in ('143','144'):
        for field in ('XYFeed','GetSpndlSpeed'):
            a=reference[oid]['nc']['feeds_compensation'][field];b=actual[oid]['nc']['feeds_compensation'][field]
            require(type(a) is float and type(b) is float and math.isfinite(a) and math.isfinite(b),'Finite observed NC scalars required')
            require(abs(a-b)<=2*max(math.ulp(a),math.ulp(b)),'NC rate changed beyond two floating-point ULPs')
            result[oid]['nc']['feeds_compensation'][field]=a
    return result


def verify_parameters(before,actual,*,configured):
    expected=expected_parameters(before) if configured else projected(before)
    observed=normalize_nc_roundoff(expected,projected(actual))
    require(group.exact(expected,observed),'Pocket parameters changed outside the reviewed finish recipe')
    return observed


def nominal_protrusion(value):
    return type(value) is float and math.isfinite(value) and abs(value-26.)<=2*max(math.ulp(value),math.ulp(26.))


def wanted_assignment(loaded):
    row=deepcopy(next(x['assigned_tool'] for x in loaded['state']['operations'] if x['native_id']==144))
    candidate=loaded['neck_tool_candidate'];tid=candidate['native_id']
    cat=next(x for x in loaded['neck_tool_checkpoint']['catalogue'] if x['native_id']==tid)
    require(type(tid) is int and tid>0 and tid!=145 and cat['tool_type_raw']==1 and cat['CutDiameter']==2. and nominal_protrusion(cat['Protrusion']),'Exact saved neck tool catalogue required')
    row.update(native_id=tid,tool_type_raw=cat['tool_type_raw'],cut_diameter_native=cat['CutDiameter'],protrusion_native=cat['Protrusion'])
    return row


def verify_route(loaded,actual,*,assigned,generated,saved_sha=None,diagnostic=None):
    before=loaded['state'];a,b=deepcopy(before),deepcopy(actual)
    require(a['operation_count']==b['operation_count']==8 and len(a['features'])==len(b['features'])==21,'Current route size differs')
    require([x['native_id'] for x in a['operations']]==[x['native_id'] for x in b['operations']]==ORDER,'Current exact operation order differs')
    old=next(x for x in a['operations'] if x['native_id']==144);new=next(x for x in b['operations'] if x['native_id']==144)
    require(old['toolpath_generated'] is False and old['toolpath_record_counts']==[] and old['assigned_tool']['native_id']==145,'Saved ungenerated144 baseline required')
    require(new['toolpath_generated'] is generated and group.exact(new['assigned_tool'],wanted_assignment(loaded) if assigned else old['assigned_tool']),'Finish assignment or generation differs')
    counts=deepcopy(new['toolpath_record_counts'])
    require((generated and len(counts)==1 and type(counts[0]) is int and 0<counts[0]<=100000) or (not generated and counts==[]),'Bounded selected finish path required')
    for key in ('assigned_tool','toolpath_generated','toolpath_record_counts'):new[key]=deepcopy(old[key])
    require(type(b['document']['needs_save']) is bool,'Observed dirty flag required')
    b['document']['needs_save']=a['document']['needs_save']
    if saved_sha is not None:
        require(actual['document']['needs_save'] is False and actual['saved_file_sha256']==saved_sha,'Saved clean source required')
        b['saved_file_sha256']=a['saved_file_sha256']
    require_state_equivalent(a,b,diagnostic=diagnostic)
    return counts


def verify_capture(loaded,value,*,configured,generated,saved_sha=None):
    counts=verify_route(loaded,value['state'],assigned=configured,generated=generated,saved_sha=saved_sha)
    verify_parameters(loaded['pocket_parameters'],value['parameters'],configured=configured)
    require(group.exact(value['startpoints'],loaded['pocket_startpoints']),'Rough entry point changed')
    if 'catalogue' in value:require(group.exact(value['catalogue'],loaded['neck_tool_checkpoint']['catalogue']),'Saved19-tool catalogue changed')
    return counts


def save_projection(value):
    result=prior.save_projection(value)
    return result


def equivalent_projection(reference,actual):
    result=deepcopy(actual);result['state']=require_state_equivalent(reference['state'],actual['state'])
    result['parameters']=normalize_nc_roundoff(reference['parameters'],actual['parameters'])
    require(group.exact(reference,result),'Save changed the configured machining plan')
    return result


class Journal(prior.tools.Journal):
    def marker_state(self):
        return dict(scope=SCOPE,source_path=self.report['source_path'],initial_source_sha256=self.report['initial_source_sha256'],
            recipe_pin=self.report['recipe_pin'],actions=deepcopy(self.report['actions']),phase=self.report['phase'],
            status=self.report['status'],model_saved=self.report['model_saved'],readback_verified=self.report['readback_verified'])


def interface_class(name,typelib,generated):
    if name=='ICWFinishMillOp3':
        from scripts.sw_cam_comtypes import _load_type_library
        return prior.pocket._verify_generated_class(getattr(_load_type_library(str(typelib)),name),'{86B3CEBB-97D6-461C-9A0D-E1047D826FBC}',generated)
    return prior.interface_class(name,typelib,generated)


class NativeBackend(prior.NativeBackend):
    def typed_finish(self,g,raw,name):
        cls=interface_class(name,self.typelib_path,self.loaded['generated_pin']);value=g.read(raw,'QueryInterface',cls)
        require(value is not None and bool(value) and isinstance(value,cls),'Exact current typed finish interface required');return value
    def owner(self,g,spec):
        raw,feature=self.target(g,144);name=spec[1]
        if name in ('lead_in','lead_out'):
            finish=self.typed_finish(g,raw,'ICWFinishMillOp')
            raw=g.read(finish,'IGetLeadin' if name=='lead_in' else 'IGetLeadout',feature)
            require(raw is not None and bool(raw),'Current feature-specific lead required');name='ICWLeadInOut'
        return self.typed_finish(g,raw,name),feature,name
    def field(self,spec):
        with self.ctx.guard() as g:
            owner,feature,_=self.owner(g,spec);value=g.read(owner,spec[2],*([feature] if spec[4]=='feature' else []))
        return list(value) if type(value) is tuple else value
    def set_field(self,spec,pending):
        with self.ctx.guard() as g:
            owner,feature,name=self.owner(g,spec);mode=spec[4];new=spec[6]
            if mode=='property':
                raw=getattr(owner,'_'+name+'__com__set_'+spec[3]);call=lambda:raw(new)
            else:
                args=[feature,new] if mode=='feature' else list(new) if mode in ('pair','depth_pair') else [new]
                call=lambda:_member(owner,spec[3],*args)
            return g.dispatch_once(call,persist_pending=pending)
    def current_tool(self):
        from scripts.sw_cam_mill_route_context import read_generic_tool
        with self.ctx.guard() as g:
            raw,_=self.target(g,144);row,_=read_generic_tool(raw,self.native['doc'],g.read,g.typed)
        return row
    def assign(self,pending):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            raw,_=self.target(g,144);tid=self.loaded['neck_tool_candidate']['native_id']
            from scripts.sw_cam_mill_route_context import read_generic_tool
            actual,_=read_generic_tool(raw,self.native['doc'],g.read,g.typed)
            require(group.exact(actual,next(x['assigned_tool'] for x in self.loaded['state']['operations'] if x['native_id']==144)),'Initial144 assignment changed before SetTool')
            rows=prior._items(g.read(self.crib,'GetAllTools'),g.typed,g.read,prior.tools.MAX_TOOLS)
            ids=[_object_id(self.native['doc'],x,g.read) for x in rows]
            require(ids==[x['native_id'] for x in self.loaded['neck_tool_checkpoint']['catalogue']] and ids.count(tid)==1,'Exact saved19-tool catalogue required')
            tool=g.typed(rows[ids.index(tid)],'ICWTool')
            require(g.read(tool,'ToolType')==1 and g.read(tool,'CutDiameter')==2. and group.exact(g.read(tool,'Protrusion'),wanted_assignment(self.loaded)['protrusion_native']),'Selected saved neck tool identity differs')
            dispatch=g.read(tool,'QueryInterface',IDispatch);op=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(op,'SetTool',dispatch),persist_pending=pending)
    def generate(self,pending):
        require(group.exact(self.current_tool(),wanted_assignment(self.loaded)),'Exact assigned neck tool required')
        with self.ctx.guard() as g:
            raw,_=self.target(g,144);op=g.typed(raw,'ICWOperation')
            require(g.read(op,'GetIsToolpathGenerated') is False,'Generated144 forbids replay')
            mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)


def initial_field_matches(spec,value):
    if spec[4]=='depth_pair':
        return type(value) is list and len(value)==2 and type(value[0]) is float and value[0]==spec[5] and type(value[1]) is bool
    return group.exact(value,spec[5])


def action(backend,journal,label,call,readback,expected):
    result=call(lambda:journal.pending(label));journal.returned(label,result)
    require(type(result) is int and result==0,'Strict single native HRESULT0 required');backend.refresh_dirty()
    actual=readback();require(group.exact(actual,expected),'Exact direct readback differs')
    journal.report['actions'][label].update(readback_verified=True,observed=deepcopy(actual));journal.persist()


def configure(backend,journal,loaded):
    r=journal.report;r['initial_headers']=backend.headers('initial_reconcile')
    verify_route(loaded,r['initial_headers'],assigned=False,generated=False)
    r['initial_parameters']=backend.parameters('initial');verify_parameters(loaded['pocket_parameters'],r['initial_parameters']['parameters'],configured=False)
    require(group.exact(r['initial_parameters']['startpoints'],loaded['pocket_startpoints']),'Existing rough start point changed')
    r['initial_catalogue']=backend.catalogue();require(group.exact(r['initial_catalogue'],loaded['neck_tool_checkpoint']['catalogue']),'Current tool catalogue changed')
    r['initial_fields']={spec[0]:backend.field(spec) for spec in FIELDS}
    require(all(initial_field_matches(spec,r['initial_fields'][spec[0]]) for spec in FIELDS),'Actual initial finish fields differ')
    journal.persist()
    action(backend,journal,'SetTool',backend.assign,backend.current_tool,wanted_assignment(loaded))
    for spec in FIELDS:
        require(group.exact(backend.field(spec),r['initial_fields'][spec[0]]),'Field changed before its single setter')
        action(backend,journal,'field:'+spec[0],lambda pending,spec=spec:backend.set_field(spec,pending),lambda spec=spec:backend.field(spec),spec[6])
    r['configured']=backend.capture_narrow('configured');verify_capture(loaded,r['configured'],configured=True,generated=False)
    r['configuration_readback_verified']=True;journal.persist()


def generate_and_save(backend,journal,loaded):
    r=journal.report;require(r.get('configuration_readback_verified') is True,'Completed exact configuration gate required')
    result=backend.generate(lambda:journal.pending('GenerateToolpath'));journal.returned('GenerateToolpath',result)
    require(type(result) is int and result==0,'Strict selected GTP HRESULT0 required');backend.refresh_dirty()
    r['generated']=backend.capture_narrow('generated')
    r['generated_record_counts']=verify_capture(loaded,r['generated'],configured=True,generated=True)
    r['actions']['GenerateToolpath']['readback_verified']=True;journal.persist()
    expected=save_projection(r['generated']);r['save_stage']={}
    def capture(label):
        if label=='before':backend.boundary();return deepcopy(expected)
        r['final']=backend.capture_full('saved');r['actual_full_capture_count']=1
        counts=verify_capture(loaded,r['final'],configured=True,generated=True,saved_sha=r['saved_source_sha256'])
        require(group.exact(counts,r['generated_record_counts']),'Saved144 count changed')
        return equivalent_projection(expected,save_projection(r['final']))
    def save():
        result=backend.save();journal.returned('SaveActiveDocument',result);return result
    def saved_hash():
        sha=backend.saved_hash(r['save_stage']);require(sha!=r['initial_source_sha256'],'New saved bytes required')
        r['saved_source_sha256']=sha;journal.persist();return sha
    run_one_existing_save(r['save_stage'],capture=capture,verify=lambda value:equivalent_projection(expected,value),guard=backend.boundary,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
    r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True)


def run_backend(backend,journal,loaded):
    r=journal.report
    try:
        backend.start();configure(backend,journal,loaded);generate_and_save(backend,journal,loaded)
    except Exception as exc:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        journal.persist()
    return r


def audit_recipe(typelib,generated):
    from ctypes import POINTER,c_int,c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    specs=[('ICWFinishMillOp3','GetSideCutAmt',80,(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,2)),
        ('ICWFinishMillOp3','SetSideCutAmt',81,(c_double,VARIANT_BOOL),(1,1)),
        ('ICWFinishMillOp3','GetFirstDepthCut',94,(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,2)),
        ('ICWFinishMillOp3','SetFirstDepthCut',95,(c_double,VARIANT_BOOL),(1,1)),
        ('ICWFinishMillOp3','GetMaxDepthCut',96,(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,2)),
        ('ICWFinishMillOp3','SetMaxDepthCut',97,(c_double,VARIANT_BOOL),(1,1)),
        ('ICWFinishMillOp2','GetPreviousAllowance',30,(POINTER(IDispatch),POINTER(c_double)),(1,10)),
        ('ICWFinishMillOp2','SetPreviousAllowance',31,(POINTER(IDispatch),c_double),(1,1)),
        ('ICWLeadInOut','GetIsSameLeadinout',16,(POINTER(VARIANT_BOOL),),(2,)),
        ('ICWLeadInOut','SetIsSameLeadinout',17,(VARIANT_BOOL,),(1,)),
        ('ICWMillOperation','SetTool',8,(POINTER(IDispatch),),(1,)),
        ('ICWMillOperation','GenerateToolpath',9,(),())]
    for owner,name,ident,scalar in (('ICWFinishMillOp','BottomFinOpt',22,VARIANT_BOOL),
        ('ICWFinishMillOp','OverridePrevAllow',27,VARIANT_BOOL),('ICWLeadInOut','ArcAngle',6,c_double)):
        specs.extend([(owner,'_get_'+name,ident,(POINTER(scalar),),(10,)),(owner,'_set_'+name,ident,(scalar,),(1,))])
    for stem,ident in (('ArcRadius2',20),('LeadOverlap2',22),('LeadAmt2',24)):
        specs.extend([('ICWLeadInOut','Get'+stem,ident,(POINTER(c_double),POINTER(VARIANT_BOOL),POINTER(c_double)),(2,2,2)),
            ('ICWLeadInOut','Set'+stem,ident+1,(c_double,VARIANT_BOOL,c_double),(1,1,1))])
    rows=[]
    for owner,name,ident,args,flags in specs:
        cls=interface_class(owner,typelib,generated);members=[m for m in cls._methods_ if m.name==name]
        require(len(members)==1,'Unique exact native member required');prior.require_abi(members[0],ident,args,flags)
        if name.startswith('_set_'):require(hasattr(POINTER(cls),'_'+owner+'__com_'+name),'Raw property HRESULT wrapper required')
        rows.append(dict(interface=owner,name=name,dispid=ident,paramflags=list(flags),argtypes=[x.__name__ for x in args]))
    return dict(all_resolved=True,native_calls=0,members=rows)


def validate_recipe(recipe):
    require(recipe['scope']=='POCKET144_LONG_NECK_FINISH_GEOMETRY_CANDIDATE','Exact reviewed engineering recipe required')
    f=recipe['finish_recipe'];tool=recipe['tool']
    require(tool['article']=='3133020' and tool['cut_diameter_mm']==2. and tool['cut_length_mm']==3.
        and tool['conservative_native_candidate']['protrusion_mm']==26.,'Exact reviewed long-neck cutter required')
    require(f['first_depth_cut']==f['max_depth_cut']==dict(value_mm=.3,percent=False)
        and f['previous_allowance']==dict(override=True,value_mm=.5,feature_id=79)
        and f['side_cut_amount']==dict(value_mm=.25,percent=False)
        and f['side_allowance_mm']==f['depth_allowance_mm']==0. and f['bottom_finish'] is True,'Reviewed depth/stock recipe differs')
    require(f['leads']==dict(type_raw=1,arc_angle_degrees=90.,arc_radius=[.5,False,0.],straight_amount=[0.,False,0.],
        overlap=[0.,False,0.],independent_in_out=True),'Reviewed rolling leads differ')
    require(f['compensation']['GetTlpComp_preserved_raw']==f['compensation']['GetCNCComp_preserved_raw']==1
        and f['production_feeds_qualified'] is False,'Unqualified unchanged production rates/compensation required')
    require(f['preserve_first_z_type_raw']==1 and f['copy_rough_start_Z'] is False and f['feature_depth_mm']==4.8,'Reviewed first/bottom levels differ')
    common._check(recipe['source_pins'])


def validate_request(request):
    import re
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='apply_pocket_finish','Exact bounded finish action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact finish request fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Exact owned process required')
    for name in ('expected_document_path','receipt_path','progress_path','tool_receipt_path','recipe_path'):
        require(type(p[name]) is str and Path(p[name]).is_absolute(),'Absolute path required')
    for name in ('expected_source_sha256','tool_receipt_sha256','recipe_sha256','expected_module_sha256'):
        require(type(p[name]) is str and re.fullmatch('[0-9a-f]{64}',p[name]),'Exact source/module hash required')
    require(p['expected_module_sha256']==_file_hash(__file__),'Current module hash differs')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact registered add-in CLSID required')
    return deepcopy(p)


def load_inputs(p):
    from scripts import sw_cam_neck_tool_continuation as parent
    loaded=parent.load_completed(p['tool_receipt_path'],p['tool_receipt_sha256'],process_id=p['process_id'],
        expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'])
    require(loaded['authority_kind']=='saved_neck_tool_candidate_unassigned','Saved separately qualified unassigned neck authority required')
    wanted_assignment(loaded)
    require(len(loaded['neck_tool_checkpoint']['catalogue'])==19,'Exact saved19-tool catalogue required')
    recipe,recipepin=read_pin(p['recipe_path'],p['recipe_sha256']);validate_recipe(recipe)
    # Completed insertion's writer is only used to load immutable evidence here.
    retired_paths={common._key(parent.__file__),common._key(parent.original.__file__)}
    retired=[x for x in loaded['pins'] if common._key(x['path']) in retired_paths]
    require({common._key(x['path']) for x in retired}==retired_paths,'Exact completed continuation/insertion writer pins required')
    live=common._merge([x for x in loaded['pins'] if x not in retired],[common._pin(__file__),common._pin(prior.__file__)])
    offline=common._merge(loaded['offline_export_proof_pins'],retired+[recipepin])
    require(len(live)<=64,'Bounded finish runtime closure exceeded')
    common._check(live);common._check(offline)
    loaded.update(pins=live,offline_export_proof_pins=offline,recipe=recipe,recipe_pin=recipepin)
    return loaded


def marker_path(source,sha):
    return common.local_evidence_root()/('pocket_finish_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,operation=144))+'.json')


def prepare(p,loaded,audit):
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p['expected_document_path'],p['expected_source_sha256'])
    protected={common._key(x['path']) for x in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']}
    protected.add(common._key(p['expected_document_path']))
    paths=[receipt,marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+label+'.json') for label in ('initial','configured','generated','saved')]
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths),'Output aliases protected evidence')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh evidence/once-marker required')
    context=deepcopy({k:v for k,v in loaded.items() if k!='recipe'})
    report=dict(schema_version=1,scope=SCOPE,status='prepared',phase='prepared',actions={},process_id=p['process_id'],
        source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],receipt_path=str(receipt),
        module_pin=common._pin(__file__),recipe_pin=loaded['recipe_pin'],parent_pin=loaded['parent_pin'],
        loaded_context_before=context,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],
        setter_interface_audit=audit,mutation_attempted=False,configuration_readback_verified=False,readback_verified=False,model_saved=False,
        phase_proofs_verified=False,reused_full_capture_count=1,actual_full_capture_count=0,**{k:False for k in FORBIDDEN})
    return report,marker


def make_context(r):
    context=deepcopy(r['loaded_context_before']);final=r['final']
    context.update(state=deepcopy(final['state']),source_sha256=r['saved_source_sha256'],authority_kind=AUTHORITY)
    context['pocket_parameters']=deepcopy(final['parameters']);context['pocket_startpoints']=deepcopy(final['startpoints'])
    context['generated_pocket_finish']=dict(native_id=144,feature_native_id=79,tool_native_id=context['neck_tool_candidate']['native_id'],
        record_counts=deepcopy(r['generated_record_counts']),geometry_acceptance_complete=False)
    context['neck_tool_checkpoint']=dict(context['neck_tool_checkpoint'],catalogue=deepcopy(final['catalogue']))
    context['current_context_sha256']=_digest(group.current_projection(context))
    return context


def validate_terminal(r):
    require(r['scope']==SCOPE and r['status']=='review_required' and r['phase']=='finished' and r['readback_verified'] is True
        and r['configuration_readback_verified'] is True and r['model_saved'] is True and r['phase_proofs_verified'] is True
        and r['actual_full_capture_count']==1,'Completed exact saved finish required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')),'Uncertain operation cannot become saved authority')
    require(all(r[k] is False for k in FORBIDDEN) and set(r['actions'])==set(ACTIONS),'Unexpected actions in terminal evidence')
    loaded=r['loaded_context_before'];verify_route(loaded,r['initial_headers'],assigned=False,generated=False)
    verify_parameters(loaded['pocket_parameters'],r['initial_parameters']['parameters'],configured=False)
    require(group.exact(r['initial_parameters']['startpoints'],loaded['pocket_startpoints'])
        and group.exact(r['initial_catalogue'],loaded['neck_tool_checkpoint']['catalogue']),'Initial known point/catalogue differs')
    require(set(r['initial_fields'])=={x[0] for x in FIELDS} and all(initial_field_matches(x,r['initial_fields'][x[0]]) for x in FIELDS),'Initial exact scalar evidence differs')
    for key,generated in (('configured',False),('generated',True),('final',True)):
        counts=verify_capture(loaded,r[key],configured=True,generated=generated,saved_sha=r['saved_source_sha256'] if key=='final' else None)
        if generated:require(group.exact(counts,r['generated_record_counts']),'Terminal finish path counts differ')
    for label,a in r['actions'].items():
        require(a['attempted'] is True and a['returned'] is True and a['pending'] is False and a['readback_verified'] is True
            and a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0,'Unverified strict-zero native action')
    require(group.exact(r['actions']['SetTool']['observed'],wanted_assignment(loaded)),'Terminal assignment differs')
    for spec in FIELDS:require(group.exact(r['actions']['field:'+spec[0]]['observed'],spec[6]),'Terminal direct scalar readback differs')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save source transition incomplete')
    require(r['source_transition']['strict_save_return']==0 and r['source_transition']['source_before_sha256']==r['initial_source_sha256']
        and r['source_transition']['source_after_sha256']==r['saved_source_sha256'],'Exact source transition differs')
    equivalent_projection(save_projection(r['generated']),save_projection(r['final']));clean_events(r)
    return make_context(r)


def execute(sw,clsid,typelib,*,loaded,params,report,marker):
    journal=Journal(report,params['receipt_path'],marker);_write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist);result=run_backend(backend,journal,loaded)
    try:
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);result['phase_proofs_verified']=True
        if result.get('readback_verified') is True:
            context=validate_terminal(result);result['checkpoint_digest']=_digest(group.current_projection(context));journal.persist()
            result['marker_pin']=common._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
    except Exception as exc:result.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved finish source/runtime/process differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    context=validate_terminal(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Saved finish checkpoint digest differs')
    marker=marker_path(r['source_path'],r['initial_source_sha256']);mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()),'Exact immutable terminal once-marker differs')
    live=common._merge([x for x in r['live_pins'] if common._key(x['path'])!=common._key(r['parent_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded completed finish runtime closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[r['parent_pin'],markpin]),parent_pin=pin,group_marker_pin=markpin)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    registration=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_recipe(typelib,loaded['generated_pin']);report,marker=prepare(p,loaded,audit)
    if validate_only:return dict(status='validated_offline',native_called=False,setter_interface_audit=audit,live_pin_count=len(loaded['pins']),marker=str(marker))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,loaded=loaded,params=p,report=report,marker=marker)


def main(argv=None):
    import argparse
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args(argv)
    request=json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
    result=dispatch_request(request,validate_only=args.validate_only)
    print(json.dumps({key:result.get(key) for key in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':
    raise SystemExit(main())
