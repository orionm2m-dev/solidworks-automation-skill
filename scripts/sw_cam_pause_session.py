"""Save one owned MILL document for pause, then close it and exit only if empty.

No parameter setters, generation, UI, process termination or automatic replay.
The saved file and bounded CAM state are verified; reopening remains unverified.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import os
import re
import shutil
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_lifecycle import _open_documents, _target

SCOPE='OWNED_MILL_PAUSE_SAVE_CLOSE_V1'
ACK='save_current_cam_then_close_only_owned_target'
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid',
    'typelib_path','receipt_path','backup_before_path','backup_after_path','module_sha256',
    'acknowledgement','expected_finish_fields','expected_operation_ids','expected_tool_count',
    'expected_feature_count','expected_generated_path_count'}
FIELDS={'out_independent':False,'first_depth':[.3,False],'max_depth':[.3,False],
    'side_step':[.25,False],'previous_allowance':.5,'override_previous':True,'bottom_finish':False}

def require(value,message):
    if not value:raise ValueError(message)

def exact(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(exact(a[k],b[k]) for k in a)
    if type(a) in (list,tuple):return len(a)==len(b) and all(exact(x,y) for x,y in zip(a,b))
    return a==b

def normalized(value):
    if type(value) in (list,tuple):return [normalized(x) for x in value]
    return value

def file_pin(path):return {'path':str(path),'sha256':_file_hash(path)}

def marker_path(p):
    return Path(p['receipt_path']).parent/('pause_once_'+_digest(dict(scope=SCOPE,
        process_id=p['process_id'],source=os.path.normcase(os.path.abspath(p['expected_document_path'])),
        source_sha256=p['expected_source_sha256']))+'.json')

def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='save_close_owned','Exact pause action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact pause request fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Exact owned PID required')
    require(p['acknowledgement']==ACK,'Reviewed pause request required')
    for k in ('expected_source_sha256','module_sha256'):
        require(type(p[k]) is str and re.fullmatch('[0-9a-f]{64}',p[k]),'Exact file hash required')
    require(p['module_sha256']==_file_hash(__file__),'Reviewed pause module changed')
    paths=[Path(p[k]) for k in ('expected_document_path','typelib_path','receipt_path','backup_before_path','backup_after_path')]
    require(all(x.is_absolute() and x.parent.is_dir() and not x.is_symlink() for x in paths),'Absolute non-link paths in existing directories required')
    require(paths[0].is_file() and paths[0].suffix.lower()=='.sldprt' and paths[1].is_file() and paths[1].suffix.lower()=='.tlb','Existing part and installed TLB required')
    require(_file_hash(paths[0])==p['expected_source_sha256'],'Saved source changed before pause')
    outputs=paths[2:]+[marker_path(p)]
    require(all(not x.exists() and not x.is_symlink() for x in outputs),'New receipt, backups and once marker required')
    require(len({os.path.normcase(os.path.abspath(x)) for x in paths+[marker_path(p)]})==len(paths)+1,'Output aliases protected input')
    require(exact(p['expected_finish_fields'],FIELDS),'Exact current partial finish fields required')
    require(p['expected_operation_ids']==[195,196,267,247,248,271,143,144]
        and p['expected_tool_count']==19 and p['expected_feature_count']==21
        and p['expected_generated_path_count']==5,'Exact paused MILL inventory required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact installed add-in CLSID required')
    return p

def verify_snapshot(s,p):
    require(s['machine_type']==1 and s['operation_ids']==p['expected_operation_ids'],'MILL operation order changed')
    require(len(s['feature_ids'])==p['expected_feature_count'] and len(set(s['feature_ids']))==len(s['feature_ids']),'Feature inventory changed')
    require(len(s['tool_ids'])==p['expected_tool_count'] and len(set(s['tool_ids']))==len(s['tool_ids']),'Tool inventory changed')
    require(sum(len(x['record_counts']) for x in s['operations'])==p['expected_generated_path_count'],'Generated stream count changed')
    require(exact(s['finish_fields'],p['expected_finish_fields']),'Partial finish settings changed')
    selected=next(x for x in s['operations'] if x['id']==144)
    require(selected['tool_id']==273 and selected['generated'] is False and selected['feature_ids']==[79],'Finish144 binding changed')

def verify_saved(before,after):
    expected=deepcopy(before);expected['document']['needs_save']=False
    expected['saved_file_sha256']=after['saved_file_sha256']
    require(exact(expected,after),'Native save changed protected CAM state or document identity')
    require(after['document']['needs_save'] is False,'Native save must leave clean document')

def backup_file(source,target,expected_sha):
    require(not Path(target).exists(),'Backup exists')
    require(_file_hash(source)==expected_sha,'Source changed before backup')
    with open(source,'rb') as src,open(target,'xb') as dst:
        shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
    require(_file_hash(source)==expected_sha==_file_hash(target),'Backup byte verification failed')
    return file_pin(target)

class Journal:
    def __init__(self,p):
        self.p=p;self.path=Path(p['receipt_path']);self.marker=marker_path(p)
        self.report=dict(schema_version=1,scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],
            source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],module_pin=file_pin(__file__),
            actions={},GTP_attempted=False,parameter_setter_attempted=False,save_verified=False,close_verified=False,
            exit_attempted=False,exit_returned=False,reopen_verified=False,automatic_replay=False)
        _write_receipt(self.path,self.report,create=True)
    def persist(self):_write_receipt(self.path,self.report)
    def claim(self,name):
        require(name not in self.report['actions'],'Native action must not repeat')
        if name=='SaveActiveDocument':
            _write_receipt(self.marker,dict(scope=SCOPE,process_id=self.p['process_id'],source_path=self.p['expected_document_path'],
                initial_source_sha256=self.p['expected_source_sha256'],receipt_path=str(self.path),save_attempted=True),create=True)
        else:require(self.marker.exists(),'Save attempt marker required')
        self.report['phase']=name;self.report['actions'][name]=dict(attempted=True,returned=False,pending=True)
        self.persist()
    def returned(self,name,value):
        self.report['actions'][name].update(returned=True,pending=False,return_type=type(value).__name__,return_value=value)
        self.persist()

class NativeBackend:
    def __init__(self,sw,p,journal):self.sw=sw;self.p=p;self.journal=journal;self.session=None;self.app=None;self.active=False
    def owned(self):require(_member(self.sw,'GetProcessID')==self.p['process_id'],'Owned process identity changed')
    def identity(self):
        self.owned();d=document_snapshot(self.sw);_target(d,self.p['expected_document_path']);return d
    def events(self,active=True):
        if self.session is None:return
        s=self.session.summary();self.journal.report['messages']=s
        require(s.get('subscribed') is True and s.get('active') is active
            and (active or s.get('disconnected') is True)
            and not any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),
            'CAM message or event transport requires stop')
    def read(self,obj,name,*args):
        self.events();value=_member(obj,name,*args);self.events();return value
    def typed(self,obj,name):
        self.events()
        if name=='ICWLeadInOut':
            from scripts.sw_cam_comtypes import _load_type_library
            cls=_load_type_library(self.p['typelib_path']).ICWLeadInOut
            require(str(cls._iid_).upper()=='{6DA10A61-7C7F-11D6-A9EF-00062999E55F}','Exact installed lead IID required')
            value=obj.QueryInterface(cls)
            require(value is not None and bool(value) and isinstance(value,cls),'Exact lead interface required')
        else:value=_typed(obj,name,self.p['typelib_path'])
        self.events();return value
    def start(self):
        from scripts.sw_cam_events import CamMessageSession
        self.identity();self.app=_bootstrap(self.sw,self.p['addin_clsid'],self.p['typelib_path'],self.p['expected_document_path'])
        self.session=CamMessageSession(self.app,self.p['typelib_path']);self.session.__enter__();self.active=True
        self.events();self.save_app=self.typed(self.app,'ICWApp')
    def boundary(self,document,sha):
        self.events();require(exact(self.identity(),document),'Active document changed')
        require(_file_hash(self.p['expected_document_path'])==sha,'Saved file changed');self.events()
    def capture(self,label):
        self.journal.report['phase']=label;self.journal.persist();self.events()
        before=self.identity();sha=_file_hash(self.p['expected_document_path'])
        raw=self.read(self.app,'IGetActiveDoc');doc=self.typed(raw,'ICWDoc3');part=self.typed(raw,'ICWPartDoc')
        require(self.read(doc,'GetDocType')==1,'CAM part required')
        machine=self.typed(self.read(part,'IGetMachine'),'ICWMachine')
        state=dict(document=before,saved_file_sha256=sha,machine_type=self.read(machine,'MachType'),feature_ids=[],feature_setup_ids=[],operations=[],operation_ids=[],operation_setup_ids=[],tool_ids=[])
        require(state['machine_type']==1,'MILL required before subtype reads')
        for rawsetup in _items(self.read(machine,'IGetEnumSetups'),self.typed,self.read,8):
            setup=self.typed(rawsetup,'ICWBaseSetup');state['feature_setup_ids'].append(_object_id(doc,setup,self.read))
            state['feature_ids'] += [_object_id(doc,x,self.read) for x in _items(self.read(setup,'IGetEnumFeatures'),self.typed,self.read,64)]
        raw144=None
        for rawsetup in _items(self.read(machine,'IGetEnumOpSetups'),self.typed,self.read,8):
            setup=self.typed(rawsetup,'ICWBaseOpSetup');sid=_object_id(doc,setup,self.read);state['operation_setup_ids'].append(sid)
            for rawop in _items(self.read(setup,'IGetEnumOperations'),self.typed,self.read,32):
                op=self.typed(rawop,'ICWOperation');oid=_object_id(doc,op,self.read)
                tool=self.typed(self.read(op,'IGetTool'),'ICWTool')
                row=dict(id=oid,setup_id=sid,generated=self.read(op,'GetIsToolpathGenerated'),suppressed=self.read(op,'Suppressed'),tool_id=_object_id(doc,tool,self.read),record_counts=[],feature_ids=[])
                require(type(row['generated']) is bool and type(row['suppressed']) is bool,'Strict native operation flags required')
                row['feature_ids']=[_object_id(doc,x,self.read) for x in _items(self.read(op,'IGetAllFeatures'),self.typed,self.read,64)]
                for rawpath in _items(self.read(op,'IGetEnumToolpaths'),self.typed,self.read,32):
                    count=self.read(self.typed(rawpath,'ICWToolpath'),'RecordCount');require(type(count) is int and 0<=count<=100000,'Bounded path count required');row['record_counts'].append(count)
                state['operations'].append(row);state['operation_ids'].append(oid)
                if oid==144:raw144=rawop
        crib=self.typed(self.read(machine,'IGetToolcrib'),'ICWToolcrib4')
        state['tool_ids']=[_object_id(doc,x,self.read) for x in _items(self.read(crib,'GetAllTools'),self.typed,self.read,128)]
        require(raw144 is not None,'Existing finish144 required')
        found=self.read(doc,'GetCWObjectFromID',1,79);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Feature79 required')
        feature=found[0];fin=self.typed(raw144,'ICWFinishMillOp');fin2=self.typed(raw144,'ICWFinishMillOp2');fin3=self.typed(raw144,'ICWFinishMillOp3')
        lead=self.typed(self.read(fin,'IGetLeadout',feature),'ICWLeadInOut')
        state['finish_fields']={
            'out_independent':self.read(lead,'GetIsSameLeadinout'),
            'first_depth':normalized(self.read(fin3,'GetFirstDepthCut')),
            'max_depth':normalized(self.read(fin3,'GetMaxDepthCut')),
            'side_step':normalized(self.read(fin3,'GetSideCutAmt')),
            'previous_allowance':self.read(fin2,'GetPreviousAllowance',feature),
            'override_previous':self.read(fin,'OverridePrevAllow'),
            'bottom_finish':self.read(fin,'BottomFinOpt')}
        self.boundary(before,sha);return state
    def save(self):return self.read(self.save_app,'SaveActiveDocument')
    def close_target(self,document,sha):
        self.boundary(document,sha);require(self.read(self.sw,'UserControl') is True,'Close requires UserControl=true')
        return self.read(self.save_app,'CloseActiveDocument')
    def documents_after(self):
        self.owned();return _open_documents(self.sw,self.p['expected_document_path'],check=lambda:self.events(self.active))
    def stop_events(self):
        if self.active:
            self.session.__exit__(None,None,None);self.active=False;self.events(False)
    def exit_owned(self):
        self.owned();require(self.documents_after()==[],'Other documents forbid application exit')
        return _member(self.sw,'ExitApp')

def run_steps(backend,journal,p):
    r=journal.report;backend.start()
    before=backend.capture('before_save');r['before']=before;journal.persist();verify_snapshot(before,p)
    require(before['saved_file_sha256']==p['expected_source_sha256'],'Initial source changed')
    r['backup_before']=backup_file(p['expected_document_path'],p['backup_before_path'],p['expected_source_sha256']);journal.persist()
    backend.boundary(before['document'],before['saved_file_sha256']);journal.claim('SaveActiveDocument')
    backend.boundary(before['document'],before['saved_file_sha256'])
    value=backend.save();journal.returned('SaveActiveDocument',value)
    require(type(value) is int and value==0,'Native CAM Save must return strict int0')
    after=backend.capture('after_save');r['after']=after;journal.persist();verify_snapshot(after,p);verify_saved(before,after)
    require(after['saved_file_sha256']!=before['saved_file_sha256'],
        'Current partial CAM changes require new saved bytes; unchanged R117 cannot close')
    r['saved_source_sha256']=after['saved_file_sha256'];r['save_verified']=True;journal.persist()
    r['backup_after']=backup_file(p['expected_document_path'],p['backup_after_path'],after['saved_file_sha256']);journal.persist()
    backend.boundary(after['document'],after['saved_file_sha256']);journal.claim('CloseActiveDocument')
    value=backend.close_target(after['document'],after['saved_file_sha256']);journal.returned('CloseActiveDocument',value)
    require(type(value) is int and value==0,'Native CAM Close must return strict int0')
    docs=backend.documents_after();r['open_documents_after']=docs;journal.persist()
    require(_file_hash(p['expected_document_path'])==r['saved_source_sha256'],'Source changed during close')
    r['close_verified']=True;journal.persist();backend.stop_events()
    finaldocs=backend.documents_after();require(exact(docs,finaldocs),'Open documents changed during cleanup')
    if finaldocs==[]:
        journal.claim('ExitApp');r['exit_attempted']=True;journal.persist()
        value=backend.exit_owned();journal.returned('ExitApp',value);r['exit_returned']=True
    else:r['exit_skipped_reason']='other_documents_remain_in_owned_process'
    r.update(status='paused_saved_closed',phase='finished');journal.persist()

def execute(sw,p):
    j=Journal(p);backend=NativeBackend(sw,p,j)
    try:run_steps(backend,j,p)
    except Exception as exc:
        j.report.update(status='uncertain' if j.report['actions'] else 'error',failed_phase=j.report['phase'],phase='finished',issue=_error(exc))
    finally:
        try:backend.stop_events()
        except Exception as exc:j.report.update(status='uncertain',cleanup_issue=_error(exc))
        j.persist()
    return j.report

def dispatch_request(request,*,validate_only=False):
    p=validate_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,marker=str(marker_path(p)))
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_operation_guard import solidworks_operation_lock
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,p)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','save_verified','close_verified','exit_returned','issue')},ensure_ascii=False))
    return 0 if r['status'] in ('validated_offline','paused_saved_closed') else 1

if __name__=='__main__':raise SystemExit(main())
