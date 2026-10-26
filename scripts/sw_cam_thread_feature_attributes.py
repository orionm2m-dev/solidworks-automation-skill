"""Bounded payload helper for a separately qualified ICWFeature attribute probe.

No COM discovery, QueryInterface, raw pointers, mutation, retry, save, or GTP.
The caller must own the active guarded native session and exact document/IDs.
This helper is NOT evidence that GetFeatureAttributes is live-qualified, that
its payload contains thread depth, or that any field meaning/unit is known.
"""
from __future__ import annotations
import math

MAX_NODES = 4096
MAX_DEPTH = 8
MAX_STRING_CHARACTERS = 16384
MAX_TOTAL_STRING_CHARACTERS = 65536
MAX_BINARY_BYTES = 262144


def bounded_variant_tree(value):
    """Copy only exact built-in scalar/list/tuple results; never introspect objects.

    Type tags describe Python marshalled values, NOT original VARIANT VARTYPE.
    This deliberately does not normalize numeric values or infer their units.
    """
    budget = {"nodes": 0, "string_characters": 0, "binary_bytes": 0}
    active = set()

    def visit(item, depth):
        budget["nodes"] += 1
        if budget["nodes"] > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("Attribute payload exceeds bounded node/depth limit")
        kind = type(item)
        if item is None:
            return {"python_type": "NoneType", "value": None}
        if kind is bool:
            return {"python_type": "bool", "value": item}
        if kind is int:
            if not -(1 << 63) <= item < (1 << 64):
                raise ValueError("Integer outside supported signed/unsigned 64-bit payload")
            return {"python_type": "int", "value": item}
        if kind is float:
            if not math.isfinite(item):
                raise ValueError("Nonfinite attribute value")
            return {"python_type": "float", "value": item}
        if kind is str:
            budget["string_characters"] += len(item)
            if len(item) > MAX_STRING_CHARACTERS or budget["string_characters"] > MAX_TOTAL_STRING_CHARACTERS:
                raise ValueError("Attribute string limit exceeded")
            return {"python_type": "str", "value": item}
        if kind is bytes:
            budget["binary_bytes"] += len(item)
            if budget["binary_bytes"] > MAX_BINARY_BYTES:
                raise ValueError("Attribute binary limit exceeded")
            return {"python_type": "bytes", "encoding": "hex", "value": item.hex()}
        if kind in (list, tuple):
            if len(item) > MAX_NODES - budget["nodes"]:
                raise ValueError("Attribute array length exceeds remaining budget")
            identity = id(item)
            if identity in active:
                raise ValueError("Cyclic attribute payload")
            active.add(identity)
            try:
                return {"python_type": "list" if kind is list else "tuple",
                        "items": [visit(child, depth + 1) for child in item]}
            finally:
                active.remove(identity)
        # Do not stringify, iterate, access .value, or QueryInterface an unknown object.
        raise ValueError("Unsupported marshalled attribute object; no fallback or introspection")

    tree = visit(value, 0)
    return {"tree": tree, "budget_used": budget,
            "native_variant_type_preserved": False,
            "field_semantics_verified": False, "units_verified": False}


def read_feature_attributes(feature, *, read, check, diagnostic):
    """Exactly one guarded GetFeatureAttributes call; caller preserves diagnostics.

    `feature` is already ICWFeature with exact current ID verified by the caller.
    `read` must itself check active event scope before/after the native getter.
    `check` additionally enforces caller identity/state invariants. Exceptions
    propagate so the caller stops; no fallback getter or replay is performed.
    """
    diagnostic.update(stage="attribute_guard", native_call_attempted=False,
                      native_call_returned=False, native_call_succeeded=False,
                      payload_copied=False, total_thread_depth_verified=False,
                      thread_condition_verified=False, mutation_attempted=False)
    check()
    diagnostic["stage"] = "GetFeatureAttributes"
    diagnostic["native_call_attempted"] = True
    raw = read(feature, "GetFeatureAttributes")
    diagnostic["native_call_returned"] = True
    check()
    diagnostic["native_call_succeeded"] = True
    diagnostic["stage"] = "copy_bounded_attribute_payload"
    result = bounded_variant_tree(raw)
    diagnostic["payload_copied"] = True
    diagnostic["stage"] = "attribute_payload_copied_no_semantics_claim"
    return {"status": "review_required", "payload": result,
            "total_thread_depth_verified": False, "thread_condition_verified": False,
            "production_ready": False, "mutation_attempted": False}
