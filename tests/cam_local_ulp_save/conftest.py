"""Installed runtime only; no staging imports or native connection."""
from pathlib import Path
import os,sys
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', Path(__file__).resolve().parents[2])).resolve()
if not(ROOT/'scripts/sw_cam_local_ulp_save.py').is_file():raise RuntimeError('Installed ULP module required')
sys.path.insert(0,str(ROOT))
import scripts
if not all(Path(p).resolve()==(ROOT/'scripts').resolve() for p in scripts.__path__):raise RuntimeError('Only installed scripts package permitted')
