"""Read explicitly requested custom properties without editing the document."""
from __future__ import annotations

from scripts.sw_connect import get_com_member
from scripts.sw_document_data import read_custom_property
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _request(process_id, expected_document_path, names, configuration_name):
    if type(process_id) is not int or process_id <= 0:
        raise ValueError("Exact positive process ID required")
    if type(expected_document_path) is not str or not absolute_document_path(expected_document_path):
        raise ValueError("Exact absolute document path required")
    if type(names) is not list or not 1 <= len(names) <= 64:
        raise ValueError("One to 64 explicit property names required")
    if any(type(name) is not str or not name.strip() or len(name) > 240 for name in names):
        raise ValueError("Nonempty property names of at most 240 characters required")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Duplicate property names are not permitted")
    if type(configuration_name) is not str or len(configuration_name) > 240:
        raise ValueError("Exact file or active configuration scope required")


def _identity(sw, process_id, expected_document_path):
    actual_pid = get_com_member(sw, "GetProcessID")
    if type(actual_pid) is not int or actual_pid != process_id:
        raise ValueError("Bound process identity differs")
    model = get_com_member(sw, "ActiveDoc")
    if model is None:
        raise ValueError("Active document unavailable")
    path = get_com_member(model, "GetPathName")
    title = get_com_member(model, "GetTitle")
    kind = get_com_member(model, "GetType")
    dirty = get_com_member(model, "GetSaveFlag")
    if type(path) is not str or type(title) is not str:
        raise ValueError("Native document path and title must be strings")
    check_document_target(path, title, expected_path=expected_document_path, required=True)
    if type(kind) is not int or kind not in (1, 2):
        raise ValueError("Saved native part or assembly required")
    if type(dirty) is not bool:
        raise ValueError("Native dirty state must be Boolean")
    manager = get_com_member(model, "ConfigurationManager")
    configuration = get_com_member(manager, "ActiveConfiguration")
    configuration_name = get_com_member(configuration, "Name")
    if type(configuration_name) is not str or not configuration_name:
        raise ValueError("Active configuration name unavailable")
    return model, {
        "process_id": actual_pid, "path": path, "title": title,
        "type": kind, "needs_save": dirty, "active_configuration": configuration_name,
    }


def _validate_property(row, name, configuration_name):
    if type(row) is not dict:
        raise ValueError("Property reader returned an invalid object")
    if row.get("name") != name or row.get("configuration") != configuration_name:
        raise ValueError("Property reader returned a different name or scope")
    status = row.get("status")
    if type(status) is not int or status not in (0, 1, 2):
        raise ValueError("Undocumented property read status")
    for key in ("exists", "was_resolved", "is_linked"):
        if type(row.get(key)) is not bool:
            raise ValueError("Property reader returned a non-Boolean " + key)
    if row["exists"] != (status != 1):
        raise ValueError("Property existence disagrees with read status")
    if type(row.get("raw")) is not str or type(row.get("resolved")) is not str:
        raise ValueError("Property raw and resolved values must be strings")
    return dict(row)


def read_custom_properties(sw, *, process_id, expected_document_path,
                           names, configuration_name=""):
    """Read file-level or currently active configuration properties only.

    Missing properties are reported, not created. Cached/unresolved values remain
    explicitly marked. An existing dirty state is preserved, never saved or reset.
    """
    result = {
        "status": "error", "read_only": True, "mutation_attempted": False,
        "model_saved": False, "read_complete": False, "state_unchanged": False,
        "may_continue": False, "properties": [],
    }
    try:
        _request(process_id, expected_document_path, names, configuration_name)
        model, before = _identity(sw, process_id, expected_document_path)
        result["before"] = before
        if configuration_name and configuration_name != before["active_configuration"]:
            raise ValueError("Only file-level or the current active configuration may be read")
        for name in names:
            result["reading_property"] = name
            row = read_custom_property(model, name, configuration_name=configuration_name)
            _current, after = _identity(sw, process_id, expected_document_path)
            result["after"] = after
            if after != before:
                raise ValueError("Document identity, configuration or dirty state changed during read")
            result["properties"].append(_validate_property(row, name, configuration_name))
        result.pop("reading_property", None)
        result.update(status="ok", read_complete=True, state_unchanged=True)
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    return result
