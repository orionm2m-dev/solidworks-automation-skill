"""Offline same-session CL transport and complete-stream preservation checks."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(ROOT)))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_group_cl as m


def binding(n=6):
    generated=m.OLD+m.NEW[:max(0,n-6)]
    return {'operations':[dict(native_id=i,suppressed=False,toolpath_generated=i in generated,
        toolpath_record_counts=[4]if i in generated else [])for i in m.ORDER]}


def raw(n=6,*,changed=None):
    out='UNITS/MM\nBOX/-1,-1,-1,1,1,1\n'
    for i in range(n):
        x=i+20 if i==changed else i
        out+=f'CUTTER/2,0,1,0,0,0,55\nTLAXIS/0,0,1\nOPFEATSTART/Same label\nRAPID/\nGOTO/{x},0,3\nFEDRAT/MMPM,24\nGOTO/{x},0,0\nOPFEATEND/Same label\n'
    return (out+'FINI\n').encode('ascii')


def result(tmp_path,name,n,**kwargs):
    p=tmp_path/name;p.write_bytes(raw(n,**kwargs))
    return dict(status='export_verified',output_verified=True,readback_verified=True,parent_session_preserved=True,
        output=dict(path=str(p),bytes=p.stat().st_size,sha256=m._file_hash(p)),expected_generated_operations=m.contract(binding(n)))


def test_real_parser_full_six_stream_match_and_ten_after_save(tmp_path):
    a=result(tmp_path,'before.cl',6);b=result(tmp_path,'after.cl',10);c=result(tmp_path,'saved.cl',10)
    r=m.verify_protected(a,b);assert r['protected_complete_streams_verified']
    assert [v['native_id']for v in r['unchanged']]==m.OLD
    assert not r['new_block_native_id_mapping_verified']and not r['geometry_verified']
    assert m.verify_all(b,c)['all_ten_complete_streams_unchanged']


@pytest.mark.parametrize('kind',['old_motion','new_motion_after_save','bytes','order','count','units','box'])
def test_protected_stream_and_save_drift_rejected(tmp_path,kind):
    a=result(tmp_path,'before.cl',6);b=result(tmp_path,'after.cl',10);c=result(tmp_path,'saved.cl',10)
    if kind=='old_motion':b=result(tmp_path,'after.cl',10,changed=3)
    if kind=='new_motion_after_save':c=result(tmp_path,'saved.cl',10,changed=8)
    if kind=='bytes':Path(b['output']['path']).write_bytes(b'changed')
    if kind=='order':b['expected_generated_operations'][0:2]=reversed(b['expected_generated_operations'][0:2])
    if kind=='count':b['expected_generated_operations'][0]['toolpath_record_counts']=[3]
    if kind in ('units','box'):
        p=Path(b['output']['path']);p.write_bytes(p.read_bytes().replace(b'UNITS/MM',b'UNITS/INCH')if kind=='units'else p.read_bytes().replace(b'BOX/-1',b'BOX/-2'))
        b['output'].update(bytes=p.stat().st_size,sha256=m._file_hash(p))
    with pytest.raises(ValueError):
        if kind=='new_motion_after_save':m.verify_all(b,c)
        else:m.verify_protected(a,b)


class Backend:
    def __init__(self,tmp_path,diagnostic,*,fail=None):
        self.source=tmp_path/'part.SLDPRT';self.source.write_bytes(b'saved')
        self.doc=object();self.session=object();self.session_active=True;self.trace=[];self.fail=fail
        self.diagnostic=diagnostic;self.saved=[];self.route=binding()
        document=dict(path=str(self.source),title=self.source.name,type=1,needs_save=False)
        self.ctx=SimpleNamespace(args={'expected_source_sha256':m._file_hash(self.source)},identity=lambda:deepcopy(document),guard=self.guard)
    def events(self,*args):
        assert self.session_active;self.trace.append('events')
    def boundary(self):
        self.events();assert m._file_hash(self.source)==self.ctx.args['expected_source_sha256']
    def persist(self):self.saved.append(deepcopy(self.diagnostic))
    def capture_binding(self,label):self.boundary();self.trace.append(label);return deepcopy(self.route)
    @contextmanager
    def guard(self):
        self.boundary();backend=self
        class Machine:
            MachType=1
            def GetController2(self):return[False,'synthetic',True]
            def SaveCLFile(self,path):
                backend.trace.append('SaveCLFile')
                assert backend.saved[-1]['native_dispatch_pending']is True
                assert backend.saved[-1]['output_directory_created']is True
                assert backend.session_active
                if backend.fail=='exception':raise RuntimeError('native failure')
                Path(path).write_bytes(raw())
                if backend.fail=='binding':backend.route['operations'][0]['suppressed']=True
                return1=1 if backend.fail=='return'else 0
                return return1
        machine=Machine();part=SimpleNamespace(IGetMachine=lambda:machine)
        class Guard:
            def typed(self,obj,name):
                backend.trace.append(('typed',name))
                return part if name=='ICWPartDoc'else obj
            def read(self,obj,name,*args):return m._member(obj,name,*args)
            def dispatch_once(self,invoke,*,persist_pending):persist_pending();return invoke()
        yield Guard()
        self.boundary()


def test_transport_reuses_parent_session_and_durable_once_export(tmp_path):
    diagnostic={};b=Backend(tmp_path,diagnostic);parent=b.session
    p=tmp_path/'new-cl'/'part.cl'
    r=m.export_current_cl(b,'before',binding(),str(p),diagnostic)
    assert r is diagnostic and r['readback_verified']and r['parent_session_preserved']
    assert b.session is parent and b.session_active and b.trace.count('SaveCLFile')==1
    assert ('typed','ICWMachine5')in b.trace and r['parse_summary']['block_count']==6
    assert r['output']['sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError):m.export_current_cl(b,'before',binding(),str(p),{})
    assert b.trace.count('SaveCLFile')==1


@pytest.mark.parametrize('failure',['exception','return','binding'])
def test_transport_failure_retains_session_and_no_export_replay(tmp_path,failure):
    d={};b=Backend(tmp_path,d,fail=failure);parent=b.session;p=tmp_path/'new-cl'/'part.cl'
    with pytest.raises((ValueError,RuntimeError)):m.export_current_cl(b,'before',binding(),str(p),d)
    assert not d['readback_verified']and not d['output_verified']and b.session is parent and b.session_active
    assert d['native_dispatch_pending']is(failure=='exception')and b.trace.count('SaveCLFile')==1
    with pytest.raises(ValueError):m.export_current_cl(b,'before',binding(),str(p),{})
    assert b.trace.count('SaveCLFile')==1


def test_three_exclusive_directories_and_dynamic_checkpoint_counts(tmp_path):
    p={k+'_cl_path':str(tmp_path/k/'part.cl')for k in ('before','generated','saved')}
    assert len(m.validate_outputs(p))==3
    p['saved_cl_path']=str(tmp_path/'before'/'other.cl')
    with pytest.raises(ValueError):m.validate_outputs(p)
    b=binding();b['operations'][2]['toolpath_record_counts']=[17]
    assert m.contract(b)[0]['toolpath_record_counts']==[17]