"""Strict schema and selected-process routing for owned imported-body repair; no CAD calls."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'mcp-server') not in sys.path:sys.path.insert(0,str(ROOT/'mcp-server'))
import server

@pytest.fixture
def params(tmp_path):
    prior=tmp_path/'prior.json';prior.write_text('{}')
    return dict(process_id=71,action='prepare',transfer_receipt_path=str(prior),
        transfer_receipt_sha256='a'*64,repaired_step_path=str(tmp_path/'repaired.step'),qualification_only=True)

@pytest.mark.parametrize('field,value',[
    ('process_id',True),('process_id',0),('qualification_only',False),('qualification_only',1),
    ('transfer_receipt_sha256','A'*64),('transfer_receipt_path','relative.json'),
    ('repaired_step_path','relative.step'),('action','repair'),('receipt_path','out.json'),
    ('expected_state_sha256','b'*64)])
def test_repair_schema_rejects_invalid_or_mutation_inputs(params,field,value):
    with pytest.raises(Exception):server.SolidWorksImportDiagnosisInput(**(params|{field:value}))

def test_repair_apply_requires_paired_state_and_new_receipt(params,tmp_path):
    with pytest.raises(Exception):server.SolidWorksImportDiagnosisInput(**(params|dict(action='apply')))
    p=server.SolidWorksImportDiagnosisInput(**(params|dict(action='apply',expected_state_sha256='b'*64,receipt_path=str(tmp_path/'receipt.json'))))
    assert p.action=='apply'
    Path(p.repaired_step_path).write_bytes(b'existing')
    with pytest.raises(Exception):server.SolidWorksImportDiagnosisInput(**params)

@pytest.mark.parametrize('wrong_pid',[False,True])
def test_repair_wrapper_requires_selected_pid_and_passes_exact_values(params,monkeypatch,wrong_pid):
    p=server.SolidWorksImportDiagnosisInput(**params);sw=object();native=Mock(return_value={'status':'ok'})
    monkeypatch.setitem(sys.modules,'scripts.sw_native_transfer',N(qualify_import_diagnosis=native))
    connect=Mock(return_value=(sw,None));monkeypatch.setattr(server,'connect_solidworks',connect)
    monkeypatch.setattr(server,'_selected_process_id',72 if wrong_pid else 71)
    monkeypatch.setattr(server,'_run_locked',lambda op,fmt:op())
    if wrong_pid:
        with pytest.raises(ValueError):server.solidworks_qualify_import_diagnosis(p)
        connect.assert_not_called();native.assert_not_called()
    else:
        assert server.solidworks_qualify_import_diagnosis(p)=={'status':'ok'}
        connect.assert_called_once_with(wait_seconds=1,process_id=71)
        native.assert_called_once_with(sw,**p.model_dump(exclude={'response_format'}))

def test_repair_tool_and_previous_component_revision_remain_registered():
    tool=server.mcp._tool_manager._tools['solidworks_qualify_import_diagnosis']
    assert tool.annotations.idempotentHint is False
    assert 'solidworks_qualify_component_revision' in server.mcp._tool_manager._tools
