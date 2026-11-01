import importlib.util,os,sys,json
from pathlib import Path
from datetime import datetime,timezone
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).parents[1]));sys.path.insert(0,root)
spec=importlib.util.spec_from_file_location('timestamp_fixed',Path(__file__).parents[1]/'scripts/sw_cam_inprocess_host_load.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.mark.parametrize('text',[
 '2026-11-01T10:59:49.3089934Z',
 '2026-11-01T10:59:49.3089939Z',
 '2026-11-01T10:59:49.308993Z',
 '2026-11-01T10:59:49.308993+00:00',
 '2026-11-01T16:29:49.3089934+05:30',
 '2026-11-01T05:59:49.3089934-05:00',
])
def test_dotnet_roundtrip_preserves_instant_at_microsecond_precision(text):
    expected=datetime(2026,11,1,10,59,49,308993,tzinfo=timezone.utc).timestamp()
    assert m.utc_epoch(text)==expected

@pytest.mark.parametrize('text',[
 '2026-11-01T10:59:49Z','2026-11-01T10:59:49+00:00',
 '2026-11-02T00:59:49+14:00','2026-10-31T20:59:49-14:00',
])
def test_no_fraction_and_offset_boundaries(text):
    assert m.utc_epoch(text)==datetime(2026,11,1,10,59,49,tzinfo=timezone.utc).timestamp()

@pytest.mark.parametrize('text',[
 '2026-11-01T10:59:49.3Z','2026-11-01T10:59:49.300Z',
 '2026-11-01T10:59:49.3000000Z',
])
def test_short_fraction_is_decimal_fraction(text):
    assert m.utc_epoch(text)==datetime(2026,11,1,10,59,49,300000,tzinfo=timezone.utc).timestamp()

@pytest.mark.parametrize('text',[
 None,True,123,'','2026-11-01T10:59:49',
 '2026-11-01T10:59:49.12345678Z','2026-11-01T10:59:49.Z',
 '2026-11-01T10:59:49,123Z','2026-11-01 10:59:49Z',
 '2026-11-01T10:59:49z','2026-11-01T10:59:49Zjunk',
 '2026-02-29T10:59:49Z','2024-02-30T10:59:49Z',
 '0000-11-01T10:59:49Z','2026-13-01T10:59:49Z',
 '2026-11-01T24:00:00Z','2026-11-01T10:59:60Z',
 '2026-11-01T10:59:49+14:01','2026-11-01T10:59:49-14:30',
 '2026-11-01T10:59:49+15:00','2026-11-01T10:59:49+01:60',
 '2026-11-01T10:59:49+00:99','2026-11-01T10:59:49+0000',
 '2026-11-01T10:59:49+00','2026-11-01T10:59:49+00:00:01',
])
def test_invalid_date_time_fraction_and_offset_rejected(text):
    with pytest.raises(ValueError):m.utc_epoch(text)


def test_seven_digit_diagnostic_verification_preserves_error_evidence():
    # Regression fixture preserves the failed loader status; parsing is separate evidence.
    record=dict(status='error',load_calls=1,load_result=0)
    data=dict(status='connected',hostProcessId=123,hostProcessName='SLDWORKS',
        addinGuid=m.HOST_CLSID,callbackRegistered=True,commandGroupReady=True,
        taskPaneReady=True,propertyManagerPageReady=True,errors=[],
        connectedAtUtc='2026-11-01T10:59:49.3089934Z',
        lastUpdatedUtc='2026-11-01T10:59:49.7611225Z')
    start=datetime(2026,11,1,10,59,49,tzinfo=timezone.utc).timestamp()
    m.verify_diagnostics(None,dict(data=data,sha256='fresh'),dict(process_id=123),start)
    assert m.utc_epoch(data['lastUpdatedUtc'])>=m.utc_epoch(data['connectedAtUtc'])
    assert record==dict(status='error',load_calls=1,load_result=0)
