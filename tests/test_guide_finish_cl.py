from pathlib import Path
import hashlib,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('SOLIDWORKS_SKILL_ROOT', str(ROOT)))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_finish_cl as m


def raw(*,changed=None,compensated=False,units='MM',box='-1,-1,-1,1,1,1'):
    text=f'UNITS/{units}\nBOX/{box}\n';counts=[]
    for i in range(10):
        x=i+20 if i==changed else i
        text+=f'CUTTER/2,0,1,0,0,0,55\nTLAXIS/0,0,1\nOPFEATSTART/Same\nRAPID/\nGOTO/{x},0,3\n'
        if compensated and i in (7,9):text+='CUTCOM/ON\nCUTCOM/LEFT\n'
        text+=f'FEDRAT/MMPM,24\nGOTO/{x},0,0\n'
        if compensated and i in (7,9):text+='CUTCOM/OFF\n'
        text+='OPFEATEND/Same\n';counts.append(7 if compensated and i in (7,9)else 4)
    return (text+'FINI\n').encode('ascii'),counts


def export(tmp_path,name,**kw):
    b,counts=raw(**kw);p=tmp_path/name;p.write_bytes(b)
    return dict(status='export_verified',output_verified=True,readback_verified=True,parent_session_preserved=True,
        output=dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest()),
        expected_generated_operations=[dict(operation_native_id=i,toolpath_record_counts=[n])for i,n in zip(m.cl.OLD+m.cl.NEW,counts)])


def test_finish_only_change_and_cutcom_removal_protects_other_eight(tmp_path):
    before=export(tmp_path,'before.cl',compensated=True)
    after=export(tmp_path,'after.cl',changed=7)
    r=m.verify_protected_eight(before,after)
    assert r['protected_eight_complete_streams_verified']
    assert [x['block']for x in r['unchanged']]==list(m.PROTECTED)
    assert m.verify_finish_without_cutcom(after)['finish_CL_without_CUTCOM_verified']
    assert not r['finish_native_mapping_verified'] and not r['geometry_verified']


@pytest.mark.parametrize('block',[0,5,6,8])
def test_changed_protected_stream_rejected(tmp_path,block):
    a=export(tmp_path,'before.cl');b=export(tmp_path,'after.cl',changed=block)
    with pytest.raises(ValueError,match='Protected'):m.verify_protected_eight(a,b)


def test_any_finish_compensation_is_rejected(tmp_path):
    b=export(tmp_path,'after.cl',compensated=True)
    with pytest.raises(ValueError,match='CUTCOM'):m.verify_finish_without_cutcom(b)


@pytest.mark.parametrize('kind',['bytes','contract','units','box'])
def test_changed_export_authority_rejected(tmp_path,kind):
    a=export(tmp_path,'before.cl');b=export(tmp_path,'after.cl')
    if kind=='bytes':Path(b['output']['path']).write_bytes(b'changed')
    if kind=='contract':b['expected_generated_operations'][6]['operation_native_id']=999
    if kind=='units':b=export(tmp_path,'after.cl',units='INCH')
    if kind=='box':b=export(tmp_path,'after.cl',box='-2,-1,-1,1,1,1')
    with pytest.raises(ValueError):m.verify_protected_eight(a,b)
