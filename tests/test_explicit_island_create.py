"""Endpoint closure tests with the real file journal; no application."""
import hashlib,os,sys
from pathlib import Path
import pytest
ROOT=Path(os.environ.get('SWMCP_RUNTIME_ROOT',str(Path.home()/'.codex/skills/solidworks-automation')))
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
component_stage=STAGE.parent/'cam_explicit_island_sketch_20261111'/'scripts'
if component_stage.exists():scripts.__path__.append(str(component_stage))
from scripts import sw_cam_explicit_island_create as api

def case(tmp_path,monkeypatch,failure=None):
    target=tmp_path/'copy.SLDPRT';target.write_bytes(b'saved native placeholder')
    sha=hashlib.sha256(target.read_bytes()).hexdigest()
    v=dict(expected_document_path=str(target),expected_source_sha256=sha,circle_receipt_path='circle',
           circle_save_receipt_path='save',feature_plan_path='plan')
    pins=[dict(path=m.__file__,sha256=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest())
          for m in (api.component,api.authority,api.chain_proof)]
    d=dict(request=v,receipt=tmp_path/'receipt.json',marker=tmp_path/'once.json',pins=pins,
        batch={'pin':{'path':'batch','sha256':'a'*64}},feature_plan={'island_sketch_names':['A','B','C','D']},
        outer_spec={},island_specs=[])
    monkeypatch.setattr(api.shared,'_consume',lambda *args:d)
    monkeypatch.setattr(api.component,'preflight',lambda _:dict(native_calls=0))
    class Context:
        def __init__(self,sw,clsid,tlb,v,data,r,persist,runtime):
            self.r=r;self.expected=dict(path=v['expected_document_path'],needs_save=False);self.closed=False
        def start(self):
            if failure=='start':raise ValueError('admission failed')
        def close(self):
            self.closed=True
            if failure=='cleanup':raise ValueError('cleanup failed')
            self.r['messages']=dict(subscribed=True,active=False,disconnected=True,event_count=0,events=[],
                overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
        def identity(self):
            if failure=='identity':raise ValueError('postcleanup identity failed')
            return self.expected
        def verify_files(self):
            if failure=='files':raise ValueError('protected pin changed')
    calls=[]
    def component(backend,plan,*,claim,persist,report,verify_chains):
        report.update(actions=[])
        for name in ['CreateMillFeature2']+['AddIslandToFeature:'+n for n in plan['island_sketch_names']]:
            row={'name':name,'pending':False,'attempted':False,'returned':False}
            report['actions'].append(row);claim(name);row.update(pending=True,attempted=True);persist();calls.append(name)
            if failure=='partial':raise ValueError('native failed')
            row.update(pending=False,returned=True);persist()
        report.update(before={'feature_count':0},after={'feature_count':1},
            header_readbacks=[{'scalars':{'native_id':20}}],new_feature_native_id=20,
            indexed_readback={'read_complete':True})
    monkeypatch.setattr(api.component,'create_one',component)
    def runtime():
        if failure=='runtime' and calls:raise ValueError('runtime changed')
    r=api.run(None,'clsid','typelib',v,runtime_check=runtime,prepared=object(),_context_factory=Context)
    return r,d,calls

def test_terminal_definition_only_real_once_marker(tmp_path,monkeypatch):
    r,d,calls=case(tmp_path,monkeypatch)
    assert r['status']=='definition_only' and all(r[k] for k in api.FLAGS)
    assert d['receipt'].exists() and d['marker'].exists() and len(calls)==5
    for key in ('Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted',
                'Import_attempted','explicit_rebuild_attempted','model_saved','production_qualified','machining_eligible'):
        assert r[key]is False

@pytest.mark.parametrize('failure',['start','partial','cleanup','identity','files','runtime'])
def test_any_partial_or_cleanup_failure_cannot_promote(tmp_path,monkeypatch,failure):
    r,d,calls=case(tmp_path,monkeypatch,failure)
    assert not any(r[k] for k in api.FLAGS)
    assert r['status']==('error'if failure=='start'else'uncertain')
    assert len(calls)==(0 if failure=='start'else 1 if failure=='partial'else 5)
    assert r['Save_attempted']is False and r['GTP_attempted']is False
    if failure=='partial':assert r['component']['actions'][-1]['pending']is True

def test_terminal_file_write_failure_revokes_flags(tmp_path,monkeypatch):
    original=api.Journal.persist
    def persist(self):
        if self.report['status']=='definition_only':raise OSError('terminal file write failed')
        return original(self)
    monkeypatch.setattr(api.Journal,'persist',persist)
    r,d,calls=case(tmp_path,monkeypatch)
    assert r['status']=='uncertain' and not any(r[k] for k in api.FLAGS)
    assert len(calls)==5 and all(x['returned']for x in r['component']['actions'])