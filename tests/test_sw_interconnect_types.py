"""@brief 3D Interconnect 原生文件的文档类型映射（纯函数，不连接 SolidWorks）。"""

import pytest

from scripts import sw_connect


@pytest.mark.parametrize("name,expected", [
    ("Gasket.ipt", 6), ("Case.IAM", 7), ("part.CATPart", 6), ("asm.CATProduct", 7),
    ("x.prt", 6), ("x.asm", 7), ("x.par", 6), ("x.psm", 6),
    ("Body.SLDPRT", None), ("Body.stp", None), ("a.step", None),
])
def test_interconnect_document_type(name, expected) -> None:
    assert sw_connect.interconnect_document_type(name) == expected


def test_toggle_constant_matches_swconst() -> None:
    assert sw_connect.SW_TOGGLE_ENABLE_3D_INTERCONNECT == 691
