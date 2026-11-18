"""Explicit four-island definition endpoint, no generation or Save."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_explicit_island_authority as authority
from scripts import sw_cam_explicit_island_feature as component
from scripts import sw_cam_explicit_island_chain_proof as chain_proof
from scripts import sw_cam_process_import as shared
from scripts import sw_cam_current_saved_generation as engine
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest

SCOPE='SAVED_SKETCHES_ONE_EXPLICIT_POCKET_FOUR_ISLANDS_V1'
FLAGS=('definition_readback_verified','inventory_delta_verified','indexed_chain_binding_verified',
       'source_unchanged','protected_files_unchanged','runtime_unchanged')
require=shared.require

def prepare(v,*,runtime_check):
    return shared.prepare(v,runtime_check=runtime_check,_validate=authority.prepare)

class Journal(engine.Journal):
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,target=r['request']['expected_document_path'],
            source_sha256=r['request']['expected_source_sha256'],receipt_path=str(self.receipt),
            authority_pins=r['authority_pins'],actions=deepcopy(r['component'].get('actions',[])),
            status=r['status'],phase=r['phase'],automatic_replay=False)
    def pending_component(self,name):
        actions=self.report['component']['actions']
        require(actions[-1]['name']==name and sum(x['name']==name for x in actions)==1,
                'One declared component action intent required')
        wanted=['CreateMillFeature2']+['AddIslandToFeature:'+x for x in self.report['feature_plan']['island_sketch_names']]
        require([x['name']for x in actions]==wanted[:len(actions)],'Exact factory/four-island order required')
        if not self.claimed:self.claim()
        self.report.update(mutation_attempted=True,phase=name)
        self.persist()

class Context(shared.ImportContext):
    def start(self):
        super().start()
        require(self.sw_configuration==self.v['expected_sw_configuration'],'Exact CAD configuration required')
        self.verify_sketches()
    def verify_sketches(self):
        outer=self.data['outer_spec']
        with self.guard()as g:
            observed,model,_=g._observe(lambda:authority.circle._snapshot(
                self.sw,self.v['process_id'],self.v['expected_document_path'],outer))
            authority.circle._verify_expected_state(self.data['expected_cad'],observed,
                authority.circle._state_digest(self.data['expected_cad']))
            observations=[]
            for spec in [outer]+self.data['island_specs']:
                f=g.read(model,'FeatureByName',spec['sketch_name'])
                require(f is not None and g.read(f,'GetTypeName2')=='ProfileFeature','Exact named sketch required')
                raw=g.read(f,'GetSpecificFeature2')
                if spec is outer:
                    native=g._observe(lambda:authority.circle._read_sketch(self.sw,raw,spec))
                else:
                    native=g._observe(lambda:authority.sketches.sketch._read_sketch(self.sw,raw,spec))
                    authority.sketches.verify_readback(spec,native)
                observations.append(dict(spec=deepcopy(spec),sketch_readback=native))
            g._boundary()
        self.r['fresh_five_sketches']=observations;self.persist()
    def capture(self,label,*,empty):
        state=super().capture(label,empty=empty)
        require(state['cam_configuration_name']==self.v['expected_cam_configuration']
            and state['associated_sw_configuration']==self.v['expected_sw_configuration'],'Exact CAM/CAD configuration binding required')
        if label=='explicit_feature_before':
            inventory=deepcopy(state);inventory.pop('sw_reference');inventory.pop('all_solid_body_count')
            require(inventory==self.data['expected_inventory'],'Fresh empty CAM differs from producer')
        return state

def revoke(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',phase='finished',runtime_error=_error(error))
    for key in FLAGS:r[key]=False
    _write_receipt(Path(r['receipt_path']),r)
    return r

def run(sw,clsid,tlb,v,*,runtime_check,prepared=None,_context_factory=Context):
    bundle=prepared if prepared is not None else prepare(v,runtime_check=runtime_check)
    data=shared._consume(bundle,v,runtime_check)
    abi=component.preflight(tlb)
    for module in (component,authority,chain_proof):
        require(any(authority.same_path(x['path'],module.__file__)and x['sha256']==_file_hash(module.__file__)
                    for x in data['pins']),'Executed component must be pre-pinned')
    r=dict(scope=SCOPE,status='running',phase='prepared',request=deepcopy(v),
        receipt_path=str(data['receipt']),marker_path=str(data['marker']),feature_plan=deepcopy(data['feature_plan']),
        authority_pins=[data['batch']['pin']]+[x for x in data['pins']if x['path']in(v['circle_receipt_path'],v['circle_save_receipt_path'],v['feature_plan_path'])],
        evidence_pins=deepcopy(data['pins']),abi=abi,component={},mutation_attempted=False,
        Save_attempted=False,GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,
        Import_attempted=False,explicit_rebuild_attempted=False,model_saved=False,
        automatic_replay=False,production_qualified=False,machining_eligible=False,
        physical_depth_verified=False,world_profile_placement_verified=False,
        source_before_sha256=v['expected_source_sha256'])
    for key in FLAGS:r[key]=False
    journal=Journal(data['receipt'],data['marker'],r);context=None
    try:
        journal.create();context=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check)
        context.start()
        component.create_one(component.Backend(context),data['feature_plan'],claim=journal.pending_component,
            persist=journal.persist,report=r['component'],
            verify_chains=lambda observed:chain_proof.verify_indexed(observed,data['outer_spec'],
                data['island_specs'],length_scale_to_mm=1.0))
        r['before']=deepcopy(r['component']['before']);r['after']=deepcopy(r['component']['after'])
        r['feature_header']=deepcopy(r['component']['header_readbacks'][-1]['scalars'])
        r['new_feature_native_id']=r['component']['new_feature_native_id']
        r['indexed_readback']=deepcopy(r['component']['indexed_readback'])
        journal.persist();context.close()
        shared.event_health(r['messages'],active=False)
        require(r['messages']['event_count']==0,'Any CAM event rejects qualification')
        actual=context.identity();require(actual==context.expected,'Cleanup changed document')
        context.verify_files();runtime_check()
        r.update(after_cleanup_document=actual,source_after_sha256=_file_hash(v['expected_document_path']))
        require(r['source_after_sha256']==v['expected_source_sha256'],'Definition-only action changed disk source')
        for key in FLAGS:r[key]=True
        r.update(status='definition_only',phase='finished',reason='EXPLICIT_NAMED_INDEXED_PROFILE_DEFINITION_NO_MACHINING_ACCEPTANCE')
    except Exception as error:
        r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',issue=_error(error))
        for key in FLAGS:r[key]=False
    finally:
        try:
            if context is not None:context.close()
            runtime_check();journal.persist()
        except Exception as error:
            r.update(status='uncertain'if r.get('mutation_attempted')else'error',phase='finished',cleanup_error=_error(error))
            for key in FLAGS:r[key]=False
            try:journal.persist()
            except Exception:r['receipt_write_failed']=True
    return r