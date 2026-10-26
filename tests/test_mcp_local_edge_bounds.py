import json
import pytest
from types import SimpleNamespace as N
from unittest.mock import Mock
from tests.test_mcp_guarded_fillet import server

@pytest.mark.parametrize('bounds',[[1,0,0,0,1,1],[0,0,0,float('nan'),1,1],[0,0,0,1,1,float('inf')]])
def test_bad_bounds_rejected(bounds):
    with pytest.raises(ValueError):
        server.SolidWorksEdgeInspectionInput(endpoint_bounds_mm=bounds)

def test_local_bounds_are_explicit_and_preserved():
    v=server.SolidWorksEdgeInspectionInput(endpoint_bounds_mm=[26,-5,4,29,5,4.4],include_convexity=False)
    assert v.endpoint_bounds_mm==[26,-5,4,29,5,4.4]
