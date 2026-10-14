"""任意正交坐标系上的原生圆角矩形切除；由 MCP 持有互斥锁。"""
from __future__ import annotations
import base64
import json
import math
import subprocess
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

class FrameCutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin_mm: tuple[float, float, float]
    x_axis: tuple[float, float, float] = (1, 0, 0)
    y_axis: tuple[float, float, float] = (0, 1, 0)
    center_mm: tuple[float, float] = (0, 0)
    width_mm: float = Field(gt=0, le=1000)
    height_mm: float = Field(gt=0, le=1000)
    radius_mm: float = Field(gt=0, le=500)
    depth_mm: float = Field(gt=0, le=2000)
    along_normal: bool = False
    feature_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")

    @model_validator(mode="after")
    def check_geometry(self):
        """在任何 COM 写入之前拒绝退化坐标系和自交轮廓。"""
        for axis in (self.x_axis, self.y_axis):
            if abs(math.sqrt(sum(v*v for v in axis))-1) > 1e-8:
                raise ValueError("Axes must be unit vectors")
        if abs(sum(a*b for a,b in zip(self.x_axis,self.y_axis))) > 1e-8:
            raise ValueError("Axes must be perpendicular")
        if 2*self.radius_mm >= min(self.width_mm,self.height_mm):
            raise ValueError("Radius must be less than half the profile size")
        return self

def create_frame_cut(sw, model, spec):
    """PIA 封装，限定当前进程、当前已保存零件及结构化轮廓。"""
    from scripts.sw_connect import get_com_member as get
    from scripts.cad_installation import discover_installation
    install=Path(discover_installation("solidworks")["executable"]).parent
    interop=next(p for p in (install/"api/redist",install) if (p/"SolidWorks.Interop.sldworks.dll").is_file())
    request={"process_id":int(get(sw,"GetProcessID")),"source":str(get(model,"GetPathName")),"spec":spec.model_dump()}
    payload=base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
    proc=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(Path(__file__).with_suffix(".ps1")),"-InputBase64",payload,"-InteropRoot",str(interop)],capture_output=True,encoding="utf-8",errors="replace",timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout.lstrip("\ufeff"))
