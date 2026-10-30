"""Create and qualify one local flat-taper tool, then save once.

Only the new tool and its unshared holder may change. No operation insertion,
assignment, generation, TechDB write, rollback or automatic retry is supported.
"""
from copy import deepcopy
from pathlib import Path
import json
import math
from scripts import sw_cam_checkpoint_reconfigure as checkpoint
from scripts import sw_cam_grouped_face_recipe as group
from scripts import sw_cam_checkpoint_exports as exports
from scripts import sw_cam_taper_profile as geometry
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_ud14_qualification import capture_local_tools, read_ud14_tool
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile
from scripts.sw_cam_sandvik_phase1 import reject_holder_alias
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch, READ_MEMBERS, READ_INTERFACES

SCOPE = 'SAVED_LOCAL_TAPER_TOOL_CANDIDATE_V1'
DB_TYPE, TOOL_TYPE = 11, 8
FIELD_ORDER = ('EndDia','TaperLength','TaperAngle','ShankDia','OverallLength',
               'MillToolShankType','ShoulderLength','NoOfFlutes',
               'ToolIdentifier','ToolVendor','ToolDescription','Protrusion')
STAGES = dict(EndDia='after_end_dia', TaperLength='after_taper_length',
              TaperAngle='after_taper_angle')
TAPER_FIELDS = ('TaperToolType','EndDia','EndRadius','ShankDia','TaperAngle',
                'TaperLength','OverallLength','ShoulderLength','NoOfFlutes',
                'MillToolShankType','ShoulderDia','ShankLength','MaxDia')
TOOL_FIELDS = ('CutDiameter','Protrusion','StnNo','ToolIdentifier','ToolVendor','ToolDescription')
INT_FIELDS = frozenset({'TaperToolType','NoOfFlutes','MillToolShankType'})
TEXT_FIELDS = frozenset({'ToolIdentifier','ToolVendor','ToolDescription'})
TAPER_READS = READ_MEMBERS | frozenset(TAPER_FIELDS+TOOL_FIELDS) | frozenset({
    'GetHolderId','GetHolderNumber','GetHolderShape','GetHolderType','GetHolderSpec',
    'GetHolderTopDia','GetHolderBottomDia','GetHolderOverallLength','GetHolderBottomLength',
    'GetProtrusion','MillToolType','MillToolSubType','EffCutlength','OverallLen',
    'EndRadius','ShoulderLength','ShoulderDia','ShankLength','NoOfFlutes',
})
TAPER_INTERFACES = READ_INTERFACES | frozenset({'ICWTaperTool','ICWMillTool'})


def scalar_equal(a,b):
    if type(b) in (str,int,bool) or b is None:
        return type(a) is type(b) and a == b
    return type(a) in (int,float) and math.isfinite(a) and abs(a-b) <= 1e-9


def marker_path(source, source_sha256):
    key = _digest(dict(scope=SCOPE,action='create_configure_save_one_tool',
        source=exports._key(source),source_sha256=source_sha256))
    return exports.local_evidence_root()/('taper_tool_'+key+'.json')


def verify_new_catalogue(before, after, new_id):
    require(type(new_id) is int and new_id>0, 'Actual positive new tool ID required')
    old={v['native_id']:v for v in before}; current={v['native_id']:v for v in after}
    require(len(old)==len(before) and len(current)==len(after) and new_id not in old,
            'Duplicate or pre-existing new tool ID')
    require(set(current)==set(old)|{new_id} and all(group.exact(current[k],v) for k,v in old.items()),
            'Exactly one added tool and unchanged prior catalogue fields required')
    require([v['native_id'] for v in after if v['native_id']!=new_id]==[v['native_id'] for v in before],
            'Prior tool order changed')
    require(type(current[new_id]['tool_type_raw']) is int and current[new_id]['tool_type_raw']==TOOL_TYPE,
            'Created tool must be native tapered type8, not DB enum11')


def verify_protected(initial, observed, new_id=None):
    for key in ('route','protected_tools','units'):
        require(group.exact(initial[key],observed[key]), 'Protected observed state changed: '+key)
    if new_id is None:
        require(group.exact(initial['tools'],observed['tools']), 'Initial tool catalogue changed')
    else:
        verify_new_catalogue(initial['tools'],observed['tools'],new_id)


def validate_recipe(recipe):
    require(type(recipe) is dict and set(recipe)=={'profile_contract','proposed_fields','api_angle_status',
        'noncutting_status','holder_file_pin'}, 'Exact tool recipe fields required')
    geometry.validate_contract(recipe['profile_contract'])
    p=recipe['proposed_fields']
    require(type(p) is dict and set(p)==set(FIELD_ORDER), 'Exact bounded property proposal required')
    expected=dict(EndDia=.6,TaperLength=.7,TaperAngle=45.,ShankDia=3.,OverallLength=40.,
        MillToolShankType=0,ShoulderLength=.7,NoOfFlutes=4,Protrusion=20.)
    require(all(scalar_equal(p[k],v) for k,v in expected.items()), 'Only reviewed nominal proposal supported')
    require(all(type(p[k]) is str and 0<len(p[k])<=1000 and '\x00' not in p[k] for k in TEXT_FIELDS),
            'Explicit bounded tool identity text required')
    require(recipe['api_angle_status']=='proposed_value_requires_immediate_profile_proof'
        and recipe['noncutting_status']=='conservative_envelope_not_factory_geometry',
        'API uncertainty and conservative geometry must remain explicit')
    exports._check([recipe['holder_file_pin']])


class Journal:
    def __init__(self, report, receipt, marker):
        self.report,self.receipt,self.marker=report,Path(receipt),Path(marker)
        self.claimed=False
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,receipt_path=str(self.receipt),source_path=r['source_path'],
            initial_source_sha256=r['initial_source_sha256'],phase=r['phase'],
            new_tool_native_id=r.get('new_tool_native_id'),actions=deepcopy(r['actions']),
            readback_verified=r.get('readback_verified',False),automatic_replay=False,
            saved_source_sha256=r.get('saved_source_sha256'))
    def persist(self):
        _write_receipt(self.receipt,self.report)
        if self.claimed:_write_receipt(self.marker,self.marker_state())
    def claim(self):
        require(not self.claimed and not self.marker.exists(),'Existing attempt forbids replay')
        _write_receipt(self.marker,self.marker_state(),create=True);self.claimed=True;self.persist()
    def pending(self,label):
        require(label not in self.report['actions'],'Action cannot be repeated')
        self.report['actions'][label]=dict(attempted=True,returned=False,pending=True)
        self.report.update(phase=label,mutation_attempted=True)
        if not self.claimed:self.claim()
        self.persist()
    def returned(self,label,value,*,pointer=False):
        row=self.report['actions'][label]
        row.update(returned=True,pending=False,native_return_type=type(value).__name__)
        if not pointer:
            require(value is None or type(value) in (bool,int,float,str),'Serializable primitive native return required')
            row['native_return_value']=value
        else:row['returned_interface_pointer']=True
        self.persist()


class ToolReadBatch(ScopedCamReadBatch):
    def read(self,obj,name,*args):
        try:
            require(name in TAPER_READS,'Getter outside tool-only read scope')
            if name=='QueryInterface':
                from comtypes import IUnknown
                require(len(args)==1 and args[0] is IUnknown,'Only canonical identity QI permitted')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(name in TAPER_INTERFACES,'Interface outside tool-only read scope')
            return self._observe_read(obj,'qi',lambda:_typed(obj,name,self.typelib_path))
        except BaseException:
            self._invalid=True;self._completed=False;raise


def read_holder(tool,read,typed):
    holder=typed(read(tool,'IGetMillToolHolder'),'ICWMillToolHolder')
    row=dict(holder_id=read(holder,'GetHolderId'))
    for name in ('GetName','GetHolderNumber','GetHolderShape','GetHolderType','GetHolderSpec',
                 'GetHolderTopDia','GetHolderBottomDia','GetHolderOverallLength',
                 'GetHolderBottomLength','GetProtrusion'):
        row[name]=read(holder,name)
    row['profile']={}
    read_segment_chains(holder,'GetHolderProfile',read=read,typed=typed,
        diagnostic={'state':row['profile']},budget=dict(curves=0,chains=0,islands=0))
    return row,holder


def read_taper(raw,doc,read,typed,diagnostic,*,profiles=True,holder=True):
    tool=typed(raw,'ICWTool');taper=typed(raw,'ICWTaperTool')
    row=dict(native_id=_object_id(doc,tool,read),tool_type_raw=read(tool,'ToolType'),parameters={},profiles={})
    diagnostic['state']=row
    require(type(row['tool_type_raw']) is int and row['tool_type_raw']==TOOL_TYPE
            and read(tool,'IsMillTool') is True,'Exact tapered MILL tool required')
    for owner,fields in ((taper,TAPER_FIELDS),(tool,TOOL_FIELDS)):
        for field in fields:
            value=read(owner,field);row['parameters'][field]=value
            if field in INT_FIELDS:require(type(value) is int,'Strict native tool integer required')
            elif field in TEXT_FIELDS:require(type(value) is str and len(value)<=4096,'Bounded native tool text required')
            else:require(type(value) in (int,float) and math.isfinite(value),'Finite native tool scalar required')
    require(row['parameters']['TaperToolType']==1 and scalar_equal(row['parameters']['EndRadius'],0.),
            'Only a flat zero-radius taper is supported')
    if not profiles:
        diagnostic['capture_complete']=True
        return row
    budget=dict(curves=0,chains=0,islands=0)
    for label,method in (('tool','GetToolProfile'),('shank','GetShankProfile')):
        partial={};row['profiles'][label]=partial
        read_segment_chains(tool,method,read=read,typed=typed,diagnostic={'state':partial},budget=budget)
    if holder:row['holder'],_=read_holder(tool,read,typed)
    diagnostic['capture_complete']=True
    return row


class NativeBackend(group.NativeBackend):
    def __init__(self,loaded,args,sw,clsid,typelib_path,report,persist):
        super().__init__(loaded,args,sw,clsid,typelib_path,report,persist)
        self.new_id=None;self.new_tool=None;self.crib=None;self.old_holders={}
    def start(self):
        super().start()
        with self.ctx.guard() as g:
            active=g.read(self.ctx.app,'IGetActiveDoc')
            doc=g.typed(active,'ICWDoc3');part=g.typed(active,'ICWPartDoc')
            require(g.read(doc,'GetDocType')==1,'CAM part required')
            machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
            require(g.read(machine,'MachType')==1,'MILL required')
            setups=_items(g.read(machine,'IGetEnumSetups'),g.typed,g.read,8)
            require([_object_id(doc,v,g.read) for v in setups]==[r['native_id'] for r in self.loaded['state']['feature_setups']],
                    'Feature setup identities changed')
            self.native=dict(doc=doc,machine=machine,setups=setups,operations={})
            self.crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4')
            self.save_app=g.typed(self.ctx.app,'ICWApp')
    def batch(self,*extra):
        def binding():
            self.events()
            require(_member(self.native['doc'],'GetDocType')==1 and _member(self.native['machine'],'MachType')==1,
                    'Retained tool context changed')
            if self.new_tool is not None:
                require(_object_id(self.native['doc'],self.new_tool,_member)==self.new_id,'New tool identity changed')
            self.events()
        return ToolReadBatch(self.sw,self.typelib_path,process_id=self.args['process_id'],
            expected_document=self.ctx.identity(),source_sha256=self.ctx.args['expected_source_sha256'],
            evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,
            verify_owned_process=self.ctx.owned,check_events=self.events,
            retained_objects=(self.native['doc'],self.native['machine'],self.crib)+tuple(extra),
            verify_retained_binding=binding,max_native_calls=5000)
    def fields(self):
        with self.ctx.guard() as g:
            result=read_taper(self.new_tool,self.native['doc'],g.read,g.typed,{},profiles=False)
        require(result['native_id']==self.new_id,'Scalar readback target changed')
        return result
    def field(self,name):
        require(name in FIELD_ORDER,'Bounded property required')
        with self.ctx.guard() as g:
            require(_object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,'Scalar readback target changed')
            target=self.new_tool if name in TOOL_FIELDS else g.typed(self.new_tool,'ICWTaperTool')
            return g.read(target,name)
    def catalogue(self):
        batch=self.batch()
        try:
            with batch:value=capture_local_tools(self.crib,self.native['doc'],batch.read,batch.typed)
            batch.require_complete();return value
        finally:self.report.setdefault('catalogue_batches',[]).append(batch.summary());self.persist()
    def candidate(self,label):
        require(self.new_tool is not None and self.new_id is not None,'Identified new tool required')
        self.report['candidate_profile_capture_count']=self.report.get('candidate_profile_capture_count',0)+1
        diagnostic=dict(label=label);self.report.setdefault('candidate_reads',[]).append(diagnostic);self.persist()
        batch=self.batch(self.new_tool)
        try:
            with batch:result=read_taper(self.new_tool,self.native['doc'],batch.read,batch.typed,diagnostic,holder=label!='cone_proof')
            batch.require_complete()
            require(result['native_id']==self.new_id,'Returned candidate ID changed')
            return result
        finally:
            diagnostic['batch']=batch.summary();self.persist()
    def snapshot(self,label):
        route=self.read_narrow(label)
        self.report['full_tool_snapshot_count']=self.report.get('full_tool_snapshot_count',0)+1
        # This is an observation projection, not a claim that every CAM setting
        # or CAD face was reread. Saved CAD/contours remain checkpoint evidence.
        projection=group.NativeBackend.save_projection(self,route)
        with self.ctx.guard() as g:
            units=read_document_cam_unit_scope(g.read(self.sw,'ActiveDoc'),self.ctx.app,sw_read=g.read,cam_read=g.read)
        require(group.exact(units,self.loaded['finish_payload']['unit_record'])
                and units['metric_document_scope_observed'] is True,'Actual metric unit scope changed')
        batch=self.batch();old={};holders={}
        try:
            with batch:
                tools=capture_local_tools(self.crib,self.native['doc'],batch.read,batch.typed)
                values=_items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,128)
                for raw in values:
                    tool=batch.typed(raw,'ICWTool');tid=_object_id(self.native['doc'],tool,batch.read)
                    if tid==self.new_id:continue
                    generic=next(x for x in tools if x['native_id']==tid)
                    kind=generic['tool_type_raw']
                    if kind==1:
                        observed=dict(native_id=tid,is_mill_tool=True,native_read_complete=True,
                            tool_type_raw=kind,cut_diameter_native=generic['CutDiameter'],protrusion_native=generic['Protrusion'])
                        full=read_full_mill_tool(tool,generic=observed,read=batch.read,typed=batch.typed,diagnostic={})
                        old[str(tid)]=full
                    elif kind==14:
                        old[str(tid)]=read_ud14_tool(tool,doc=self.native['doc'],read=batch.read,typed=batch.typed,diagnostic={})
                        old[str(tid)]['holder'],_=read_holder(tool,batch.read,batch.typed)
                    else:
                        raise ValueError('Unsupported old tool type; stop before creation, extend reader first')
                    holders[tid]=batch.typed(batch.read(tool,'IGetMillToolHolder'),'ICWMillToolHolder')
            batch.require_complete()
        finally:self.report.setdefault('tool_batches',[]).append(batch.summary());self.persist()
        if self.new_id is None:self.old_holders=holders
        return dict(route=projection,protected_tools=old,tools=tools,units=units)
    def create(self,pending,returned):
        with self.ctx.guard() as g:
            result=g.dispatch_once(lambda:_member(self.crib,'AddNewTool3',DB_TYPE),persist_pending=pending)
        from scripts.sw_cam_comtypes import _is_comtypes_pointer
        returned(result)
        require(_is_comtypes_pointer(result) and bool(result),'Creator must return one non-null native interface')
        self.refresh_dirty()
        with self.ctx.guard() as g:
            tool=g.typed(result,'ICWTool')
            ident=_object_id(self.native['doc'],tool,g.read)
            require(g.read(tool,'ToolType')==TOOL_TYPE and g.read(tool,'IsMillTool') is True,'Unexpected created tool type')
        self.new_tool,self.new_id=tool,ident
        self.report['new_tool_native_id']=ident;self.persist()
        return ident
    def property(self,name,value,pending):
        require(name in FIELD_ORDER,'Property outside fixed new-tool scope')
        with self.ctx.guard() as g:
            require(self.new_id not in self.old_holders and _object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,
                    'Setter target must remain the exact new tool')
            target=self.new_tool if name in TOOL_FIELDS else g.typed(self.new_tool,'ICWTaperTool')
            return g.dispatch_once(lambda:setattr(target,name,value),persist_pending=pending)
    def attach_holder(self,path,pending):
        with self.ctx.guard() as g:
            require(_object_id(self.native['doc'],self.new_tool,g.read)==self.new_id and self.new_id not in self.old_holders,
                    'Holder target must belong to exact new tool')
            holder=g.typed(g.read(self.new_tool,'IGetMillToolHolder'),'ICWMillToolHolder')
            reject_holder_alias(holder,self.old_holders,identity=lambda value:__import__(
                'scripts.sw_cam_sandvik_phase1',fromlist=['com_identity']).com_identity(value,g.read))
            return g.dispatch_once(lambda:_member(holder,'SetFilePathForUserDefinedHolder',path),persist_pending=pending)


def validate_candidate(row,recipe,holder_recipe,*,stage='complete'):
    require(type(row.get('native_id')) is int and row['tool_type_raw']==TOOL_TYPE,'Actual tapered candidate required')
    profile=geometry.validate_native_profiles(row['profiles'],recipe['profile_contract'],stage=stage)
    if stage=='complete':
        require(profile['complete_qualified'] is True,'Full exact cutting/conservative shank profile required')
        for name,wanted in recipe['proposed_fields'].items():
            require(scalar_equal(row['parameters'][name],wanted),'Candidate field differs: '+name)
        require(scalar_equal(row['parameters']['MaxDia'],2.),'Actual calculated maximum diameter must be2mm')
        require(exports._key(row['holder']['GetName'])==exports._key(recipe['holder_file_pin']['path']),
                'Exact selected holder file required')
        holder=verify_holder_profile(row['holder']['profile'],holder_recipe,recipe['proposed_fields']['Protrusion'])
        return dict(profile=profile,holder=holder,native_candidate_qualified=True,
                    factory_shank_geometry_verified=False,production_qualified=False)
    return dict(profile=profile,native_candidate_qualified=False)


def run_backend(backend,journal,loaded,recipe):
    r=journal.report;persist=journal.persist
    try:
        backend.start()
        initial=backend.snapshot('initial');r['initial_observation']=initial;persist()
        require(group.exact(initial['route'],expected_route(loaded)),'Initial observed route differs from authority')
        require(initial['units']['metric_document_scope_observed'] is True
                and group.exact(initial['units'],loaded['finish_payload']['unit_record']),'Actual metric scope required')
        old_id=str(loaded['finish_payload']['full_tool']['tool_native_id'])
        require(group.exact(initial['protected_tools'][old_id],loaded['finish_payload']['full_tool']),
                'Previously qualified working tool profile or holder changed')
        new_id=backend.create(lambda:journal.pending('AddNewTool3'),
                             lambda value:journal.returned('AddNewTool3',value,pointer=True))
        forbidden={v['geometry']['native_id'] for v in loaded['state']['features']}
        forbidden|={v['native_id'] for v in loaded['state']['operations']+loaded['state']['feature_setups']+loaded['state']['operation_setups']}
        require(new_id not in forbidden,'New tool ID collides with protected CAM object')
        verify_new_catalogue(initial['tools'],backend.catalogue(),new_id)
        row=backend.fields()
        r['created_candidate']=row;r['new_tool_native_id']=new_id;persist()
        for name in FIELD_ORDER:
            if name=='Protrusion':
                result=backend.attach_holder(recipe['holder_file_pin']['path'],
                    lambda:journal.pending('SetFilePathForUserDefinedHolder'))
                journal.returned('SetFilePathForUserDefinedHolder',result)
                require(type(result) is int and result==0,'Strict successful holder-reference HRESULT required')
                backend.refresh_dirty()
                # The holder loader may set its own protrusion. Read its result
                # before the sole requested P20 assignment.
                row['parameters'][name]=backend.field(name)
            wanted=recipe['proposed_fields'][name];before=row['parameters'][name]
            label='property:'+name
            r.setdefault('field_readbacks',[]).append(dict(property=name,before=before,requested=wanted))
            if not scalar_equal(before,wanted):
                result=backend.property(name,wanted,lambda label=label:journal.pending(label))
                journal.returned(label,result)
                require(result is None,'Property dispatch must return PythonNone; readback proves value')
                backend.refresh_dirty()
            actual=backend.field(name)
            require(scalar_equal(actual,wanted),'Immediate property readback differs: '+name)
            row['parameters'][name]=actual
            r['field_readbacks'][-1].update(actual=actual)
            # Unknown template geometry is not used. All three proposed cone
            # fields are set and reread before one physical-profile proof.
            if name=='TaperAngle':
                cone=backend.candidate('cone_proof')
                r['cone_qualification']=validate_candidate(cone,recipe,loaded['holder_recipe'],stage='after_taper_angle')
                r['cone_candidate']=cone
            persist()
        candidate=backend.candidate('configured')
        r['candidate_qualification']=validate_candidate(candidate,recipe,loaded['holder_recipe'])
        r['configured_candidate']=candidate
        configured=backend.snapshot('configured');verify_protected(initial,configured,new_id)
        r['configured_observation']=configured;persist()
        def capture(label):
            if label=='before':
                backend.boundary()
                return dict(observation=configured,candidate=candidate)
            observation=backend.snapshot('save_'+label);verify_protected(initial,observation,new_id)
            tool=backend.candidate('save_'+label)
            validate_candidate(tool,recipe,loaded['holder_recipe'])
            require(group.exact(candidate,tool),'Candidate changed around Save')
            r['final_candidate']=tool;r['final_observation']=observation
            r['final_state']=deepcopy(backend.current_state);persist()
            return dict(observation=observation,candidate=tool)
        def verify(value):
            require(group.exact(value,dict(observation=configured,candidate=candidate)),'Save projection differs')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            digest=backend.saved_hash(r['save_stage'])
            require(digest!=r['initial_source_sha256'],'Changed tool must change saved source hash')
            r['saved_source_sha256']=digest;persist();return digest
        r['save_stage']={}
        run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        backend.finish()
        r.update(phase='finished',status='review_required',readback_verified=True,model_saved=True,
            exact_one_tool_created=True,assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,
            operation_creation_attempted=False,production_qualified=False)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',
            failed_phase=r['phase'],readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        persist()
    return r


def expected_route(loaded):
    state=loaded['state']
    binding=next(v['assigned_tool'] for v in state['operations']
                 if v['native_id']==loaded['generated_face_operation_id'])
    return dict(operations=deepcopy(state['operations']),operation_counts=deepcopy(state['operation_counts']),
        operation_setups=deepcopy(state['operation_setups']),settings=deepcopy(loaded['settings']),
        units=deepcopy(loaded['finish_payload']['unit_record']),assigned_tool=deepcopy(binding))


def make_checkpoint(report):
    current=deepcopy(report['current_before'])
    current.update(state=deepcopy(report['final_state']),source_sha256=report['saved_source_sha256'])
    cp=dict(current=current,settings=deepcopy(report['settings_before']),
        generated_face_operation_id=report['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(report['toolpath_record_counts']),
        local_tool_candidate=deepcopy(report['final_candidate']),
        profile_contract=deepcopy(report['recipe']['profile_contract']),
        candidate_qualification=deepcopy(report['candidate_qualification']),
        preservation_scope='operation_headers_face_nc_settings_and_all_observed_prior_tool_profiles_holders',
        saved_cad_and_contours_reused_from_historical_checkpoint=True)
    return cp


def validate_terminal(data):
    require(data.get('scope')==SCOPE and data.get('phase')=='finished'
        and data.get('status')=='review_required' and data.get('readback_verified') is True
        and data.get('model_saved') is True and data.get('phase_proofs_verified_after_native') is True,
        'Completed and verified saved candidate required')
    require(not any(k in data for k in ('issue','failed_phase','cleanup_issue','receipt_write_error','phase_proof_error')),
            'Uncertain result cannot become a checkpoint')
    for k in ('assignment_attempted','GTP_attempted','GOP_attempted','operation_creation_attempted',
              'production_qualified','automatic_retry','automatic_replay'):
        require(data.get(k) is False,'Forbidden claim or action: '+k)
    require(type(data.get('full_tool_snapshot_count')) is int and data['full_tool_snapshot_count']==3
        and type(data.get('candidate_profile_capture_count')) is int and data['candidate_profile_capture_count']==3,
        'Exact bounded capture counts required')
    before=data['current_before']
    require(set(before)==set(group.CURRENT_KEYS) and _digest(before)==data['current_before_sha256'],
            'Immutable initial context differs')
    recipe=data['recipe'];validate_recipe(recipe)
    loaded=dict(before,settings=data['settings_before'],
        generated_face_operation_id=data['generated_face_operation_id'])
    require(group.exact(data['initial_observation']['route'],expected_route(loaded)),'Initial route differs from authority')
    require(group.exact(data['initial_observation']['units'],before['finish_payload']['unit_record'])
        and data['initial_observation']['units']['metric_document_scope_observed'] is True,'Metric scope not proven')
    new_id=data['new_tool_native_id']
    for name in ('configured_observation','final_observation'):
        verify_protected(data['initial_observation'],data[name],new_id)
    require(group.exact(data['configured_candidate'],data['final_candidate'])
        and data['final_candidate']['native_id']==new_id,'Saved candidate differs')
    result=validate_candidate(data['final_candidate'],recipe,before['holder_recipe'])
    require(group.exact(result,data['candidate_qualification']),'Final geometry qualification differs')
    cone=validate_candidate(data['cone_candidate'],recipe,before['holder_recipe'],stage='after_taper_angle')
    require(group.exact(cone,data['cone_qualification']),'First cone proof differs')
    require([v['property'] for v in data['field_readbacks']]==list(FIELD_ORDER),'Exact ordered bounded field readbacks required')
    actions=data['actions']
    expected={'AddNewTool3','SetFilePathForUserDefinedHolder','SaveActiveDocument'}
    for row in data['field_readbacks']:
        name=row['property'];wanted=recipe['proposed_fields'][name]
        require(scalar_equal(row['requested'],wanted) and scalar_equal(row['actual'],wanted),'Scalar readback differs')
        if not scalar_equal(row['before'],wanted):expected.add('property:'+name)
    require(set(actions)==expected,'Unexpected native action inventory')
    for name,row in actions.items():
        require(row.get('attempted') is True and row.get('returned') is True and row.get('pending') is False,
                'Incomplete native action')
        if name=='AddNewTool3':require(row.get('returned_interface_pointer') is True,'Creator return not captured')
        elif name.startswith('property:'):
            require(row.get('native_return_type')=='NoneType' and row.get('native_return_value') is None,'Property outcome differs')
        else:require(row.get('native_return_type')=='int' and type(row.get('native_return_value')) is int
                     and row['native_return_value']==0,'Strict successful HRESULT required')
    save=data['save_stage'];transition=data['source_transition'];sha=data['saved_source_sha256']
    require(save.get('save_readback_verified') is True and save.get('native_call_returned') is True
        and save.get('save_pending') is False and save.get('native_return_type')=='int'
        and type(save.get('native_return_value')) is int and save['native_return_value']==0
        and save['saved_file_sha256']==sha==transition['source_after_sha256']
        and transition['source_before_sha256']==data['initial_source_sha256']==before['source_sha256']
        and sha!=data['initial_source_sha256'] and type(transition['strict_save_return']) is int
        and transition['strict_save_return']==0,'Changed-source Save transition required')
    require(group.exact(save['before'],save['after'])
        and group.exact(save['after'],dict(observation=data['final_observation'],candidate=data['final_candidate'])),
        'Save projection does not match final evidence')
    final=data['final_state'];reference=deepcopy(before['state'])
    reference['saved_file_sha256']=sha;reference['document']['needs_save']=False
    require(group.exact(reference,final) and final['document']['needs_save'] is False
        and group.exact(transition['document'],final['document']),'Final route identity differs')
    cp=make_checkpoint(data)
    require(group.exact(cp,data['checkpoint']) and _digest(cp)==data['checkpoint_sha256'],'Flat terminal checkpoint differs')
    from scripts.sw_cam_mill_selected_plan_evidence import clean_events
    clean_events(data)
    return cp


OFFLINE_PHASE_NAMES=frozenset({'sw_cam_profile_sketch.py','sw_cam_mill_circle_geometry.py',
                               'sw_cam_empty_mill_stock_export.py'})


def derive_closure(parent, recipepin, cataloguepin):
    from scripts import sw_cam_ud14_qualification as ud
    from scripts import sw_cam_taper_tool_checkpoint as history
    # These functions belong to full CAD/sketch/stock capture. This operation
    # executes only route headers and tool readers; their imports run before
    # connection. Actual feature_sketch._call_method remains LIVE through guards.
    retired=[p for p in parent['pins'] if Path(p['path']).name in OFFLINE_PHASE_NAMES]
    require({Path(p['path']).name for p in retired}==OFFLINE_PHASE_NAMES,'Exact phase-specific proof pins required')
    keys={exports._key(p['path']) for p in retired}
    live=exports._merge([p for p in parent['pins'] if exports._key(p['path']) not in keys],
                       [exports._pin(__file__),exports._pin(geometry.__file__),exports._pin(ud.__file__)])
    require(len(live)<=64,'Native dependency budget exceeded')
    offline=exports._merge(parent['offline_export_proof_pins'],retired,
        [exports._pin(history.__file__),parent['historical_source_pin'],recipepin,cataloguepin])
    return live,offline,retired


def load_inputs(params,*,check_current=True):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
    from scripts.sw_cam_taper_tool_checkpoint import load_historical_parent
    identity={k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    parent=load_historical_parent(params['checkpoint_receipt_path'],params['checkpoint_receipt_sha256'],
        historical_source_path=params['historical_source_path'],**identity)
    if check_current:require(_file_hash(params['expected_document_path'])==params['expected_source_sha256'],
                             'Current saved source differs before creation')
    recipe,recipepin=read_pin(params['recipe_path'],params['recipe_sha256']);validate_recipe(recipe)
    catalogue,cataloguepin=read_pin(params['catalogue_receipt_path'],params['catalogue_receipt_sha256'])
    require(catalogue.get('readback_verified') is True and catalogue.get('phase_proofs_verified_after_read') is True
        and catalogue.get('read_only') is True and catalogue['process_id']==params['process_id']
        and catalogue.get('phase')=='finished' and type(catalogue.get('native_mutation_calls')) is int
        and catalogue['native_mutation_calls']==0 and group.exact(catalogue['before'],catalogue['after'])
        and catalogue['checkpoint_pin']==parent['parent_pin']
        and catalogue['current_context_sha256']==parent['current_context_sha256']
        and catalogue['source_sha256']==params['expected_source_sha256']
        and exports._key(catalogue['source_path'])==exports._key(params['expected_document_path']),
        'Saved native catalogue authority differs')
    clean_events(catalogue)
    live,offline,retired=derive_closure(parent,recipepin,cataloguepin)
    loaded=dict(parent,pins=live,offline_export_proof_pins=offline,
                tool_phase_retired=retired,recipe=recipe,recipe_pin=recipepin,catalogue_pin=cataloguepin)
    exports._check(live);exports._check(offline);return loaded


def prepare(params):
    loaded=load_inputs(params);marker=marker_path(params['expected_document_path'],params['expected_source_sha256'])
    exports._local_receipt(params['receipt_path'])
    require(not Path(params['receipt_path']).exists() and not marker.exists()
        and not Path(params['receipt_path']).is_symlink() and not marker.is_symlink(),'Fresh local receipt and attempt required')
    protected={exports._key(p['path']) for p in loaded['pins']+loaded['offline_export_proof_pins']}
    protected.add(exports._key(params['expected_document_path']))
    require(exports._key(params['receipt_path']) not in protected and exports._key(marker) not in protected
        and exports._key(params['receipt_path'])!=exports._key(marker),'Evidence alias forbidden')
    report=dict(schema_version=1,scope=SCOPE,status='running',phase='prepared',actions={},
        module_pin=exports._pin(__file__),process_id=params['process_id'],source_path=params['expected_document_path'],
        initial_source_sha256=params['expected_source_sha256'],receipt_path=params['receipt_path'],
        parent_pin=deepcopy(loaded['parent_pin']),historical_source_pin=deepcopy(loaded['historical_source_pin']),
        recipe=deepcopy(loaded['recipe']),recipe_pin=deepcopy(loaded['recipe_pin']),catalogue_pin=deepcopy(loaded['catalogue_pin']),
        current_before=group.current_projection(loaded),current_before_sha256=loaded['current_context_sha256'],
        settings_before=deepcopy(loaded['settings']),generated_face_operation_id=loaded['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(loaded['toolpath_record_counts']),
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        phase_retired_pins=deepcopy(loaded['tool_phase_retired']),mutation_attempted=False,
        readback_verified=False,model_saved=False,automatic_retry=False,automatic_replay=False,
        phase_proofs_verified_after_native=False,full_tool_snapshot_count=0,candidate_profile_capture_count=0,
        assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,operation_creation_attempted=False,
        production_qualified=False)
    return loaded,report,marker


def execute(sw,clsid,typelib,*,params,loaded,report,marker):
    journal=Journal(report,params['receipt_path'],marker)
    _write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist)
    result=run_backend(backend,journal,loaded,loaded['recipe'])
    try:
        exports._check(loaded['offline_export_proof_pins']);exports._check(loaded['bootstrap_export_pins'])
        result['phase_proofs_verified_after_native']=True
        if result.get('readback_verified') is True:
            result['checkpoint']=make_checkpoint(result);result['checkpoint_sha256']=_digest(result['checkpoint'])
            validate_terminal(result);journal.persist()
            result['marker_pin']=exports._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker changed')
    except Exception as exc:
        result.update(status='uncertain',readback_verified=False,phase_proofs_verified_after_native=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    data,receiptpin=read_pin(path,digest);cp=validate_terminal(data)
    require(data['module_pin']==exports._pin(__file__) and data['process_id']==process_id
        and exports._key(data['source_path'])==exports._key(expected_document_path)
        and exports._key(data['receipt_path'])==exports._key(path)
        and cp['current']['source_sha256']==expected_source_sha256==_file_hash(expected_document_path),
        'Current source/process/runtime differs')
    params=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=data['initial_source_sha256'],
        checkpoint_receipt_path=data['parent_pin']['path'],checkpoint_receipt_sha256=data['parent_pin']['sha256'],
        historical_source_path=data['historical_source_pin']['path'],
        recipe_path=data['recipe_pin']['path'],recipe_sha256=data['recipe_pin']['sha256'],
        catalogue_receipt_path=data['catalogue_pin']['path'],catalogue_receipt_sha256=data['catalogue_pin']['sha256'])
    parent=load_inputs(params,check_current=False)
    require(group.exact(group.current_projection(parent),data['current_before'])
        and group.exact(parent['settings'],data['settings_before'])
        and group.exact(parent['pins'],data['live_pins'])
        and group.exact(parent['offline_export_proof_pins'],data['offline_proof_pins'])
        and group.exact(parent['tool_phase_retired'],data['phase_retired_pins'])
        and group.exact(parent['generated_face_operation_id'],data['generated_face_operation_id'])
        and group.exact(parent['toolpath_record_counts'],data['toolpath_record_counts'])
        and group.exact(parent['recipe'],data['recipe'])
        and group.exact(parent['historical_source_pin'],data['historical_source_pin']),
        'Exact historical parent or derived closure differs')
    marker=marker_path(data['source_path'],data['initial_source_sha256'])
    mark,markpin=read_pin(str(marker),data['marker_pin']['sha256'])
    require(exports._key(data['marker_pin']['path'])==exports._key(marker)
        and group.exact(mark,Journal(data,path,marker).marker_state()),'Completed local marker differs')
    # This completed tool-only marker is offline provenance for the next step;
    # its exact bytes are checked now and after each future native phase.
    live=exports._merge([p for p in parent['pins']
        if exports._key(p['path'])!=exports._key(parent['parent_pin']['path'])],[receiptpin])
    offline=exports._merge(parent['offline_export_proof_pins'],[markpin,parent['parent_pin']])
    result=dict(cp['current'],pins=live,current_context_sha256=_digest(cp['current']),
        parent_pin=receiptpin,group_marker_pin=deepcopy(parent['group_marker_pin']),
        generated_pin=deepcopy(parent['generated_pin']),settings=deepcopy(cp['settings']),
        generated_face_operation_id=cp['generated_face_operation_id'],toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        local_tool_candidate=deepcopy(cp['local_tool_candidate']),profile_contract=deepcopy(cp['profile_contract']),
        candidate_qualification=deepcopy(cp['candidate_qualification']),tool_checkpoint=data,
        bootstrap_export_pins=deepcopy(parent['bootstrap_export_pins']),offline_export_proof_pins=offline,
        authority_kind='saved_local_taper_candidate',historical_parent_pin=deepcopy(parent['parent_pin']))
    exports._check(live);exports._check(offline);exports.operation_contract(result);return result


PARAMS=exports.COMMON|{'recipe_path','recipe_sha256','catalogue_receipt_path',
                       'catalogue_receipt_sha256','historical_source_path'}


def validate_request(request):
    import re
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action']=='create_taper_candidate','Only bounded tool-only action allowed')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Exact owned process required')
    for name,value in p.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if name.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy']=='vendor_default','Explicit bounded qualification required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),
            'Exact CAM CLSID required')
    return dict(p)


def dispatch_request(request):
    params=validate_request(request);loaded,report,marker=prepare(params)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=params['process_id']):
        exports._check(loaded['pins']);exports._check(loaded['offline_export_proof_pins'])
        registration=exports.discover_export_registration(loaded,params['addin_clsid'])
        sw,_=connect_solidworks(process_id=params['process_id'],launch_new_instance=False,wait_seconds=1)
        typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
        report['bootstrap_validation']=deepcopy(loaded['bootstrap_validation'])
        return execute(sw,registration['clsid'],typelib,params=params,loaded=loaded,report=report,marker=marker)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true')
    options=parser.parse_args(argv);request=json.loads(Path(options.request).read_text(encoding='utf-8-sig'))
    if options.validate_only:
        loaded,_,_=prepare(validate_request(request))
        print(json.dumps(dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']))));return 0
    result=dispatch_request(request)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','new_tool_native_id','saved_source_sha256','issue')},
                     ensure_ascii=False))
    return 0 if result.get('readback_verified') is True and result.get('phase_proofs_verified_after_native') is True else 1


if __name__=='__main__':raise SystemExit(main())
