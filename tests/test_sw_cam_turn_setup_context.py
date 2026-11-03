"""Real two-capture setup traversal with synthetic native-shaped objects."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_sw_cam_turn_variable_allowance import env
from test_sw_cam_turn_bore_options import bore
from scripts import sw_cam_turn_variable_allowance as common
from scripts import sw_cam_turn_setup_context as setup_reader
from scripts import sw_cam_operation_profile as profile


@pytest.fixture(params=[5,6])
def current(bore,request,monkeypatch):
    e=bore
    e["operation"]["OpernType"]=request.param
    e["args"]["expected_operation_type"]=request.param
    e["inventory"].update(feature_setup_count=1,feature_counts_by_setup=[1],operations=[
        dict(setup_index=0,operation_index=0,turn_operation_type=request.param,toolpath_generated=True,toolpath_record_counts=[12])])
    counts=dict(expected_feature_count=1,expected_operation_count=1,expected_feature_setup_count=1,
        expected_operation_setup_count=1,expected_generated_operation_count=1,expected_toolpath_record_count=12)
    e["args"].update(counts)
    unknown="{11111111-1111-1111-1111-111111111111}"
    def metadata_object(guid):
        attr=SimpleNamespace(guid=guid,typekind=4,cFuncs=7)
        info={"GetTypeAttr":lambda:attr}
        return {"GetTypeInfo":lambda index:info},attr
    point,point_attr=metadata_object(setup_reader._INTERFACES["ICWPosition"])
    point["GetCoordinates"]=(1.,2.,3.)
    outputs=[metadata_object(unknown)[0] for _ in range(4)]
    transforms=[];data_getters=[]
    for number in range(2):
        value,attr=metadata_object(setup_reader._INTERFACES["ICWTransform"])
        data=Mock(return_value=tuple(outputs)+(1.,False));value["GetData"]=data
        transforms.append(value);data_getters.append(data)
    fsetup={"native_id":100,"QueryInterface":lambda iid:"feature_identity",
        "IGetEnumFeatures":e["collection"]([e["feature"]]),"Axis":(0.,0.,1.),"IsReverseDirection":False,
        "IGetRefPoint":lambda:point,"IGetXYTransform":lambda:transforms[0]}
    e["setup"].update(native_id=200,GetSetup=lambda:fsetup,Axis=(0.,0.,1.),
        GetSetupOriginInFCSSpace=(0.,0.,8.),IGetXYTransform=lambda:transforms[1])
    e["machine"]["IGetEnumSetups"]=e["collection"]([fsetup])
    monkeypatch.setattr(setup_reader,"_typed",lambda obj,*args:obj)
    monkeypatch.setattr(profile,"_typed",lambda obj,*args:obj)
    monkeypatch.setattr(setup_reader,"_object_id",lambda doc,obj,read:read(obj,"native_id"))
    monkeypatch.setattr(setup_reader,"_items",common._items)
    monkeypatch.setattr(setup_reader,"setup_abi",lambda path:dict(native_calls=0))
    e.update(feature_setup=fsetup,point=point,point_attr=point_attr,outputs=outputs,transforms=transforms,data_getters=data_getters)
    e["run"]=lambda **kw:setup_reader.inspect_turn_setup_context(e["sw"],"clsid","fixture.tlb",**dict(e["args"],**kw))
    return e


def test_two_complete_setup_captures_link_by_native_id_without_matrix(current):
    r=current["run"]()
    assert r["status"]=="ok" and r["readback_verified"] and r["before"]==r["after"]
    assert r["inspection_scope"]=="turn_setup_context"
    q=r["before"]["setup_context"];s=q["selected_setup"]
    assert q["complete"] and q["setup_native_ids_discovered"]
    assert q["feature_setups"]==[dict(index=0,native_id=100,feature_native_ids=[11])]
    assert q["operation_setups"][0]["feature_setup_native_id"]==100
    assert q["operation_setups"][0]["feature_setup_canonical_identity_equal"] is True
    assert s["operation_setup_native_id"]==200 and s["feature_setup_native_id"]==100
    assert s["reference_point_native"]==[1.,2.,3.] and s["origin_in_fcs_native"]==[0.,0.,8.]
    assert s["is_reverse_direction"] is False
    for name in ("feature_xy_transform","operation_xy_transform"):
        transform=s[name]
        assert transform["GetData_called"] and not transform["decoded"] and not transform["output_coordinates_read"]
        assert transform["scale_raw"]==1. and transform["rotate_raw"] is False
        assert set(transform["output_types"])=={"x_axis","y_axis","z_axis","translation"}
        assert len({x["guid"] for x in transform["output_types"].values()})==1
    assert current["calls"].count("GetCoordinates")==2  # only reference point, never transform outputs
    assert current["calls"].count("inventory")==4
    assert all(g.call_count==2 for g in current["data_getters"])
    assert not set(current["calls"]) & {"IGetTool","profile","IGetAllDefaultOperations","GetAllVariableAllowances",
        "GetAllowanceMethodVariable","SetData","InsertTurnSetup1","GenerateToolpath","Save"}
    assert not any(r[k] for k in ("mutation_attempted","GTP_attempted","GOP_attempted","model_saved","CL_read_attempted","production_qualified"))
    assert not q["coordinate_frame_verified"] and not q["units_verified"]
    assert r["messages"]["disconnected"] and not r["messages"]["active"]


@pytest.mark.parametrize("field,value", [("expected_feature_count",True),("expected_operation_count",0),
    ("expected_feature_setup_count",65),("expected_operation_setup_count",0),("expected_generated_operation_count",2),
    ("expected_toolpath_record_count",12.),("expected_feature_setup_native_id",True),
    ("expected_operation_setup_native_id",0),("expected_process_create_time",None),
    ("expected_operation_type",4),("expected_operation_type",7),("expected_operation_native_id",None),
    ("expected_linked_feature_ids",[]),("expected_source_sha256","invalid"),("action","identify"),("action","apply")])
def test_invalid_request_stops_before_application(current,field,value):
    r=current["run"](**{field:value})
    assert r["status"]=="error" and not current["calls"]


@pytest.mark.parametrize("field", list(setup_reader._COUNTS))
def test_exact_count_drift_blocks_before_frame(current,field):
    changed=current["args"][field]+1
    # Use a valid but mismatching generated expectation.
    if field=="expected_generated_operation_count":changed=0
    r=current["run"](**{field:changed})
    assert r["status"]=="error" and "GetSetup" not in current["calls"]
    assert not any(g.called for g in current["data_getters"])


def test_explicit_setup_ids_are_checked(current):
    r=current["run"](expected_feature_setup_native_id=100,expected_operation_setup_native_id=200)
    assert r["status"]=="ok" and not r["before"]["setup_context"]["setup_native_ids_discovered"]


@pytest.mark.parametrize("field",setup_reader._SETUP_IDS)
def test_wrong_setup_id_prevents_frame_read(current,field):
    r=current["run"](**{field:999})
    assert r["status"]=="error" and "Axis" not in current["calls"]


def test_getsetup_native_link_cannot_be_guessed_from_index(current):
    wrong=dict(current["feature_setup"],native_id=999)
    current["setup"]["GetSetup"]=lambda:wrong
    r=current["run"]()
    assert r["status"]=="error" and "Axis" not in current["calls"]


def test_canonical_inequality_is_reported_without_equating_views(current):
    view=dict(current["feature_setup"],QueryInterface=lambda iid:"different_view")
    current["setup"]["GetSetup"]=lambda:view
    r=current["run"]()
    assert r["status"]=="ok"
    assert r["before"]["setup_context"]["operation_setups"][0]["feature_setup_canonical_identity_equal"] is False


@pytest.mark.parametrize("getter",["GetSetup","QueryInterface","Axis","IsReverseDirection","GetSetupOriginInFCSSpace",
    "IGetRefPoint","GetCoordinates","IGetXYTransform","GetTypeInfo","GetTypeAttr","GetData"])
def test_event_stops_at_exact_getter(current,getter):
    def hook(name):
        if name==getter:current["session"].state["event_count"]=1
    current["hook"]=hook
    r=current["run"]()
    assert r["status"]=="error" and current["calls"][-1]==getter and current["calls"].count(getter)==1
    assert not r["readback_verified"] and "after" not in r


@pytest.mark.parametrize("fault",["reverse","origin","axis","point_type","transform_type","data_shape","scale","rotate","null_output","output_metadata"])
def test_invalid_frame_or_metadata_stops_without_fallback(current,fault):
    if fault=="reverse":current["feature_setup"]["IsReverseDirection"]=1
    elif fault=="origin":current["setup"]["GetSetupOriginInFCSSpace"]=(0.,float("nan"),0.)
    elif fault=="axis":current["feature_setup"]["Axis"]=(True,0.,1.)
    elif fault=="point_type":current["point_attr"].guid="{11111111-1111-1111-1111-111111111111}"
    elif fault=="transform_type":current["transforms"][0]["GetTypeInfo"]=current["outputs"][0]["GetTypeInfo"]
    elif fault=="data_shape":current["data_getters"][0].return_value=()
    elif fault=="scale":current["data_getters"][0].return_value=tuple(current["outputs"])+(float("inf"),False)
    elif fault=="rotate":current["data_getters"][0].return_value=tuple(current["outputs"])+(1.,0)
    elif fault=="null_output":current["data_getters"][0].return_value=(None,)+tuple(current["outputs"][1:])+(1.,False)
    else:current["outputs"][0]["GetTypeInfo"]=lambda i:None
    r=current["run"]()
    assert r["status"]=="error" and not r["readback_verified"] and "after" not in r
    assert not r["before"]["capture_complete"]


@pytest.mark.parametrize("change",["reverse","origin","metadata"])
def test_second_capture_detects_changed_frame_or_metadata(current,change):
    def hook(name):
        if name=="GetData" and current["calls"].count(name)==2:
            if change=="reverse":current["feature_setup"]["IsReverseDirection"]=True
            elif change=="origin":current["setup"]["GetSetupOriginInFCSSpace"]=(0.,0.,9.)
            else:current["transforms"][0]["GetData"]=Mock(return_value=tuple(current["outputs"])+(2.,False))
    current["hook"]=hook
    r=current["run"]()
    assert r["status"]=="error" and not r["readback_verified"]
    assert r["before"]["capture_complete"] and r["after"]["capture_complete"]


@pytest.mark.parametrize("change",["source","process","inventory","dirty"])
def test_boundary_pins_remain_active_during_frame_read(current,change):
    def hook(name):
        if name=="GetData":
            if change=="source":current["digest"]="b"*64
            elif change=="process":current["process"]["create_time"]+=1
            elif change=="inventory":current["inventory"]["operation_count"]+=1
            else:current["dirty"]=True
    current["hook"]=hook
    r=current["run"]()
    assert r["status"]=="error" and "after" not in r
    assert not r["before"]["capture_complete"]


def test_setup_abi_failure_precedes_native(current,monkeypatch):
    fn=Mock(side_effect=ValueError("Changed setup ABI"));monkeypatch.setattr(setup_reader,"setup_abi",fn)
    r=current["run"]();assert r["status"]=="error" and not current["calls"]


def metadata_interfaces():
    from ctypes import HRESULT, POINTER, c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch, VARIANT
    dispatch=POINTER(IDispatch)
    rows=[
        ("ICWBaseSetup","_get_Axis",5,(POINTER(VARIANT),),(10,),True),
        ("ICWBaseSetup","IsReverseDirection",10,(POINTER(VARIANT_BOOL),),(10,),False),
        ("ICWBaseSetup","IGetRefPoint",6,(POINTER(dispatch),),(10,),False),
        ("ICWBaseSetup","IGetXYTransform",7,(POINTER(dispatch),),(10,),False),
        ("ICWBaseOpSetup","_get_Axis",2,(POINTER(VARIANT),),(10,),True),
        ("ICWBaseOpSetup","GetSetup",30,(POINTER(dispatch),),(10,),False),
        ("ICWBaseOpSetup","GetSetupOriginInFCSSpace",13,(POINTER(c_double),)*3,(2,)*3,False),
        ("ICWBaseOpSetup","IGetXYTransform",18,(POINTER(dispatch),),(10,),False),
        ("ICWTransform","GetData",3,(POINTER(dispatch),)*4+(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,)*6,False),
        ("ICWPosition","GetCoordinates",1,(POINTER(c_double),)*3,(2,)*3,False)]
    result={}
    for owner,name,dispid,args,flags,prop in rows:
        interface=result.setdefault(owner,SimpleNamespace(_iid_=setup_reader._INTERFACES[owner],_methods_=[]))
        interface._methods_.append(SimpleNamespace(name=name,restype=HRESULT,
            idlflags=(dispid,"propget") if prop else (dispid,),argtypes=args,
            paramflags=tuple((flag,"value") for flag in flags)))
    return result


def test_exact_typed_setup_contract_is_metadata_only(monkeypatch):
    from scripts import sw_cam_comtypes as bridge
    interfaces=metadata_interfaces()
    monkeypatch.setattr(bridge,"_load_type_library",lambda path:SimpleNamespace(**interfaces))
    r=setup_reader.setup_abi("fixture")
    assert r["native_calls"]==0 and len(r["methods"])==10
    assert next(x for x in r["methods"] if x["interface"]=="ICWTransform")["iid"]=="{9DA5A2DD-7E9A-4D87-BEB7-848B3BECF9F8}"
    interfaces["ICWTransform"]._iid_="{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(ValueError):setup_reader.setup_abi("fixture")


@pytest.mark.parametrize("owner,name",[("ICWBaseSetup","IsReverseDirection"),("ICWBaseOpSetup","GetSetup"),
    ("ICWBaseOpSetup","GetSetupOriginInFCSSpace"),("ICWTransform","GetData")])
@pytest.mark.parametrize("fault",["dispid","flags","args","return_type","duplicate"])
def test_altered_setup_abi_is_rejected_before_dispatch(monkeypatch,owner,name,fault):
    from ctypes import c_int
    interfaces=metadata_interfaces();interface=interfaces[owner]
    member=next(x for x in interface._methods_ if x.name==name)
    if fault=="dispid":member.idlflags=(999,)
    elif fault=="flags":member.paramflags=((1,"value"),)*len(member.argtypes)
    elif fault=="args":member.argtypes=(c_int,)
    elif fault=="return_type":member.restype=c_int
    else:interface._methods_.append(member)
    monkeypatch.setattr(setup_reader,"_interface_class",lambda name,path:interfaces[name])
    with pytest.raises(ValueError):setup_reader.setup_abi("fixture")


def test_repeated_setup_enumeration_must_match_pinned_selected_operation(current):
    original=current["setup"]["IGetEnumOperations"]
    other=dict(current["operation"],native_id=999)
    contradictory=current["collection"]([other])
    # The same contradiction in both captures would otherwise compare equal.
    current["setup"]["IGetEnumOperations"]=Mock(side_effect=[original,contradictory,original,contradictory])
    r=current["run"]()
    assert r["status"]=="error" and not r["readback_verified"]
    assert r["before"]["selected_operation"]["native_id"]==22
    assert "Axis" not in current["calls"] and "after" not in r
