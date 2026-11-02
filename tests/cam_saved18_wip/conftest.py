"""Installed runtime only; fixtures are synthetic and never connect to CAD."""
from pathlib import Path
import os,sys
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', Path(__file__).resolve().parents[2])).resolve()
for name in ('sw_cam_saved18_optimized_wip.py','sw_cam_saved18_wip_binding.py'):
    if not (ROOT/'scripts'/name).is_file():raise RuntimeError('Installed saved18 WIP modules required')
sys.path.insert(0,str(ROOT))
import scripts
if not all(Path(p).resolve()==(ROOT/'scripts').resolve() for p in scripts.__path__):raise RuntimeError('Only installed scripts package permitted')
