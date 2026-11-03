"""Bounded read-only TURN feature recipe metadata; no profile, NC or setter calls."""
from __future__ import annotations

from pathlib import Path
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_operation_profile import _integer, _number, _values
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _catalog, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target


class RecipeInspectionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(value, code):
    if not value:
        raise RecipeInspectionError(code)


def _strict_int(value, low, high, code):
    _require(type(value) is int and low <= value <= high, code)
    return value


def _text(value, limit, code):
    _require(type(value) is str and 1 <= len(value) <= limit, code)
    return value


def _catalog_ids(turn, requested, read):
    catalog = _catalog(turn, requested, read)
    _require(catalog["names_resolved"] and bool(catalog["names"]), "CATALOG_NAMES_UNRESOLVED")
    _require(requested is None or requested in catalog["names"], "REQUESTED_ATTRIBUTE_ABSENT")
    rows = []
    for name in catalog["names"]:
        value = catalog["requested_id"] if name == requested else read(turn, "GetTdbIdForAttribute", name)
        rows.append({"name": name, "native_id": _strict_int(value, 0, 2147483647, "CATALOG_ID_INVALID")})
    ids = {row["native_id"] for row in rows}
    aliases = [{"native_id": value, "names": [row["name"] for row in rows if row["native_id"] == value]}
               for value in sorted(ids) if sum(row["native_id"] == value for row in rows) > 1]
    return {**catalog, "attributes": rows, "native_ids_unique": not aliases, "id_aliases": aliases,
            "apply_eligible": False, "lookup_has_native_success_flag": False,
            "database_row_id_mapping_qualified": False}


def _capture(sw, clsid, typelib_path, config, report):
    diagnostic = {"phase": "capture", "features": [], "operations": []}
    report["snapshots"].append(diagnostic)

    def read(obj, name, *args):
        diagnostic["stage"] = name
        report["guarded_member_reads"] += 1
        return _member(obj, name, *args)

    def owner():
        _require(_integer(read(sw, "GetProcessID")) == config["process_id"], "PROCESS_MISMATCH")

    owner()
    initial_document = document_snapshot(sw)
    _require(initial_document is not None, "DOCUMENT_ABSENT")
    check_document_target(initial_document["path"], initial_document["title"],
                          expected_path=config["expected_document_path"], required=True)
    _require(initial_document["type"] == 1 and initial_document["needs_save"] is False, "CLEAN_PART_REQUIRED")
    _require(_file_hash(initial_document["path"]) == config["expected_source_sha256"], "SOURCE_HASH_MISMATCH")
    before, doc, _part, machine, app = _context(sw, clsid, typelib_path, read)
    _require(before == initial_document, "DOCUMENT_CHANGED_DURING_CONTEXT")
    diagnostic["document"] = before
    limits = dict(max_features=config["max_features"], max_operations=config["max_operations"], max_setups=64)
    inventory = _inventory(machine, typelib_path, read, **limits)
    diagnostic["inventory"] = inventory
    features, operations = diagnostic["features"], diagnostic["operations"]
    selected = None
    for si, raw_setup in enumerate(_items(read(machine, "IGetEnumSetups"), typelib_path, read, limit=64)):
        setup = _typed(raw_setup, "ICWBaseSetup", typelib_path)
        for raw in _items(read(setup, "IGetEnumFeatures"), typelib_path, read,
                          limit=config["max_features"] - len(features)):
            feature_id = _object_id(doc, raw, read)
            turn = _typed(raw, "ICWTurnFeature", typelib_path)
            kind = _integer(read(turn, "GetTurnFeatureType"))
            features.append(dict(setup_index=si, native_id=feature_id, turn_feature_type_raw=kind))
            if feature_id == config["expected_feature_native_id"]:
                _require(selected is None and si == config["feature_setup_index"], "TARGET_FEATURE_ID_OR_SETUP_AMBIGUOUS")
                _require(kind == config["expected_turn_feature_type"], "TARGET_FEATURE_TYPE_MISMATCH")
                selected = turn
    feature_ids = {row["native_id"] for row in features}
    _require(len(feature_ids) == len(features), "DUPLICATE_FEATURE_IDS")
    _require(selected is not None, "EXACT_FEATURE_NOT_FOUND")
    _require(len(features) == inventory["feature_count"], "FEATURE_INVENTORY_CHANGED")
    for si, count in enumerate(inventory["feature_counts_by_setup"]):
        _require(sum(row["setup_index"] == si for row in features) == count, "FEATURE_SETUP_COUNTS_CHANGED")
    for si, raw_setup in enumerate(_items(read(machine, "IGetEnumOpSetups"), typelib_path, read, limit=64)):
        setup = _typed(raw_setup, "ICWBaseOpSetup", typelib_path)
        for oi, raw in enumerate(_items(read(setup, "IGetEnumOperations"), typelib_path, read,
                                       limit=config["max_operations"] - len(operations))):
            op = _typed(raw, "ICWOperation", typelib_path)
            turn = _typed(raw, "ICWTurnOperation", typelib_path)
            linked = _items(read(op, "IGetAllFeatures"), typelib_path, read, limit=config["max_features"])
            ids = [_object_id(doc, item, read) for item in linked]
            _require(len(set(ids)) == len(ids) and set(ids) <= feature_ids, "INVALID_OPERATION_FEATURE_LINKS")
            operations.append(dict(setup_index=si, operation_index=oi, native_id=_object_id(doc, op, read),
                turn_operation_type=_integer(read(turn, "OpernType")), linked_feature_ids=ids))
    _require(len({row["native_id"] for row in operations}) == len(operations), "DUPLICATE_OPERATION_IDS")
    positions = {(row["setup_index"], row["operation_index"]): row for row in inventory["operations"]}
    _require(len(positions) == len(operations) == inventory["operation_count"], "OPERATION_INVENTORY_CHANGED")
    for row in operations:
        observed = positions.get((row["setup_index"], row["operation_index"]))
        _require(observed is not None and observed["turn_operation_type"] == row["turn_operation_type"], "OPERATION_TYPE_CHANGED")
    catalog = _catalog_ids(selected, config["attribute_name"], read)
    diagnostic["catalog"] = catalog
    current = dict(native_id=_strict_int(read(selected, "Attribute"), 0, 2147483647, "CURRENT_ATTRIBUTE_ID_INVALID"),
                   name=_text(read(selected, "GetAttributeName"), 1000, "CURRENT_ATTRIBUTE_NAME_INVALID"))
    matching = [row for row in catalog["attributes"] if row["name"] == current["name"]]
    _require(len(matching) == 1, "CURRENT_ATTRIBUTE_NAME_ABSENT")
    current_lookup_id = matching[0]["native_id"]
    spindle = _integer(read(selected, "GetSpindleType"))
    diameters = dict(zip(("minimum", "maximum"),
                         map(_number, _values(read(selected, "GetMinMaxDiameter"), 2))))
    stock = _typed(read(machine, "IGetWorkpiece"), "ICWTurnWorkpiece", typelib_path)
    stock_attribute = _integer(read(stock, "GetAttribute"))
    techdb = _text(read(app, "IGetTechDBPath"), 32767, "TECHDB_PATH_INVALID")
    state = dict(document=before, source_sha256=config["expected_source_sha256"], inventory=inventory,
                 features=features, operations=operations, current_attribute=current, catalog=catalog,
                 current_name_in_catalog=True, current_attribute_lookup_id_raw=current_lookup_id,
                 current_id_matches_lookup=current["native_id"] == current_lookup_id,
                 current_attribute_id_mapping_qualified=False, apply_eligible=False,
                 selected_feature_native_id=config["expected_feature_native_id"],
                 feature_spindle_type_raw=spindle, feature_diameters_native=diameters,
                 diameter_source="ICWTurnFeature.GetMinMaxDiameter", diameter_units_qualified=False,
                 stock_attribute_raw=stock_attribute,
                 stock_attribute_source="ICWTurnWorkpiece.GetAttribute",
                 spindle_source="ICWTurnFeature.GetSpindleType",
                 techdb_path_raw=techdb, techdb_path_source="ICWApp4.IGetTechDBPath",
                 database_condition_mapping_qualified=False)
    diagnostic.update(current_attribute=current, feature_spindle_type_raw=spindle,
                      stock_attribute_raw=stock_attribute, feature_diameters_native=diameters, techdb_path_raw=techdb)
    owner()
    _require(document_snapshot(sw) == before, "DOCUMENT_CHANGED_DURING_INSPECTION")
    _require(_file_hash(before["path"]) == config["expected_source_sha256"], "SOURCE_CHANGED_DURING_INSPECTION")
    diagnostic["stage"] = "complete"
    return state


def inspect_turn_feature_recipe(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, feature_setup_index, expected_feature_native_id,
        expected_turn_feature_type, attribute_name=None, max_features=64, max_operations=64):
    """Observe one exact TURN recipe twice; return raw identities without changing CAM."""
    report = dict(scope="TURN_FEATURE_RECIPE_METADATA_V1", status="error", phase="preflight",
                  read_only=True, mutation_attempted=False, generation_attempted=False, model_saved=False,
                  readback_verified=False, persistence_verified=False, native_recipe_qualified=False,
                  apply_eligible=False, current_attribute_id_mapping_qualified=False,
                  profiles_read=False, NC_parameters_read=False, TechDB_modified=False,
                  full_model_geometry_verified=False,
                  document_verification_scope="path_title_type_dirty_flag_snapshot",
                  guarded_member_reads=0, snapshots=[])
    try:
        for name, value, low, high in (
            ("process_id", process_id, 1, 2**31-1), ("feature_setup_index", feature_setup_index, 0, 63),
            ("expected_feature_native_id", expected_feature_native_id, 1, 4294967295),
            ("expected_turn_feature_type", expected_turn_feature_type, 0, 2147483647),
            ("max_features", max_features, 1, 64), ("max_operations", max_operations, 1, 64)):
            _strict_int(value, low, high, "INVALID_" + name.upper())
        _require(type(expected_document_path) is str and absolute_document_path(expected_document_path)
                 and Path(expected_document_path).suffix.casefold() == ".sldprt", "EXACT_SAVED_PART_PATH_REQUIRED")
        _require(type(expected_source_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256), "EXACT_SOURCE_SHA256_REQUIRED")
        if attribute_name is not None:
            _text(attribute_name, 1000, "ATTRIBUTE_NAME_INVALID")
        config = dict(process_id=process_id, expected_document_path=expected_document_path,
                      expected_source_sha256=expected_source_sha256, feature_setup_index=feature_setup_index,
                      expected_feature_native_id=expected_feature_native_id,
                      expected_turn_feature_type=expected_turn_feature_type, attribute_name=attribute_name,
                      max_features=max_features, max_operations=max_operations)
        report["request"] = config
        report["phase"] = "before"
        before = _capture(sw, clsid, typelib_path, config, report)
        report["before"] = before
        report["phase"] = "after"
        after = _capture(sw, clsid, typelib_path, config, report)
        report["after"] = after
        _require(after == before, "RECIPE_METADATA_CHANGED")
        report.update(status="ok", phase="inspected", readback_verified=True,
                      catalog=after["catalog"], current_attribute=after["current_attribute"],
                      current_name_in_catalog=after["current_name_in_catalog"],
                      current_attribute_lookup_id_raw=after["current_attribute_lookup_id_raw"],
                      current_id_matches_lookup=after["current_id_matches_lookup"],
                      feature_spindle_type_raw=after["feature_spindle_type_raw"],
                      feature_diameters_native=after["feature_diameters_native"],
                      stock_attribute_raw=after["stock_attribute_raw"], techdb_path_raw=after["techdb_path_raw"],
                      linked_operations=[row for row in after["operations"]
                          if expected_feature_native_id in row["linked_feature_ids"]],
                      document_unchanged=True, saved_file_unchanged=True, inventory_unchanged=True)
    except Exception as exc:
        report["issue"] = _error(exc)
    return report
