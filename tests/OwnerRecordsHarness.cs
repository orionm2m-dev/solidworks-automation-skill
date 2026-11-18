using System;
using System.Collections.Generic;
using System.Linq;
using System.Web.Script.Serialization;
namespace CadStudio.SolidWorks.AddinHost {
internal class SwAddin {}
internal class OwnerRecordsHarness {
    sealed class Fake : CamTurnRecordRead.IRecordSource {
        internal int N=40, CountCalls=0, Items=0, RapidCalls=0, PointCalls=0, TypeCalls=0;
        internal bool Fail=false, NullItem=false, Nonfinite=false, ChangedCount=false;
        public int Count() {CountCalls++;return N+(ChangedCount && CountCalls>1 ? 1:0);}
        public object Item(int i) {Items++;if(Fail && i==3) throw new System.Runtime.InteropServices.COMException("vendor failure",unchecked((int)0x80040201));return NullItem?null:(object)i;}
        public int Type(object r) {TypeCalls++;return (int)r % 2 == 0 ? 7:35;}
        public int Rapid(object r) {RapidCalls++;return -3;}
        public double[] Point(object r) {PointCalls++;return new double[] {0.1,Nonfinite?Double.NaN:2,3};}
    }
    static readonly List<string> passed = new List<string>();
    static void Check(bool value,string name) {if(!value) throw new Exception(name);passed.Add(name);}
    static Dictionary<string,object> Selection() {return new Dictionary<string,object>{{"operation_native_id",501},{"feature_native_id",301},{"operation_type",7},{"setup_index",0},{"operation_index",0},{"expected_operation_count",1},{"expected_setup_count",1},{"expected_record_count",40}};}
    static bool Reject(Action a) {try {a();return false;}catch {return true;}}
    public static int Main() {
        try {
            var fake=new Fake();int opens=0,paths=0;
            var r=CamTurnRecordRead.Read(40,()=>{opens++;return fake;},()=>{paths++;return 40;});
            Check((string)r["status"]=="observed" && fake.Items==40 && fake.TypeCalls==40 && opens==1 && paths==2,"forty_records_once");
            Check(fake.PointCalls==20 && fake.RapidCalls==20,"goto_only_decoding");
            var rows=(List<Dictionary<string,object>>)r["records"];
            Check((int)rows[0]["rapid_raw"]==-3 && !rows[1].ContainsKey("point_native"),"raw_rapid_unknown_payload_preserved");
            Check(rows.Select(x=>(int)x["index"]).SequenceEqual(Enumerable.Range(0,40)),"original_order");
            fake=new Fake{Fail=true};opens=0;r=CamTurnRecordRead.Read(40,()=>{opens++;return fake;},()=>40);
            Check((string)r["status"]=="error" && (int)r["hresult"]==unchecked((int)0x80040201) && fake.Items==4 && opens==1,"first_hresult_no_retry");
            Check(((List<Dictionary<string,object>>)r["records"]).Count==3 && (string)r["stage"]=="Item" && (int)r["record_index"]==3,"partial_rows_last_stage");
            fake=new Fake{N=41};r=CamTurnRecordRead.Read(40,()=>fake,()=>40);Check((string)r["status"]=="error" && fake.Items==0,"wrong_collection_count_no_items");
            fake=new Fake{NullItem=true};r=CamTurnRecordRead.Read(40,()=>fake,()=>40);Check((string)r["status"]=="error" && fake.Items==1 && fake.TypeCalls==0,"null_record_stop");
            fake=new Fake{Nonfinite=true};r=CamTurnRecordRead.Read(40,()=>fake,()=>40);Check((string)r["status"]=="error" && fake.Items==1,"nonfinite_xyz_stop");
            fake=new Fake{ChangedCount=true};r=CamTurnRecordRead.Read(40,()=>fake,()=>40);Check((string)r["status"]=="error" && (string)r["stage"]=="Count_after","changed_final_count");
            opens=0;r=CamTurnRecordRead.Read(257,()=>{opens++;return new Fake();},()=>257);Check((string)r["status"]=="error" && opens==0,"limit_before_native");
            opens=0;r=CamTurnRecordRead.Read(40,()=>{opens++;return new Fake();},()=>39);Check((string)r["status"]=="error" && opens==0,"wrong_path_count_before_enum");
            r=CamTurnRecordRead.Read(40,()=>{throw new System.Runtime.InteropServices.COMException("failure",unchecked((int)0x80040201));},()=>40);Check((string)r["stage"]=="GetEnumRecords" && (string)r["status"]=="error","enum_failure_no_indexed_fallback");
            var s=Selection();var selected=CamTurnRecordRead.Parse(s);Check(selected.OperationId==501 && selected.RecordCount==40,"generic_ids");
            foreach(var v in new object[]{true,7.0,"7"}) {s=Selection();s["operation_type"]=v;Check(Reject(()=>CamTurnRecordRead.Parse(s)),"strict_type_"+v.GetType().Name);}
            s=Selection();s["extra"]=1;Check(Reject(()=>CamTurnRecordRead.Parse(s)),"unknown_selection_field");
            s=Selection();s["expected_record_count"]=0;Check(Reject(()=>CamTurnRecordRead.Parse(s)),"empty_count_rejected");
            var row=new Dictionary<string,object>{{"native_id",(uint)501},{"setup_index",0},{"operation_index",0},{"turn_operation_type",7},{"linked_feature_ids",new uint[]{301}},{"suppressed",false},{"toolpath_generated",true},{"toolpath_record_counts",new List<int>{40}}};
            var inv=new Dictionary<string,object>{{"operation_count",1},{"operation_setup_count",1},{"operations",new List<Dictionary<string,object>>{row}}};
            CamTurnRecordRead.VerifySelection(inv,selected);Check(true,"actual_row_binding");
            ((List<Dictionary<string,object>>)inv["operations"])[0]["native_id"]=(uint)502;Check(Reject(()=>CamTurnRecordRead.VerifySelection(inv,selected)),"wrong_native_id");
            var request=new Dictionary<string,object>{{"schema_version",1},{"expected_process_id",123},{"expected_document_path",System.IO.Path.Combine(Environment.CurrentDirectory,"fixture.SLDPRT")},{"cam_addin_clsid",CamBatchReader.CamClass},{"max_operations",16},{"max_tools",16},{"record_read",Selection()}};
            var json=new JavaScriptSerializer().Serialize(request);var parsed=CamBatchReader.Parse(json);Check(parsed.RecordRead.OperationId==501,"extended_request_parse");
            var noApp=new JavaScriptSerializer().DeserializeObject(CamBatchReader.Execute(null,1,json)) as Dictionary<string,object>;
            Check((string)noApp["status"]=="error" && (string)noApp["message"]=="HOST_NOT_CONNECTED" && !(bool)noApp["readback_verified"],"no_application_no_com_activation");
            Console.WriteLine(new JavaScriptSerializer().Serialize(new {status="passed",checks=passed.Count,names=passed}));return 0;
        }catch(Exception e){Console.Error.WriteLine(e);return 1;}
    }
}
}
