"""Read one existing native mixed pocket after its geometric match stopped.

Reuse the owned MILL reader and chain extractor; persist complete and partial
native observations before interpretation. No creation, save, or generation.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_mixed_root_resume as previous
from scripts import sw_cam_profile_sketch as cad_core
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error

common,group,cl=previous.common,previous.group,previous.cl
SCOPE='EXISTING_MIXED_POCKET_RAW_DIAGNOSTIC_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','expected_feature_native_id',
        'failed_receipt_path','failed_receipt_sha256','module_sha256','receipt_path'}


def failed_contract(r,feature_id):
    require(r.get('scope')==previous.SCOPE and r.get('module_pin')==common._pin(previous.__file__),'Exact resumed producer required')
    require(r.get('status')=='uncertain'and r.get('phase')=='finished'and r.get('cleanup_session_active')is False,'Terminated uncertain feature match required')
    require(type(feature_id)is int and feature_id>0 and r.get('new_feature_ids')==[feature_id],'Exactly one actual returned native feature required')
    require(list(r['actions'])==['CreatePocket:0'],'No later mutation may have started')
    require(r['actions']['CreatePocket:0']==dict(status='pending',attempted=True,returned=False,readback_verified=False,native_dispatch_pending=True),'Exact original pending action required')
    require(all(r.get(k)is False for k in ('save_attempted','model_saved','readback_verified','continuation_ready','GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted')),'No later operation/save/generation permitted')
    require(r['issue']['type']=='ValueError'and r['issue']['locations'][-1]==dict(file='sw_cam_signed_mixed_profile.py',function='match_rows',line=164),'Exact geometric match failure required')
    require(r['adopted_first_sketch'].get('read_only')is True and r['adopted_first_sketch'].get('recreated')is False,'Prior first sketch adoption must be read-only')
    require(r['current_document']['needs_save']is True and r['created_cad_features']==[],'Only existing first sketch and one native pocket permitted')
    require(group.exact(r['before'],r['initial_context']['guide_parameters']['expected_parameters']),'Original full17/eight baseline differs')
    return r


class NativeBackend(previous.NativeBackend):
    def create_pocket(self,*a):raise ValueError('Read-only feature diagnostic')
    def create_sketch(self,*a):raise ValueError('Read-only feature diagnostic')
    def adopt_first_sketch(self,*a):raise ValueError('No repeated sketch adoption is needed')
    def save(self,*a):raise ValueError('Read-only feature diagnostic')
    def capture_snapshot(self,*a,**k):raise ValueError('Do not repeat full seventeen/eight parameter capture')
    def capture_binding(self,label):
        return previous.NativeBackend.capture_snapshot(self,label,full=False)['binding']
    def cad(self,spec):
        self.boundary();state,model,refs=cad_core._snapshot(self.sw,self.args['process_id'],self.args['expected_document_path'],spec);self.boundary()
        return state,model,refs
    def raw_feature(self,native_id):
        self.boundary()
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');found=g.read(doc,'GetCWObjectFromID',1,native_id)
            require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact feature lookup required')
            header,raw=previous.read_header(found[0],doc,g.read,g.typed,69);mill=g.typed(raw,'ICWMillFeature');count=g.read(mill,'IGetIslandCount')
            result=dict(owner_setup_native_id=69,header=header,island_count=count,contours={})
            self.report['raw_feature']=result;self.report['raw_contour_diagnostics']={};self.persist()
            require(header.get('native_id')==native_id,'Actual feature identity differs from requested ID')
            budget=dict(curves=0,chains=0,islands=0)
            for name,method in(('top','IGetTopSegChain'),('bottom','IGetBottomSegChain')):
                partial={};result['contours'][name]=partial
                diagnostic={'state':partial};self.report['raw_contour_diagnostics'][name]=diagnostic;self.persist()
                try:previous.inventory.read_segment_chains(mill,method,read=g.read,typed=g.typed,diagnostic=diagnostic,budget=budget)
                finally:self.persist()
        self.report['raw_feature_read_complete']=True;self.persist();return result


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='read_existing_mixed_feature','Exact read-only feature action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact read-only request fields required')
    require(p['module_sha256']==previous._file_hash(__file__),'Exact diagnostic implementation required')
    r,pin=previous.authority.reconciliation.read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);failed_contract(r,p['expected_feature_native_id'])
    require(type(p['process_id'])is int and p['process_id']==r['ownership']['process_id']==r['request']['process_id'],'Exact owned process required')
    require(common._key(p['expected_document_path'])==common._key(r['source_path']),'Exact failed document required')
    require(p['expected_source_sha256']==r['source_sha256']==previous._file_hash(p['expected_document_path']),'Saved source must remain unchanged')
    loaded=deepcopy(r['initial_context'])
    require(group.exact(loaded['ownership'],r['ownership'])and group.exact(loaded['guide_parameters']['document'],r['current_document']),'Exact current dirty document/owner required')
    canonical=common._pin(r['request']['receipt_path']);require(canonical['sha256']==pin['sha256'],'Failed canonical receipt differs from archive')
    marker=common.local_evidence_root()/('two_mixed_root_pockets_'+group._digest(dict(scope=previous.SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.once.json')
    marker_pin=common._pin(marker);value,_=previous.authority.reconciliation.read_pin(str(marker),marker_pin['sha256'])
    require(group.exact(value,previous.Journal(r,r['request']['receipt_path'],marker)._marker_state()),'Original pending marker changed')
    retired=[v for v in loaded['pins']if Path(v['path']).name=='sw_cam_signed_mixed_profile_sketch.py']
    require(len(retired)==1,'Exact creation-only sketch module phase required')
    # cad() calls the shared snapshot directly; no signed sketch creator executes.
    loaded['pins']=common._merge([v for v in loaded['pins']if v not in retired],[common._pin(__file__)])
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],retired,[pin,canonical,marker_pin,common._pin(__file__)])
    require(len(loaded['pins'])<=63,'Shared guard maximum with source required')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=loaded['root_pocket_registration'];typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    require(common._pin(typelib)in loaded['pins'],'Actual native typelib differs')
    p['expected_configuration']=r['request']['expected_configuration']
    guard=previous.base.guard_constructor_preflight(p,loaded,typelib)
    output=common._local_receipt(p['receipt_path']);protected={common._key(v['path'])for v in loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(not output.exists()and not output.is_symlink()and output.parent.is_dir()and common._key(output)not in protected,'Fresh nonaliased diagnostic output required')
    return p,r,pin,loaded,registration,typelib,guard


def run_backend(backend,report,failed,persist):
    report.update(status='error',phase='reading',actions={},readback_verified=False,raw_feature_read_complete=False,
        mutation_attempted=False,save_attempted=False,GTP_attempted=False,GOP_attempted=False,feature_geometry_accepted=False)
    try:
        backend.start();backend.proof_boundary()
        report['before_binding']=backend.capture_binding('raw_feature_before');persist()
        require(group.exact(report['before_binding'],failed['before']['binding']),'Known seventeen-operation binding changed')
        report['before_cad']=backend.cad(failed['profile_specs'][0])[0];persist()
        backend.raw_feature(failed['new_feature_ids'][0]);persist()
        # All geometric interpretation is deliberately left to offline review.
        report['headers']=backend.headers();persist()
        previous.verify_headers(failed['before_features'],report['headers'],failed['new_feature_ids'])
        report['after_binding']=backend.capture_binding('raw_feature_after');persist()
        report['after_cad']=backend.cad(failed['profile_specs'][0])[0];persist()
        require(group.exact(report['after_binding'],report['before_binding']),'Read-only binding changed')
        previous.verify_cad(failed['before_cad'],report['before_cad'],[])
        previous.verify_cad(report['before_cad'],report['after_cad'],[])
        require(report['before_cad']['needs_save']is True and report['after_cad']['needs_save']is True,'Dirty flag changed during read')
        backend.proof_boundary();backend.finish()
        report.update(status='raw_feature_observed',phase='finished',readback_verified=True)
    except Exception as exc:report.update(status='error',phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:previous.generation.close_checked(backend,report)
        except Exception as exc:report.update(cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return report


def dispatch_request(request,*,validate_only=False):
    p,failed,pin,loaded,registration,typelib,guard=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_calls=0,live_pins=len(loaded['pins']),proof_pins=len(loaded['checkpoint_pins']),guard=guard)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts import sw_connect
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),failed_receipt_pin=pin,
                    source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=loaded['ownership'],native_guard_preflight=guard)
        persist=lambda:_write_receipt(p['receipt_path'],report)
        persist();backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,persist)
        return run_backend(backend,report,failed,persist)
