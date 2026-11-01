"""Offline contract tests for saving an already configured empty wall."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import tempfile,unittest
from wall_test_fixtures import failed_wall_receipt
from scripts import sw_cam_wall_apply_all_save as m

NEW_SHA='b'*64

def fixture():
    prior=failed_wall_receipt();loaded=prior['loaded_context_before']
    loaded['pocket_parameters']=deepcopy(prior['configured']['parameters'])
    loaded['pocket_parameters']['144']['finish']['PerimeterPassType']=2
    for key in m.group.CURRENT_KEYS:loaded.setdefault(key,None)
    loaded['source_sha256']='a'*64;loaded['state']['saved_file_sha256']='a'*64
    loaded['state']['document']['needs_save']=False
    initial=dict(state=deepcopy(loaded['state']),parameters=deepcopy(loaded['pocket_parameters']),
        startpoints=deepcopy(loaded['pocket_startpoints']),catalogue=deepcopy(loaded['neck_tool_checkpoint']['catalogue']),
        restrictions=dict(LeadInOutApplyToAll=False,GougeCheck=True))
    configured=deepcopy(initial);configured['state']['document']['needs_save']=True
    configured['restrictions']['LeadInOutApplyToAll']=True
    status=dict(operation_native_id=144,feature_native_id=79,tool_native_id=273,
        background_over_before=False,background_over_after=False,generated=False,generated_for_feature=False,record_counts=[])
    actions={}
    for spec in m.candidate.FIELDS:
        actions['field:'+spec[0]]=dict(attempted=True,returned=True,pending=False,native_return_type='int',native_return_value=0,readback_verified=True,observed=deepcopy(spec[6]))
    actions['GenerateToolpath']=dict(attempted=True,returned=True,pending=False,native_return_type='int',native_return_value=0,readback_verified=True)
    return dict(scope=m.candidate.SCOPE,status='no_toolpath_no_save',phase='finished',model_saved=False,
        generation_verified=False,generated_record_counts=[],readback_verified=True,configuration_readback_verified=True,
        initial_full_capture_verified=True,phase_proofs_verified=True,actions=actions,loaded_context_before=loaded,
        initial_status=status,generation_status=deepcopy(status),initial=initial,configured=configured,generated=deepcopy(configured),
        source_path=str(Path('synthetic_part.SLDPRT').resolve()),initial_source_sha256='a'*64,
        checkpoint_pin=dict(path=str(Path('synthetic_checkpoint.json').resolve()),sha256='c'*64),
        messages=dict(subscribed=True,disconnected=True,active=False),**{k:False for k in m.candidate.FORBIDDEN})

def report(parent):
    loaded=m.validate_empty(parent)
    pin=dict(path='parent.json',sha256='a'*64)
    return dict(scope=m.SCOPE,status='prepared',phase='prepared',source_path=parent['source_path'],
        initial_source_sha256=parent['initial_source_sha256'],parent_pin=pin,actions={},mutation_attempted=False,
        model_saved=False,readback_verified=False,loaded_context_before=loaded,
        catalogue_reuse=dict(parent_pin=pin,catalogue_sha256=m._digest(loaded['neck_tool_checkpoint']['catalogue']),fresh_full_profile_reads=0),
        **{k:False for k in m.FORBIDDEN})


class Backend:
    def __init__(self,parent,r,*,save_return=0,drift=None,new_sha=NEW_SHA):
        self.parent,self.report=parent,r;self.save_return=save_return;self.drift=drift;self.new_sha=new_sha
        self.calls=[];self.saved=False
    def start(self):self.calls.append('start')
    def close(self):self.calls.append('close')
    def finish(self):self.calls.append('finish');self.report['messages']=deepcopy(self.parent['messages'])
    def boundary(self):self.calls.append('boundary')
    def outcome(self):
        value=deepcopy(self.parent['generation_status'])
        if self.drift=='output':value.update(generated=True,generated_for_feature=True,record_counts=[1])
        return value
    def restrictions(self):return dict(LeadInOutApplyToAll=True,GougeCheck=self.drift!='gouge')
    def capture_narrow(self,label):
        self.calls.append(label);value=deepcopy(self.parent['generated'])
        if label.endswith('after'):
            value['state']['saved_file_sha256']=self.new_sha;value['state']['document']['needs_save']=False
            if self.drift=='after':value['restrictions']['LeadInOutApplyToAll']=False
        if self.drift=='route':value['state']['operations'][0]['suppressed']=not value['state']['operations'][0]['suppressed']
        return value
    def save(self):self.calls.append('save');self.saved=True;return self.save_return
    def saved_hash(self,stage):
        assert stage['native_call_returned'] is True and stage['native_return_value']==0
        self.calls.append('saved_hash');self.report['source_transition']=dict(strict_save_return=0,
            source_before_sha256=self.report['initial_source_sha256'],source_after_sha256=self.new_sha)
        return self.new_sha


class SaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.parent=fixture()
    def run_case(self,**kwargs):
        parent=deepcopy(self.parent);r=report(parent);b=Backend(parent,r,**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            j=m.Journal(r,Path(folder)/'receipt.json',Path(folder)/'marker.json')
            m.run_backend(b,j,r['loaded_context_before'])
        return r,b
    def test_synthetic_terminal_parent_accepted(self):
        loaded=m.validate_empty(self.parent)
        self.assertFalse(loaded['state']['operations'][-1]['toolpath_generated'])
        self.assertEqual(loaded['state']['operations'][-1]['toolpath_record_counts'],[])
    def test_parent_rejects_uncertainty(self):
        for key,value in [('status','uncertain'),('readback_verified',False),('phase_proofs_verified',False),('issue',{})]:
            with self.subTest(key=key):
                bad=deepcopy(self.parent);bad[key]=value
                with self.assertRaises(ValueError):m.validate_empty(bad)
    def test_parent_rejects_false_or_nonzero_hresult(self):
        for value in (False,1,None):
            bad=deepcopy(self.parent);bad['actions']['GenerateToolpath']['native_return_value']=value
            with self.assertRaises(ValueError):m.validate_empty(bad)
    def test_parent_rejects_pending_generation(self):
        bad=deepcopy(self.parent);bad['actions']['GenerateToolpath']['pending']=True
        with self.assertRaises(ValueError):m.validate_empty(bad)
    def test_parent_rejects_any_unapproved_write(self):
        for key in m.candidate.FORBIDDEN:
            bad=deepcopy(self.parent);bad[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):m.validate_empty(bad)
    def test_parent_rejects_changed_recorded_field(self):
        bad=deepcopy(self.parent);bad['actions']['field:lead_in_radius']['observed']=[1.,False,0.]
        with self.assertRaises(ValueError):m.validate_empty(bad)
    def test_parent_rejects_save_or_toolpath(self):
        for field in ('save','path'):
            bad=deepcopy(self.parent)
            if field=='save':bad['actions']['SaveActiveDocument']={}
            else:bad['generated_record_counts']=[100]
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate_empty(bad)
    def test_parent_rejects_protected_route_drift(self):
        bad=deepcopy(self.parent);bad['generated']['state']['operations'][2]['toolpath_record_counts']=[761]
        with self.assertRaises(ValueError):m.validate_empty(bad)
    def test_success_saves_once_and_keeps_no_path(self):
        r,b=self.run_case();r['phase_proofs_verified']=True
        context=m.validate_saved(r)
        self.assertEqual(b.calls.count('save'),1);self.assertEqual(b.calls.count('close'),1)
        self.assertTrue(r['readback_verified']);self.assertEqual(set(r['actions']),{'SaveActiveDocument'})
        self.assertNotIn('generated_pocket_finish',context)
        self.assertFalse(context['wall_apply_all_configuration']['generated'])
        self.assertEqual(context['source_sha256'],NEW_SHA)
        self.assertEqual(context['neck_tool_checkpoint']['catalogue'],r['loaded_context_before']['neck_tool_checkpoint']['catalogue'])
    def test_before_guards_prevent_save(self):
        for drift in ('route','gouge','output'):
            with self.subTest(drift=drift):
                r,b=self.run_case(drift=drift);self.assertFalse(r['readback_verified']);self.assertNotIn('save',b.calls)
    def test_bad_save_return_never_retries(self):
        for value in (False,None,1):
            with self.subTest(value=value):
                r,b=self.run_case(save_return=value);self.assertEqual(b.calls.count('save'),1)
                self.assertEqual(r['status'],'uncertain');self.assertNotIn('saved_hash',b.calls)
    def test_after_readback_drift_never_retries(self):
        r,b=self.run_case(drift='after');self.assertEqual(b.calls.count('save'),1);self.assertFalse(r['readback_verified'])
        self.assertNotIn('finish',b.calls)
    def test_unchanged_disk_hash_not_authority(self):
        r,b=self.run_case(new_sha=self.parent['initial_source_sha256'])
        self.assertEqual(b.calls.count('save'),1);self.assertFalse(r['readback_verified'])
    def test_saved_validator_rejects_gouge_or_coverage_claim(self):
        good,_=self.run_case();good['phase_proofs_verified']=True
        for field in ('gouge','catalogue','GTP','return','path','restriction'):
            bad=deepcopy(good)
            if field=='gouge':bad['final']['restrictions']['GougeCheck']=False
            elif field=='catalogue':bad['catalogue_reuse']['fresh_full_profile_reads']=19
            elif field=='GTP':bad['GTP_attempted']=True
            elif field=='return':bad['source_transition']['strict_save_return']=False
            elif field=='path':bad['generated_record_counts']=[1]
            else:bad['final']['restrictions']['LeadInOutApplyToAll']=False
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate_saved(bad)
    def test_write_methods_and_full_catalogue_are_disabled(self):
        backend=object.__new__(m.NativeBackend)
        for name in ('set_field','assign','generate','capture_full'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):getattr(backend,name)()
    def test_journal_rejects_non_save_and_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            r=report(deepcopy(self.parent));j=m.Journal(r,Path(folder)/'receipt.json',Path(folder)/'marker.json')
            with self.assertRaises(ValueError):j.pending('GenerateToolpath')
            j.pending('SaveActiveDocument')
            with self.assertRaises(ValueError):j.pending('SaveActiveDocument')
    def test_existing_marker_prevents_save_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/'marker.json';marker.write_text('{}')
            j=m.Journal(report(deepcopy(self.parent)),Path(folder)/'receipt.json',marker)
            with self.assertRaises(ValueError):j.pending('SaveActiveDocument')
    def test_completed_loader_validates_parent_and_new_source(self):
        r,_=self.run_case();r.update(phase_proofs_verified=True,process_id=55,module_pin={'path':'module','sha256':'x'},
            live_pins=[],offline_proof_pins=[],bootstrap_export_pins=[])
        context=m.validate_saved(r);r['checkpoint_digest']=m._digest(m.group.current_projection(context));r['marker_pin']={'sha256':'f'*64}
        receiptpin={'path':str(Path('new.json').resolve()),'sha256':'e'*64};markerpin={'path':str(Path('mark.json').resolve()),'sha256':'f'*64}
        mark=m.Journal(r,'new.json','mark.json').marker_state()
        def read(path,sha):
            if path=='new.json':return deepcopy(r),receiptpin
            if path==r['parent_pin']['path']:return deepcopy(self.parent),r['parent_pin']
            return mark,markerpin
        with patch.object(m,'read_pin',side_effect=read),patch.object(m,'_file_hash',return_value=NEW_SHA),patch.object(m.common,'_pin',return_value=r['module_pin']),patch.object(m.common,'_check'),patch.object(m,'marker_path',return_value=Path('mark.json')):
            loaded=m.load_completed('new.json','n',process_id=55,expected_document_path=r['source_path'],expected_source_sha256=NEW_SHA)
            self.assertEqual(loaded['parent_pin'],receiptpin);self.assertEqual(loaded['state']['operations'][-1]['toolpath_record_counts'],[])
            with self.assertRaises(ValueError):m.load_completed('new.json','n',process_id=56,expected_document_path=r['source_path'],expected_source_sha256=NEW_SHA)


if __name__=='__main__':unittest.main()
