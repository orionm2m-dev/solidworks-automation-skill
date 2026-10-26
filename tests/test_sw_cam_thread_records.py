"""CL 原始 OUT 顺序、严格边界、事件停止、无写入及完整序列回归。"""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_thread_records as cam
from scripts import sw_cam_events as events

@pytest.fixture
def probe(tmp_path,monkeypatch):
    # 离线 fake-object 回归保留解码逻辑；运行时默认门禁不可由请求解除。
    monkeypatch.setattr(cam,"CL_RECORD_ACCESS_DISABLED",False)
    path=tmp_path/"thread.sldprt";path.write_bytes(b"saved")
    document=dict(path=str(path),title=path.name,type=1,needs_save=False)
    state=dict(on_enter=None,on_exit=None,on_thread=None)
    point=N(GetCoordinates=Mock(return_value=(29.,0.,-20.)))
    records=[N(GetType=Mock(return_value=8),GetSpindleParams=Mock(return_value=(800.,2000.,0.,0,1,30.,"RPM"))),
        N(GetType=Mock(return_value=7),GetRapidLine=Mock(return_value=1),GetToolpathPoint=Mock(return_value=point)),
        N(GetType=Mock(return_value=36)),N(GetType=Mock(return_value=14))]
    def thread():
        if state["on_thread"]:state["on_thread"]()
        return (29.1,0.,-16.1,1.5,.92)
    records[2].GetThreadRecordParams=Mock(side_effect=thread)
    collection=N(Count=4,Item=Mock(side_effect=lambda i:records[i]))
    toolpath=N(RecordCount=4,GetEnumRecords=Mock(return_value=collection),
        GetRecordAtIndex=Mock(side_effect=AssertionError("Indexed native accessor must never be retried")))
    operation=N(native_id=474,IGetEnumToolpaths=Mock(return_value=[toolpath]))
    setup=N(IGetEnumOperations=Mock(return_value=[operation]))
    machine=N(IGetEnumOpSetups=Mock(return_value=[setup]))
    doc=N(GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    app=N();addin=N(GetCWApp=Mock(return_value=app))
    sw=N(GetProcessID=Mock(return_value=26552),GetAddInObject=Mock(return_value=addin))
    inventory=dict(feature_count=9,operation_count=1,operation_setup_count=1,operations=[dict(setup_index=0,
        operation_index=0,turn_operation_type=12,toolpath_generated=True,toolpath_record_counts=[4])])
    forbidden=[Mock(side_effect=AssertionError("No write/GTP/save")) for _ in range(5)]
    operation.GenerateToolpath,app.SaveActiveDocument,app.ActiveDocGTP,toolpath.DeleteAllCLRecords,records[2].SetThreadRecordParams=forbidden
    class Session:
        def __init__(self):
            self.data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,
                callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
        def __enter__(self):
            self.data.update(subscribed=True,active=True)
            if state["on_enter"]:state["on_enter"]()
            return self
        def __exit__(self,*_):
            self.data.update(active=False,disconnected=True)
            if state["on_exit"]:state["on_exit"]()
        def summary(self):return deepcopy(self.data)
    session=Session();factory=Mock(return_value=session)
    def context(*args):
        assert session.data["active"]
        return deepcopy(document),doc,object(),machine,app
    def items(value,_path,read,limit=512):
        assert session.data["active"] and len(value)<=limit
        return list(value)
    def inv(*_):
        assert session.data["active"]
        return deepcopy(inventory)
    monkeypatch.setattr(cam,"_context",context)
    monkeypatch.setattr(cam,"_items",items)
    monkeypatch.setattr(cam,"_inventory",inv)
    monkeypatch.setattr(cam,"_typed",lambda value,*_:value)
    monkeypatch.setattr(cam,"document_snapshot",lambda *_:deepcopy(document))
    monkeypatch.setattr(events,"CamMessageSession",factory)
    def call(**changes):
        values=dict(process_id=26552,expected_document_path=str(path),setup_index=0,operation_index=0,
            expected_operation_native_id=474,max_records=10,message_policy="vendor_default")
        return cam.inspect_thread_records(sw,"clsid","registered/camworks.tlb",**(values|changes))
    return N(**locals())


def test_exact_thread_goto_spindle_out_order_and_unknown_types_are_honest(probe):
    result=probe.call()
    assert result["status"]=="ok" and result["readback_verified"]
    rows=result["paths"][0]["records"]
    assert rows[0]["spindle_direction_raw"]==1 and rows[0]["speed_native"]==800.
    assert rows[1]["point_native"]==[29.,0.,-20.] and rows[1]["rapid_line_raw"]==1
    assert rows[2]["end_native"]==[29.1,0.,-16.1]
    assert rows[2]["pitch_native"]==1.5 and rows[2]["height_native"]==.92
    assert rows[3]["kind"]=="UNDECODED" and not rows[3]["payload_decoded"]
    assert result["record_types"]=={"7":1,"8":1,"14":1,"36":1}
    assert result["thread_record_payloads_complete"] and not result["all_record_payloads_decoded"]
    assert not result["thread_depth_verified"] and not result["length_units_verified"]
    assert not result["handedness_verified"] and not result["post_cleanup_cam_read_performed"]
    assert result["messages"]["disconnected"] and not result["messages"]["active"]
    assert probe.collection.Item.call_args_list==[((0,),),((1,),),((2,),),((3,),)]
    probe.toolpath.GetRecordAtIndex.assert_not_called()
    for method in probe.forbidden:method.assert_not_called()


def test_raw_sequence_digest_changes_for_actual_record_change(probe):
    before=probe.call()["sequence_sha256"]
    probe.records[2].GetThreadRecordParams.side_effect=None
    probe.records[2].GetThreadRecordParams.return_value=(29.,0.,-16.1,1.5,.92)
    after=probe.call()["sequence_sha256"]
    assert before!=after


@pytest.mark.parametrize("field,value",[("process_id",True),("setup_index",1.0),
    ("expected_operation_native_id",0),("max_records",True),("max_records",0),("max_records",100001),
    ("expected_document_path","relative.sldprt"),("message_policy","accept")])
def test_invalid_inputs_stop_before_bootstrap(probe,field,value):
    assert probe.call(**{field:value})["status"]=="error"
    probe.sw.GetAddInObject.assert_not_called();probe.factory.assert_not_called()


def test_wrong_pid_stops_before_cam_bootstrap(probe):
    probe.sw.GetProcessID.return_value=999
    assert probe.call()["status"]=="error"
    probe.sw.GetAddInObject.assert_not_called()


@pytest.mark.parametrize("change",["wrong_id","wrong_type","ungenerated","count_limit","zero_records"])
def test_preconditions_stop_before_any_record_payload(probe,change):
    args={}
    if change=="wrong_id":args["expected_operation_native_id"]=999
    elif change=="wrong_type":probe.inventory["operations"][0]["turn_operation_type"]=3
    elif change=="ungenerated":probe.inventory["operations"][0]["toolpath_generated"]=False
    elif change=="count_limit":args["max_records"]=3
    else:probe.toolpath.RecordCount=0
    assert probe.call(**args)["status"]=="error"
    probe.toolpath.GetRecordAtIndex.assert_not_called()


@pytest.mark.parametrize("result",[(1.,2.),(1.,2.,3.,True,5.),(1.,2.,3.,float("nan"),5.),None])
def test_bad_thread_out_shape_preserves_partial_sequence_and_stops(probe,result):
    probe.records[2].GetThreadRecordParams.side_effect=None;probe.records[2].GetThreadRecordParams.return_value=result
    report=probe.call()
    assert report["status"]=="error" and report["read_count"]==2
    assert report["paths"][0]["records"][-1]["type_raw"]==36
    probe.records[3].GetType.assert_not_called()


@pytest.mark.parametrize("when",["enter","thread","exit"])
def test_event_blocks_next_native_read_and_no_cam_getter_after_disconnect(probe,when):
    def event():probe.session.data["event_count"]=1
    probe.state["on_"+when]=event
    report=probe.call();assert report["status"]=="error" and not report["readback_verified"]
    if when=="enter":probe.machine.IGetEnumOpSetups.assert_not_called()
    if when=="thread":probe.records[3].GetType.assert_not_called()
    assert report["messages"]["disconnected"]


@pytest.mark.parametrize("change",["file","dirty","inventory","record_count"])
def test_changed_state_during_read_is_not_verified(probe,change):
    def changed():
        if change=="file":probe.path.write_bytes(b"changed")
        elif change=="dirty":probe.document["needs_save"]=True
        elif change=="inventory":probe.inventory["feature_count"]=10
        else:probe.toolpath.RecordCount=5
    probe.state["on_thread"]=changed
    report=probe.call();assert report["status"]=="error" and not report["readback_verified"]
    for method in probe.forbidden:method.assert_not_called()


def test_no_thread_records_is_successful_raw_read_not_thread_geometry_proof(probe):
    probe.records[2].GetType.return_value=14
    report=probe.call()
    assert report["status"]=="ok" and report["thread_record_count"]==0
    assert not report["thread_record_payloads_complete"] and not report["thread_depth_verified"]


@pytest.mark.parametrize("count",[3,5,-1,True])
def test_collection_count_mismatch_blocks_all_item_reads(probe,count):
    probe.collection.Count=count
    result=probe.call()
    assert result["status"]=="error" and result["read_count"]==0
    probe.collection.Item.assert_not_called()
    probe.toolpath.GetRecordAtIndex.assert_not_called()


def test_collection_item_event_stops_without_decoding_or_fallback(probe):
    def item(index):
        probe.session.data["event_count"]=1
        return probe.records[index]
    probe.collection.Item.side_effect=item
    result=probe.call()
    assert result["status"]=="error" and result["read_count"]==0
    probe.records[0].GetType.assert_not_called()
    probe.toolpath.GetRecordAtIndex.assert_not_called()


def test_collection_count_change_during_read_is_rejected(probe):
    probe.state["on_thread"]=lambda:setattr(probe.collection,"Count",5)
    assert probe.call()["status"]=="error"


def test_units_and_feedrate_exact_out_contracts_preserve_raw_values(probe):
    probe.records[0]=N(GetType=Mock(return_value=24),GetUnitParams=Mock(return_value="MM"))
    probe.records[1]=N(GetType=Mock(return_value=29),GetFeedrateParams=Mock(return_value=(1.5,1)))
    result=probe.call()
    assert result["status"]=="ok" and result["unit_strings_raw"]==["MM"]
    assert result["feedrate_records"][0]["value_native"]==1.5
    assert result["feedrate_records"][0]["is_metric_raw"]==1
    assert not result["length_units_verified"]


@pytest.mark.parametrize("kind,value",[(24,None),(24,["MM"]),(24,"x"*1001),
    (29,(1.5,True)),(29,(1.5,)),(29,(float("inf"),1))])
def test_malformed_units_feedrate_fail_without_later_native_reads(probe,kind,value):
    record=N(GetType=Mock(return_value=kind))
    setattr(record,"GetUnitParams" if kind==24 else "GetFeedrateParams",Mock(return_value=value))
    probe.records[0]=record
    result=probe.call()
    assert result["status"]=="error" and result["read_count"]==0
    probe.records[1].GetType.assert_not_called()


def test_default_runtime_block_precedes_all_native_access(tmp_path,monkeypatch):
    monkeypatch.setattr(cam,"CL_RECORD_ACCESS_DISABLED",True)
    sw=Mock(side_effect=AssertionError("No native accessor allowed"))
    sw.GetAddInObject=Mock(side_effect=AssertionError("No native accessor allowed"))
    sw.GetProcessID=Mock(side_effect=AssertionError("No native accessor allowed"))
    result=cam.inspect_thread_records(sw,"clsid","camworks.tlb",process_id=1,expected_document_path=str(tmp_path/"part.sldprt"),
        setup_index=0,operation_index=0,expected_operation_native_id=474)
    assert result["status"]=="blocked" and not result["readback_verified"]
    sw.GetAddInObject.assert_not_called();sw.GetProcessID.assert_not_called()
