from copy import deepcopy
import pytest
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
from scripts import sw_cam_circular_reconfigure as writer


def fixture_stream(*, target_feed=100, extra_target=False, first_feed=100, duplicate_last=False):
    lines=["UNITS/ MM", "BOX/ 0,0,0,100,100,100", "CUTTER/ 8,0,4,0,0,0,64,", "TLAXIS/ 0,0,1"]
    for i in range(3):
        if i:lines.extend(["CUTTER/ 8,0,4,0,0,0,64,", "TLAXIS/ 0,0,1"])
        x=0 if i==0 or (i==2 and duplicate_last) else i*10
        rate=first_feed if i==0 else target_feed if i==1 else 100
        lines.extend([f"OPFEATSTART/part-{i}", f"FEDRAT/ MMPM,{rate}", f"GOTO/ {x},0,1", f"GOTO/ {x+1},0,1"])
        if i==1 and extra_target:lines.append(f"GOTO/ {x+2},0,1")
        lines.append(f"OPFEATEND/part-{i}")
    lines.append("FINI")
    counts=[3,4 if extra_target else 3,3]
    parsed=parse_generic_cl_bytes(("\n".join(lines)+"\n").encode("ascii"), expected_block_record_counts=counts)
    assert parsed["parse_complete"] and parsed["native_count_matches"]
    rows=[dict(operation_native_id=oid,toolpath_record_counts=[count]) for oid,count in zip([11,22,33],counts)]
    return parsed,rows


def compare(before,after,oid=22):
    return writer.compare_replacement_cl(before[0],after[0],before[1],after[1],oid)


def test_selected_middle_replacement_preserves_shifted_later_stream():
    before=fixture_stream();after=fixture_stream(target_feed=150,extra_target=True)
    result=compare(before,after)
    assert result["protected_complete_streams_verified"] is True
    assert result["protected_operation_native_ids"]==[11,33]
    assert result["protected_block_count"]==2 and result["replaced_block_index"]==1
    assert result["world_geometry_verified"] is False and result["production_qualified"] is False


def test_protected_feed_change_rejected():
    with pytest.raises(ValueError, match="Protected"):
        compare(fixture_stream(),fixture_stream(first_feed=101,target_feed=150))


def test_ambiguous_protected_stream_rejected():
    with pytest.raises(ValueError, match="ambiguous"):
        compare(fixture_stream(),fixture_stream(target_feed=150,duplicate_last=True))


@pytest.mark.parametrize("mutation", ["order","duplicate","missing_target"])
def test_native_identity_context_cannot_be_relabelled(mutation):
    before=fixture_stream();after=fixture_stream(target_feed=150)
    if mutation=="order":after[1].reverse()
    elif mutation=="duplicate":after[1][2]["operation_native_id"]=11
    else:
        before[1][1]["operation_native_id"]=44
        after[1][1]["operation_native_id"]=44
    with pytest.raises(ValueError, match="inventory"):
        compare(before,after)


@pytest.mark.parametrize("field,value", [("parse_complete",False),("native_count_matches",False),("declared_units",["INCH"])])
def test_unqualified_parse_rejected(field,value):
    before=fixture_stream();after=fixture_stream(target_feed=150);after[0][field]=value
    with pytest.raises(ValueError, match="CL"):
        compare(before,after)


def test_stock_declaration_cannot_change():
    before=fixture_stream();after=fixture_stream(target_feed=150)
    next(c for c in after[0]["commands"] if c["name"]=="BOX")["raw"]="BOX/ 0,0,0,200,100,100"
    with pytest.raises(ValueError, match="stock"):
        compare(before,after)


def test_wrong_supplied_record_context_rejected_even_with_true_parse_flags():
    before=fixture_stream();after=fixture_stream(target_feed=150,extra_target=True)
    after[1][1]["toolpath_record_counts"]=[999]
    with pytest.raises(ValueError):compare(before,after)


def test_boolean_id_not_accepted_as_native_identity():
    before=fixture_stream();after=fixture_stream(target_feed=150)
    before[1][0]["operation_native_id"]=True;after[1][0]["operation_native_id"]=True
    with pytest.raises(ValueError):compare(before,after)
