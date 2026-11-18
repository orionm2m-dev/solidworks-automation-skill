"""Portable v2 GTP wiring tests; synthetic backend, no application."""
from pathlib import Path
from copy import deepcopy
import os,sys,hashlib
import pytest
ROOT=Path(__file__).resolve().parents[1]
RT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RT));sys.path.insert(0,str(RT/'tests'))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_generate_v2 as core
from test_current_pocket_generate import flow as original_flow,request


@pytest.fixture
def flow(original_flow,monkeypatch):
    from scripts import sw_cam_current_pocket_generate as legacy
    b,j,d,r=original_flow;d['save_bundle']=d['bundle'];r['scope']=core.SCOPE
    monkeypatch.setattr(core.current,'save_current_baseline',legacy.current.save_current_baseline)
    j=core.Journal(d['receipt'],d['marker'],r)
    return b,j,d,r


def test_v2_native_sequence_remains_single_gtp_save_cl(flow):
    b,j,d,r=flow;out=core.run_backend(b,j,d)
    assert out['status']=='review_required',out
    assert b.calls.count('GTP')==b.calls.count('Save')==b.calls.count('CL')==1
    assert len(out['field_readbacks'])==7 and all(x['readback_verified']for x in out['field_readbacks'])
    assert all(out[k]for k in core.FLAGS) and j.marker.exists()


@pytest.mark.parametrize('failure',['setter','gtp_exception','gtp_bool','post_gtp_delta','post_save','CL','cleanup','runtime'])
def test_v2_uncertain_outcome_never_replays(flow,failure):
    b,j,d,r=flow;b.fail=failure;out=core.run_backend(b,j,d)
    assert out['status']=='uncertain' and not any(out[k]for k in core.FLAGS)
    assert all(b.calls.count(n)<=1 for n in ('GTP','Save','CL'))
    with pytest.raises(ValueError):core.Journal(j.receipt,j.marker,out).create()


def test_native_primitives_are_existing_implementations():
    assert core.Backend.generate is core.generation.NativeGenerationContext.generate
    assert core.Backend.export_cl is core.generation.NativeGenerationContext.export_cl
    assert core.Backend.parse_cl is core.generation.NativeGenerationContext.parse_cl
    assert core.current.run_one_existing_save is core.current.legacy.run_one_existing_save


def test_v2_reuses_v1_target_source_once_key(tmp_path):
    v=request(tmp_path)
    expected=Path(v['expected_document_path']).parent/('current_pocket_first_gtp_'+core._digest(dict(scope='CURRENT_POCKET_SEVEN_FIELDS_FIRST_GTP_SAVE_CL_V1',target=core.reader.definition.creator.canonical(v['expected_document_path']),source_sha256=v['expected_source_sha256']))+'.json')
    assert core.marker_path(v)==expected and core.SCOPE!='CURRENT_POCKET_SEVEN_FIELDS_FIRST_GTP_SAVE_CL_V1'
    assert core.current.SCOPE!=core.current.legacy.SCOPE


def test_inherited_dispatch_and_pair_guards_cover_all_68_pins(tmp_path):
    pins=[]
    for i in range(68):
        p=tmp_path/(str(i)+'.bin');p.write_bytes(str(i).encode());pins.append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    v=request(tmp_path);v['expected_document_path']=pins[0]['path'];v['expected_source_sha256']=pins[0]['sha256']
    context=dict(pins=pins,expected_source_sha256=pins[0]['sha256'])
    b=core.Backend(object(),'clsid','tlb',v,{'bundle':{'context':context}},{},lambda:None,lambda:None,{'generated_pin':{}})
    b.expected_document=dict(path=pins[0]['path'],title='0.bin',type=1,needs_save=False)
    dispatch=b.guard()
    pair=core.reader.ReadGuard(b.sw,b.typelib_path,process_id=v['process_id'],expected_document=b.expected_document,source_sha256=b.source,evidence_pins=pins,verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None,generated_pin={},report={},evidence_pin_limit=core.PIN_LIMIT)
    assert dispatch.evidence_pin_limit==pair.evidence_pin_limit==128
    assert len(dispatch._rows)==len(pair._rows)==68
    expected={(str(Path(p['path']).resolve()).casefold(),p['sha256'])for p in pins}
    assert {(canonical,sha)for path,sha,canonical in dispatch._rows}==expected=={(canonical,sha)for path,sha,canonical in pair._rows}


def test_guard_budget_cannot_be_supplied_through_mcp_request(tmp_path):
    v=request(tmp_path);v['evidence_pin_limit']=128
    with pytest.raises(Exception):core.shape(v)



def test_consumed_v1_marker_blocks_v2_prepare_before_backend(tmp_path,monkeypatch):
    v=request(tmp_path);source=Path(v['expected_document_path']);source.write_bytes(b'synthetic part');v['expected_source_sha256']=core._file_hash(source)
    previous=tmp_path/'previous.json';previous.write_text('{}',encoding='utf-8');pin={'path':str(previous),'sha256':core._file_hash(previous)}
    recipe=Path(v['recipe_path']);recipe.write_text('{}',encoding='utf-8');v['recipe_sha256']=core._file_hash(recipe)
    state={'operations':[{'mill_operation_type':kind,'toolpath_generated':False,'toolpath_record_counts':[]}for kind in (0,1)],'generated_operation_count':0,'total_record_count':0}
    context={'expected_document_path':str(source),'pins':[pin,{'path':str(source),'sha256':v['expected_source_sha256']}]}
    bundle={'state':state,'parameters':[],'context':context,'root_pins':[pin],'receipt_pin':pin,'lineage_pins':[pin]}
    monkeypatch.setattr(core.current,'load_current_baseline',lambda value:bundle)
    monkeypatch.setattr(core.delta,'flatten',lambda snapshot:state)
    monkeypatch.setattr(core.reader.definition,'read_pin',lambda path,sha:({},dict(path=path,sha256=sha)))
    row={'operation_native_id':v['selected_operation_native_id'],'feature_native_id':v['expected_feature_native_id'],'existing_tool_native_id':None,'fields':[{'field':x}for x in core.FIELD_NAMES]}
    monkeypatch.setattr(core.fields,'compile_plan',lambda *a:{'rows':[row]})
    monkeypatch.setattr(core.fields,'parameter_row',lambda *a:{'rough':{'depth':{'DepthAllow':{'raw':0.}}}})
    monkeypatch.setattr(core.fields,'field_value',lambda *a:0.)
    monkeypatch.setattr(core,'_fresh_path',lambda path:Path(path))
    legacy=Path(v['expected_document_path']).parent/('current_pocket_first_gtp_'+core._digest(dict(scope=core.LEGACY_MARKER_SCOPE,target=core.reader.definition.creator.canonical(v['expected_document_path']),source_sha256=v['expected_source_sha256']))+'.json')
    legacy.write_text('{"scope":"CURRENT_POCKET_SEVEN_FIELDS_FIRST_GTP_SAVE_CL_V1","attempted":true}',encoding='utf-8')
    old=legacy.read_bytes()
    with pytest.raises(Exception,match='Fresh receipt and unused'):core.prepare(v)
    assert legacy.read_bytes()==old and not Path(v['receipt_path']).exists()
