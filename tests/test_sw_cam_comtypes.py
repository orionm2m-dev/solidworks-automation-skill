"""No-CAD tests for the standard-marshaling CAM vtable bridge."""
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from scripts import sw_cam_comtypes as bridge


def test_unknown_interface_is_rejected_before_library_load(monkeypatch):
    loader = Mock(side_effect=AssertionError("must not load"))
    monkeypatch.setattr(bridge, "_load_type_library", loader)
    with pytest.raises(ValueError):
        bridge._interface_class("UntrustedClass", "unused.tlb")
    loader.assert_not_called()


def test_generated_interface_iid_must_match_verified_definition(monkeypatch):
    monkeypatch.setattr(bridge, "_load_type_library", Mock(return_value=SimpleNamespace(
        ICWDoc3=SimpleNamespace(_iid_="{00000000-0000-0000-0000-000000000000}"))))
    with pytest.raises(ValueError):
        bridge._interface_class("ICWDoc3", "unused.tlb")


def test_null_input_is_rejected_without_transport(monkeypatch):
    transport = Mock()
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", transport)
    with pytest.raises(ValueError):
        bridge.query_cam_interface(None, "ICWDoc3", "unused.tlb")
    transport.assert_not_called()


def test_existing_typed_pointer_uses_native_qi_without_remarshal(monkeypatch):
    target_class = object()
    source = SimpleNamespace(QueryInterface=Mock(return_value="typed-interface"))
    monkeypatch.setattr(bridge, "_interface_class", Mock(return_value=target_class))
    monkeypatch.setattr(bridge, "_is_comtypes_pointer", Mock(return_value=True))
    transport = Mock(side_effect=AssertionError("must not remarshal"))
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", transport)
    assert bridge.query_cam_interface(source, "ICWDoc3", "verified.tlb") == "typed-interface"
    source.QueryInterface.assert_called_once_with(target_class)
    transport.assert_not_called()


def test_pywin32_source_is_transferred_then_native_qi_is_used(monkeypatch):
    target_class, source = object(), object()
    unknown = SimpleNamespace(QueryInterface=Mock(return_value="typed-interface"))
    monkeypatch.setattr(bridge, "_interface_class", Mock(return_value=target_class))
    monkeypatch.setattr(bridge, "_is_comtypes_pointer", Mock(return_value=False))
    transport = Mock(return_value=unknown)
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", transport)
    assert bridge.query_cam_interface(source, "ICWDoc3", "verified.tlb") == "typed-interface"
    transport.assert_called_once_with(source)
    unknown.QueryInterface.assert_called_once_with(target_class)


class MemoryStream:
    def __init__(self, payload=b"trusted-test-objref", size=None):
        self.payload = payload
        self.size = len(payload) if size is None else size
        self.seeks = []

    def Seek(self, offset, origin):
        self.seeks.append((offset, origin))
        return self.size if origin == 2 else 0

    def Read(self, size):
        return self.payload[:size]


def fake_pythoncom(monkeypatch, stream):
    fake = SimpleNamespace(
        IID_IUnknown="standard-IUnknown", MSHCTX_INPROC=3, MSHLFLAGS_NORMAL=0,
        CreateStreamOnHGlobal=Mock(return_value=stream),
        CoMarshalInterface=Mock(), CoReleaseMarshalData=Mock(),
    )
    monkeypatch.setitem(sys.modules, "pythoncom", fake)
    return fake


def test_marshaled_normal_packet_is_consumed_once_without_double_release(monkeypatch):
    stream = MemoryStream()
    native_source = object()
    wrapped_source = SimpleNamespace(_oleobj_=native_source)
    fake = fake_pythoncom(monkeypatch, stream)
    result = object()
    consume = Mock(return_value=result)
    monkeypatch.setattr(bridge, "_unmarshal_unknown", consume)
    assert bridge._marshal_pywin32_unknown(wrapped_source) is result
    fake.CoMarshalInterface.assert_called_once_with(stream, fake.IID_IUnknown,
                                                    native_source, 3, 0)
    consume.assert_called_once_with(stream.payload)
    fake.CoReleaseMarshalData.assert_not_called()


def test_raw_pywin32_input_is_preserved_without_address_extraction(monkeypatch):
    stream, source = MemoryStream(), object()
    fake = fake_pythoncom(monkeypatch, stream)
    monkeypatch.setattr(bridge, "_unmarshal_unknown", Mock(return_value=object()))
    bridge._marshal_pywin32_unknown(source)
    assert fake.CoMarshalInterface.call_args.args[2] is source


def test_failed_unmarshal_releases_packet_and_propagates_original_error(monkeypatch):
    stream = MemoryStream()
    fake = fake_pythoncom(monkeypatch, stream)
    original = RuntimeError("transport failed")
    monkeypatch.setattr(bridge, "_unmarshal_unknown", Mock(side_effect=original))
    with pytest.raises(bridge.CamComBridgeError) as caught:
        bridge._marshal_pywin32_unknown(object())
    assert caught.value.code == "CAM_COM_UNMARSHAL_FAILED"
    assert caught.value.error_type == "RuntimeError"
    assert "transport failed" not in str(caught.value)
    fake.CoReleaseMarshalData.assert_called_once_with(stream)
    assert stream.seeks[-1] == (0, 0)


@pytest.mark.parametrize("size,payload", [(0, b""), (bridge._MAX_MARSHAL_BYTES + 1, b"x"), (10, b"short")])
def test_invalid_or_truncated_packet_is_not_unmarshaled_and_is_released(monkeypatch, size, payload):
    stream = MemoryStream(payload, size)
    fake = fake_pythoncom(monkeypatch, stream)
    consume = Mock(side_effect=AssertionError("must not consume"))
    monkeypatch.setattr(bridge, "_unmarshal_unknown", consume)
    with pytest.raises(bridge.CamComBridgeError) as caught:
        bridge._marshal_pywin32_unknown(object())
    assert caught.value.code == "CAM_COM_STREAM_READ_FAILED"
    consume.assert_not_called()
    fake.CoReleaseMarshalData.assert_called_once_with(stream)


def test_failed_marshal_does_not_try_to_unmarshal_or_release_uncreated_packet(monkeypatch):
    stream = MemoryStream()
    fake = fake_pythoncom(monkeypatch, stream)
    fake.CoMarshalInterface.side_effect = RuntimeError("marshal failed")
    consume = Mock()
    monkeypatch.setattr(bridge, "_unmarshal_unknown", consume)
    with pytest.raises(RuntimeError):
        bridge._marshal_pywin32_unknown(object())
    consume.assert_not_called()
    fake.CoReleaseMarshalData.assert_not_called()


def test_generated_coclass_and_dispatch_are_unwrapped_without_com_getattr(monkeypatch):
    stream, source = MemoryStream(), object()
    fake = fake_pythoncom(monkeypatch, stream)
    wrapped = SimpleNamespace(_dispobj_=SimpleNamespace(_oleobj_=source))
    monkeypatch.setattr(bridge, "_unmarshal_unknown", Mock(return_value=object()))
    bridge._marshal_pywin32_unknown(wrapped)
    assert fake.CoMarshalInterface.call_args.args[2] is source


@pytest.mark.parametrize("kind", ["null", "cyclic", "too_deep"])
def test_invalid_wrapper_chain_rejected_before_marshal(monkeypatch, kind):
    fake = fake_pythoncom(monkeypatch, MemoryStream())
    if kind == "null":
        wrapped = SimpleNamespace(_dispobj_=None)
    elif kind == "cyclic":
        wrapped = SimpleNamespace()
        wrapped._dispobj_ = wrapped
    else:
        wrapped = object()
        for _ in range(10):
            wrapped = SimpleNamespace(_dispobj_=wrapped)
    with pytest.raises(bridge.CamComBridgeError) as caught:
        bridge._marshal_pywin32_unknown(wrapped)
    assert caught.value.code == "CAM_COM_SOURCE_INVALID"
    fake.CoMarshalInterface.assert_not_called()


def test_marshal_error_reports_stage_and_types_without_exception_payload(monkeypatch):
    fake = fake_pythoncom(monkeypatch, MemoryStream())
    fake.CoMarshalInterface.side_effect = ValueError("SECRET_OBJREF_OR_LICENSE_CONTENT")
    wrapped = SimpleNamespace(_dispobj_=SimpleNamespace(_oleobj_=object()))
    with pytest.raises(bridge.CamComBridgeError) as caught:
        bridge._marshal_pywin32_unknown(wrapped)
    err = caught.value
    assert err.code == "CAM_COM_MARSHAL_FAILED"
    assert err.bridge_stage == "marshal"
    assert err.error_type == "ValueError"
    assert err.input_type == "SimpleNamespace"
    assert err.source_type == "object"
    assert "SECRET_OBJREF_OR_LICENSE_CONTENT" not in str(err)
    assert "SECRET_OBJREF_OR_LICENSE_CONTENT" not in repr(err.__dict__)


def test_native_qi_failure_has_distinct_sanitized_stage(monkeypatch):
    source = SimpleNamespace(QueryInterface=Mock(side_effect=RuntimeError("SECRET_CONTENT")))
    monkeypatch.setattr(bridge, "_interface_class", Mock(return_value=object()))
    monkeypatch.setattr(bridge, "_is_comtypes_pointer", Mock(return_value=True))
    with pytest.raises(bridge.CamComBridgeError) as caught:
        bridge.query_cam_interface(source, "ICWDoc3", "verified.tlb")
    assert caught.value.code == "CAM_COM_NATIVE_QI_FAILED"
    assert caught.value.bridge_stage == "native_query_interface"
    assert "SECRET_CONTENT" not in str(caught.value)


def test_standard_memory_stream_roundtrip_with_coclass_wrapper_uses_no_cad():
    """Real Windows COM infrastructure only: no CAD/ROT/server activation."""
    pythoncom = pytest.importorskip("pythoncom")
    source = pythoncom.CreateStreamOnHGlobal()
    expected = b"cam-standard-stream-check"
    source.Write(expected)
    source.Seek(0, 0)
    wrapped = SimpleNamespace(_dispobj_=SimpleNamespace(_oleobj_=source))
    unknown = bridge._marshal_pywin32_unknown(wrapped)
    stream = unknown.QueryInterface(bridge._stream_interface())
    data, count = stream.RemoteRead(len(expected))
    assert count == len(expected)
    assert bytes(data[:count]) == expected


def test_real_comtypes_pointer_hierarchy_uses_iunknown_not_scalar_type_code():
    from ctypes import POINTER
    from comtypes import IUnknown
    from comtypes.automation import IDispatch
    pointer = POINTER(IDispatch)()
    assert type(pointer)._type_ == "P"
    assert isinstance(pointer, IUnknown)
    assert bridge._is_comtypes_pointer(pointer) is True
    assert bridge._is_comtypes_pointer(object()) is False


def test_generated_cam_machine_pointer_is_recognized_without_cad():
    from ctypes import POINTER
    from pathlib import Path
    path = Path(r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS CAM\camworks.tlb")
    if not path.is_file():
        pytest.skip("Installed CAM 2026 typelib is unavailable")
    module = bridge._load_type_library(str(path))
    pointer = POINTER(module.ICWMillMachine)()  # Null pointer: metadata only.
    assert type(pointer).__name__ == "POINTER(ICWMillMachine)"
    assert bridge._is_comtypes_pointer(pointer) is True


def test_null_typed_pointer_is_rejected_before_qi_or_remarshal(monkeypatch):
    from ctypes import POINTER
    from comtypes.automation import IDispatch
    monkeypatch.setattr(bridge, "_interface_class", Mock(return_value=IDispatch))
    transport = Mock(side_effect=AssertionError("must not marshal typed pointer"))
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", transport)
    with pytest.raises(ValueError, match="null typed"):
        bridge.query_cam_interface(POINTER(IDispatch)(), "ICWDoc3", "verified.tlb")
    transport.assert_not_called()


def test_real_standard_stream_pointer_uses_direct_qi_without_pywin32_transport(monkeypatch):
    pythoncom = pytest.importorskip("pythoncom")
    source = pythoncom.CreateStreamOnHGlobal()
    source.Write(b"typed-qi")
    source.Seek(0, 0)
    unknown = bridge._marshal_pywin32_unknown(source)
    stream_class = bridge._stream_interface()
    typed = unknown.QueryInterface(stream_class)
    monkeypatch.setattr(bridge, "_interface_class", Mock(return_value=stream_class))
    transport = Mock(side_effect=AssertionError("must not remarshal typed pointer"))
    monkeypatch.setattr(bridge, "_marshal_pywin32_unknown", transport)
    result = bridge.query_cam_interface(typed, "ICWDoc3", "verified.tlb")
    data, count = result.RemoteRead(8)
    assert bytes(data[:count]) == b"typed-qi"
    transport.assert_not_called()
