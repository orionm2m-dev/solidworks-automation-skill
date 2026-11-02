"""Installed runtime only. No alternate module path or stage fallback."""
from pathlib import Path
import os,sys
ROOT=Path(os.environ.get("SOLIDWORKS_SKILL_ROOT", Path(__file__).resolve().parents[2])).resolve()
if not(ROOT/'scripts/sw_cam_saved18_serial_dirty_verify.py').is_file():
    raise RuntimeError('Installed saved18 serial module required')
sys.path.insert(0,str(ROOT))
import scripts
expected=(ROOT/'scripts').resolve()
if not all(Path(p).resolve()==expected for p in scripts.__path__):
    raise RuntimeError('Only the installed scripts package may be used')
