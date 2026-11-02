"""Resume two exact mixed pockets from the proved existing first sketch.

Reuses the existing sketch scaffold, seventeen/eight reader, fourteen-stream
exporter and one-save helper. No operation creation, GOP, GTP or tool assignment.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_deep_long_cut_reopen as authority
from scripts import sw_cam_deep_long_tool_replace as base
from scripts import sw_cam_signed_mixed_profile as mixed
from scripts import sw_cam_signed_mixed_profile_sketch as sketch
from scripts import sw_cam_mill_inventory_geometry as inventory
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_upper_cone_feature import UpperConeContext
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam import _member,_error
from scripts.sw_cam_rough_firstcut import require

common,group,cl=authority.common,authority.group,authority.cl
config,generation=base.config,base.generation
SCOPE='EXISTING_FIRST_SKETCH_TWO_MIXED_POCKETS_V1'
ACTION='resume_two_mixed_root_pockets'
PROOF_ONLY={'sw_cam_deep_long_cut_reopen.py','sw_cam_long_cut_cutter_geometry.py','sw_cam_ud14_qualification.py','sw_cam_guide_group_definitions.py'}


def contour_rows(contour):
    require(contour.get('status')=='observed' and contour.get('declared_chain_count')==1 and len(contour.get('chains',[]))==1,'Exactly one observed closed contour required')
    chain=contour['chains'][0];require(chain.get('read_complete')is True and chain.get('declared_curve_count')==len(chain['curves']),'Complete declared contour required')
    out=[]
    for curve in chain['curves']:
        require(curve.get('read_complete')is True and curve['curve_type'] in(0,1),'Exact LINE/ARC native contour required')
        start,end=mixed.vector(curve['start_native']),mixed.vector(curve['end_native'])
        row={'type':'line'if curve['curve_type']==0 else'arc','points_model_m':[[v/1000 for v in p]for p in(start,end)]}
        if curve['curve_type']==0:
            row.update(mid_model_m=[(a+b)/2000 for a,b in zip(start,end)],length_m=math.dist(start,end)/1000)
        else:
            center=mixed.vector(curve['centre_native']);mid=mixed.vector(curve['mid_native']);radius=mixed.number(curve['radius_native'])
            normal=mixed.vector(curve['normal_native']);require(radius>0 and abs(math.hypot(*normal)-1)<1e-8 and math.hypot(normal[0],normal[1])<1e-8,'World XY native circle required')
            angles=[math.atan2(p[1]-center[1],p[0]-center[0])for p in(start,mid,end)]
            ccw=(angles[2]-angles[0])%mixed.TAU;advance=(angles[1]-angles[0])%mixed.TAU
            sweep=ccw if advance<ccw else ccw-mixed.TAU
            require(1e-6<abs(sweep)<mixed.TAU-1e-6,'Nondegenerate native partial arc required')
            for p in(start,mid,end):require(abs(math.dist(p,center)-radius)<=1e-5,'Native arc points/radius disagree')
            row.update(center_model_m=[x/1000 for x in center],radius_m=radius/1000,mid_model_m=[x/1000 for x in mid],length_m=radius*abs(sweep)/1000,native_sense_raw=curve['sense_raw'])
        out.append(row)
    return out


def verify_pocket(observed,spec,*,native_id,owner=69):
    h=observed['header'];require(h['native_id']==native_id and observed['owner_setup_native_id']==owner,'Exact new pocket identity/owner required')
    require(h['volume_type']==2 and h['suppressed']is False and abs(h['depth_native']-3.4)<=1e-8,'Active pocket of depth3.4 required')
    require(math.dist(h['axis_native'],[0,0,-1])<=1e-8 and abs(h['start_native'][2]-10.9)<=1e-5,'Actual top/axis must agree with world geometry')
    require(observed['island_count']==0,'New cleanup pocket must contain no islands')
    expected=spec['profile']['segments'];mapping={}
    for label,z in(('top',10.9),('bottom',7.5)):
        shifted=deepcopy(expected)
        for seg in shifted:
            for key in list(seg):
                if key.endswith('_model_mm'):seg[key][2]=z
        rows=contour_rows(observed['contours'][label])
        mapping[label]=mixed.match_rows(shifted,rows,1e-8)
    return dict(native_id=native_id,owner_setup_native_id=owner,top_world_z_mm=10.9,floor_world_z_mm=7.5,physical_depth_mm=3.4,full_top_bottom_curves_verified=True,segment_mapping=mapping)


def verify_headers(before,after,learned):
    ids=[r['header']['native_id']for r in after]
    require(len(ids)==len(set(ids)) and len(after)==len(before)+len(learned),'Exact additive feature count required')
    old=[r for r in after if r['header']['native_id']not in learned]
    # Appending features may change only the index of the newly appended rows.
    require(group.exact(old,before),'Existing feature headers or order changed')
    require([i for i in ids if i in learned]==list(learned),'New native feature order changed')


def verify_cad(before,after,created):
    names=[x['name']for x in created]
    require(len(names)==len(set(names)),'Duplicate new CAD name')
    require([x for x in after['features']if x['name']not in names]==before['features'],'Existing CAD feature tree changed')
    require([x for x in after['features']if x['name']in names]==created,'Only exact new planes/sketches may be added')
    require(sketch.core._same_bodies(before['solids'],after['solids']),'Solid body invariants changed')


class Journal(group.GroupJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),status=r['status'],phase=r['phase'],actions=deepcopy(r['actions']),new_feature_ids=r.get('new_feature_ids',[]),native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


class NativeBackend(base.NativeBackend):
    def __init__(self,*args):
        super().__init__(*args)
        self.ctx=UpperConeContext(self.loaded,self.args,self.sw,self.typelib_path,None,self.events,{'document':self.loaded['guide_parameters']['document']})
    def assign(self,*a):raise ValueError('Feature-only packet cannot assign tools')
    def generate(self,*a):raise ValueError('Feature-only packet cannot generate paths')
    def set_field(self,*a):raise ValueError('Feature-only packet cannot change parameters')
    def set_nc(self,*a):raise ValueError('Feature-only packet cannot change NC parameters')
    def proof_boundary(self):common._check(self.loaded['checkpoint_pins']);self.boundary()
    def cad(self,spec):
        self.boundary();state,model,refs=sketch.core._snapshot(self.sw,self.args['process_id'],self.args['expected_document_path'],spec);self.boundary()
        return state,model,refs
    def create_sketch(self,spec,pending):
        before,model,refs=self.cad(spec);names={x['name'].casefold()for x in before['features']}
        require(spec['sketch_name'].casefold()not in names and spec['plane_name'].casefold()not in names,'New sketch/plane name already exists')
        diagnostic={};self.report.setdefault('sketch_creations',[]).append(diagnostic);self.persist();pending()
        created=sketch._create(self.sw,model,before,refs,self.refresh_dirty,diagnostic)
        self.refresh_dirty();after,_,_=self.cad(spec)
        records=[x for x in after['features']if x['name']in created];verify_cad(before,after,records)
        require(diagnostic['sketch_edit_exited']is True,'Sketch edit not closed')
        return dict(created_features=records,readback=diagnostic['sketch_readback'])
    def adopt_first_sketch(self,spec,failed):
        before,model,refs=self.cad(spec)
        self.report['adoption_before_cad']=deepcopy(before);self.persist()
        created=[dict(name=spec['plane_name'],type='RefPlane'),dict(name=spec['sketch_name'],type='ProfileFeature')]
        verify_cad(failed['before_cad'],before,created)
        require(before['needs_save']is True,'Expected existing unsaved first sketch')
        feature=next((f for f in refs if str(f.Name)==spec['sketch_name']),None)
        require(feature is not None,'Existing first sketch missing')
        native=sketch.call(feature,'GetSpecificFeature2')
        observed=sketch._read_sketch(self.sw,native,spec)
        after,_,_=self.cad(spec)
        self.report['adoption_after_cad']=deepcopy(after);self.persist()
        verify_cad(before,after,[])
        require(after['needs_save']is True,'Read-only adoption changed save flag')
        return dict(created_features=created,readback=observed,read_only=True,recreated=False)

    def headers(self):
        self.boundary();out=[]
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');machine=g.typed(g.read(g.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            require(g.read(machine,'MachType')==1,'MILL machine required')
            setups=_items(g.read(machine,'IGetEnumSetups'),g.typed,g.read,8)
            for raw in setups:
                setup=g.typed(raw,'ICWBaseSetup');sid=_object_id(doc,setup,g.read)
                for feature in _items(g.read(setup,'IGetEnumFeatures'),g.typed,g.read,64-len(out)):
                    header,_=read_header(feature,doc,g.read,g.typed,sid)
                    out.append(dict(owner_setup_native_id=sid,header=header))
        require(1<=len(out)<=64,'Bounded feature inventory required');return out
    def catalogue(self):
        with self.ctx.guard()as g:
            machine=g.typed(g.read(g.typed(self.doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4')
            return [_object_id(self.doc,t,g.read)for t in _items(g.read(crib,'GetAllTools'),g.typed,g.read,64)]
    def feature(self,native_id):
        self.boundary()
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');found=g.read(doc,'GetCWObjectFromID',1,native_id)
            require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact feature lookup required')
            header,raw=read_header(found[0],doc,g.read,g.typed,69);mill=g.typed(raw,'ICWMillFeature');count=g.read(mill,'IGetIslandCount')
            require(type(count)is int and count==0,'No islands allowed')
            result=dict(owner_setup_native_id=69,header=header,island_count=count,contours={});budget=dict(curves=0,chains=0,islands=0)
            for name,method in(('top','IGetTopSegChain'),('bottom','IGetBottomSegChain')):
                result['contours'][name]=inventory.read_segment_chains(mill,method,read=g.read,typed=g.typed,diagnostic={},budget=budget)
        return result
    def create_pocket(self,spec,pending):
        self.boundary()
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');machine=g.typed(g.read(g.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            candidates=[]
            for raw in _items(g.read(machine,'IGetEnumSetups'),g.typed,g.read,8):
                setup_base=g.typed(raw,'ICWBaseSetup')
                if _object_id(doc,setup_base,g.read)==69:candidates.append(raw)
            require(len(candidates)==1,'Exact owner setup missing or ambiguous')
            setup=g.typed(candidates[0],'ICWSetup');require(_object_id(doc,setup,g.read)==69,'Owner setup changed')
            value=g.dispatch_once(lambda:_member(setup,'CreateMillFeature2',0,spec['sketch_name'],False,3.4,False,False,False,False,0.,-1,False,0,0),persist_pending=pending)
        require(value is not None and type(value)not in(bool,int,float,str,list,tuple,dict),'Native feature interface required')
        self.refresh_dirty()
        with self.ctx.guard()as g:native_id=_object_id(self.doc,value,g.read)
        require(type(native_id)is int and native_id>0,'Native returned feature ID required');return native_id


def _returned(journal,name,observed):
    row=journal.report['actions'][name];require(row['attempted']is True,'Mutation bypassed pending marker')
    row.update(returned=True,native_dispatch_pending=False);journal.report.update(native_call_returned=True,native_dispatch_pending=False)
    journal.verified(name,observed)


def run_backend(backend,journal,loaded,specs):
    r=journal.report;r.update(status='error',phase='preflight',actions={},new_feature_ids=[],mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,save_attempted=False,model_saved=False,readback_verified=False,continuation_ready=False,GOP_attempted=False,GTP_attempted=False,SetTool_attempted=False,operation_creation_attempted=False,tool_creation_attempted=False,automatic_retry=False,automatic_rollback=False,production_qualified=False,persistence_after_reopen_verified=False)
    try:
        journal.create();backend.start();backend.proof_boundary()
        r['before']=backend.capture_snapshot('before',full=True);require(group.exact(r['before'],loaded['guide_parameters']['expected_parameters']),'Saved seventeen/eight baseline changed')
        r['before_tool_ids']=backend.catalogue();require(r['before_tool_ids']==loaded['tool_catalogue_ids'],'Saved tool catalogue changed')
        r['before_features']=backend.headers();r['before_cad']=backend.cad(specs[0])[0];r['created_cad_features']=[]
        require(r['before_cad']['needs_save']is True,'Adopt the existing dirty first sketch only')
        failed=loaded['first_sketch_failure'];require(group.exact(r['before_features'],failed['before_features']),'No native feature may precede adoption')
        r['adopted_first_sketch']=backend.adopt_first_sketch(specs[0],failed);journal.persist()
        for i,spec in enumerate(specs):
            if i==1:
                name='CreateSketch:1';journal.entry(name)
                result=backend.create_sketch(spec,lambda:journal.pending(name));r['created_cad_features']+=result['created_features'];_returned(journal,name,result)
            name='CreatePocket:'+str(i);journal.entry(name)
            native_id=backend.create_pocket(spec,lambda:journal.pending(name))
            require(native_id not in [x['header']['native_id']for x in r['before_features']]+r['new_feature_ids'],'Returned duplicate feature ID')
            r['new_feature_ids'].append(native_id);journal.persist()
            observed=backend.feature(native_id);checked=verify_pocket(observed,spec,native_id=native_id)
            r.setdefault('new_features',[]).append(observed);_returned(journal,name,checked)
            verify_headers(r['before_features'],backend.headers(),r['new_feature_ids'])
            require(group.exact(backend.capture_binding('after_pocket_'+str(i)),r['before']['binding']),'Pocket creation changed protected route before next action')
        r['after_features']=backend.headers();r['after_cad']=backend.cad(specs[0])[0]
        verify_headers(r['before_features'],r['after_features'],r['new_feature_ids']);verify_cad(r['before_cad'],r['after_cad'],r['created_cad_features'])
        r['configured']=backend.capture_snapshot('configured',full=True);require(group.exact(r['configured'],r['before']),'Feature creation changed old seventeen/eight state')
        backend.proof_boundary();r['save_stage']={};journal.entry('SaveActiveDocument');r['save_attempted']=True
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['configured'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['configured']),'Save changed protected parameters/bindings')
        def save():
            value=backend.save();row=r['actions']['SaveActiveDocument'];require(row['attempted']is True,'Save pending marker missing')
            row.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Save did not advance source')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_features']=backend.headers();require(group.exact(r['saved_features'],r['after_features']),'Save changed feature headers')
        r['saved_new_features']=[backend.feature(i)for i in r['new_feature_ids']]
        require(group.exact(r['saved_new_features'],r['new_features']),'Save changed full native contours')
        r['saved_cad']=backend.cad(specs[0])[0];verify_cad(r['before_cad'],r['saved_cad'],r['created_cad_features'])
        r['saved_tool_ids']=backend.catalogue();require(r['saved_tool_ids']==r['before_tool_ids'],'Feature-only packet changed tool catalogue')
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['protected_cl']=cl.verify_all(loaded['generated']['saved_cl'],r['saved_cl'])
        backend.proof_boundary();backend.finish()
        r.update(status='saved_resumed_mixed_pockets_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False,continuation_ready=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r.update(receipt_write_error=_error(exc),continuation_ready=False)
    return r
PARAMS={'process_id','expected_document_path','expected_source_sha256','reopen_receipt_path','reopen_receipt_sha256','failed_receipt_path','failed_receipt_sha256','profiles_path','profiles_sha256','geometry_path','geometry_sha256','source_backup_path','source_backup_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}


def profile_specs(raw):
    require(raw.get('scope')=='EXPECTED_TWO_LOCAL_ROOT_FEATURES_UNDER_EXISTING_REMOVAL_NOTE' and raw.get('expected_native_construction_plane_z_mm')==10.9,'Exact approved profile geometry required')
    require(len(raw.get('profiles',[]))==2 and raw.get('native_feature_enum')==0,'Exactly two closed pocket profiles required')
    out=[]
    for i,p in enumerate(raw['profiles']):
        require(p['construction_plane_world_z_mm']==10.9 and p['nominal_floor_world_z_mm']==7.5 and p['physical_depth_mm']==3.4 and p['mirrored']is False,'Exact independent root geometry required')
        rows=[]
        for v in p['segments']:
            require(v['kind']in('GeomAbs_Line','GeomAbs_Circle'),'Only LINE/ARC approved input')
            row=dict(kind='line'if v['kind']=='GeomAbs_Line'else'arc',start_model_mm=v['start_world_mm'],end_model_mm=v['end_world_mm'],mid_model_mm=v['mid_world_mm'])
            if row['kind']=='arc':row.update(center_model_mm=v['center_world_mm'],radius_mm=v['radius_mm'],sweep_radians=v['sweep_radians'])
            rows.append(row)
        require(len(rows)==13,'Exactly thirteen bounded segments per root required')
        out.append(sketch._input(dict(plane_axis='Z',plane_offset_mm=10.9,sketch_name='RootRestProfile'+str(i+1),plane_name='RootRestPlane'+str(i+1),profile=dict(kind='closed_mixed',segments=rows))))
    return out


def validate_reopen(r):
    require(r.get('scope')==authority.SCOPE and r.get('module_pin')==common._pin(authority.__file__),'Exact saved mixed-tool reopen producer required')
    require(r.get('status')=='reopen_verified' and r.get('phase')=='finished' and r.get('cleanup_session_active')is False,'Completed disconnected reopen required')
    require(all(r.get(k)is True for k in('close_verified','reopen_verified','persistence_after_reopen_verified','readback_verified','cl_persistence_verified')),'Full reopen persistence evidence required')
    require(r.get('save_attempted')is False and r.get('GTP_attempted')is False,'Reopen must not have changed the source')
    require(r['cl_persistence_comparison']['all_fourteen_complete_streams_unchanged']is True,'Fourteen complete persisted streams required')
    return r


def failed_contract(receipt):
    from scripts import sw_cam_mixed_root_pockets as original
    original_pin=common._pin(original.__file__)
    require(receipt.get('scope') == 'SAVED_ROUTE_TWO_MIXED_ROOT_POCKETS_V1' and receipt.get('module_pin') == original_pin,
            'Exact original mixed-pocket producer required')
    require(receipt.get('status') == 'uncertain' and receipt.get('phase') == 'finished', 'Exact terminated failure required')
    require(receipt.get('cleanup_session_active') is False and receipt.get('new_feature_ids') == [], 'No native pocket was created')
    require(list(receipt['actions']) == ['CreateSketch:0'], 'Only the first sketch may have been attempted')
    action = receipt['actions']['CreateSketch:0']
    require(action == dict(status='pending', attempted=True, returned=False, readback_verified=False, native_dispatch_pending=True),
            'Original uncertain sketch boundary changed')
    require(all(receipt.get(k) is False for k in ('save_attempted','model_saved','readback_verified','continuation_ready',
            'GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted')),
            'No later native mutation or save allowed')
    require(receipt['issue']['type'] == 'ValueError' and receipt['issue']['locations'][-1] ==
            dict(file='sw_cam_mixed_profile.py', function='curve_interval', line=150), 'Exact interval failure required')
    require(len(receipt['sketch_creations']) == 1 and receipt['sketch_creations'][0].get('sketch_edit_exited') is True,
            'Owned first sketch must already be closed')
    require(receipt['profile_specs'][0]['sketch_name'] == 'RootRestProfile1' and
            receipt['profile_specs'][0]['plane_name'] == 'RootRestPlane1', 'Exact existing first sketch required')
    return receipt


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact mixed-pocket action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact mixed-pocket request fields required')
    require(type(p['process_id'])is int and p['process_id']>0 and p['acknowledgement']=='two_profile_pockets_only_preserve_solid_and_saved_cam_route','Explicit feature-only scope required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v)is str and Path(v).is_absolute(),'Explicit absolute path required')
        if k.endswith('_sha256'):require(type(v)is str and re.fullmatch('[0-9a-f]{64}',v),'Exact SHA256 required')
    require(p['module_sha256']==_file_hash(__file__),'Mixed-pocket adapter changed')
    reopen,pin=authority.reconciliation.read_pin(p['reopen_receipt_path'],p['reopen_receipt_sha256']);validate_reopen(reopen)
    require(reopen['request']['process_id']==p['process_id']and common._key(reopen['source_path'])==common._key(p['expected_document_path'])and reopen['source_sha256']==p['expected_source_sha256'],'Reopen owner/source mismatch')
    loaded,registration,typelib,abi,parent_pin=authority.load_checkpoint(deepcopy(reopen['request']))
    require(group.exact(reopen['reopened'],loaded['guide_parameters']['expected_parameters']),'Actual reopened parameters differ from saved source')
    loaded['generated']={'saved_cl':deepcopy(reopen['reopened_cl'])}
    raw,profile_pin=authority.reconciliation.read_pin(p['profiles_path'],p['profiles_sha256']);specs=profile_specs(raw)
    geometry,geometry_pin=authority.reconciliation.read_pin(p['geometry_path'],p['geometry_sha256'])
    require(geometry.get('scope')=='EXACT_LOCAL_ROOT_FEATURE_INTEGRATION_GEOMETRY'and geometry.get('world_top_z_mm')==10.9 and geometry.get('world_floor_z_mm')==7.5,'Approved depth/bounds evidence required')
    require(any(common._key(v['path'])==common._key(profile_pin['path'])and v['sha256']==profile_pin['sha256']for v in geometry['source_pins']),'Geometry/profile evidence mismatch')
    backup=common._pin(p['source_backup_path']);require(backup['sha256']==p['source_backup_sha256']==p['expected_source_sha256']and common._key(backup['path'])!=common._key(p['expected_document_path']),'Independent unchanged source backup required')
    retired=[v for v in loaded['pins']if Path(v['path']).name in PROOF_ONLY]
    require({Path(v['path']).name for v in retired}==PROOF_ONLY,'Exact completed authority-only pin roles required')
    new=[common._pin(x)for x in(__file__,mixed.__file__,sketch.__file__,sketch.core.__file__)]
    loaded['pins']=common._merge([v for v in loaded['pins']if Path(v['path']).name not in PROOF_ONLY],new)
    require(len(loaded['pins'])<=63,'Shared guard requires at most63 evidence files plus source')
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],retired,new,[pin,parent_pin,profile_pin,geometry_pin,backup,reopen['reopened_cl']['output']])
    require(len(loaded['checkpoint_pins'])<=360,'Bounded immutable history required')
    loaded['configuration_pins']=deepcopy(loaded['checkpoint_pins'])
    loaded['root_pocket_specs']=specs;loaded['root_pocket_registration']=registration;loaded['root_pocket_parent_pin']=pin;loaded['root_pocket_backup_pin']=backup
    failed,failed_pin=authority.reconciliation.read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);failed_contract(failed)
    require(failed['ownership']==loaded['ownership'] and failed['source_sha256']==p['expected_source_sha256'],'Exact failed native owner/source required')
    require(group.exact(failed['before'],loaded['guide_parameters']['expected_parameters']) and group.exact(failed['profile_specs'],specs),'Failed baseline/profiles differ')
    require(common._key(failed['source_path'])==common._key(p['expected_document_path']),'Failed document differs')
    loaded['root_pocket_saved_document']=deepcopy(loaded['guide_parameters']['document'])
    loaded['guide_parameters']['document']['needs_save']=True
    loaded['first_sketch_failure']=failed;loaded['first_sketch_failure_pin']=failed_pin
    from scripts import sw_cam_mixed_root_pockets as original
    canonical=common._pin(failed['request']['receipt_path']);require(canonical['sha256']==failed_pin['sha256'],'Original failed receipt changed after archive')
    prior_marker=common.local_evidence_root()/('two_mixed_root_pockets_'+group._digest(dict(scope=original.SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.once.json')
    prior_marker_pin=common._pin(prior_marker);marker_value,_=authority.reconciliation.read_pin(str(prior_marker),prior_marker_pin['sha256'])
    require(group.exact(marker_value,original.Journal(failed,failed['request']['receipt_path'],prior_marker)._marker_state()),'Original pending marker differs')
    loaded['first_sketch_failure_marker_pin']=prior_marker_pin
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[canonical,prior_marker_pin])
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],[failed_pin,failed['module_pin']])
    loaded['configuration_pins']=deepcopy(loaded['checkpoint_pins'])
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins']);p['expected_configuration']=loaded['guide_parameters']['configuration']['sw_configuration_name']
    preflight=base.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);output=cl._fresh_path(p['saved_cl_path'])
    marker=common.local_evidence_root()/('two_mixed_root_pockets_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.once.json')
    outputs=(receipt,progress,output,marker);protected={common._key(x['path'])for x in loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(x)for x in outputs})==4,'Distinct output paths required')
    for path in outputs:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh nonaliased outputs and no previous attempt required')
    for path in(receipt,progress,marker):require(path.parent.is_dir(),'Diagnostic parent directory must exist')
    return p,loaded,registration,typelib,abi,receipt,marker,preflight


def validate_terminal(r):
    require(r.get('scope')==SCOPE and r.get('module_pin')==common._pin(__file__),'Exact mixed-pocket producer required')
    require(r.get('status')=='saved_resumed_mixed_pockets_review_required'and r.get('phase')=='finished','Successful terminal packet required')
    require(all(r.get(k)is True for k in('model_saved','readback_verified','continuation_ready'))and r.get('cleanup_session_active')is False,'Saved disconnected readback required')
    require(all(r.get(k)is False for k in('GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted','automatic_retry','automatic_rollback','production_qualified')),'Feature-only action contract required')
    names=['CreatePocket:0','CreateSketch:1','CreatePocket:1','SaveActiveDocument'];require(list(r['actions'])==names,'Exact once-only five action order required')
    for name in names:
        v=r['actions'][name];require(v.get('attempted')is True and v.get('returned')is True and v.get('readback_verified')is True and v.get('native_dispatch_pending')is False,'Every declared action must have exact successful readback')
    require(group.exact(r['profile_specs'],r['initial_context']['root_pocket_specs'])and len(r['profile_specs'])==2,'Exact approved two profiles required')
    require(group.exact(r['before'],r['initial_context']['guide_parameters']['expected_parameters']),'Initial trusted seventeen/eight state changed')
    require([x['native_id']for x in r['saved']['binding']['operations']]==list(base.OLD+base.IDS)and [x['operation_native_id']for x in r['saved']['parameters']]==[322,324,326,328,*base.IDS],'Exact seventeen/eight order required')
    require(len(r['saved_new_features'])==len(r['new_features'])==2,'Exactly two full saved feature observations required')
    require(len(r['new_feature_ids'])==2 and len(set(r['new_feature_ids']))==2,'Two real distinct native IDs required')
    require(group.exact(r['before'],r['configured'])and group.exact(r['configured'],r['saved']),'Protected seventeen/eight route changed')
    verify_headers(r['before_features'],r['saved_features'],r['new_feature_ids']);verify_cad(r['before_cad'],r['saved_cad'],r['created_cad_features'])
    require(group.exact(r['saved_new_features'],r['new_features']),'Saved full contours differ')
    for i,(row,spec,ident)in enumerate(zip(r['saved_new_features'],r['profile_specs'],r['new_feature_ids'])):
        checked=verify_pocket(row,spec,native_id=ident)
        require(group.exact(r['actions']['CreatePocket:'+str(i)]['observed'],checked),'Action feature readback differs')
        observed=(r['adopted_first_sketch']if i==0 else r['actions']['CreateSketch:1']['observed'])['readback']
        require(observed.get('arc_interval_midpoint_verified')is True and observed.get('native_rotation_direction_assumed')is False and observed.get('native_rotation_direction_qualified')is True and observed.get('underlying_curve_trim_used')is False and observed.get('native_arc_trim_basis')=='native_endpoints_rotation_and_independent_length','Actual signed native arc readback required')
        mixed.match_rows(spec['profile']['segments'],observed['entities'],1e-8)
    failed=r['initial_context']['first_sketch_failure'];failed_contract(failed)
    failure_pin=r['initial_context']['first_sketch_failure_pin'];archived,_=authority.reconciliation.read_pin(failure_pin['path'],failure_pin['sha256'])
    require(group.exact(failed,archived),'Original failed authority changed')
    require(failed['source_sha256']==r['source_sha256'] and group.exact(failed['before'],r['before']) and group.exact(failed['profile_specs'],r['profile_specs']),'Original failed baseline/source/profiles differ')
    require(common._key(failed['source_path'])==common._key(r['source_path']) and group.exact(failed['ownership'],r['ownership']),'Original failed document/owner differs')
    expected_dirty=deepcopy(r['initial_context']['root_pocket_saved_document']);expected_dirty['needs_save']=True
    require(group.exact(expected_dirty,r['initial_context']['guide_parameters']['document']),'Only proved RAM dirty state may change at resume')
    expected_adopted=[dict(name=r['profile_specs'][0]['plane_name'],type='RefPlane'),dict(name=r['profile_specs'][0]['sketch_name'],type='ProfileFeature')]
    require(group.exact(r['adopted_first_sketch']['created_features'],expected_adopted),'Only exact existing plane and sketch may be adopted')
    created=r['actions']['CreateSketch:1']['observed']['created_features'];require(group.exact(created,r['created_cad_features']),'Remaining CAD additions differ from action readback')
    expected_sketch=dict(name=r['profile_specs'][1]['sketch_name'],type='ProfileFeature');expected_plane=dict(name=r['profile_specs'][1]['plane_name'],type='RefPlane')
    require(created==[expected_sketch]or created==[expected_plane,expected_sketch],'Only remaining sketch and optional offset plane may be created')
    require(r['adopted_first_sketch'].get('read_only')is True and r['adopted_first_sketch'].get('recreated')is False,'First sketch must only be adopted')
    require(group.exact(r['before_features'],failed['before_features']),'Initial native inventory changed before adoption')
    verify_cad(failed['before_cad'],r['adoption_before_cad'],r['adopted_first_sketch']['created_features'])
    verify_cad(r['adoption_before_cad'],r['adoption_after_cad'],[])
    verify_cad(r['before_cad'],r['adoption_after_cad'],[])
    require(r['saved_tool_ids']==r['before_tool_ids']==r['initial_context']['tool_catalogue_ids'],'Tool catalogue changed')
    require(r['protected_cl']['all_fourteen_complete_streams_unchanged']is True,'Protected complete streams changed')
    require(r['source_transition']['source_before_sha256']==r['source_sha256']and r['source_transition']['source_after_sha256']==r['saved_source_sha256']and r['source_transition']['strict_save_return']==0,'Exact one-Save source transition required')
    require(r['saved_source_sha256']!=r['source_sha256'],'Saved source did not change')
    require(r['source_sha256']==r['initial_context']['source_sha256'],'Initial source authority differs')
    require(group.exact(r['source_transition']['document'],r['initial_context']['root_pocket_saved_document']),'Save changed exact saved document identity')
    from scripts.sw_cam_mill_selected_plan_evidence import clean_events
    clean_events(r)
    require(r['source_transition']['document']['needs_save']is False and r['saved_cad']['needs_save']is False,'Exact clean saved document required')
    return r


def load_completed(path,sha,*,check_current=True):
    r,pin=authority.reconciliation.read_pin(path,sha);validate_terminal(r)
    loaded=deepcopy(r['initial_context']);common._check(loaded['checkpoint_pins']);common._check(loaded['pins'])
    require(_file_hash(loaded['root_pocket_backup_pin']['path'])==r['source_sha256'],'Historical source backup changed')
    before=loaded['guide_parameters']['expected_parameters'];require(group.exact(before,r['before']),'Terminal baseline differs from trusted initial context')
    loaded['guide_parameters'].update(document=deepcopy(r['source_transition']['document']),baseline=deepcopy(r['saved']['binding']),expected_parameters=deepcopy(r['saved']))
    loaded['source_sha256']=r['saved_source_sha256'];loaded['generated']={'saved_cl':deepcopy(r['saved_cl'])};loaded['root_pocket_native_inventory']=deepcopy(r['saved_features']);loaded['root_pocket_full_features']=deepcopy(r['saved_new_features']);loaded['root_pocket_cad']=deepcopy(r['saved_cad']);loaded['root_pocket_checkpoint_pin']=pin
    if check_current:require(_file_hash(r['source_path'])==r['saved_source_sha256'],'Current saved source changed')
    cl.verify_all(r['initial_context']['generated']['saved_cl'],r['saved_cl'])
    return loaded


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,guard=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,live_pin_count=len(loaded['pins']),proof_pin_count=len(loaded['checkpoint_pins']),guard_constructor=guard,profile_count=2,protected_operation_count=17,protected_path_count=14,actions=['AdoptExistingSketch:0(read-only)','CreatePocket:0','CreateSketch:1','CreatePocket:1','SaveActiveDocument'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts import sw_connect
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=loaded['ownership'],profile_specs=deepcopy(loaded['root_pocket_specs']),initial_context=deepcopy(loaded),interface_audit=abi,native_guard_preflight=guard)
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        result=run_backend(backend,journal,loaded,loaded['root_pocket_specs'])
        if result.get('continuation_ready')is True:
            try:validate_terminal(result)
            except Exception as exc:result.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc));journal.persist()
        return result