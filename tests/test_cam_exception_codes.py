"""Numeric-only EXCEPINFO additions, with no native application dependency."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import traceback
import pytest

from scripts.sw_cam import _error as error
SECRET = "private-license-or-path-do-not-publish"


def exception(info=None, argerror=None):
    result = RuntimeError(SECRET)
    result.hresult = -2147352567
    result.excepinfo = info
    result.argerror = argerror
    return result


def checked(exc):
    result = error(exc)
    assert SECRET not in json.dumps(result)
    assert "excepinfo" not in result
    return result


@pytest.mark.parametrize("container", [tuple, list])
@pytest.mark.parametrize("wcode,scode,arg", [(0,0,0),(65535,-2147467259,3),(1,4294967295,4294967295)])
def test_valid_numeric_codes_only(container,wcode,scode,arg):
    result=checked(exception(container([wcode,SECRET,SECRET,SECRET,SECRET,scode]),arg))
    assert result["excepinfo_codes"]==dict(wCode=wcode,scode=scode)
    assert result["argerror"]==arg and result["hresult"]==-2147352567
    assert set(result)=={"type","hresult","actual_return_type","locations","excepinfo_codes","argerror"}


@pytest.mark.parametrize("info", [None,SECRET,{},(),[],(1,),tuple([SECRET]*5),tuple([SECRET]*7),
    {"wCode":2,"scode":3,"description":SECRET},SimpleNamespace(wCode=2,scode=3,description=SECRET)])
def test_nonstandard_shape_is_not_parsed(info):
    result=checked(exception(info))
    assert "excepinfo_codes" not in result and "argerror" not in result


class PretendInt(int):
    pass


@pytest.mark.parametrize("index,bad", [(0,True),(0,False),(0,1.),(0,"17"),(0,None),(0,-1),(0,65536),(0,PretendInt(1)),
    (5,True),(5,1.),(5,SECRET),(5,{}),(5,-2147483649),(5,4294967296),(5,PretendInt(3))])
def test_invalid_numeric_slot_is_omitted_independently(index,bad):
    info=[7,SECRET,SECRET,SECRET,SECRET,-5]; info[index]=bad
    result=checked(exception(info))
    assert result["excepinfo_codes"]==({"scode":-5} if index==0 else {"wCode":7})


@pytest.mark.parametrize("bad", [True,False,1.,"1",SECRET,None,{},[], -1, 4294967296,PretendInt(2)])
def test_invalid_argerror_is_omitted_without_coercion(bad):
    result=checked(exception([1,SECRET,SECRET,SECRET,SECRET,2],bad))
    assert "argerror" not in result and result["excepinfo_codes"]==dict(wCode=1,scode=2)


def test_untrusted_text_and_nested_payloads_never_leave_excepinfo():
    result=checked(exception([SECRET,{"description":SECRET},[SECRET],SECRET,{"secret":SECRET},SECRET],SECRET))
    assert "excepinfo_codes" not in result and "argerror" not in result


def test_exception_args_are_not_used_as_a_fallback():
    exc=RuntimeError(-2147352567,SECRET,(7,SECRET,SECRET,SECRET,SECRET,-5),2)
    result=checked(exc)
    assert "excepinfo_codes" not in result and "argerror" not in result


class UnsafeTuple(tuple):
    def __getitem__(self,index):
        raise AssertionError("untrusted indexer must not run")


def test_subclass_container_is_not_traversed():
    result=checked(exception(UnsafeTuple((1,SECRET,SECRET,SECRET,SECRET,2))))
    assert "excepinfo_codes" not in result


def test_throwing_new_metadata_properties_do_not_break_error_reporting():
    class Broken(RuntimeError):
        @property
        def excepinfo(self): raise ValueError(SECRET)
        @property
        def argerror(self): raise ValueError(SECRET)
    result=checked(Broken(SECRET))
    assert result["type"]=="Broken" and "excepinfo_codes" not in result and "argerror" not in result


def test_existing_bridge_metadata_and_traceback_shape_are_preserved():
    try: raise exception((0,SECRET,SECRET,SECRET,SECRET,-1),2)
    except RuntimeError as exc:
        exc.code="BRIDGE_FAILURE"; exc.bridge_stage="GetCWApp"; exc.error_type="COMError"
        exc.input_type="IDispatch"; exc.source_type="ICWApp"; exc.actual_return_type="NoneType"
        result=checked(exc)
    assert result["code"]=="BRIDGE_FAILURE" and result["bridge_stage"]=="GetCWApp"
    assert result["actual_return_type"]=="NoneType"
    assert 1<=len(result["locations"])<=3
    assert set(result["locations"][0])=={"file","function","line"}
