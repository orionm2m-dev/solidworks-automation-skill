"""Pure exact inventory contract for bounded machine-scope CL export."""
MAX_OPERATIONS = 32
MAX_RECORDS = 100000

def _id(value):
    return type(value) is int and 1 <= value <= 0xFFFFFFFF

def generated_operation_contract(selected_id, selected_counts, ungenerated_ids, generated_operations=None):
    if (not _id(selected_id) or type(selected_counts) is not list
            or not 1 <= len(selected_counts) <= MAX_OPERATIONS
            or any(type(v) is not int or not 0 <= v <= MAX_RECORDS for v in selected_counts)
            or not 1 <= sum(selected_counts) <= MAX_RECORDS):
        raise ValueError("Exact selected generated counts required")
    if (type(ungenerated_ids) is not list or any(not _id(v) for v in ungenerated_ids)
            or len(set(ungenerated_ids)) != len(ungenerated_ids)):
        raise ValueError("Exact unique ungenerated operation IDs required")
    if generated_operations is None:
        result = [dict(operation_native_id=selected_id, toolpath_record_counts=list(selected_counts))]
    else:
        if type(generated_operations) is not list or not 1 <= len(generated_operations) <= MAX_OPERATIONS:
            raise ValueError("Explicit bounded ordered generated operation list required")
        result = []
        for row in generated_operations:
            if type(row) is not dict or set(row) != {"operation_native_id", "toolpath_record_counts"}:
                raise ValueError("Exact generated operation ID/count fields required")
            counts = row["toolpath_record_counts"]
            if (not _id(row["operation_native_id"]) or type(counts) is not list or len(counts) != 1
                    or type(counts[0]) is not int or not 1 <= counts[0] <= MAX_RECORDS):
                raise ValueError("One positive native path count per explicit generated operation required")
            result.append(dict(operation_native_id=row["operation_native_id"],toolpath_record_counts=list(counts)))
    ids = [r["operation_native_id"] for r in result]
    if (len(set(ids)) != len(ids) or set(ids).intersection(ungenerated_ids)
            or len(ids) + len(ungenerated_ids) > MAX_OPERATIONS
            or sum(sum(r["toolpath_record_counts"]) for r in result) > MAX_RECORDS):
        raise ValueError("Duplicate, overlapping or oversized exact operation inventory")
    matches = [r for r in result if r["operation_native_id"] == selected_id]
    if len(matches) != 1 or matches[0]["toolpath_record_counts"] != selected_counts:
        raise ValueError("Selected operation/count differs from explicit generated list")
    return result

def verify_export_operation_inventory(operations, selected_id, selected_counts, ungenerated_ids, generated_operations=None):
    expected = generated_operation_contract(selected_id, selected_counts, ungenerated_ids, generated_operations)
    if type(operations) is not list or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise ValueError("Bounded operation inventory required")
    ids = [r.get("native_id") if type(r) is dict else None for r in operations]
    wanted = {r["operation_native_id"] for r in expected} | set(ungenerated_ids)
    if any(not _id(v) for v in ids) or len(ids) != len(wanted) or set(ids) != wanted:
        raise ValueError("Exact expected MILL operation inventory required")
    generated = []
    for row in operations:
        if row.get("suppressed") is not False:
            raise ValueError("All exported inventory operations must remain unsuppressed")
        if row["native_id"] in ungenerated_ids:
            if row.get("toolpath_generated") is not False or row.get("toolpath_record_counts") != []:
                raise ValueError("Expected unsuppressed sibling is generated or contains paths")
        else:
            if row.get("toolpath_generated") is not True:
                raise ValueError("Expected generated operation is not generated")
            generated.append(dict(operation_native_id=row["native_id"],toolpath_record_counts=row.get("toolpath_record_counts")))
    if generated != expected:
        raise ValueError("Ordered generated operation IDs/counts differ from native inventory")
    return expected
