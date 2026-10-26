"""Bounded saved knowledge-index queries. Pure files/JSON: no CAD, locks or execution."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

MAX_INDEX_BYTES=5*1024*1024
MAX_TOPICS=500
MAX_SOURCES=2000
MAX_VERIFY_SOURCES=20
MAX_SOURCE_BYTES=256*1024*1024
MAX_VERIFIED_BYTES=512*1024*1024


class KnowledgeError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _text(value,label,maximum=4096,empty=False):
    if (type(value) is not str or len(value)>maximum or '\x00' in value or
            (not empty and not value.strip())):
        raise KnowledgeError('invalid_index',label+' must be a bounded string')
    return value


def _path(value):
    _text(value,'absolute path',4096)
    path=Path(value)
    if not path.is_absolute():raise KnowledgeError('invalid_path','Exact absolute file path required')
    return path


def _read_file(path,limit,keep=False):
    if path.is_symlink():raise KnowledgeError('symlink_rejected','Named source must not be a symlink')
    before=path.stat()
    if not path.is_file():raise KnowledgeError('not_regular_file','Named source must be a regular file')
    if before.st_size>limit:raise KnowledgeError('file_bound_exceeded','File exceeds explicit byte bound')
    digest=hashlib.sha256();chunks=[];size=0
    with path.open('rb') as stream:
        while True:
            chunk=stream.read(min(1024*1024,limit-size+1))
            if not chunk:break
            size+=len(chunk)
            if size>limit:raise KnowledgeError('file_bound_exceeded','File grew beyond explicit byte bound')
            digest.update(chunk)
            if keep:chunks.append(chunk)
    after=path.stat()
    signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
    if signature(before)!=signature(after) or size!=after.st_size:
        raise KnowledgeError('file_changed','File changed while being read')
    return dict(sha256=digest.hexdigest(),bytes=size,signature=signature(after),data=b''.join(chunks) if keep else None)


def _json(data):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise KnowledgeError('duplicate_json_key','Duplicate JSON object key')
            result[key]=value
        return result
    def invalid(_):raise KnowledgeError('invalid_json','Nonfinite JSON is not supported')
    return json.loads(data.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=invalid)


def _strings(value,label,maximum=100,empty=False):
    if type(value) is not list or len(value)>maximum:
        raise KnowledgeError('invalid_index',label+' must be a bounded array')
    for item in value:_text(item,label,empty=empty)
    return value


def _validate(index):
    if type(index) is not dict or set(index)!={'schema_version','kind','metadata','sources','topics'}:
        raise KnowledgeError('invalid_index','Exact schema_version/kind/metadata/sources/topics fields required')
    if type(index['schema_version']) is not int or index['schema_version']!=1 or index['kind']!='solidworks_fork_knowledge_index':
        raise KnowledgeError('unsupported_index','Only solidworks_fork_knowledge_index schema_version1 is supported')
    if type(index['metadata']) is not dict:
        raise KnowledgeError('invalid_index','metadata must be an object')
    sources={};topics={}
    for key,limit,dest in [('sources',MAX_SOURCES,sources),('topics',MAX_TOPICS,topics)]:
        rows=index[key]
        if type(rows) is not list or len(rows)>limit:
            raise KnowledgeError('index_bound_exceeded',key+' exceeds explicit item bound')
        for item in rows:
            if type(item) is not dict:raise KnowledgeError('invalid_index','Rows must be objects')
            ident=_text(item.get('id'),key+' ID',200)
            if ident in dest:raise KnowledgeError('duplicate_id','Duplicate ID in '+key)
            dest[ident]=item
            if key=='sources':
                if set(item)!={'id','path','sha256','role'}:raise KnowledgeError('invalid_index','Unexpected source fields')
                _path(item['path']);_text(item['role'],'source role')
                if type(item['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',item['sha256']) is None:
                    raise KnowledgeError('invalid_index','Exact lower-case SHA256 required')
            else:
                if set(item)!={'id','type','title','summary','keywords','tool_names','verification','how_to','source_ids','related_ids'}:
                    raise KnowledgeError('invalid_index','Unexpected topic fields')
                for field in ('type','title','summary'):_text(item[field],field)
                for field in ('keywords','tool_names','source_ids','related_ids'):_strings(item[field],field,500 if field=='related_ids' else 100,empty=field=='keywords')
                if type(item['how_to']) is not dict:raise KnowledgeError('invalid_index','how_to must be an object')
                v=item['verification']
                if type(v) is not dict or set(v)!={'level','scope','limitations'}:
                    raise KnowledgeError('invalid_index','Exact verification level/scope/limitations required')
                _text(v['level'],'verification level');_text(v['scope'],'verification scope');_strings(v['limitations'],'limitations')
    for item in topics.values():
        if any(i not in sources for i in item['source_ids']) or any(i not in topics for i in item['related_ids']):
            raise KnowledgeError('unknown_reference','Topic references an unknown source or related topic')
    return sources,topics


def _score(topic,query):
    q=query.casefold();terms=q.split()
    fields=[topic['id'],topic['type'],topic['title'],topic['summary'],*topic['keywords'],*topic['tool_names']]
    text=' '.join(fields).casefold()
    if not all(term in text for term in terms):return None
    exact={topic['id'].casefold(),*(v.casefold() for v in topic['tool_names'])}
    title=topic['title'].casefold();keywords=' '.join(topic['keywords']).casefold()
    return (1000 if q in exact else 0)+(100 if q in title else 0)+sum(10*(t in title)+5*(t in keywords)+1 for t in terms)


def _hit(topic,sources,detail):
    if detail:result=deepcopy(topic)
    else:
        result={k:deepcopy(topic[k]) for k in ('id','type','title','summary','tool_names','verification','source_ids','related_ids')}
        result['title']=result['title'][:240]
        result['summary']=result['summary'][:600]
        result['text_truncated']=len(topic['title'])>240 or len(topic['summary'])>600
    result['source_refs']=[deepcopy(sources[i]) for i in dict.fromkeys(topic['source_ids'])]
    return result


def _verify(sources,selected,requested):
    result=dict(requested=requested,status='not_requested',checked=0,total_selected=len(selected),
        complete=False,all_selected_sources_match=None,results=[],issues=[],not_checked_ids=[])
    if not requested:return result
    if not selected:result['status']='no_selected_sources';return result
    total=0
    for index,ident in enumerate(selected):
        if index>=MAX_VERIFY_SOURCES:
            result['not_checked_ids']=selected[index:]
            result['issues'].append(dict(code='verification_limit_exceeded',limit=MAX_VERIFY_SOURCES))
            break
        source=sources[ident];row=dict(id=ident,path=source['path'],expected_sha256=source['sha256'],matches=False)
        result['checked']+=1
        try:
            remaining=MAX_VERIFIED_BYTES-total
            if remaining<=0:raise KnowledgeError('total_bound_exceeded','Total source verification bound exceeded')
            actual=_read_file(_path(source['path']),min(MAX_SOURCE_BYTES,remaining))
            total+=actual['bytes'];row.update(actual_sha256=actual['sha256'],bytes=actual['bytes'],matches=actual['sha256']==source['sha256'])
            if not row['matches']:row['issue']=dict(code='source_hash_mismatch')
        except (OSError,KnowledgeError) as exc:
            row['issue']=dict(code=getattr(exc,'code','source_read_error'),message=str(exc))
        if 'issue' in row:result['issues'].append(dict(source_id=ident,**row['issue']))
        result['results'].append(row)
    result['complete']=not result['not_checked_ids']
    result['all_selected_sources_match']=result['complete'] and not result['issues']
    result['status']='pass' if result['all_selected_sources_match'] else ('incomplete' if not result['complete'] else 'mismatch')
    result['bytes_hashed']=total
    return result


def query_knowledge_index(*,index_path,action,query=None,topic_id=None,limit=5,detail=False,verify_sources=False):
    report=dict(status='error',action=action,verification_level_upgraded=False,live_state_verified=False,
        native_mutation_authorized=False,CAD_called=False)
    try:
        path=_path(index_path)
        if path.suffix.casefold()!='.json':raise KnowledgeError('invalid_path','Knowledge index must be a JSON file')
        if action not in ('summary','search','get'):raise KnowledgeError('invalid_action','Use summary/search/get')
        if type(limit) is not int or not 1<=limit<=20 or type(detail) is not bool or type(verify_sources) is not bool:
            raise KnowledgeError('invalid_input','Strict limit1..20 and boolean detail/verify_sources required')
        if action=='search':
            _text(query,'query',2000)
            if topic_id is not None:raise KnowledgeError('invalid_input','Search rejects topic_id')
        elif action=='get':
            _text(topic_id,'topic_id',200)
            if query is not None:raise KnowledgeError('invalid_input','Get rejects query')
        elif query is not None or topic_id is not None:raise KnowledgeError('invalid_input','Summary rejects selectors')
        first=_read_file(path,MAX_INDEX_BYTES,keep=True)
        index=_json(first['data']);sources,topics=_validate(index)
        report.update(index=dict(path=str(path),sha256=first['sha256'],schema_version=1,kind=index['kind']),
            counts=dict(topics=len(topics),sources=len(sources)))
        if action=='summary':
            report.update(metadata=deepcopy(index['metadata']),topic_types=dict(Counter(t['type'] for t in topics.values())),
                declared_verification_levels=dict(Counter(t['verification']['level'] for t in topics.values())))
            chosen=[]
        elif action=='get':
            if topic_id not in topics:raise KnowledgeError('topic_not_found','Exact topic ID was not found')
            chosen=[topics[topic_id]];report['matched_count']=1
        else:
            scored=[(score,t) for t in topics.values() if (score:=_score(t,query)) is not None]
            scored.sort(key=lambda item:(-item[0],item[1]['id']))
            chosen=[t for _,t in scored[:limit]];report['matched_count']=len(scored)
        if action!='summary':
            report.update(hits=[_hit(t,sources,detail) for t in chosen],returned_count=len(chosen))
        selected=list(dict.fromkeys(i for t in chosen for i in t['source_ids']))
        report['source_verification']=_verify(sources,selected,verify_sources)
        last=_read_file(path,MAX_INDEX_BYTES)
        if first['sha256']!=last['sha256'] or first['signature']!=last['signature']:
            raise KnowledgeError('index_changed','Knowledge index changed during query')
        report.update(status='ok',index_unchanged=True)
    except (OSError,ValueError,TypeError,RecursionError) as exc:
        report.update(status='error',issue=dict(code=getattr(exc,'code','invalid_json_or_index'),message=str(exc)),index_unchanged=False)
        report.pop('hits',None)
    return report
