"""Synthetic boundary tests for the pure larger CL reader."""
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
m=required_module('sw_cam_generic_cl_reader_bounded')

def cl(counts):
    rows=['UNITS/MM']
    for i,count in enumerate(counts):
        assert count>=4
        rows.extend([f'OPFEATSTART/B{i}','CUTTER/2,0,0,0,0,0,40','TLAXIS/0,0,1','RAPID/'])
        rows.extend(['RAPID/']*(count-4))
        rows.extend(['GOTO/0,0,0',f'OPFEATEND/B{i}'])
    rows.append('FINI')
    return ('\n'.join(rows)+'\n').encode('ascii')

def test_exact_total_limit_accepts_two_maximum_blocks():
    p=m.parse_generic_cl_bytes(cl([100000,100000]),expected_block_record_counts=[100000,100000])
    assert p['parse_complete'] is True
    assert p['native_count_matches'] is True
    assert p['block_command_counts']==[100000,100000]
    assert p['native_calls']==0 and p['production_qualified'] is False
    assert p['circle_direction_semantics_verified'] is False

@pytest.mark.parametrize('counts',[[100000,100000,1],[100001],[True],[0],[-1],[1.0],[],tuple([4]),[4]*33])
def test_invalid_ordered_count_contract_rejected(counts):
    with pytest.raises(ValueError,match='Bounded ordered'):
        m.parse_generic_cl_bytes(cl([4]),expected_block_record_counts=counts)

def test_legacy_limit_unchanged():
    with pytest.raises(ValueError,match='bounded positive-total'):
        m.parse_generic_cl_bytes(cl([4]),expected_record_counts=[100000,1])

def test_ambiguous_count_arguments_rejected():
    with pytest.raises(ValueError,match='mutually exclusive'):
        m.parse_generic_cl_bytes(cl([4]),expected_record_counts=[4],expected_block_record_counts=[4])

def test_text_line_limit_accepts_exact_and_rejects_one_more():
    raw=cl([4]);raw+=b'\n'*(m.MAX_TEXT_LINES-len(raw.splitlines()))
    assert len(raw.splitlines())==200100
    assert m.parse_generic_cl_bytes(raw,expected_block_record_counts=[4])['parse_complete'] is True
    with pytest.raises(ValueError,match='text line'):
        m.parse_generic_cl_bytes(raw+b'\n',expected_block_record_counts=[4])

def test_byte_limit_unchanged():
    with pytest.raises(ValueError,match='CL bytes'):
        m.parse_generic_cl_bytes(b' '*(64*1024*1024+1),expected_block_record_counts=[4])

@pytest.mark.parametrize('raw',[b'',bytearray(b'FINI'),None,'FINI'])
def test_strict_raw_byte_type(raw):
    with pytest.raises(ValueError,match='CL bytes'):
        m.parse_generic_cl_bytes(raw,expected_block_record_counts=[4])

def test_nul_rejected():
    with pytest.raises(ValueError,match='NUL'):
        m.parse_generic_cl_bytes(cl([4])+b'\x00',expected_block_record_counts=[4])

def test_unknown_grammar_does_not_become_complete():
    p=m.parse_generic_cl_bytes(cl([4]).replace(b'RAPID/',b'UNKNOWN/'),expected_block_record_counts=[4])
    assert p['parse_complete'] is False and p['unknown_commands']

def test_wrong_native_count_does_not_become_complete():
    p=m.parse_generic_cl_bytes(cl([4]),expected_block_record_counts=[5])
    assert p['parse_complete'] is False and p['native_count_matches'] is False

def test_invalid_numeric_value_remains_incomplete():
    p=m.parse_generic_cl_bytes(cl([4]).replace(b'GOTO/0,0,0',b'GOTO/nan,0,0'),expected_block_record_counts=[4])
    assert p['parse_complete'] is False and p['invalid_commands']
