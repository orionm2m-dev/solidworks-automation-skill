"""Public typelib metadata and construction only; no application access."""
import importlib.util,os,sys
from pathlib import Path
import pytest
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE));sys.path.insert(0,str(RUNTIME))
spec=importlib.util.spec_from_file_location('import_actual_abi',STAGE/'scripts/sw_cam_process_import.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_actual_public_import_abi_and_no_application_constructor():
    tlb=os.environ.get('SWMCP_CAM_TYPELIB')
    if not tlb:pytest.skip('Set SWMCP_CAM_TYPELIB for offline public ABI qualification')
    a=module.preflight(tlb);assert a==dict(interface='ICWApp4',method='ImportCAMData',dispid=45,existing_data=0,merge_setup=False,native_calls=0)
    class NoApplication:
        def __getattribute__(self,name):raise AssertionError('Unexpected application access: '+name)
    c=module.ImportContext(NoApplication(),'observed-clsid',tlb,{}, {}, {}, lambda:None,lambda:None)
    assert c.session is None and c.expected is None and c.closed is False
