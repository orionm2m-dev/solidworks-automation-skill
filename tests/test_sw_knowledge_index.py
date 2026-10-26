import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from scripts import sw_knowledge_index as know


def topic(ident='thread',**kw):
    return dict(id=ident,type='capability',title='TURN thread depth',summary='Полная глубина резьбы пока не подтверждена',
        keywords=['M60','резьба','depth'],tool_names=['solidworks_example'],
        verification=dict(level='research_only',scope='Installed API only',limitations=['Not production qualification']),
        how_to=dict(mcp_tool='solidworks_example',input_fields=[],guidance='Read evidence first'),source_ids=['s1'],related_ids=[])|kw


@pytest.fixture
def fixture(tmp_path):
    src=tmp_path/'receipt.json';src.write_text('{"saved":true}',encoding='utf-8')
    index=tmp_path/'knowledge.json'
    data=dict(schema_version=1,kind='solidworks_fork_knowledge_index',metadata=dict(title='Fork knowledge'),
        sources=[dict(id='s1',path=str(src),sha256=hashlib.sha256(src.read_bytes()).hexdigest(),role='saved evidence')],
        topics=[topic(),topic('milling',title='MILL geometry',summary='Координаты подтверждены, глубина нет',keywords=['MILL'],tool_names=['mill_inspect'])])
    def save():index.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    save()
    def run(action='summary',**kw):return know.query_knowledge_index(index_path=str(index),action=action,**kw)
    return dict(src=src,index=index,data=data,save=save,run=run)


def test_summary_is_compact_and_keeps_declared_levels(fixture):
    out=fixture['run']()
    assert out['status']=='ok' and out['counts']==dict(topics=2,sources=1)
    assert out['metadata']['title']=='Fork knowledge' and out['declared_verification_levels']==dict(research_only=2)
    assert 'hits' not in out and out['index']['sha256']==hashlib.sha256(fixture['index'].read_bytes()).hexdigest()
    assert out['source_verification']['status']=='not_requested' and not out['CAD_called']
    assert not out['verification_level_upgraded'] and not out['live_state_verified'] and not out['native_mutation_authorized']


def test_search_unicode_and_tool_name_ranking_are_literal_and_bounded(fixture):
    out=fixture['run']('search',query='РЕЗЬБЫ',limit=1)
    assert out['returned_count']==1 and out['hits'][0]['id']=='thread'
    exact=fixture['run']('search',query='mill_inspect')
    assert exact['hits'][0]['id']=='milling' and exact['hits'][0]['source_refs'][0]['sha256']==fixture['data']['sources'][0]['sha256']
    assert 'how_to' not in exact['hits'][0]


def test_get_detail_preserves_howto_and_verification_without_promotion(fixture):
    out=fixture['run']('get',topic_id='thread',detail=True,verify_sources=True)
    assert out['source_verification']['status']=='pass' and out['source_verification']['checked']==1
    assert out['hits'][0]['how_to']==fixture['data']['topics'][0]['how_to']
    assert out['hits'][0]['verification']['level']=='research_only' and not out['verification_level_upgraded']


def test_tampered_source_is_reported_but_topic_claim_is_never_rewritten(fixture):
    fixture['src'].write_text('tampered',encoding='utf-8')
    out=fixture['run']('get',topic_id='thread',verify_sources=True)
    assert out['status']=='ok' and out['source_verification']['status']=='mismatch'
    assert out['source_verification']['all_selected_sources_match'] is False
    assert out['source_verification']['issues'][0]['code']=='source_hash_mismatch'
    assert out['hits'][0]['verification']==fixture['data']['topics'][0]['verification']


def test_only_selected_sources_read_and_verification_is_opt_in(fixture,monkeypatch):
    absent=fixture['src'].parent/'missing.json'
    fixture['data']['sources'].append(dict(id='s2',path=str(absent),sha256='0'*64,role='unselected'))
    fixture['data']['topics'][1]['source_ids']=['s2'];fixture['save']()
    reads=[];original=know._read_file
    def read(path,*args,**kw):reads.append(path);return original(path,*args,**kw)
    monkeypatch.setattr(know,'_read_file',read)
    assert fixture['run']('get',topic_id='thread')['status']=='ok'
    assert reads==[fixture['index'],fixture['index']]
    reads.clear();out=fixture['run']('get',topic_id='thread',verify_sources=True)
    assert out['source_verification']['status']=='pass' and absent not in reads
    out=fixture['run']('get',topic_id='milling',verify_sources=True)
    assert out['source_verification']['status']=='mismatch' and out['source_verification']['issues'][0]['code']=='source_read_error'


def test_twenty_source_bound_is_explicit_and_not_a_pass(fixture):
    data=fixture['data'];data['sources']=[dict(data['sources'][0],id='s'+str(n)) for n in range(21)]
    data['topics'][0]['source_ids']=[s['id'] for s in data['sources']];fixture['save']()
    out=fixture['run']('get',topic_id='thread',verify_sources=True)
    verification=out['source_verification']
    assert verification['checked']==20 and verification['not_checked_ids']==['s20']
    assert verification['status']=='incomplete' and verification['all_selected_sources_match'] is False


@pytest.mark.parametrize('case',['duplicate_topic','duplicate_source','unknown_source','unknown_related','bool_version','kind','topics_bound','bad_sha'])
def test_malformed_index_is_rejected_before_results(fixture,case,monkeypatch):
    d=fixture['data']
    if case=='duplicate_topic':d['topics'].append(deepcopy(d['topics'][0]))
    if case=='duplicate_source':d['sources'].append(deepcopy(d['sources'][0]))
    if case=='unknown_source':d['topics'][0]['source_ids']=['absent']
    if case=='unknown_related':d['topics'][0]['related_ids']=['absent']
    if case=='bool_version':d['schema_version']=True
    if case=='kind':d['kind']='other'
    if case=='topics_bound':monkeypatch.setattr(know,'MAX_TOPICS',1)
    if case=='bad_sha':d['sources'][0]['sha256']='broken'
    fixture['save']();out=fixture['run']()
    assert out['status']=='error' and 'hits' not in out


def test_duplicate_JSON_keys_and_nonfinite_values_rejected(fixture):
    fixture['index'].write_text('{"schema_version":1,"schema_version":1}')
    assert fixture['run']()['issue']['code']=='duplicate_json_key'
    fixture['index'].write_text('{"x":NaN}')
    assert fixture['run']()['issue']['code']=='invalid_json'


def test_index_size_bound(fixture,monkeypatch):
    monkeypatch.setattr(know,'MAX_INDEX_BYTES',20)
    assert fixture['run']()['issue']['code']=='file_bound_exceeded'


def test_index_changed_during_source_verification_invalidates_hits(fixture,monkeypatch):
    original=know._read_file
    def read(path,*args,**kw):
        result=original(path,*args,**kw)
        if path==fixture['src']:
            fixture['data']['metadata']['changed']=True;fixture['save']()
        return result
    monkeypatch.setattr(know,'_read_file',read)
    out=fixture['run']('get',topic_id='thread',verify_sources=True)
    assert out['status']=='error' and out['issue']['code']=='index_changed' and 'hits' not in out


def test_compact_truncation_and_full_detail(fixture):
    fixture['data']['topics'][0]['summary']='X'*3000;fixture['save']()
    compact=fixture['run']('get',topic_id='thread')['hits'][0]
    detailed=fixture['run']('get',topic_id='thread',detail=True)['hits'][0]
    assert len(compact['summary'])==600 and compact['text_truncated'] and len(detailed['summary'])==3000


def test_payload_text_is_never_executed(fixture):
    marker=fixture['src'].parent/'executed.txt'
    payload="__import__('pathlib').Path("+repr(str(marker))+").write_text('bad')"
    fixture['data']['topics'][0]['how_to']['guidance']=payload
    fixture['data']['topics'][0]['keywords']=[payload];fixture['save']()
    out=fixture['run']('search',query=payload,detail=True)
    assert out['status']=='ok' and out['hits'][0]['how_to']['guidance']==payload and not marker.exists()
    tree=ast.parse(Path(know.__file__).read_text(encoding='utf-8'))
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
    assert not any('scripts' in str(x) or 'pythoncom' in str(x) or 'subprocess' in str(x) for x in imports)


@pytest.mark.parametrize('kwargs',[dict(action='get'),dict(action='get',topic_id='missing'),dict(action='search'),dict(action='search',query=' '),dict(action='summary',query='q'),dict(action='search',query='q',topic_id='id'),dict(action='summary',limit=True),dict(action='summary',limit=21),dict(action='summary',detail=1),dict(action='summary',verify_sources=1)])
def test_exact_action_and_strict_inputs(fixture,kwargs):
    assert fixture['run'](**kwargs)['status']=='error'


def test_empty_keyword_is_valid_string_array_and_cannot_match_every_query(fixture):
    fixture['data']['topics'][0]['keywords']=[''];fixture['save']()
    assert fixture['run']()['status']=='ok'
    assert fixture['run']('search',query='not_present_anywhere')['returned_count']==0
