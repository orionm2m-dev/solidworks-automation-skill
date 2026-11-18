"""Full existing reader parity over fixed synthetic native values; no COM."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RT=Path(os.environ['SWMCP_RUNTIME_ROOT']);sys.path.insert(0,str(RT))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_pair_retained as m
from scripts import sw_cam_dispatch_guard as guard
from scripts import sw_cam_mill_packet_projection as packet

class Obj:
    def __init__(self,role,owner=0,interface='',rows=None):
        self.role,self.owner,self.interface,self.rows=role,owner,interface,rows

class Graph:
    def __init__(self,generated=False):
        fixture=json.loads((RT/'tests/fixtures/cam_mill_packet17_8_synthetic.json').read_text(encoding='utf-8'))
        self.raw=deepcopy(fixture['packet']['parameters'][:2])
        self.models=[packet.PacketReplay(r)for r in self.raw]
        self.ids=[r['operation_native_id']for r in self.raw];self.fid=self.raw[0]['feature_native_id'];self.sid=self.raw[0]['setup_native_id']
        self.doc=Obj('doc');self.machine=Obj('machine');self.feature=Obj('feature');self.setup=Obj('setup');self.ops=[Obj('operation',i)for i in range(2)]
        self.trace=[];self.error=None;self.on_read=None;self.generated=generated
        source=fixture['packet']['binding']['operations']
        self.rows=[deepcopy(next(x for x in source if x['native_id']==oid))for oid in self.ids]
        for i,r in enumerate(self.rows):r.update(setup_index=0,operation_index=i,toolpath_generated=bool(generated and i==0),toolpath_record_counts=[17]if generated and i==0 else [])
        self.state=dict(operations=self.rows,operation_setups=[dict(index=0,native_id=self.sid,operation_count=2)])
        self.native=dict(doc=self.doc,machine=self.machine,selected_feature=self.feature)
    def oid(self,obj):
        return {'operation':self.ids[obj.owner],'feature':self.fid,'setup':self.sid,'tool':self.raw[obj.owner]['tool_native_id']}.get(obj.role)
    def read(self,obj,name,*args):
        self.trace.append((obj.role,obj.owner,obj.interface,name))
        if self.error==name:raise RuntimeError('injected '+name)
        if self.on_read:self.on_read(obj,name)
        if name=='QueryInterface':return Obj(obj.role,obj.owner)
        if name=='GetDocType':return 1
        if name=='MachType':return 1
        if name=='GetCWObjectID':return self.oid(args[0]),True
        if name=='GetCWObjectFromID':return self.ops[self.ids.index(args[1])],True
        if name=='IGetMachine':return self.machine
        if name=='IGetEnumOpSetups':return Obj('collection',rows=[self.setup])
        if name=='IGetEnumOperations':return Obj('collection',rows=self.ops)
        if name=='Count':return len(obj.rows)
        if name=='Item':return obj.rows[args[0]]
        if name=='OpernType':return obj.owner
        if name=='Suppressed':return False
        if name=='GetIsToolpathGenerated':return bool(self.generated and obj.owner==0)
        if name=='IGetAllFeatures':return Obj('collection',rows=[self.feature])
        model=self.models[obj.owner];handle=model.handle(obj.role,obj.interface)
        converted=tuple(model.feature if isinstance(a,Obj)and a.role=='feature'else a for a in args)
        value=model.read(handle,name,*converted)
        def convert(x):
            if type(x)is packet._Handle:return Obj(x.role,obj.owner,x.interface)
            if type(x)is tuple:return tuple(convert(v)for v in x)
            return x
        return convert(value)
    def typed(self,batch,obj,name):
        return batch.observed(obj,'qi',name,lambda:Obj(obj.role,obj.owner,name,obj.rows))
    def plane(self,obj,name,diagnostic):
        self.trace.append((obj.role,obj.owner,obj.interface,name))
        return self.models[obj.owner].plane(self.models[obj.owner].handle(obj.role,obj.interface),name,diagnostic)

@pytest.fixture
def env(tmp_path,monkeypatch):
    g=Graph();source=tmp_path/'part.SLDPRT';source.write_bytes(b'saved source')
    evidence=tmp_path/'proof.json';evidence.write_bytes(b'evidence')
    pin=lambda p:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    document=dict(path=str(source),title=source.name,type=1,needs_save=False)
    state=dict(pid=123,doc=deepcopy(document),events=True,owned=True,binding=True)
    counts=dict(identity=0,events=0,owned=0,binding=0)
    sw=object()
    def identity(_):counts['identity']+=1;return deepcopy(state['doc'])
    def sysread(obj,name,*args):assert obj is sw and name=='GetProcessID';return state['pid']
    def events():counts['events']+=1;assert state['events'],'event'
    def owned():counts['owned']+=1;assert state['owned'],'lifetime'
    def binding():counts['binding']+=1;assert state['binding'],'binding'
    monkeypatch.setattr(guard,'_member',sysread);monkeypatch.setattr(guard,'raw_part_identity',identity)
    monkeypatch.setattr(m.reader,'_member',lambda *a:g.read(*a));monkeypatch.setattr(m,'_member',lambda *a:g.read(*a))
    monkeypatch.setattr(m.reader.guide.ParameterReadBatch,'typed',lambda batch,obj,name:g.typed(batch,obj,name))
    monkeypatch.setattr(m.reader.pocket.planes,'pointer_value',lambda *a:g.plane(*a))
    kwargs=dict(process_id=123,expected_document=document,source_sha256=pin(source)['sha256'],evidence_pins=[pin(evidence)],verify_evidence=lambda:None,verify_owned_process=owned,check_events=events,generated_pin=pin(evidence),report={})
    def make(retained=True):
        kw=deepcopy({k:v for k,v in kwargs.items()if k not in('verify_evidence','verify_owned_process','check_events')});kw.update({k:kwargs[k]for k in('verify_evidence','verify_owned_process','check_events')})
        if retained:return m.RetainedPairReadBatch(sw,'none.tlb',**kw,retained_objects=(g.doc,g.machine,g.feature),verify_retained_binding=binding,max_native_calls=m.reader.MAX_CALLS,evidence_pin_limit=128)
        return m.reader.ReadGuard(sw,'none.tlb',**kw,evidence_pin_limit=128)
    return dict(graph=g,make=make,state=state,counts=counts,source=source,evidence=evidence,document=document,kwargs=kwargs,sw=sw,pin=pin,events=events,owned=owned)


def execute(e,retained):
    g=e['graph'];out={};batch=e['make'](retained);g.trace.clear();g.models=[packet.PacketReplay(r)for r in g.raw]
    with batch:m.generation.read_pair(deepcopy(g.state),g.native,g.rows,batch,out,lambda:None,{g.ids[0]:[17]}if g.generated else {})
    if retained:batch.require_complete()
    return out,deepcopy(g.trace),batch.summary(),batch.calls

@pytest.mark.parametrize('generated',[False,True])
def test_full_existing_payload_and_every_parameter_read_exact_parity(env,generated):
    g=env['graph'];g.generated=generated
    g.rows[0].update(toolpath_generated=generated,toolpath_record_counts=[17]if generated else [])
    legacy,trace1,old,calls1=execute(env,False)
    fast,trace2,new,calls2=execute(env,True)
    assert legacy==fast and trace1==trace2 and calls1==calls2 and calls1>300
    assert new['metadata_checks']<old['metadata_checks']/10
    assert new['complete_boundary_checks']==old['complete_boundary_checks']+1
    assert new['read_scope_complete'] and not new['per_getter_active_document_checks']
    assert set(fast['parameters'][0])>={'levels','rough','tool','nc','read_complete'}
    assert set(fast['parameters'][1])>={'levels','finish','finish_fields','protected_finish','leads','tool','nc','read_complete'}
    assert not new['dispatch_available'] and not new['atomic_snapshot']

@pytest.mark.parametrize('fault',['events','pid','dirty','lifetime','binding','evidence'])
def test_changed_exit_rejects_completed_parameter_payload(env,fault):
    g=env['graph'];b=env['make']()
    with pytest.raises((ValueError,AssertionError)):
        with b:
            b.read(g.doc,'GetCWObjectID',g.feature)
            if fault=='events':env['state']['events']=False
            elif fault=='pid':env['state']['pid']=124
            elif fault=='dirty':env['state']['doc']['needs_save']=True
            elif fault=='lifetime':env['state']['owned']=False
            elif fault=='binding':env['state']['binding']=False
            else:env['evidence'].write_bytes(b'changed!')
    with pytest.raises(ValueError):b.require_complete()

@pytest.mark.parametrize('member',['SetTool','SaveActiveDocument','GenerateToolpath','IGetActiveDoc','ImportCAMData'])
def test_no_mutator_or_global_reacquisition_can_invoke(env,member):
    b=env['make']();g=env['graph']
    with pytest.raises(ValueError):
        with b:b.read(g.doc,member)
    assert not g.trace
    with pytest.raises(ValueError):b.require_complete()


def test_foreign_root_and_foreign_native_argument_reject(env):
    for obj,arg in [(Obj('doc'),env['graph'].feature),(env['graph'].doc,Obj('feature'))]:
        b=env['make']()
        with pytest.raises(ValueError):
            with b:b.read(obj,'GetCWObjectID',arg)
        with pytest.raises(ValueError):b.require_complete()


def test_getter_failure_stops_without_replay(env):
    g=env['graph'];g.error='GetSpiralRadius'
    with pytest.raises(RuntimeError,match='GetSpiralRadius'):execute(env,True)
    assert sum(x[-1]=='GetSpiralRadius'for x in g.trace)==1
    assert not any(x[-1]=='GetSpiralPitch'for x in g.trace)


def test_event_after_getter_stops_before_next_getter(env):
    g=env['graph'];g.on_read=lambda obj,n:env['state'].update(events=False)if n=='GetSpiralRadius'else None
    with pytest.raises(AssertionError,match='event'):execute(env,True)
    assert g.trace[-1][-1]=='GetSpiralRadius'


def test_read_scope_cannot_dispatch_or_be_reentered(env):
    b=env['make']();called=[]
    with pytest.raises(ValueError):
        with b:b.dispatch_once(lambda:called.append(1),persist_pending=lambda:called.append(2))
    assert not called
    with pytest.raises(ValueError):
        with b:pass


def snapshot(env):
    out,_,_,_=execute(env,False);state=deepcopy(env['graph'].state);state['document']=deepcopy(env['document']);return dict(inventory=state,parameters=out['parameters'])

@pytest.mark.parametrize('fault',['extra_generated','wrong_count','bool_id','second_kind','missing_row','second_setup','empty_count','bool_count','bool_kind'])
def test_selection_rejects_unsupported_pair_before_capture(env,fault):
    s=snapshot(env);obs={};rows=s['inventory']['operations']
    if fault=='extra_generated':obs={rows[1]['native_id']:[17]}
    elif fault=='wrong_count':obs={rows[0]['native_id']:[17]}
    elif fault=='bool_id':rows[0]['native_id']=True
    elif fault=='second_kind':rows[1]['mill_operation_type']=0
    elif fault=='missing_row':s['parameters'].pop()
    elif fault=='second_setup':rows[1]['setup_native_id']+=1
    elif fault=='empty_count':obs={rows[0]['native_id']:[]}
    elif fault=='bool_count':obs={rows[0]['native_id']:[True]}
    else:rows[1]['mill_operation_type']=True
    with pytest.raises(ValueError):m.selection(s,obs)


def test_complete_adapter_before_after_and_exact_payload(env,monkeypatch):
    s=snapshot(env);calls=[];context=dict(request={'process_id':123},expected_source_sha256=env['kwargs']['source_sha256'],pins=[env['pin'](Path(p))for p in (m.__file__,m.generation.__file__,m.definition_capture.__file__,m.retained.__file__)])
    def capture(*args):calls.append('capture');return deepcopy(s['inventory']),env['graph'].native
    monkeypatch.setattr(m.definition_capture,'capture',capture)
    monkeypatch.setattr(m.reader.definition,'verify_files',lambda c:None)
    monkeypatch.setattr(m.reader.definition,'identity',lambda *a:dict(document=deepcopy(env['state']['doc'])))
    diag={};out=m.capture_pair(env['sw'],'fixed','none.tlb',context,expected_snapshot=s,generation_observations={},check_events=env['events'],runtime_check=env['owned'],abi={'generated_pin':env['pin'](env['evidence'])},diagnostic=diag,persist=lambda:None)
    assert out==s and calls==['capture','capture']and diag['read_complete']
    assert diag['binding_native_calls']>0 and not diag['native_parity_qualified']
    assert set(diag['timing_seconds'])=={'before_definition','parameters','after_definition'}
    assert all(0<=v<=diag['elapsed_seconds']for v in diag['timing_seconds'].values())
    assert not any(diag[k]for k in ('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','automatic_retry'))
