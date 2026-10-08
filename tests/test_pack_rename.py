"""显式 Pack and Go 文件映射防护回归。"""
from pathlib import Path
import pytest
from scripts.sw_pack_rename import CopyEntry,validate_mapping,_names


def mapping(tmp_path):
    source=tmp_path/'old.SLDPRT';source.write_bytes(b'source')
    return [CopyEntry(source=str(source),target=str(tmp_path/'new.SLDPRT'))]


def test_mapping_follows_native_order(tmp_path):
    entries=mapping(tmp_path)
    other=tmp_path/'old.SLDASM';other.write_bytes(b'assembly')
    entries.append(CopyEntry(source=str(other),target=str(tmp_path/'new.SLDASM')))
    assert validate_mapping(entries,[entries[1].source,entries[0].source])==[entries[1].target,entries[0].target]


def test_incomplete_native_enumeration_is_rejected(tmp_path):
    entries=mapping(tmp_path)
    with pytest.raises(ValueError,match='enumeration'):validate_mapping(entries,[])


@pytest.mark.parametrize('kind',['existing','self','extension','duplicate'])
def test_dangerous_destinations_are_rejected(tmp_path,kind):
    entries=mapping(tmp_path)
    if kind=='existing':Path(entries[0].target).write_bytes(b'keep')
    if kind=='self':entries[0].target=entries[0].source
    if kind=='extension':entries[0].target=str(tmp_path/'new.SLDASM')
    if kind=='duplicate':entries.append(entries[0])
    with pytest.raises((ValueError,FileExistsError)):validate_mapping(entries,[e.source for e in entries])
    assert Path(entries[0].source).read_bytes()==b'source'


def test_unknown_schema_field_is_rejected():
    with pytest.raises(ValueError):CopyEntry(source='a',target='b',overwrite=True)


def test_com_out_array_is_normalized_without_boolean():
    assert _names((True,('a.SLDASM','b.SLDPRT')))==['a.SLDASM','b.SLDPRT']


def test_mcp_registers_guarded_rename_tool():
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp-server'))
    import server
    assert 'solidworks_pack_and_go_renamed' in server.mcp._tool_manager._tools
    assert issubclass(server.SolidWorksPackRenameInput,server.ActiveDocumentInput)
