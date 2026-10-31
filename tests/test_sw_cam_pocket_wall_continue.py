"""Offline wall continuation regressions; no COM or CAD access."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(r'C:/Users/Denis Fedorov/.codex/skills/solidworks-automation')
STAGE=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
m=module('wall_staged',STAGE/'scripts/sw_cam_pocket_wall_continue.py')
f=module('finish_fixture',ROOT/'tests/test_sw_cam_pocket_finish_apply.py')


def baseline():
    loaded=f.baseline();loaded['state']['operations'][-1]['assigned_tool']=m.original.wanted_assignment(loaded)
    value=m.original.projected(loaded['pocket_parameters'])
    value['144']['finish'].update(FirstDepthCut=.3,MaxDepthCut=.3,SideCutAmt=.25,GetPreviousAllowance=.5,OverridePrevAllow=True,BottomFinOpt=False)
    for side in ('lead_in','lead_out'):value['144']['leads'][side]['GetIsSameLeadinout']=False
    loaded['pocket_parameters']=value
    return loaded


def capture(loaded,configured=False,generated=False,saved=False):
    state=deepcopy(loaded['state']);state['document']['needs_save']=configured and not saved
    if generated:state['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[1200])
    if saved:state['saved_file_sha256']='b'*64
    return dict(state=state,parameters=m.expected_parameters(loaded['pocket_parameters'],configured),startpoints=deepcopy(loaded['pocket_startpoints']),catalogue=deepcopy(loaded['neck_tool_checkpoint']['catalogue']))


class Backend(f.Backend):
    def __init__(self,loaded,r,fail=None):
        super().__init__(loaded,r,fail=fail);self.values=m.initial_fields()
    def capture_full(self,label):
        v=capture(self.loaded,label!='initial',label!='initial',label!='initial')
        if label=='initial' and self.fail=='initial_comp':v['parameters']['144']['nc']['feeds_compensation']['GetCNCComp']=0
        if label=='saved' and self.fail=='save_drift':v['parameters']['144']['finish']['BottomFinOpt']=True
        return v
    def capture_narrow(self,label):
        v=capture(self.loaded,True,self.generated)
        if label=='configured' and self.fail=='configured_floor':v['parameters']['144']['finish']['BottomFinOpt']=True
        return v
    def set_field(self,spec,pending):
        pending();self.calls.append(spec[0])
        if self.fail=='pending':raise RuntimeError('native dispatch interrupted')
        if self.fail!='mismatch':self.values[spec[0]]=deepcopy(spec[6])
        return True if self.fail=='bool_hresult' else 1 if self.fail==spec[0] else 0
    def generate(self,pending):
        pending();self.calls.append('generate');self.generated=True
        return 1 if self.fail=='generate' else 0


def run(fail=None):
    loaded=baseline();r=f.report(loaded);r.update(scope=m.SCOPE,initial_full_capture_verified=False,floor_candidate_included=False,**{k:False for k in m.FORBIDDEN})
    b=Backend(loaded,r,fail);m.run_backend(b,f.Journal(r),loaded);return loaded,r,b


class Tests(unittest.TestCase):
    def test_only_eight_leads_change(self):
        old=baseline()['pocket_parameters'];new=m.expected_parameters(old,True)
        self.assertEqual(new['143'],old['143']);self.assertEqual(new['144']['finish'],old['144']['finish']);self.assertEqual(new['144']['nc'],old['144']['nc']);self.assertFalse(new['144']['finish']['BottomFinOpt'])
        self.assertEqual(len(m.FIELDS),8);self.assertFalse(any('bottom' in x[0] for x in m.FIELDS))
    def test_saved_tool_reused_without_assignment(self):
        _,r,b=run();self.assertTrue(r['readback_verified'],r.get('issue'));self.assertNotIn('assign',b.calls)
        self.assertEqual(b.calls.count('generate'),1);self.assertEqual(b.calls.count('save'),1);self.assertEqual(set(r['actions']),set(m.ACTIONS))
    def test_fresh_nc_mismatch_stops_before_mutation(self):
        _,r,b=run('initial_comp');self.assertFalse(r['mutation_attempted']);self.assertEqual(b.calls,['start','close'])
    def test_actual_mismatch_is_retained_no_generation(self):
        _,r,b=run('mismatch');self.assertEqual(r['actions']['field:lead_in_angle']['observed'],45.);self.assertNotIn('generate',b.calls);self.assertFalse(r['readback_verified'])
    def test_pending_call_never_replayed(self):
        _,r,b=run('pending');self.assertTrue(r['actions']['field:lead_in_angle']['pending']);self.assertEqual(b.calls.count('lead_in_angle'),1);self.assertNotIn('generate',b.calls)
    def test_nonzero_or_bool_hresult_stops(self):
        for fail in ('lead_in_angle','bool_hresult'):
            _,r,b=run(fail);self.assertFalse(r['readback_verified']);self.assertNotIn('generate',b.calls)
    def test_floor_drift_prevents_generation(self):
        _,r,b=run('configured_floor');self.assertFalse(r['readback_verified']);self.assertNotIn('generate',b.calls)
    def test_failed_gtp_does_not_save(self):
        _,r,b=run('generate');self.assertEqual(b.calls.count('generate'),1);self.assertNotIn('save',b.calls)
    def test_save_readback_drift_not_accepted(self):
        _,r,b=run('save_drift');self.assertEqual(b.calls.count('save'),1);self.assertFalse(r['readback_verified'])
    def test_other_five_paths_cannot_change(self):
        loaded=baseline()
        for oid in (267,247,248,271,143):
            c=capture(loaded);next(v for v in c['state']['operations'] if v['native_id']==oid)['toolpath_record_counts'][0]+=1
            with self.assertRaises(ValueError):m.verify_capture(loaded,c)
    def test_unrelated_drill_cannot_generate(self):
        loaded=baseline();c=capture(loaded);c['state']['operations'][0]['toolpath_generated']=True
        with self.assertRaises(ValueError):m.verify_capture(loaded,c)
    def test_assignment_cannot_drift(self):
        loaded=baseline();c=capture(loaded);c['state']['operations'][-1]['assigned_tool']['native_id']=145
        with self.assertRaises(ValueError):m.verify_capture(loaded,c)
    def test_catalogue_startpoint_nc_and_bottom_preserved(self):
        loaded=baseline()
        for kind in ('catalogue','startpoints','comp','feed','bottom'):
            c=capture(loaded,True)
            if kind in ('catalogue','startpoints'):c[kind]=[]
            elif kind=='bottom':c['parameters']['144']['finish']['BottomFinOpt']=True
            else:c['parameters']['144']['nc']['feeds_compensation']['GetTlpComp' if kind=='comp' else 'XYFeed']=0
            with self.assertRaises(ValueError):m.verify_capture(loaded,c,configured=True)
    def test_terminal_success_and_tamper(self):
        loaded,r,_=run()
        with patch.object(m.group,'current_projection',lambda c:{'state':c['state'],'source_sha256':c['source_sha256']}):
            ctx=m.validate_terminal(r);self.assertFalse(ctx['generated_pocket_finish']['floor_candidate_included'])
            r['actions']['field:lead_in_angle']['observed']=45.
            with self.assertRaises(ValueError):m.validate_terminal(r)
    def test_native_writer_rejects_floor_setter_without_com(self):
        b=object.__new__(m.NativeBackend)
        with self.assertRaises(ValueError):b.set_field(m.original.FIELDS[6],lambda:None)
        with self.assertRaises(RuntimeError):b.assign(lambda:None)
    def test_reopen_binding_drift_fails_before_history_or_com(self):
        p=dict(reopen_receipt_path='r.json',reopen_receipt_sha256='a'*64,process_id=3,expected_source_sha256='b'*64,expected_document_path='C:/part.sldprt')
        receipt=dict(process_id=4,source_sha256='b'*64,source_path='C:/part.sldprt')
        with patch.object(m.reopen,'load_verified_reopen',return_value=receipt),patch.object(m,'read_pin') as read:
            with self.assertRaises(ValueError):m.load_inputs(p)
            read.assert_not_called()


if __name__=='__main__':unittest.main()
