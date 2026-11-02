from pathlib import Path
from types import SimpleNamespace as N
import sys,json
import pytest
from cam_public_test_support import add_runtime,required_module
S=add_runtime()
sys.path.insert(0,str(S/'scripts'))
m=required_module('review_reconciled_engagement_chunk')
if Path(m.authority.__file__).resolve() != (S/'scripts/saved_generation_engagement.py').resolve():
    raise RuntimeError('Chunk authority came from an unexpected runtime location')

@pytest.fixture
def batch(tmp_path,monkeypatch):
    source=tmp_path/'model';source.write_text('model')
    adapter=tmp_path/'actual_cl_engagement_adapter.py';adapter.write_text('adapter')
    kernel=tmp_path/'continuous_radial_engagement.py';kernel.write_text('kernel')
    parser=tmp_path/'sw_cam_generic_cl_reader_bounded.py';parser.write_text('parser')
    qualified=tmp_path/'authority.json';qualified.write_text('{}')
    pin=m.authority.pin
    v=dict(direct_dependency_pins=[pin(adapter),pin(kernel)],extended_parser_pin=pin(parser),saved_cl={'output':pin(source)},source_sha256='new',prefix_check={'protected14_full_streams_unchanged':True},frame={'z_offset_mm':26},profiles_by_block={14:{'tool_native_id':342}},learned_targets=[{'operation_native_id':344}]*4)
    parsed={'motions':[{'block':14,'mode':'feed','line':10},{'block':14,'mode':'rapid','line':11},{'block':14,'mode':'feed','line':12}]}
    seen=[]
    def query(current,motion,previous,events,**kwargs):
        seen.append((motion['line'],previous['line']if previous else None,kwargs))
        return {'status':'PROVED_NOMINAL_EXPORTED_COORDINATE_MODEL','prefix':{'sources':['earlier']}}
    a=N(__file__=str(adapter),k=N(__file__=str(kernel)),collect_events=lambda *a,**k:(['event'],[]),PrefixIndex=lambda e:'index',query_actual_motion=query)
    monkeypatch.setattr(m.authority,'load_qualified',lambda *a:v)
    monkeypatch.setattr(m.authority,'parse_qualified',lambda v:parsed)
    monkeypatch.setattr(m.importlib,'import_module',lambda n:a)
    args=N(qualified=qualified,qualified_sha256='sha',block=14,first=1,count=1,max_cells=2000,output=tmp_path/'chunk.json')
    return args,a,seen

def test_chunk_preserves_actual_immediate_previous_motion(batch):
    args,a,seen=batch;r,pin=m.run(args)
    assert seen[0][0:2]==(12,11)
    assert seen[0][2]['motion_index']==2 and seen[0][2]['prefix_index']=='index'
    assert r['complete_block_review']is False and r['whole_operation_model_bound_proved']is False
    assert r['rows'][0]['prefix']=={'credited_source_count':1}

def test_full_block_needs_every_actual_feed(batch):
    args,a,seen=batch;args.first=0;args.count=2;r,_=m.run(args)
    assert r['complete_block_review']is True and r['whole_operation_model_bound_proved']is True
    assert [(v[0],v[1])for v in seen]==[(10,None),(12,11)]

def test_unresolved_does_not_become_proved(batch):
    args,a,seen=batch;args.first=0;args.count=2;a.query_actual_motion=lambda *a,**k:{'status':'UNRESOLVED'}
    r,_=m.run(args);assert r['complete_block_review']is True and r['whole_operation_model_bound_proved']is False

@pytest.mark.parametrize('field,value',[('block',13),('block',True),('first',-1),('first',3),('count',257),('count',False),('max_cells',0),('max_cells',100001)])
def test_chunk_bounds(batch,field,value):
    args,a,seen=batch;setattr(args,field,value)
    with pytest.raises(ValueError):m.run(args)
    assert seen==[]
