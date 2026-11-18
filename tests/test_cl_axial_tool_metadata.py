import pytest
from scripts import sw_cam_generic_cl_reader as m
from test_cam_route_cl_helix import helix


def test_antiparallel_metadata_preserves_geometry_without_claiming_frame():
    positive=m.parse_generic_cl_bytes(helix(),expected_block_record_counts=[4])
    negative=m.parse_generic_cl_bytes(helix(axis='0,0,-1'),expected_block_record_counts=[4])
    assert positive['parse_complete'] and negative['parse_complete'] and negative['native_count_matches']
    assert negative['block_command_counts']==[4]
    assert negative['motions'][0]['axis_raw']==[0,0,-1]
    assert [x['xyz'] for x in positive['motions']]==[x['xyz'] for x in negative['motions']]
    for key in ('center_raw','normal_raw','start_raw','endpoint_raw','angle_raw_rad','pitch_raw_per_rev','helical_envelope_bounds_raw'):
        assert positive['circle_records'][0][key]==negative['circle_records'][0][key]
    c=negative['circle_records'][0]
    assert c['tool_axis_relation_to_local_circle_normal']=='antiparallel_declared_metadata'
    assert not c['tool_axis_coordinate_frame_verified'] and not c['tool_axis_transformed']
    assert not negative['coordinate_frame_verified'] and not negative['physical_poses_verified'] and not negative['production_qualified']


@pytest.mark.parametrize('kw',[{'axis':'0,1,0'},{'axis':'0.6,0,-0.8'},{'normal':'0,0,-1','axis':'0,0,-1'},{'direction':'CLOCKWISE','axis':'0,0,-1'},{'end':'-3,0,1.5','axis':'0,0,-1'},{'end':'0,-3,-1.5','axis':'0,0,-1'}])
def test_other_geometry_not_admitted(kw):
    assert not m.parse_generic_cl_bytes(helix(**kw))['parse_complete']


def test_axis_change_between_helix_endpoints_rejected():
    raw=helix(axis='0,0,-1').replace(b'CIRCLE/',b'TLAXIS/0,0,1\nCIRCLE/')
    assert not m.parse_generic_cl_bytes(raw)['parse_complete']

