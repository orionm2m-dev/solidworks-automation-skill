"""Real retained-owner plumbing; native scalar/profile bodies use explicit fakes."""
import os,sys,hashlib
from pathlib import Path
from copy import deepcopy
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pair_tool as core
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard

class Obj:
    def __init__(self,kind,ident=0):self.kind,self.ident=kind,ident

@pytest.fixture
def graph(tmp_path,monkeypatch):
    source=tmp_path/'part.sldprt';source.write_bytes(b'unchanged')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    doc=dict(path=str(source),title=source.name,type=1,needs_save=False)
    old,fresh,machine,crib,collection,tool,holder=[Obj(k,i)for k,i in [('old',1),('fresh',1),('machine',2),('crib',3),('collection',4),('tool',77),('holder',78)]]
    calls=[]
    def member(obj,name,*args):
        calls.append((obj,name))
        if name=='GetDocType':assert obj in (old,fresh);return 1
        if name=='MachType':assert obj is machine;return 1
        if name=='GetAllTools':assert obj is crib;return collection
        if name=='Count':assert obj is collection;return 1
        if name=='Item':assert obj is collection and args==(0,);return tool
        if name=='GetCWObjectID':assert obj in (old,fresh);return args[0].ident,True
        if name=='IGetMillToolHolder':assert obj is tool;return holder
        if name=='IsMillTool':assert obj is tool;return True
        if name in core.factory.TEXT_FIELDS:assert obj is tool;return name
        raise AssertionError(name)
    monkeypatch.setattr(core.prior,'_member',member)
    monkeypatch.setattr(core.prior,'_typed',lambda obj,name,tlb:obj)
    # Only external application's identity query is fake; retain/content/live
    # checks and the real ToolReadBatch lifecycle remain enabled.
    monkeypatch.setattr(ScopedCamDispatchGuard,'_identity',lambda self:None)
    b=object.__new__(core.Backend);b.sw=Obj('NoApplication');b.typelib_path='metadata-only';b.ctx=b
    b.args=dict(process_id=51,expected_source_sha256=digest);b.loaded=dict(pins=[dict(path=str(source),sha256=digest)])
    b.d=dict(expected_source_sha256=digest,pins=b.loaded['pins']);b.abi=dict(generated_pin={})
    b.native=dict(doc=old,machine=machine);b.doc=old;b.crib=crib;b.new_tool=None;b.new_id=None
    b.report={};b.old_holders={};b.expected_document=doc;b.clsid='fake'
    b.identity=lambda:deepcopy(doc);b.files=lambda:None;b.owned=lambda:None;b.events=lambda *a:None;b.persist=lambda:None
    rows=[dict(native_id=77,tool_type_raw=1,CutDiameter=20.,Protrusion=60.)]
    b.catalogue=lambda:deepcopy(rows)
    state=dict(operations=[])
    monkeypatch.setattr(core.reader.definition,'capture',lambda *a:(deepcopy(state),dict(doc=fresh,machine=machine)))
    class ParameterScope:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
    monkeypatch.setattr(core.reader,'ReadGuard',ParameterScope)
    monkeypatch.setattr(core.reader,'read_pair',lambda state,native,rows,batch,out,persist:out.update(parameters=[]))
    def profile(value,*,generic,read,typed,diagnostic):
        assert value is tool
        h=typed(read(value,'IGetMillToolHolder'),'ICWMillToolHolder')
        assert h is holder
        return {'verified_fake_profile':True}
    monkeypatch.setattr(core,'read_full_mill_tool',profile)
    return b,old,fresh,tool,calls

def test_capture_refreshes_alias_and_actual_tool_batches_use_fresh_owner(graph):
    b,old,fresh,tool,calls=graph
    b.capture_current('before');assert b.doc is b.native['doc'] is fresh
    assert b.initial_tools()[0]['native_id']==77
    assert b.full_existing(77,'before')['native_id']==77
    ids=[obj for obj,name in calls if name=='GetCWObjectID']
    assert len(ids)==2 and all(obj is fresh for obj in ids)
    assert b.handles[77]is tool and b.old_holders[77].kind=='holder'

@pytest.mark.parametrize('method',['initial_tools','full_existing'])
def test_same_actual_batch_rejects_stale_alias_before_identity_getter(graph,method):
    b,old,fresh,tool,calls=graph
    b.capture_current('before')
    if method=='full_existing':b.initial_tools()
    b.doc=old;calls.clear()
    with pytest.raises(ValueError,match='Native owner was not acquired'):
        b.initial_tools() if method=='initial_tools' else b.full_existing(77,'before')
    assert not any(obj is old and name=='GetCWObjectID'for obj,name in calls)

def test_later_capture_refreshes_alias_again_without_reacquiring_protected_tools(graph,monkeypatch):
    b,old,fresh,tool,calls=graph;b.capture_current('before');b.initial_tools()
    third=Obj('fresh',1)
    monkeypatch.setattr(core.reader.definition,'capture',lambda *a:(dict(operations=[]),dict(doc=third,machine=b.native['machine'])))
    b.capture_current('after');assert b.doc is b.native['doc'] is third
    assert b.handles[77]is tool and b.old_holders[77].kind=='holder'
