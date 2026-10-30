"""可移植的纯数据测试夹具；不读取真实会话、CAD 文件或生产凭据。"""
from copy import deepcopy
from pathlib import Path
import sys
from scripts import sw_cam
REPO = Path(sw_cam.__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests'))
IDS=dict(target_feature_native_id=244,target_operation_native_id=247,target_operation_setup_native_id=93,expected_candidate_tool_native_id=263,finish_operation_native_id=248,finish_tool_native_id=249)

def state(generated=False):
    rows=[]
    for i,oid in enumerate((143,144,195,196,247,248)):
        tid=263 if oid==247 else 249 if oid==248 else 300+i
        rows.append(dict(native_id=oid,operation_index=i,setup_index=0,setup_native_id=93,mill_operation_type=1 if oid==248 else 0,
            linked_feature_ids=[244],suppressed=False,toolpath_generated=oid==247 or (oid==248 and generated),
            toolpath_record_counts=[191] if oid==247 else [74] if oid==248 and generated else [],
            assigned_tool=dict(native_id=tid,is_mill_tool=True,native_read_complete=True,tool_type_raw=1,cut_diameter_native=8.,protrusion_native=25.)))
    return dict(document=dict(path=str(Path.cwd()/'synthetic_source.SLDPRT'),title='synthetic_source.SLDPRT',type=1,needs_save=False),
        saved_file_sha256='a'*64,features=[dict(geometry=dict(native_id=220+i)) for i in range(19)],
        feature_setups=[dict(native_id=i) for i in (69,70,71)],operation_setups=[dict(native_id=i) for i in (93,94,95)],
        operations=rows,operation_count=6,operation_counts=[6,0,0])

def payload():
    return dict(rough=dict(candidate=dict(tool=dict(native_id=263)),levels=dict(depth=10.),entry=dict(angle=30.)),
        finish=dict(details=dict(finish={k:dict(raw=v) for k,v in dict(GetPreviousAllowance=.5,SideCutAmt=5.,SideAllow=0.,OverridePrevAllow=False,FinalDepthCut=0.).items()}),
            levels=dict(levels=dict(machining_depth_native=10.)),leads=dict(lead_in=dict(LeadType=dict(raw=1))),
            full_tool=dict(profile='synthetic'),unit_record=dict(unit='mm')))

def arguments():
    return dict(IDS,process_id=1234,expected_document_path=state()['document']['path'],expected_source_sha256='a'*64,
        qualification_only=True,acknowledge_disposable_copy=True,software_only_experiment=True,message_policy='vendor_default',receipt_path=str(Path.cwd()/'synthetic_receipt.json'))
