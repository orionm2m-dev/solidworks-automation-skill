using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using CamWorks.Interop;
using SolidWorks.Interop.sldworks;
namespace CadStudio.SolidWorks.AddinHost {
[ComVisible(true), Guid("63CD9668-1A04-4D45-AC42-AD484D30F9EB"), InterfaceType(ComInterfaceType.InterfaceIsDual)]
public interface ICamTurnBoreBuilder { [DispId(1)] string QualifyCreateBoundTurnBore(string requestJson); }
[ComVisible(false)]
internal static class CamTurnBoreBuilder {
    internal const string Scope = "TURN_OWNER_STA_BORE_QUALIFICATION_V1";
    internal const string Engine = "turn-bore-builder-1";
    static readonly string[] Fields = {"schema_version","expected_process_id","expected_process_creation_time","expected_document_path","expected_source_sha256","protected_document_path","protected_source_sha256","protected_part_pins","qualification_root","expected_sw_configuration","expected_cam_configuration","expected_inventory","expected_tools","selected_tool_id","feature_id","anchor_id","default_name","default_id","max_tools","native_receipt_path","expected_host_module_version_id"};
    internal sealed class Request {
        internal int ProcessId, ToolId, FeatureId, AnchorId, DefaultId, MaxTools;
        internal double ProcessCreated;
        internal string CopyPath, CopySha, ProtectedPath, ProtectedSha, Root, SwConfig, CamConfig, DefaultName, ReceiptPath, Mvid;
        internal Dictionary<string,object> Inventory;
        internal object[] Tools, ProtectedParts;
        internal string Marker { get { return Path.Combine(Path.GetDirectoryName(CopyPath), "." + Path.GetFileName(CopyPath) + ".turn-bore-qualification.once.json"); } }
    }
    internal interface IBackend : IDisposable {
        Dictionary<string,object> Capture();
        void Prepare(Request request);
        int Insert();
        void Bind(int newId);
        void ReadOwn(int newId, Dictionary<string,object> evidence, Action persist);
        void CleanEvents();
        object Messages { get; }
    }
    internal static void Require(bool value,string message) { if(!value) throw new InvalidOperationException(message); }
    internal static JavaScriptSerializer Json() { return new JavaScriptSerializer { MaxJsonLength=1048576, RecursionLimit=32 }; }
    internal static int Int(object value,int low,int high) { return CamBatchReader.Integer(value,low,high); }
    static string Str(object value,int maximum) { var s=value as string; Require(s!=null && s.Length>0 && s.Length<=maximum,"TEXT_REQUIRED"); return s; }
    static string Absolute(object value) { var p=Str(value,32767);Require(Path.IsPathRooted(p),"ABSOLUTE_PATH_REQUIRED");return Path.GetFullPath(p); }
    internal static string Hash(string path) { using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)) using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToLowerInvariant(); }
    static string Sha(object value) { var s=Str(value,64);Require(s.Length==64 && s.All(c=>"0123456789abcdef".Contains(c)),"SHA256_REQUIRED");return s; }
    internal static bool Same(object a,object b) {
        if(a==null || b==null)return a==b;
        var da=a as IDictionary<string,object>;var db=b as IDictionary<string,object>;
        if(da!=null || db!=null)return da!=null && db!=null && da.Count==db.Count && da.All(x=>db.ContainsKey(x.Key)&&Same(x.Value,db[x.Key]));
        if(!(a is string) && a is IEnumerable && !(b is string) && b is IEnumerable) {var aa=((IEnumerable)a).Cast<object>().ToArray();var bb=((IEnumerable)b).Cast<object>().ToArray();return aa.Length==bb.Length&&aa.Zip(bb,(x,y)=>Same(x,y)).All(x=>x);}
        if(a is bool || b is bool || a is string || b is string)return a.Equals(b);
        if(a is IConvertible && b is IConvertible) {try {var x=Convert.ToDouble(a);var y=Convert.ToDouble(b);return !Double.IsNaN(x)&&!Double.IsInfinity(x)&&x==y;}catch {return false;}}
        return a.Equals(b);
    }
    internal static Request Parse(string text) {
        Require(text!=null && text.Length>0 && Encoding.UTF8.GetByteCount(text)<=262144,"REQUEST_SIZE");
        var d=Json().DeserializeObject(text) as Dictionary<string,object>;Require(d!=null&&d.Count==Fields.Length&&Fields.All(d.ContainsKey),"REQUEST_FIELDS");
        Require(Int(d["schema_version"],1,1)==1,"SCHEMA_VERSION");
        var r=new Request { ProcessId=Int(d["expected_process_id"],1,Int32.MaxValue), ToolId=Int(d["selected_tool_id"],1,Int32.MaxValue), FeatureId=Int(d["feature_id"],1,Int32.MaxValue),AnchorId=Int(d["anchor_id"],1,Int32.MaxValue),DefaultId=Int(d["default_id"],1,Int32.MaxValue),MaxTools=Int(d["max_tools"],1,64),CopyPath=Absolute(d["expected_document_path"]),CopySha=Sha(d["expected_source_sha256"]),ProtectedPath=Absolute(d["protected_document_path"]),ProtectedSha=Sha(d["protected_source_sha256"]),Root=Absolute(d["qualification_root"]),SwConfig=Str(d["expected_sw_configuration"],4096),CamConfig=Str(d["expected_cam_configuration"],4096),DefaultName=Str(d["default_name"],1000),ReceiptPath=Absolute(d["native_receipt_path"]),Mvid=Guid.Parse(Str(d["expected_host_module_version_id"],36)).ToString(),Inventory=d["expected_inventory"] as Dictionary<string,object>,Tools=d["expected_tools"] as object[], ProtectedParts=d["protected_part_pins"] as object[] };
        Require(!(d["expected_process_creation_time"] is bool)&&!(d["expected_process_creation_time"] is string),"PROCESS_TIME_TYPE");r.ProcessCreated=Convert.ToDouble(d["expected_process_creation_time"]);Require(r.ProcessCreated>0&&!Double.IsNaN(r.ProcessCreated)&&!Double.IsInfinity(r.ProcessCreated),"PROCESS_TIME");
        Require(r.CopySha==r.ProtectedSha,"COPY_MUST_MATCH_BASELINE_BYTES");
        Require(r.ProtectedParts!=null&&r.ProtectedParts.Length>=1&&r.ProtectedParts.Length<=8,"PROTECTED_PART_PINS");
        var protectedKeys=new HashSet<string>();bool primary=false;
        foreach(var value in r.ProtectedParts){var part=value as Dictionary<string,object>;Require(part!=null&&part.Count==2&&part.ContainsKey("path")&&part.ContainsKey("sha256"),"PROTECTED_PIN_SCHEMA");var path=Absolute(part["path"]);var hash=Sha(part["sha256"]);Require(protectedKeys.Add(CamBatchReader.Key(path)),"DUPLICATE_PROTECTED_PIN");Require(CamBatchReader.Key(path)!=CamBatchReader.Key(r.CopyPath),"COPY_IS_PROTECTED_ARCHIVE");if(CamBatchReader.Key(path)==CamBatchReader.Key(r.ProtectedPath)){Require(hash==r.ProtectedSha,"PROTECTED_PRIMARY_HASH");primary=true;}}
        Require(primary,"PRIMARY_PROTECTED_PIN_MISSING");

        var key=CamBatchReader.Key(r.CopyPath);var root=CamBatchReader.Key(r.Root)+"\\";var original=CamBatchReader.Key(r.ProtectedPath);
        Require(key.StartsWith(root,StringComparison.Ordinal)&&!original.StartsWith(root,StringComparison.Ordinal)&&key!=original,"QUALIFICATION_COPY_REQUIRED");
        Require(Path.GetExtension(r.CopyPath).Equals(".sldprt",StringComparison.OrdinalIgnoreCase)&&Path.GetExtension(r.ProtectedPath).Equals(".sldprt",StringComparison.OrdinalIgnoreCase),"PART_PATHS_REQUIRED");
        Require(Path.GetExtension(r.ReceiptPath).Equals(".json",StringComparison.OrdinalIgnoreCase)&&CamBatchReader.Key(r.ReceiptPath).StartsWith(root,StringComparison.Ordinal),"RECEIPT_IN_QUALIFICATION_ROOT");
        Require(new[]{key,original,CamBatchReader.Key(r.Marker),CamBatchReader.Key(r.ReceiptPath)}.Distinct().Count()==4,"OUTPUT_ALIAS");
        Require(r.Inventory!=null&&r.Inventory.Count==4&&r.Inventory.ContainsKey("machine_type")&&r.Inventory.ContainsKey("operation_setup_count")&&r.Inventory.ContainsKey("operation_count")&&r.Inventory.ContainsKey("operations"),"INVENTORY_SCHEMA");
        Require(Int(r.Inventory["machine_type"],3,3)==3&&Int(r.Inventory["operation_setup_count"],1,1)==1,"SINGLE_TURN_SETUP");
        var rows=r.Inventory["operations"] as object[];Require(rows!=null&&rows.Length==Int(r.Inventory["operation_count"],1,63),"INVENTORY_COUNT");
        var ids=new HashSet<int>();bool anchor=false;
        for(int i=0;i<rows.Length;i++) { var row=rows[i] as Dictionary<string,object>;Require(row!=null&&row.Count==8&&new[]{"setup_index","operation_index","native_id","turn_operation_type","linked_feature_ids","suppressed","toolpath_generated","toolpath_record_counts"}.All(row.ContainsKey),"OPERATION_SCHEMA");
            Require(Int(row["setup_index"],0,0)==0&&Int(row["operation_index"],0,62)==i,"OPERATION_ORDER");var id=Int(row["native_id"],1,Int32.MaxValue);Require(ids.Add(id),"DUPLICATE_OPERATION_ID");var kind=Int(row["turn_operation_type"],1,64);
            var links=row["linked_feature_ids"] as object[];var counts=row["toolpath_record_counts"] as object[];Require(links!=null&&links.Length<=16&&counts!=null&&counts.Length<=64&&row["suppressed"] is bool&&row["toolpath_generated"] is bool,"OPERATION_VALUES");
            var ff=links.Select(x=>Int(x,1,Int32.MaxValue)).ToArray();Require(ff.Distinct().Count()==ff.Length,"FEATURE_DUPLICATE");foreach(var count in counts)Int(count,0,Int32.MaxValue);Require((bool)row["toolpath_generated"]||counts.Length==0,"PATH_FLAGS");
            Require(!((kind==5||kind==6)&&ff.Contains(r.FeatureId)),"BORE_ALREADY_EXISTS");if(id==r.AnchorId){Require(kind==9&&!(bool)row["suppressed"]&&ff.SequenceEqual(new[]{r.FeatureId}),"ANCHOR_BINDING");anchor=true;}
        }
        Require(anchor,"ANCHOR_ABSENT");Require(r.Tools!=null&&r.Tools.Length>0&&r.Tools.Length<=r.MaxTools,"TOOLS_SCHEMA");
        var selected=r.Tools.Cast<Dictionary<string,object>>().Where(x=>Convert.ToInt64(x["native_id"])==r.ToolId).ToArray();Require(selected.Length==1,"SELECTED_TOOL_ABSENT");
        var t=selected[0];Require(t.ContainsKey("candidate")&&t["candidate"] is bool&&(bool)t["candidate"]&&t.ContainsKey("complete")&&t["complete"] is bool&&(bool)t["complete"],"BORING_TOOL_REQUIRED");var dims=t["insert_dimensions_native"] as Dictionary<string,object>;Require(dims!=null&&Convert.ToDouble(dims["IncludedAngle"])==80.0,"80_DEGREE_CANDIDATE_REQUIRED");
        return r;
    }
    [StructLayout(LayoutKind.Sequential)] struct FileInfoNative {internal uint Attributes;internal System.Runtime.InteropServices.ComTypes.FILETIME Created,Accessed,Written;internal uint Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow;}
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetFileInformationByHandle(Microsoft.Win32.SafeHandles.SafeFileHandle handle,out FileInfoNative data);
    internal static string FileIdentity(string path) {using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)){FileInfoNative info;Require(GetFileInformationByHandle(f.SafeFileHandle,out info),"FILE_ID_UNAVAILABLE");return info.Volume+":"+info.IndexHigh+":"+info.IndexLow;}}
    internal static void Files(Request r) {
        foreach(var p in new[]{r.CopyPath,r.ProtectedPath}){var f=new FileInfo(p);Require(f.Exists&&f.Length>0&&f.Length<=134217728&&(f.Attributes&FileAttributes.ReparsePoint)==0,"REGULAR_PART_REQUIRED");}
        Require(FileIdentity(r.CopyPath)!=FileIdentity(r.ProtectedPath),"COPY_ALIASES_PROTECTED_FILE");
        Require(Hash(r.CopyPath)==r.CopySha&&Hash(r.ProtectedPath)==r.ProtectedSha,"SOURCE_HASH_CHANGED");
        foreach(var value in r.ProtectedParts){var part=(Dictionary<string,object>)value;var path=(string)part["path"];Require(FileIdentity(r.CopyPath)!=FileIdentity(path),"COPY_ALIASES_PROTECTED_ARCHIVE");Require(Hash(path)==(string)part["sha256"],"PROTECTED_ARCHIVE_CHANGED");}
    }
    internal static void Persist(string path,object value,bool fresh) {var bytes=new UTF8Encoding(false).GetBytes(Json().Serialize(value));using(var f=new FileStream(path,fresh?FileMode.CreateNew:FileMode.Create,FileAccess.Write,FileShare.Read)){f.Write(bytes,0,bytes.Length);f.Flush(true);}}
    internal static Dictionary<string,object> Added(Dictionary<string,object> before,Dictionary<string,object> after,Request r,int id) {
        Require(id>0,"NEW_ID_INVALID");var old=Json().DeserializeObject(Json().Serialize(before)) as Dictionary<string,object>;var rows=((object[])old["operations"]).Cast<Dictionary<string,object>>().ToList();Require(!rows.Any(x=>Convert.ToInt32(x["native_id"])==id),"OLD_ID_RETURNED");var index=rows.FindIndex(x=>Convert.ToInt32(x["native_id"])==r.AnchorId)+1;Require(index>0,"ANCHOR_ABSENT");
        foreach(var row in rows.Skip(index))row["operation_index"]=Convert.ToInt32(row["operation_index"])+1;
        var added=new Dictionary<string,object>{{"setup_index",0},{"operation_index",index},{"native_id",id},{"turn_operation_type",5},{"linked_feature_ids",new[]{r.FeatureId}},{"suppressed",false},{"toolpath_generated",false},{"toolpath_record_counts",new int[0]}};
        rows.Insert(index,added);old["operations"]=rows;old["operation_count"]=rows.Count;Require(Same(old,after),"UNEXPECTED_ROUTE_DELTA");return added;
    }
    internal static Dictionary<string,object>[] PreserveTools(Request r, object observed) {
        var tools=((IEnumerable)observed).Cast<Dictionary<string,object>>().ToArray();
        Require(tools.Length<=r.MaxTools && tools.Select(x=>Convert.ToInt32(x["native_id"])).Distinct().Count()==tools.Length,"TOOL_ID_OR_COUNT_DRIFT");
        foreach(var value in r.Tools){var old=(Dictionary<string,object>)value;var found=tools.Where(x=>Same(x["native_id"],old["native_id"])).ToArray();Require(found.Length==1&&Same(old,found[0]),"PREEXISTING_TOOL_CHANGED");}
        return tools;
    }
    internal static Dictionary<string,object> Run(Request r,IBackend backend,Dictionary<string,object> result) {
        bool started=false;
        try {
            Require(!File.Exists(r.Marker)&&!File.Exists(r.ReceiptPath),"ATTEMPT_OR_RECEIPT_EXISTS");Files(r);Persist(r.ReceiptPath,result,true);started=true;
            result["stage"]="preflight";backend.Prepare(r);var before=backend.Capture();result["before"]=before;
            Require(Same(before["inventory"],r.Inventory)&&Same(before["tools"],r.Tools),"BASELINE_DRIFT");
            var bd=(Dictionary<string,object>)before["document"];Require(bd["needs_save"] is bool&&!(bool)bd["needs_save"],"DIRTY_COPY");backend.CleanEvents();Files(r);
            Persist(r.Marker,new Dictionary<string,object>{{"scope",Scope},{"status","claimed_no_replay"},{"copy",r.CopyPath},{"sha256",r.CopySha},{"feature_id",r.FeatureId},{"anchor_id",r.AnchorId},{"receipt",r.ReceiptPath}},true);
            result["stage"]="insert";result["mutation_attempted"]=true;result["insert_attempted"]=true;result["native_dispatch_pending"]=true;Persist(r.ReceiptPath,result,false);
            var id=backend.Insert();result["insert_returned"]=true;result["native_dispatch_pending"]=false;result["new_operation_id"]=id;backend.CleanEvents();
            var inserted=backend.Capture();result["after_insert"]=inserted;Added(r.Inventory,(Dictionary<string,object>)inserted["inventory"],r,id);PreserveTools(r,inserted["tools"]);Files(r);
            result["stage"]="bind";result["bind_attempted"]=true;result["native_dispatch_pending"]=true;Persist(r.ReceiptPath,result,false);
            backend.Bind(id);result["bind_returned"]=true;result["native_dispatch_pending"]=false;backend.CleanEvents();
            result["stage"]="own_readback";result["own_read_attempted"]=true;Persist(r.ReceiptPath,result,false);var own=new Dictionary<string,object>{{"operation_native_id",id}};result["own_readback"]=own;backend.ReadOwn(id,own,()=>Persist(r.ReceiptPath,result,false));result["own_read_returned"]=true;Require(Convert.ToInt32(own["tool_native_id"])==r.ToolId&&Convert.ToInt32(own["operation_native_id"])==id,"OWN_TOOL_MISMATCH");CamBatchReader.Number(Convert.ToDouble(own["spindle_speed_native"]));CamBatchReader.Number(Convert.ToDouble(own["feed_rate_ipm_native"]));backend.CleanEvents();
            var after=backend.Capture();result["after"]=after;Added(r.Inventory,(Dictionary<string,object>)after["inventory"],r,id);
            var ad=(Dictionary<string,object>)after["document"];var doc=Json().DeserializeObject(Json().Serialize(bd)) as Dictionary<string,object>;Require(ad["needs_save"] is bool,"DIRTY_FLAG_TYPE");doc["needs_save"]=ad["needs_save"];Require(Same(doc,ad)&&Same(before["configuration"],after["configuration"]),"DOCUMENT_CONFIGURATION_DRIFT");
            var tools=PreserveTools(r,after["tools"]);
            result["new_crib_entries"]=tools.Where(x=>!r.Tools.Cast<Dictionary<string,object>>().Any(y=>Same(x["native_id"],y["native_id"]))).ToArray();backend.CleanEvents();Files(r);
            result["status"]="created_bound_nc_read_ram_only";result["readback_verified"]=true;result["stage"]="finished";
        } catch(Exception e) {result["status"]=result.ContainsKey("mutation_attempted")&&(bool)result["mutation_attempted"]?"uncertain":"error";result["failed_stage"]=result["stage"];result["hresult"]=e.HResult;result["error_type"]=e.GetType().Name;result["message"]=e.Message;result["readback_verified"]=false;}
        finally {try{backend.Dispose();}catch(Exception e){result["cleanup_error"]=e.Message;result["status"]=(bool)result["mutation_attempted"]?"uncertain":"error";result["readback_verified"]=false;}result["messages"]=backend.Messages;if((bool)result["readback_verified"]){var messages=backend.Messages as Dictionary<string,object>;bool quiet=messages!=null&&messages.ContainsKey("subscribed")&&messages.ContainsKey("disconnected")&&messages.ContainsKey("active")&&Same(messages["subscribed"],true)&&Same(messages["disconnected"],true)&&Same(messages["active"],false)&&Same(messages["event_count"],0)&&Same(messages["overflow"],0)&&Same(messages["callback_error_count"],0)&&messages["cleanup_error"]==null;if(!quiet){result["status"]="uncertain";result["readback_verified"]=false;result["cleanup_error"]="FINAL_EVENTS_NOT_QUIET";}}if(started)Persist(r.ReceiptPath,result,false);}
        return result;
    }
    internal static Dictionary<string,object> Initial() {return new Dictionary<string,object>{{"schema_version",1},{"scope",Scope},{"engine_version",Engine},{"status","prepared"},{"stage","request"},{"process_id",Process.GetCurrentProcess().Id},{"host_module_version_id",typeof(SwAddin).Module.ModuleVersionId.ToString()},{"host_assembly_location",typeof(SwAddin).Assembly.Location},{"mutation_attempted",false},{"insert_attempted",false},{"insert_returned",false},{"bind_attempted",false},{"bind_returned",false},{"own_read_attempted",false},{"own_read_returned",false},{"native_dispatch_pending",false},{"readback_verified",false},{"model_saved",false},{"GTP_attempted",false},{"GOP_attempted",false},{"tool_creation_attempted",false},{"existing_tool_edit_attempted",false},{"persistence_qualified",false},{"physical_tool_qualified",false},{"production_qualified",false},{"protected_CL_bytes_compared",false}};}
    internal static string Execute(ISldWorks app,int ownerThreadId,string requestJson) {
        var result=Initial();var clock=Stopwatch.StartNew();
        try {var r=Parse(requestJson);Require(app!=null&&ownerThreadId!=0,"HOST_NOT_CONNECTED");Require(Thread.CurrentThread.ManagedThreadId==ownerThreadId&&Thread.CurrentThread.GetApartmentState()==ApartmentState.STA,"HOST_THREAD_MISMATCH");Require(r.Mvid==typeof(SwAddin).Module.ModuleVersionId.ToString(),"LOADED_HOST_MVID");result=Run(r,new NativeBackend(app,r),result);}
        catch(Exception e){result["readback_verified"]=false;result["status"]=(bool)result["mutation_attempted"]?"uncertain":"error";result["hresult"]=e.HResult;result["error_type"]=e.GetType().Name;result["message"]=e.Message;}
        result["elapsed_ms"]=clock.Elapsed.TotalMilliseconds;return Json().Serialize(result);
    }

    internal sealed class NativeBackend : IBackend {
        readonly ISldWorks app;readonly Request r;readonly CamBatchReader.Request readRequest;
        ICWApp4 cam;ICWDoc3 doc;ICWMachine machine;ICWTurnFeature feature;object anchor,tool;readonly Dictionary<int,object> created=new Dictionary<int,object>();BoreMessageSession events;
        internal NativeBackend(ISldWorks application,Request request) {app=application;r=request;readRequest=new CamBatchReader.Request {ProcessId=r.ProcessId,DocumentPath=r.CopyPath,MaxOperations=64,MaxTools=r.MaxTools};}
        void Owner() {var loaded=app.GetDocuments() as Array;Require(loaded!=null&&loaded.Rank==1&&loaded.Length==1,"ONLY_QUALIFICATION_COPY_MAY_BE_LOADED");var sole=loaded.GetValue(loaded.GetLowerBound(0)) as IModelDoc2;Require(sole!=null&&CamBatchReader.Key(sole.GetPathName())==CamBatchReader.Key(r.CopyPath),"LOADED_DOCUMENT_NOT_COPY");Require(Process.GetCurrentProcess().Id==r.ProcessId&&app.GetProcessID()==r.ProcessId,"PROCESS_MISMATCH");var start=Process.GetCurrentProcess().StartTime.ToUniversalTime();var seconds=(start-new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc)).TotalSeconds;Require(Math.Abs(seconds-r.ProcessCreated)<=0.001,"PROCESS_LIFETIME_MISMATCH");}
        Dictionary<string,object> Configuration() {var c=(ICWConfiguration)doc.GetActiveConfiguration();Require(c!=null,"CAM_CONFIGURATION_ABSENT");var name=CamBatchReader.Text(doc.GetActiveConfigurationName());CamBatchReader.ValidateConfigurationBinding(name,CamBatchReader.Text(c.ConfigurationName),CamBatchReader.Text(c.SWConfigurationName),r.SwConfig);Require(name==r.CamConfig,"CAM_CONFIGURATION_MISMATCH");return new Dictionary<string,object>{{"name",name},{"object_name",c.ConfigurationName},{"associated_sw_name",c.SWConfigurationName}};}
        public void Prepare(Request request) {
            Owner();var before=CamBatchReader.Document(app,readRequest);Require((string)before["configuration"]==r.SwConfig,"SW_CONFIGURATION_MISMATCH");
            dynamic bridge=app.GetAddInObject(CamBatchReader.CamClass);Require(bridge!=null,"CAM_ADDIN_NOT_LOADED");object rawApp=bridge.GetCWApp();cam=(ICWApp4)rawApp;object active=cam.IGetActiveDoc();Require(active!=null,"CAM_DOCUMENT_ABSENT");doc=(ICWDoc3)active;Require(doc.GetDocType()==1,"CAM_PART_REQUIRED");Configuration();machine=(ICWMachine)((ICWPartDoc)active).IGetMachine();Require(machine!=null&&machine.MachType==3,"TURN_MACHINE_REQUIRED");
            events=new BoreMessageSession(((ICWApp)rawApp).IGetEventNotifier());events.Subscribe();
            var setups=CamBatchReader.Items(machine.IGetEnumOpSetups(),8);Require(setups.Length==1,"SINGLE_SETUP_REQUIRED");var ops=CamBatchReader.Items(((ICWBaseOpSetup)setups[0]).IGetEnumOperations(),64);anchor=ops.Single(x=>CamBatchReader.Identity(doc,x)==r.AnchorId);Require((int)((ICWTurnOperation)anchor).OpernType==9,"DRILL_ANCHOR_REQUIRED");
            var features=CamBatchReader.Items(((ICWOperation)anchor).IGetAllFeatures(),16);Require(features.Length==1&&CamBatchReader.Identity(doc,features[0])==r.FeatureId,"FEATURE_BINDING_MISMATCH");feature=(ICWTurnFeature)features[0];Require((int)feature.GetTurnFeatureType()==2,"INTERNAL_FEATURE_REQUIRED");
            int kind=(int)CWTurnOperationTypes_e.CW_TURN_OP_ROUGH_BORE;Require(kind==5,"ROUGH_BORE_ENUM_CHANGED");object namesRaw=feature.IGetAllDefaultOperations(kind);string[] names;
            if(namesRaw is string)names=new[]{(string)namesRaw};else {var array=namesRaw as Array;Require(array!=null&&array.Rank==1&&array.Length<=64,"DEFAULT_NAMES_SHAPE");names=array.Cast<object>().Select(x=>CamBatchReader.Text((string)x)).ToArray();}
            Require(names.Distinct().Count()==names.Length&&names.Contains(r.DefaultName),"DEFAULT_NAME_ABSENT");Require(feature.GetTdbIdForDefaultOperation(kind,r.DefaultName)==r.DefaultId,"DEFAULT_ID_CHANGED");
            var crib=(ICWToolcrib4)machine.IGetToolcrib();tool=CamBatchReader.Items(crib.GetAllTools(),r.MaxTools).Single(x=>CamBatchReader.Identity(doc,x)==r.ToolId);var t=(ICWTool)tool;var tt=(ICWTurnTool)tool;Require(t.ToolType==15&&(int)tt.ToolType==1&&(int)tt.InsertType==1&&tt.IncludedAngle==80.0,"SELECTED_BORING_INSERT_MISMATCH");var holder=(ICWTurnToolHolder)tt.IGetTurnToolHolder();Require(holder!=null&&(int)holder.GetHolderType()==2,"BORING_HOLDER_REQUIRED");CleanEvents();
        }
        public Dictionary<string,object> Capture() {Owner();var d=CamBatchReader.Document(app,readRequest);Require((string)d["configuration"]==r.SwConfig,"SW_CONFIGURATION_CHANGED");var handles=new Dictionary<uint,ICWTurnOperation>();var state=new Dictionary<string,object>{{"document",d},{"configuration",Configuration()},{"inventory",CamBatchReader.Inventory(machine,doc,readRequest,handles)},{"tools",CamBatchReader.Tools(machine,doc,readRequest)}};CleanEvents();return state;}
        public int Insert() {object op=feature.InsertOperation((int)CWTurnOperationTypes_e.CW_TURN_OP_ROUGH_BORE,r.DefaultId,anchor);Require(op!=null,"INSERT_RETURNED_NULL");int id=checked((int)CamBatchReader.Identity(doc,op));created.Add(id,op);return id;}
        public void Bind(int newId) {Require(created.ContainsKey(newId),"NEW_OPERATION_NOT_LOCAL");Require(CamBatchReader.Identity(doc,tool)==r.ToolId,"LOCAL_TOOL_ID_CHANGED");((ICWTurnOperation)created[newId]).SetTool(tool);}
        public void ReadOwn(int newId,Dictionary<string,object> evidence,Action persist) {
            Require(created.ContainsKey(newId),"NEW_OPERATION_NOT_LOCAL");object op=created[newId];Require(CamBatchReader.Identity(doc,op)==newId,"NEW_OPERATION_ID_CHANGED");
            evidence["stage"]="IGetTool";evidence["tool_getter_attempted"]=true;persist();object assigned=((ICWOperation)op).IGetTool();evidence["tool_getter_returned"]=true;evidence["tool_present"]=assigned!=null;persist();Require(assigned!=null,"OWN_TOOL_ABSENT");
            uint id=CamBatchReader.Identity(doc,assigned);evidence["tool_native_id"]=id;persist();Require(id==r.ToolId,"OWN_TOOL_COPY_LIFECYCLE_UNQUALIFIED");
            evidence["stage"]="IGetTurnNCParam";evidence["nc_getter_attempted"]=true;persist();object raw=((ICWTurnOperation)op).IGetTurnNCParam();evidence["nc_getter_returned"]=true;evidence["nc_present"]=raw!=null;persist();Require(raw!=null,"OWN_NC_ABSENT");
            evidence["stage"]="ICWTurnNCParam";persist();var nc=(ICWTurnNCParam)raw;evidence["nc_interface_verified"]=true;
            evidence["stage"]="GetSpndlSpeed";persist();evidence["spindle_speed_native"]=CamBatchReader.Number(nc.GetSpndlSpeed());
            evidence["stage"]="GetFeedRateIPM";persist();evidence["feed_rate_ipm_native"]=CamBatchReader.Number(nc.GetFeedRateIPM());evidence["units_qualified"]=false;evidence["stage"]="finished";persist();
        }
        public void CleanEvents(){if(events!=null)events.Clean();}
        public object Messages {get{return events==null?new Dictionary<string,object>{{"subscribed",false},{"event_count",0},{"disconnected",false}}:events.Summary();}}
        public void Dispose(){if(events!=null)events.Dispose();}
    }
}
[ComVisible(true),Guid("046D82BC-7F81-3EB9-BC2E-A6AD9EF1E95D"),ClassInterface(ClassInterfaceType.None)]
public sealed class BoreMessageSink : _IDialogEvents {
    readonly BoreMessageSession owner;
    internal BoreMessageSink(BoreMessageSession session){owner=session;}
    public void CWMsg(int messageType,int id,string message){try{owner.Record(messageType,id,message);}catch(Exception e){owner.CallbackError(e);}}
}
[ComVisible(false)]
internal sealed class BoreMessageSession : IDisposable {
    static readonly List<BoreMessageSession> failedConnections=new List<BoreMessageSession>();
    readonly object notifier;readonly BoreMessageSink sink;IConnectionPoint point;int cookie;bool subscribed,disconnected;int count,overflow,callbackErrors;readonly List<Dictionary<string,object>> rows=new List<Dictionary<string,object>>();string cleanupError;
    internal BoreMessageSession(object value){CamTurnBoreBuilder.Require(value!=null,"EVENT_NOTIFIER_ABSENT");notifier=value;sink=new BoreMessageSink(this);}
    internal void Subscribe(){lock(failedConnections){CamTurnBoreBuilder.Require(failedConnections.Count==0,"PRIOR_EVENT_CLEANUP_UNCERTAIN");}var iid=new Guid("7532C711-3BC4-11D6-A9AF-00062999E55F");((IConnectionPointContainer)notifier).FindConnectionPoint(ref iid,out point);CamTurnBoreBuilder.Require(point!=null,"EVENT_CONNECTION_POINT_ABSENT");point.Advise(sink,out cookie);subscribed=true;}
    internal void Record(int type,int id,string message){lock(rows){count++;if(rows.Count>=100){overflow++;return;}var text=message??"";rows.Add(new Dictionary<string,object>{{"message_type",type},{"message_id",id},{"message",text.Substring(0,Math.Min(1000,text.Length))},{"message_truncated",text.Length>1000},{"response","default_unknown"}});}}
    internal void CallbackError(Exception error){Interlocked.Increment(ref callbackErrors);}
    internal void Clean(){lock(rows){CamTurnBoreBuilder.Require(subscribed&&!disconnected&&count==0&&overflow==0&&callbackErrors==0,"CAM_EVENT_OR_CALLBACK_ERROR");}}
    internal object Summary(){lock(rows){return new Dictionary<string,object>{{"policy","vendor_default"},{"response","default_unknown"},{"subscribed",subscribed},{"disconnected",disconnected},{"active",subscribed&&!disconnected},{"event_count",count},{"events",rows.ToArray()},{"overflow",overflow},{"callback_error_count",callbackErrors},{"cleanup_error",cleanupError}};}}
    public void Dispose(){if(subscribed&&!disconnected){try{point.Unadvise(cookie);disconnected=true;}catch(Exception e){cleanupError=e.Message;lock(failedConnections)failedConnections.Add(this);throw;}}}
}
}
