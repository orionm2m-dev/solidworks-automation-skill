from pathlib import Path
from copy import deepcopy
import importlib.util,json,sys,hashlib,os
from types import SimpleNamespace
import pytest

R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', str(Path(__file__).resolve().parents[1])))
sys.path.insert(0,str(R))
S=Path(__file__).resolve().parents[1]
D=Path(os.environ['SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT']) if os.environ.get('SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT') else S.parent
spec=importlib.util.spec_from_file_location('deep_preflight_under_test',S/'scripts/sw_cam_deep_guide_preflight.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def context():
    if not (D/'guide_finish_cnc_none_fix_20261102/ACTUAL_CORRECTED_SAVED_NATIVE.json').is_file():
        pytest.skip('Set SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT to run saved-route integration checks')
    r=json.loads((D/'guide_finish_cnc_none_fix_20261102/ACTUAL_CORRECTED_SAVED_NATIVE.json').read_text(encoding='utf-8'))
    cp=r['saved_checkpoint_context']
    loaded={'generated':r,'guide_parameters':{'document':deepcopy(cp['document']),'configuration':deepcopy(cp['configuration']),
      'baseline':deepcopy(r['saved']['binding']),'expected_parameters':deepcopy(r['saved'])},'pins':[],'checkpoint_pins':[]}
    geo=json.loads((D/'guide_pockets_resume_20261101/EXACT_GUIDE_GEOMETRY.json').read_text(encoding='utf-8'))
    hist=json.loads(Path(geo['source_pins'][1]['path']).read_text(encoding='utf-8'))
    headers,shapes=m.geometry_contract(geo,hist)
    return loaded,geo,hist,headers,shapes

def test_real_saved_recipe_keeps_actual_tool_and_feed(context):
    loaded,_,_,_,shapes=context;p=m.recipe_preflight(loaded,shapes)
    assert len(p['rows'])==4 and p['protected_operation_order']==list(m.ORDER)
    assert p['protected_generated_ids']==list(m.GENERATED)
    assert p['ready_for_native_mutation'] is False and p['geometry_accepted'] is False
    for r in p['rows']:
        assert r['target_levels']['depth_mm']==4.4 and r['target_levels']['floor_world_mm']==6.5
        assert r['target_levels']['nominal_layer_count']==15 and r['tool_native_id']==273
        assert r['new_operation_native_id'] is None
        assert r['reference_nc']['GetCNCComp']==0 and r['reference_nc']['GetTlpComp']==1
        actual=next(x for x in loaded['generated']['saved']['parameters']if x['operation_native_id']==r['reference_operation_native_id'])
        assert r['reference_nc']==actual['nc']['feeds_compensation']
        assert r['reference_tool_dimensions']==actual['tool']
        assert not r['inherited_spindle_and_feed_are_process_qualified']

@pytest.mark.parametrize('damage',['order','generated','count','extra_empty','already','dirty','binding','saved'])
def test_bad_baseline_rejected(context,damage):
    l,*_=context;b=l['guide_parameters']['baseline'];row=b['operations'][-1]
    if damage=='order':b['operations'].reverse()
    elif damage=='generated':row['toolpath_generated']=False
    elif damage=='count':row['toolpath_record_counts']=[0]
    elif damage=='extra_empty':b['operations'][0]['toolpath_record_counts']=[1]
    elif damage=='already':row['linked_feature_ids']=[80]
    elif damage=='dirty':l['guide_parameters']['document']['needs_save']=True
    elif damage=='binding':l['guide_parameters']['expected_parameters']['binding']['operations'][-1]['suppressed']=True
    elif damage=='saved':l['generated']['saved']['parameters'][0]['read_complete']=False
    with pytest.raises(ValueError):m.baseline_contract(l)

@pytest.mark.parametrize('damage',['proof','source','owner','depth','floor','width','radius','association','duplicate'])
def test_bad_geometry_rejected(context,damage):
    _,g,h,_,_=context;r=g['features'][0]
    if damage=='proof':g['width_and_end_radius_verified']=False
    elif damage=='source':g['source_part_sha256']='0'*64
    elif damage=='owner':next(x for x in h['loaded_context_before']['state']['features']if x['geometry']['native_id']==80)['setup_native_id']=70
    elif damage=='depth':r['native_depth_mm']=1.
    elif damage=='floor':r['floor_z_mm']=7.
    elif damage=='width':r['dimensions']['width_mm']=2.3
    elif damage=='radius':r['dimensions']['end_radius_mm']=1.1
    elif damage=='association':r['header_start_to_exact_floor_vertex_error_mm']=.01
    elif damage=='duplicate':g['features'].append(deepcopy(r))
    with pytest.raises(ValueError):m.geometry_contract(g,h)

@pytest.mark.parametrize('damage',['cnc','tlp','feed','spindle','dimension','tool','reference','percent','step','bottom','allowance'])
def test_bad_recipe_rejected(context,damage):
    l,_,_,_,shapes=context;a=l['guide_parameters']['expected_parameters']['parameters'][-1];r=l['generated']['recipe'][-1]
    if damage=='cnc':a['nc']['feeds_compensation']['GetCNCComp']=1
    elif damage=='tlp':a['nc']['feeds_compensation']['GetTlpComp']=0
    elif damage=='feed':a['nc']['feeds_compensation']['XYFeed']=float('nan')
    elif damage=='spindle':a['nc']['feeds_compensation']['GetSpndlSpeed']=False
    elif damage=='dimension':a['tool']['dimension_read_complete']=False
    elif damage=='tool':a['tool']['generic']['native_id']=145
    elif damage=='reference':r['operation_type']=0
    elif damage=='percent':r['fields']['first_depth']=[.3,True]
    elif damage=='step':r['fields']['max_depth']=[.4,False]
    elif damage=='bottom':r['fields']['bottom_finish']=True
    elif damage=='allowance':r['fields']['previous_allowance']=.01
    # Keep duplicate saved authority internally consistent, so field tests reach their local guard.
    l['generated']['saved']=deepcopy(l['guide_parameters']['expected_parameters'])
    with pytest.raises(ValueError):m.recipe_preflight(l,shapes)

def observation(context):
    l,_,_,headers,shapes=context;p=m.recipe_preflight(l,shapes)
    choices={r['key']:{'name':f'actual-kind-{r["operation_type"]}','default_operation_id':100+r['operation_type']}for r in p['rows']}
    guides=[{'feature_native_id':fid,'defaults_catalogue':[{'operation_type':k,'entries':[{'name':f'actual-kind-{k}','default_operation_id':100+k}]}for k in (0,1)]}for fid in (80,81)]
    o=dict(scope=m.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,mutation_attempted=False,
      model_saved=False,GTP_attempted=False,setter_attempted=False,before=deepcopy(l['guide_parameters']['expected_parameters']),
      after_binding=deepcopy(l['guide_parameters']['baseline']),deep_headers_before=deepcopy(headers),deep_headers_after=deepcopy(headers),guides=guides,preflight=p)
    return o,choices

def test_catalogue_choices_are_exact_and_not_authority_to_mutate(context):
    o,c=observation(context);p=m.compile_definition_plan(o,c)
    assert p['definition_choices_observed'] is True and p['ready_for_native_mutation'] is False
    assert all(r['feature_owner_setup_native_id']==69 and r['operation_setup_native_id']==93 for r in p['rows'])

@pytest.mark.parametrize('damage',['missing','invented_id','wrong_kind','duplicate','pending','issue','mutation','route','header'])
def test_unproven_catalogue_plan_rejected(context,damage):
    o,c=observation(context)
    if damage=='missing':c.pop('guide80_rough')
    elif damage=='invented_id':c['guide80_rough']['default_operation_id']=999
    elif damage=='wrong_kind':c['guide80_rough']=deepcopy(c['guide80_finish'])
    elif damage=='duplicate':o['guides'][0]['defaults_catalogue'][0]['entries']*=2
    elif damage=='pending':o['status']='prepared'
    elif damage=='issue':o['issue']='failed'
    elif damage=='mutation':o['setter_attempted']=True
    elif damage=='route':o['after_binding']['operations'][-1]['toolpath_record_counts']=[116]
    elif damage=='header':o['deep_headers_after']['80']['depth_native']=1
    with pytest.raises(ValueError):m.compile_definition_plan(o,c)

class Backend:
    def __init__(self,l,headers,fail=None):
        self.l,self.headers,self.fail=l,headers,fail;self.calls=[]
        self.ctx=SimpleNamespace(identity=lambda:deepcopy(l['guide_parameters']['document']))
    def start(self):self.calls.append('start')
    def capture_parameters(self,label):
        self.calls.append('full:'+label)
        if self.fail=='full':raise ValueError('failed full')
        r=deepcopy(self.l['guide_parameters']['expected_parameters'])
        if self.fail=='baseline':r['parameters'][0]['read_complete']=False
        return r
    def inspect_guides(self,headers):
        self.calls.append('catalogues')
        if self.fail=='catalogues':raise ValueError('failed catalogue')
        return deepcopy(headers),[],deepcopy(headers)
    def capture_binding(self,label):
        self.calls.append('binding:'+label);r=deepcopy(self.l['guide_parameters']['baseline'])
        if self.fail=='route':r['operations'][-1]['toolpath_record_counts']=[116]
        return r
    def finish(self):
        self.calls.append('finish')
        if self.fail=='finish':raise ValueError('event failure')
    def close(self):self.calls.append('close')

@pytest.mark.parametrize('failure',[None,'full','baseline','catalogues','route','finish','source','pin'])
def test_read_flow_one_full_snapshot_stop_on_error_and_cleanup(context,monkeypatch,failure):
    l,_,_,headers,_=context;b=Backend(l,headers,failure);p={'expected_document_path':'source','expected_source_sha256':'a'*64};r={'phase':'prepared'}
    monkeypatch.setattr(m,'_file_hash',lambda p:'b'*64 if failure=='source' else'a'*64)
    def check(p):
        if failure=='pin':raise ValueError('pin changed')
    monkeypatch.setattr(m.common,'_check',check)
    out=m.run_backend(b,p,{'loaded':l,'headers':headers},r,lambda:None)
    assert b.calls.count('full:deep_baseline')==1 and b.calls[-1]=='close'
    assert out['readback_verified'] is (failure is None)
    assert out['status']==('observed'if failure is None else'error')
    if failure in ('full','baseline'):assert 'catalogues' not in b.calls
    if failure=='catalogues':assert 'binding:deep_inspect_after'not in b.calls
    assert not any(x.startswith(('save','gtp','set','insert'))for x in b.calls)

def test_new_backend_has_no_mutation_methods():
    assert set(m.NativeBackend.__dict__)-{'__module__','__doc__'}=={'inspect_guides'}
