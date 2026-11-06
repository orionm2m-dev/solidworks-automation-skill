from copy import deepcopy
from pathlib import Path
import json,inspect,ast
import pytest
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts import sw_cam_current_saved_generation as generation
from scripts import sw_cam_current_circular_authority as authority
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_current_saved_generation_delta as plain_delta
from scripts.sw_cam_current_circular_continuation import CircularGenerationContext
from scripts.sw_cam_current_generation_native import NativeGenerationContext
from test_circular_engines import circular_engine
from test_circular_continuation import completed,pin
from test_current_saved_generation_engine import Backend


def jitter(state,step):
    out=deepcopy(state)
    mass=out['sketch_state']['solids'][0]['mass_raw']
    mass[0]=mass[0]*(1.+step*1.e-13)
    return out


def test_every_configure_and_gtp_capture_tolerates_only_mass_without_rewriting_raw(circular_engine,monkeypatch):
    e=circular_engine;original=batch.run_current_saved_configuration;counter=[0]
    def wrapped(*args,_context_factory,**kw):
        class Context(_context_factory):
            def capture(self,label,consumers):
                raw=super().capture(label,consumers);counter[0]+=1;actual=jitter(raw,counter[0]);self.report[label]=actual;self.persist();return actual
        return original(*args,_context_factory=Context,**kw)
    monkeypatch.setattr(batch,'run_current_saved_configuration',wrapped)
    prepared=e['run']('prepare');assert prepared['readback_verified'],prepared
    assert prepared['before']!=prepared['confirm_before']
    assert prepared['state_sha256']==authority._digest(prepared['before'])
    result=e['run']('apply');assert result['model_saved'] and result['readback_verified'],result
    assert result['saved']!=result['confirm_saved'] and result['before']!=prepared['before']
    saved_raw=deepcopy(result['saved']);cp=pin(e['root']/'jitter_configured.json',result)
    loaded=authority.load_configured(cp['path'],cp['sha256'],process_id=123,source_path=e['v']['expected_document_path'],source_sha256='c'*64,selected_ids=[13])
    assert loaded['state']==saved_raw
    class CircularBackend(Backend):
        def __init__(self):super().__init__();self.value=deepcopy(loaded['state']);self.source='c'*64;self.capture_index=0
        def capture(self,label,partial):
            value=super().capture(label,partial);self.capture_index+=1;value=jitter(value,self.capture_index);partial.clear();partial.update(deepcopy(value));return value
        def generate(self,oid,prior,*,pending,returned):super().generate(oid,prior,pending=pending,returned=returned);self.value['sketch_state']['needs_save']=True
        def save(self,*,returned):
            value=super().save(returned=returned);self.value['sketch_state'].update(needs_save=False,saved_file_sha256='d'*64);return value
        def adopt_saved_source(self,report):self.source='d'*64;return self.source
    backend=CircularBackend();report={};journal=generation.Journal(e['root']/'jitter_generated.json',e['root']/'gtp_once.json',report);generation.run_once(backend,journal,loaded)
    assert report['readback_verified'] and report['model_saved'],report
    assert report['saved']!=report['confirm_saved']
    assert report['save_stage']['before']==report['save_stage']['after']
    assert report['save_stage']['before']['sketch_state']['solids'][0]['mass_raw']==loaded['state']['sketch_state']['solids'][0]['mass_raw']
    assert report['saved']['sketch_state']['solids'][0]['mass_raw']!=loaded['state']['sketch_state']['solids'][0]['mass_raw']
    assert backend.calls.count('gtp')==backend.calls.count('save')==backend.calls.count('preCL')==backend.calls.count('postCL')==1
    assert report['CL_preservation']['protected_operation_native_ids']==[12]


@pytest.mark.parametrize('defect',['CAM_scalar','tool_scalar','bbox','excess_mass','mass_type','mass_shape'])
def test_configure_still_rejects_every_nonadmitted_delta_before_mutation(circular_engine,monkeypatch,defect):
    e=circular_engine;original=batch.run_current_saved_configuration
    def wrapped(*args,_context_factory,**kw):
        class Context(_context_factory):
            def capture(self,label,consumers):
                value=super().capture(label,consumers)
                if label=='confirm_before':
                    if defect=='CAM_scalar':value['operation_parameters'][0]['rough']['entry']['GetSpiralRadius']['raw']+=1.e-9
                    elif defect=='tool_scalar':value['parameter_batch']['candidate_tool']['generic']['cut_diameter_native']+=1.e-9
                    elif defect=='bbox':value['sketch_state']['solids'][0]['box_m'][0]+=1.e-15
                    elif defect=='excess_mass':value['sketch_state']['solids'][0]['mass_raw'][0]*=1.001
                    elif defect=='mass_type':value['sketch_state']['solids'][0]['mass_raw'][0]=True
                    else:value['sketch_state']['solids'][0]['mass_raw'].pop()
                    self.persist()
                return value
        return original(*args,_context_factory=Context,**kw)
    monkeypatch.setattr(batch,'run_current_saved_configuration',wrapped);result=e['run']('prepare')
    assert not result['readback_verified'] and not result['mutation_attempted'] and e['calls']==[]


def test_default_global_and_native_cl_compare_remain_strict(completed):
    state=completed['receipt']['saved'];changed=jitter(state,1)
    assert not fields.equal(state,changed) and not plain_delta.equal(state,changed)
    assert authority.circular_state_equal(state,changed)
    assert '_captured_state_equal' not in NativeGenerationContext.__dict__
    assert CircularGenerationContext._captured_state_equal(state,changed)
    source=inspect.getsource(NativeGenerationContext.export_cl)
    assert "getattr(self,'_captured_state_equal',delta.equal)" in source and source.count('same(')==2
    assert fields.equal(state,completed['receipt']['saved'])
