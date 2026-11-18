using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using CamWorks.Interop;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;
[assembly: ComVisible(false)]
[assembly: Guid("91FE2D85-D19A-4DBB-8BB0-B6D02A948FA5")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]
namespace CadStudio.SolidWorks.CamIslandQualification {
[ComVisible(true),Guid("36B207A9-AF3A-4F89-B211-5755E7CF6327"),InterfaceType(ComInterfaceType.InterfaceIsDual)]
public interface ICamExplicitIslandQualification {
 [DispId(1)] string GetHostStatus();
 [DispId(2)] string QualifyCreatePocketAndIslands(string requestJson);
}
[ComVisible(true),Guid(AddinGuid),ProgId("CadStudio.SolidWorks.CamIslandQualification"),ClassInterface(ClassInterfaceType.None),ComDefaultInterface(typeof(ICamExplicitIslandQualification))]
public sealed class IslandAddin : ISwAddin, ICamExplicitIslandQualification {
 public const string AddinGuid="F69869EF-C175-4A06-9426-E1502BFA8921";
 ISldWorks app;Control dispatcher;int ownerThread;int busy;bool connected;
 readonly ConnectionDiagnostics diagnostics=new ConnectionDiagnostics();
 public bool ConnectToSW(object application,int cookie) {
  string stage="connect_entered";
  try {
   diagnostics.Record(stage,null,false,false);
   Qualification.Require(!connected&&dispatcher==null,"ALREADY_CONNECTED");
   stage="validate_owner_sta";diagnostics.Record(stage,null,false,false);
   Qualification.Require(Thread.CurrentThread.GetApartmentState()==ApartmentState.STA,"CONNECT_NOT_STA");
   stage="cast_application";diagnostics.Record(stage,null,false,false);
   app=(ISldWorks)application;ownerThread=Thread.CurrentThread.ManagedThreadId;
   stage="register_callback";diagnostics.Record(stage,null,false,false);
   bool callback=app.SetAddinCallbackInfo2(0,this,cookie);
   diagnostics.Record("callback_returned",null,callback,false);
   Qualification.Require(callback,"CALLBACK_REGISTRATION_FAILED");
   stage="create_dispatcher";diagnostics.Record(stage,null,true,false);
   dispatcher=new Control();var handle=dispatcher.Handle;
   Qualification.Require(handle!=IntPtr.Zero,"DISPATCH_HANDLE_ABSENT");
   connected=true;diagnostics.Record("connected",null,true,true);return true;
  } catch(Exception error) {
   // A failed callback/STA/dispatcher step is durable evidence, not a silent false.
   diagnostics.TryFailure(stage,error);
   try{if(dispatcher!=null)dispatcher.Dispose();}catch(Exception cleanup){diagnostics.TryFailure("cleanup_after_connect_failure",cleanup);}
   dispatcher=null;app=null;ownerThread=0;connected=false;return false;
  }
 }
 public bool DisconnectFromSW(){if(Interlocked.CompareExchange(ref busy,0,0)!=0)return false;try{if(dispatcher!=null)dispatcher.Dispose();dispatcher=null;app=null;connected=false;ownerThread=0;diagnostics.Record("disconnected",null,false,false);return true;}catch(Exception error){diagnostics.TryFailure("disconnect",error);return false;}}
 string Owner(Func<string> action){Qualification.Require(connected&&app!=null,"HOST_NOT_CONNECTED");if(Interlocked.Exchange(ref busy,1)!=0)throw new InvalidOperationException("QUALIFICATION_BUSY");try{if(Thread.CurrentThread.ManagedThreadId==ownerThread)return action();Qualification.Require(dispatcher!=null&&!dispatcher.IsDisposed&&dispatcher.IsHandleCreated,"OWNER_DISPATCH_UNAVAILABLE");return (string)dispatcher.Invoke(action);}finally{Interlocked.Exchange(ref busy,0);}}
 public string GetHostStatus(){return Owner(()=>Qualification.Json().Serialize(Qualification.Status(app,ownerThread)));}
 public string QualifyCreatePocketAndIslands(string requestJson){return Owner(()=>Qualification.Execute(app,ownerThread,requestJson));}
}
// Separate from the existing AddInHost diagnostics. No constructor writes and no CAD calls.
internal sealed class ConnectionDiagnostics {
 readonly List<Dictionary<string,object>> stages=new List<Dictionary<string,object>>();
 string PathName{get{return Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData),"CAD Studio","SolidWorksCamIslandQualification","host-status-"+Process.GetCurrentProcess().Id+".json");}}
 internal void Record(string stage,Exception error,bool callback,bool ready){
  var process=Process.GetCurrentProcess();var entry=new Dictionary<string,object>{{"stage",stage},{"utc",DateTime.UtcNow.ToString("o")},{"thread_id",Thread.CurrentThread.ManagedThreadId},{"apartment",Thread.CurrentThread.GetApartmentState().ToString()}};
  if(error!=null){var chain=new List<Dictionary<string,object>>();for(var e=error;e!=null&&chain.Count<6;e=e.InnerException)chain.Add(new Dictionary<string,object>{{"type",e.GetType().FullName},{"hresult",e.HResult},{"message",e.Message}});entry["exceptions"]=chain;}
  if(stages.Count>=32)stages.RemoveAt(0);stages.Add(entry);
  var result=new Dictionary<string,object>{{"schema_version",1},{"scope","CAM_ISLAND_SIDECAR_CONNECTION_V1"},{"status",error!=null?"error":stage},{"stage",stage},{"process_id",process.Id},{"process_creation_time",Qualification.Created()},{"host_module_version_id",typeof(IslandAddin).Module.ModuleVersionId.ToString()},{"host_assembly_location",typeof(IslandAddin).Assembly.Location},{"owner_thread_id",Thread.CurrentThread.ManagedThreadId},{"apartment",Thread.CurrentThread.GetApartmentState().ToString()},{"callback_registered",callback},{"dispatcher_ready",ready},{"visible_ui_created",false},{"CAM_calls",0},{"connection_stages",stages}};
  string path=PathName;Directory.CreateDirectory(Path.GetDirectoryName(path));byte[] bytes=new UTF8Encoding(false).GetBytes(Qualification.Json().Serialize(result));
  using(var file=new FileStream(path,FileMode.Create,FileAccess.Write,FileShare.Read)){file.Write(bytes,0,bytes.Length);file.Flush(true);}
 }
 internal void TryFailure(string failedStage,Exception error){try{Record("failed:"+failedStage,error,false,false);}catch{ /* The caller returns false; unavailable diagnostic storage cannot turn failure into success. */ }}
}
internal static class Qualification {
 internal const string Scope="MILL_OWNER_STA_EXPLICIT_ISLAND_QUALIFICATION_V1";
 internal const string Engine="explicit-island-owner-sta-1";
 internal const string CamClass="{CCAC6208-0E19-6455-2022-2026CEB541FA}";
 internal static readonly string[] Fields={"schema_version","expected_process_id","expected_process_creation_time","expected_document_path","expected_source_sha256","protected_document_path","protected_source_sha256","qualification_root","expected_sw_configuration","expected_cam_configuration","expected_host_module_version_id","native_receipt_path","expected_cad_fingerprint","owner_setup_native_id","operation_setup_native_id","axis_native","origin_native","outer_sketch_name","island_sketch_names","depth_native","expected_shape","island_count_limit"};
 internal sealed class Request {
  internal int Pid,SetupId,OpSetupId,Shape,Limit;internal double Created,Depth;internal string Copy,Sha,Protected,ProtectedSha,Root,SwConfig,CamConfig,Mvid,Receipt,Outer;internal string[] Islands;internal double[] Axis,Origin;internal Dictionary<string,object> Cad;
  internal string Marker{get{return Path.Combine(Path.GetDirectoryName(Copy),"."+Path.GetFileName(Copy)+".owner-sta-explicit-island.once.json");}}
 }
 internal interface IBackend : IDisposable {
  void Prepare();void Boundary(bool clean);Dictionary<string,object> Capture();object Create();int Identify(object feature);bool Add(object sameFeature,int index);Dictionary<string,object> Header(int id);object Chains(int id,int count);void Quiet();object Messages{get;}
 }
 internal static void Require(bool ok,string message){if(!ok)throw new InvalidOperationException(message);}
 internal static JavaScriptSerializer Json(){return new JavaScriptSerializer{MaxJsonLength=2097152,RecursionLimit=48};}
 internal static string Key(string p){return Path.GetFullPath(p).TrimEnd('\\','/').Replace('/','\\').ToUpperInvariant();}
 internal static int Int(object v,int min,int max){Require(v is int&&(int)v>=min&&(int)v<=max,"INTEGER_RANGE");return (int)v;}
 internal static double Number(object v){Require(!(v is bool)&&!(v is string)&&v is IConvertible,"NUMBER_TYPE");double x=Convert.ToDouble(v);Require(!Double.IsNaN(x)&&!Double.IsInfinity(x),"NONFINITE_NUMBER");return x;}
 static string Text(object v,int max){var s=v as string;Require(!String.IsNullOrEmpty(s)&&s.Length<=max,"TEXT_REQUIRED");return s;}
 static string Absolute(object v){string p=Text(v,32767);Require(Path.IsPathRooted(p),"ABSOLUTE_PATH_REQUIRED");return Path.GetFullPath(p);}
 static string Sha(object v){string s=Text(v,64);Require(s.Length==64&&s.All(x=>"0123456789abcdef".Contains(x)),"SHA256_REQUIRED");return s;}
 static double[] Vector(object value){var a=value as object[];Require(a!=null&&a.Length==3,"VECTOR_REQUIRED");return a.Select(Number).ToArray();}
 internal static bool Same(object a,object b){
  if(a==null||b==null)return a==b;var da=a as IDictionary<string,object>;var db=b as IDictionary<string,object>;
  if(da!=null||db!=null)return da!=null&&db!=null&&da.Count==db.Count&&da.All(x=>db.ContainsKey(x.Key)&&Same(x.Value,db[x.Key]));
  if(!(a is string)&&a is IEnumerable&&!(b is string)&&b is IEnumerable){var aa=((IEnumerable)a).Cast<object>().ToArray();var bb=((IEnumerable)b).Cast<object>().ToArray();return aa.Length==bb.Length&&aa.Zip(bb,Same).All(x=>x);}
  if(a is bool||b is bool||a is string||b is string)return a.Equals(b);
  try{return Number(a)==Number(b);}catch{return false;}
 }
 static bool Near(object a,object b,double absolute){var aa=((IEnumerable)a).Cast<object>().Select(Number).ToArray();var bb=((IEnumerable)b).Cast<object>().Select(Number).ToArray();return aa.Length==bb.Length&&aa.Zip(bb,(x,y)=>Math.Abs(x-y)<=absolute+Math.Abs(y)*1e-10).All(x=>x);}
 internal static void CadEqual(Dictionary<string,object> expected,Dictionary<string,object> observed,bool allowAttributes){
  var old=((IEnumerable)expected["feature_tree"]).Cast<object>().ToArray();var now=((IEnumerable)observed["feature_tree"]).Cast<object>().ToArray();
  Require(now.Length>=old.Length&&Same(old,now.Take(old.Length).ToArray()),"CAD_FEATURE_TREE_CHANGED");
  Require(allowAttributes?now.Skip(old.Length).All(x=>(string)((Dictionary<string,object>)x)["type"]=="Attribute"):now.Length==old.Length,"CAD_UNEXPECTED_SUFFIX");
  var a=((IEnumerable)expected["solids"]).Cast<Dictionary<string,object>>().ToArray();var b=((IEnumerable)observed["solids"]).Cast<Dictionary<string,object>>().ToArray();
  Require(a.Length==b.Length,"CAD_BODY_COUNT_CHANGED");for(int i=0;i<a.Length;i++)Require(Same(a[i]["box_m"],b[i]["box_m"])&&Near(a[i]["mass_raw"],b[i]["mass_raw"],0),"CAD_BODY_FINGERPRINT_CHANGED");
 }
 internal static Request Parse(string text){
  Require(text!=null&&Encoding.UTF8.GetByteCount(text)<=262144,"REQUEST_SIZE");var d=Json().DeserializeObject(text) as Dictionary<string,object>;Require(d!=null&&d.Count==Fields.Length&&Fields.All(d.ContainsKey),"REQUEST_FIELDS");Int(d["schema_version"],1,1);
  var r=new Request{Pid=Int(d["expected_process_id"],1,Int32.MaxValue),Created=Number(d["expected_process_creation_time"]),Copy=Absolute(d["expected_document_path"]),Sha=Sha(d["expected_source_sha256"]),Protected=Absolute(d["protected_document_path"]),ProtectedSha=Sha(d["protected_source_sha256"]),Root=Absolute(d["qualification_root"]),SwConfig=Text(d["expected_sw_configuration"],1024),CamConfig=Text(d["expected_cam_configuration"],1024),Mvid=Guid.Parse(Text(d["expected_host_module_version_id"],36)).ToString(),Receipt=Absolute(d["native_receipt_path"]),Cad=d["expected_cad_fingerprint"] as Dictionary<string,object>,SetupId=Int(d["owner_setup_native_id"],64,64),OpSetupId=Int(d["operation_setup_native_id"],65,65),Axis=Vector(d["axis_native"]),Origin=Vector(d["origin_native"]),Outer=Text(d["outer_sketch_name"],1024),Depth=Number(d["depth_native"]),Shape=Int(d["expected_shape"],2,2),Limit=Int(d["island_count_limit"],1,4)};
  Require(r.Limit==1||r.Limit==4,"ISLAND_LIMIT_1_OR_4");var names=d["island_sketch_names"] as object[];Require(names!=null&&names.Length==4,"FOUR_ISLAND_NAMES_REQUIRED");r.Islands=names.Select(x=>Text(x,1024)).ToArray();
  Require(r.Created>0&&r.Depth==13.2&&Same(r.Axis,new[]{0.0,0.0,-1.0})&&Same(r.Origin,new[]{0.0,0.0,0.0}),"FIXED_CASE_GEOMETRY_REQUIRED");
  Require(r.Outer=="CAM_UPPER_PROFILE_R25"&&r.Islands.SequenceEqual(new[]{"CAM_GUIDE_FULL_25","CAM_GUIDE_FULL_155","CAM_GUIDE_FULL_205","CAM_GUIDE_FULL_335"}),"EXACT_FIVE_SKETCH_NAMES_REQUIRED");
  Require(r.Sha==r.ProtectedSha&&Key(r.Copy)!=Key(r.Protected),"FRESH_COPY_SAME_SAVED_BYTES_REQUIRED");
  var root=Key(r.Root)+"\\";Require(Key(r.Copy).StartsWith(root,StringComparison.Ordinal)&&Key(r.Receipt).StartsWith(root,StringComparison.Ordinal)&&!Key(r.Protected).StartsWith(root,StringComparison.Ordinal),"QUALIFICATION_ROOT_BINDING");
  Require(Path.GetExtension(r.Copy).Equals(".sldprt",StringComparison.OrdinalIgnoreCase)&&Path.GetExtension(r.Protected).Equals(".sldprt",StringComparison.OrdinalIgnoreCase)&&Path.GetExtension(r.Receipt).Equals(".json",StringComparison.OrdinalIgnoreCase),"FILE_EXTENSIONS");
  Require(new[]{Key(r.Copy),Key(r.Protected),Key(r.Receipt),Key(r.Marker)}.Distinct().Count()==4,"OUTPUT_ALIAS");
  Require(r.Cad!=null&&r.Cad.Count==2&&r.Cad.ContainsKey("feature_tree")&&r.Cad.ContainsKey("solids"),"CAD_FINGERPRINT_SCHEMA");
  var tree=r.Cad["feature_tree"] as object[];var solids=r.Cad["solids"] as object[];Require(tree!=null&&tree.Length>0&&tree.Length<=256&&solids!=null&&solids.Length==1,"CAD_FINGERPRINT_COUNTS");
  foreach(var v in tree){var row=v as Dictionary<string,object>;Require(row!=null&&row.Count==2&&row.ContainsKey("name")&&row.ContainsKey("type"),"CAD_TREE_ROW");Text(row["name"],1024);Text(row["type"],1024);}
  foreach(var v in solids){var row=v as Dictionary<string,object>;Require(row!=null&&row.Count==2&&row.ContainsKey("box_m")&&row.ContainsKey("mass_raw"),"CAD_BODY_ROW");foreach(var pair in new[]{Tuple.Create("box_m",6),Tuple.Create("mass_raw",12)}){var arr=row[pair.Item1] as object[];Require(arr!=null&&arr.Length==pair.Item2,"CAD_BODY_ARRAY");foreach(var x in arr)Number(x);}}
  foreach(string name in new[]{r.Outer}.Concat(r.Islands))Require(tree.Cast<Dictionary<string,object>>().Count(x=>(string)x["name"]==name&&(string)x["type"]=="ProfileFeature")==1,"CAD_NAMED_SKETCH_MISSING");return r;
 }
 internal static string Hash(string path){using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(f)).Replace("-","").ToLowerInvariant();}
 [StructLayout(LayoutKind.Sequential)]struct NativeFileInfo{internal uint Attr;internal System.Runtime.InteropServices.ComTypes.FILETIME Created,Accessed,Written;internal uint Vol,High,Low,Links,IndexHigh,IndexLow;}
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool GetFileInformationByHandle(Microsoft.Win32.SafeHandles.SafeFileHandle h,out NativeFileInfo info);
 static string FileIdentity(string path){using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)){NativeFileInfo i;Require(GetFileInformationByHandle(f.SafeFileHandle,out i),"FILE_ID_UNAVAILABLE");return i.Vol+":"+i.IndexHigh+":"+i.IndexLow;}}
 internal static void Files(Request r){foreach(string p in new[]{r.Copy,r.Protected}){var f=new FileInfo(p);Require(f.Exists&&f.Length>0&&f.Length<=134217728&&(f.Attributes&FileAttributes.ReparsePoint)==0,"REGULAR_PART_REQUIRED");}Require(FileIdentity(r.Copy)!=FileIdentity(r.Protected),"COPY_FILE_ALIAS");Require(Hash(r.Copy)==r.Sha&&Hash(r.Protected)==r.ProtectedSha,"SOURCE_HASH_CHANGED");}
 internal static void Persist(string path,object value,bool fresh){byte[] data=new UTF8Encoding(false).GetBytes(Json().Serialize(value));using(var f=new FileStream(path,fresh?FileMode.CreateNew:FileMode.Create,FileAccess.Write,FileShare.Read)){f.Write(data,0,data.Length);f.Flush(true);}}
 internal static double Created(){return(Process.GetCurrentProcess().StartTime.ToUniversalTime()-new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc)).TotalSeconds;}
 internal static Dictionary<string,object> Status(ISldWorks app,int owner){Require(app!=null&&Thread.CurrentThread.ManagedThreadId==owner&&Thread.CurrentThread.GetApartmentState()==ApartmentState.STA,"OWNER_STA_REQUIRED");return new Dictionary<string,object>{{"schema_version",1},{"status","connected"},{"scope",Scope},{"process_id",Process.GetCurrentProcess().Id},{"process_creation_time",Created()},{"host_module_version_id",typeof(IslandAddin).Module.ModuleVersionId.ToString()},{"host_assembly_location",typeof(IslandAddin).Assembly.Location},{"owner_thread_id",owner},{"current_thread_id",Thread.CurrentThread.ManagedThreadId},{"apartment",Thread.CurrentThread.GetApartmentState().ToString()},{"dispatcher_ready",true},{"native_calls",0},{"visible_ui_created",false}};}
 internal static Dictionary<string,object> Initial(){var r=new Dictionary<string,object>{{"schema_version",1},{"scope",Scope},{"engine_version",Engine},{"status","prepared"},{"stage","request"},{"process_id",Process.GetCurrentProcess().Id},{"process_creation_time",Created()},{"host_module_version_id",typeof(IslandAddin).Module.ModuleVersionId.ToString()},{"host_assembly_location",typeof(IslandAddin).Assembly.Location},{"actions",new List<Dictionary<string,object>>()}};foreach(string k in new[]{"mutation_attempted","create_attempted","create_returned","add_attempted","add_returned","native_dispatch_pending","readback_verified","source_unchanged","Save_attempted","GOP_attempted","GTP_attempted","AFR_attempted","model_saved","production_qualified","machining_eligible","physical_depth_verified","world_profile_placement_verified","automatic_retry","persistence_qualified"})r[k]=false;return r;}
 internal static void Error(Dictionary<string,object> r,Exception e){r["status"]=(bool)r["mutation_attempted"]?"uncertain":"error";r["failed_stage"]=r["stage"];r["error_type"]=e.GetType().FullName;r["hresult"]=e.HResult;r["message"]=e.Message;r["readback_verified"]=false;}
 internal static void VerifyHeader(Request r,Dictionary<string,object> h,int count){Require(Convert.ToInt32(h["native_id"])>0&&Convert.ToInt32(h["owner_setup_native_id"])==r.SetupId&&Convert.ToInt32(h["shape"])==r.Shape&&Convert.ToInt32(h["volume_type"])==2&&Same(h["suppressed"],false)&&Same(h["axis_native"],r.Axis)&&Math.Abs(Number(h["depth_native"])-r.Depth)<=1e-8&&Number(h["taper_angle_native"])==0&&Convert.ToInt32(h["island_count"])==count&&Convert.ToInt32(h["sketch_count"])==count+1&&Same(h["sketch_names"],new[]{r.Outer}.Concat(r.Islands.Take(count)).ToArray()),"FEATURE_HEADER_MISMATCH");}
 // Validation is separate from COM reads so every rejected observation can be tested offline.
 internal static object Value(Dictionary<string,object> row,string key){object value;return row.TryGetValue(key,out value)?value:null;}
 internal static bool Is(Dictionary<string,object> row,string key,object expected){return Same(Value(row,key),expected);}
 internal static void ValidateSwBoundary(Request q,Dictionary<string,object> row,bool clean,Action recorded){
  recorded();Require(Is(row,"process_id",q.Pid)&&Is(row,"application_process_id",q.Pid)&&Value(row,"process_creation_time")!=null&&Math.Abs(Number(row["process_creation_time"])-q.Created)<=0.001,"PROCESS_ID_LIFETIME_CHANGED");
  Require(Is(row,"active_present",true),"ACTIVE_COPY_ABSENT");Require(Is(row,"document_type",1),"ACTIVE_COPY_DOCUMENT_TYPE_CHANGED");
  Require(Value(row,"path") is string&&Key((string)row["path"])==Key(q.Copy),"ACTIVE_COPY_PATH_CHANGED");Require(Is(row,"sw_configuration",q.SwConfig),"ACTIVE_COPY_CONFIGURATION_CHANGED");
  Require(!clean||Is(row,"needs_save",false),"CLEAN_SAVED_COPY_REQUIRED");
  Require(Is(row,"loaded_collection_valid",true)&&Is(row,"loaded_count",1),"SOLE_QUALIFICATION_DOCUMENT_REQUIRED");
  var paths=Value(row,"loaded_paths") as IEnumerable<string>;Require(Is(row,"loaded_document_typed",true)&&paths!=null&&paths.Count()==1&&Key(paths.Single())==Key(q.Copy),"SOLE_QUALIFICATION_DOCUMENT_PATH_CHANGED");
 }
 internal static void ValidateCamContext(Request q,Dictionary<string,object> row,uint expectedFeatureId,Action recorded){
  recorded();Require(Is(row,"present",true),"CAM_ACTIVE_DOCUMENT_ABSENT");Require(Is(row,"document_type",1),"CAM_DOCUMENT_TYPE_CHANGED");
  Require(Is(row,"configuration_present",true),"CAM_CONFIGURATION_ABSENT");Require(Is(row,"active_configuration",q.CamConfig)&&Is(row,"cam_configuration",q.CamConfig)&&Is(row,"sw_configuration",q.SwConfig),"CAM_CONFIGURATION_CHANGED");
  Require(Is(row,"machine_present",true)&&Is(row,"machine_type",1),"CAM_MILL_MACHINE_CHANGED");
  Require(Is(row,"setup_collection_present",true)&&Is(row,"setup_count",1)&&Is(row,"setup_present",true),"CAM_EXACT_SETUP_REQUIRED");Require(Is(row,"setup_id_returned",true)&&Is(row,"setup_id",q.SetupId),"CAM_SETUP_NATIVE_ID_CHANGED");
  Require(Is(row,"axis_native",q.Axis),"CAM_SETUP_AXIS_CHANGED");Require(Is(row,"origin_native",q.Origin),"CAM_SETUP_ORIGIN_CHANGED");
  int featureCount=expectedFeatureId==0?0:1;var expectedIds=expectedFeatureId==0?new uint[0]:new[]{expectedFeatureId};
  Require(Is(row,"feature_collection_present",true)&&Is(row,"feature_count",featureCount)&&Is(row,"feature_count_after",featureCount)&&Is(row,"feature_ids",expectedIds)&&(featureCount==0||Is(row,"feature_present",true)&&Is(row,"feature_id_returned",true)),"CAM_FEATURE_MEMBERSHIP_CHANGED");
  Require(Is(row,"operation_setup_collection_present",true)&&Is(row,"operation_setup_count",1)&&Is(row,"operation_setup_present",true),"CAM_EXACT_OPERATION_SETUP_REQUIRED");Require(Is(row,"operation_setup_id_returned",true)&&Is(row,"operation_setup_id",q.OpSetupId),"CAM_OPERATION_SETUP_NATIVE_ID_CHANGED");
  Require(Is(row,"operation_collection_present",true)&&Is(row,"operation_count",0),"CAM_EMPTY_OPERATIONS_REQUIRED");Require(Is(row,"setup_count_after",1)&&Is(row,"operation_setup_count_after",1),"CAM_SETUP_COLLECTION_DRIFT");
 }
 internal static Dictionary<string,object> Run(Request q,IBackend backend,Dictionary<string,object> r){bool receipt=false;int id=0;var clock=Stopwatch.StartNew();Action persist=()=>Persist(q.Receipt,r,false);var actions=(List<Dictionary<string,object>>)r["actions"];Dictionary<string,object> active=null;
  try{
   Require(!File.Exists(q.Marker)&&!File.Exists(q.Receipt),"ATTEMPT_OR_RECEIPT_EXISTS");Files(q);r["island_count_limit"]=q.Limit;Persist(q.Receipt,r,true);receipt=true;
   r["stage"]="preflight";backend.Prepare();backend.Boundary(true);r["before"]=backend.Capture();CadEqual(q.Cad,(Dictionary<string,object>)((Dictionary<string,object>)r["before"])["cad_fingerprint"],false);backend.Quiet();Files(q);persist();
   Persist(q.Marker,new Dictionary<string,object>{{"scope",Scope},{"status","claimed_no_replay"},{"copy",q.Copy},{"sha256",q.Sha},{"receipt",q.Receipt},{"process_id",q.Pid},{"process_creation_time",q.Created},{"island_count_limit",q.Limit},{"actions",new[]{"CreateMillFeature2"}.Concat(q.Islands.Take(q.Limit).Select(n=>"AddIslandToFeature:"+n)).ToArray()}},true);
   r["stage"]="CreateMillFeature2";active=new Dictionary<string,object>{{"name","CreateMillFeature2"},{"attempted",true},{"pending",true},{"returned",false}};actions.Add(active);r["mutation_attempted"]=true;r["create_attempted"]=true;r["native_dispatch_pending"]=true;persist();
   // Exact locally returned object stays in this owner STA; no external feature interface is accepted.
   object localFeature=backend.Create();active["returned"]=true;active["pending"]=false;active["return_is_object"]=localFeature!=null;active=null;r["create_returned"]=true;r["native_dispatch_pending"]=false;persist();Require(localFeature!=null,"FACTORY_RETURNED_NULL");
   id=backend.Identify(localFeature);r["new_feature_native_id"]=id;backend.Boundary(false);backend.Quiet();Files(q);r["after_create_header"]=backend.Header(id);VerifyHeader(q,(Dictionary<string,object>)r["after_create_header"],0);persist();
   var headers=new List<Dictionary<string,object>>();r["after_add_headers"]=headers;
   for(int islandIndex=0;islandIndex<q.Limit;islandIndex++){
    backend.Boundary(false);backend.Quiet();Files(q);r["stage"]="AddIslandToFeature:"+q.Islands[islandIndex];active=new Dictionary<string,object>{{"name",r["stage"]},{"attempted",true},{"pending",true},{"returned",false}};actions.Add(active);r["add_attempted"]=true;r["native_dispatch_pending"]=true;persist();
    bool added=backend.Add(localFeature,islandIndex);active["returned"]=true;active["pending"]=false;active["return_value"]=added;active=null;r["add_return_value"]=added;r["native_dispatch_pending"]=false;persist();Require(added,"ADD_ISLAND_RETURNED_FALSE");
    r["stage"]="readback_after_island_"+(islandIndex+1);backend.Boundary(false);backend.Quiet();Files(q);var h=backend.Header(id);headers.Add(h);persist();VerifyHeader(q,h,islandIndex+1);
   }
   r["add_returned"]=true;r["bounded_chain_readback"]=backend.Chains(id,q.Limit+1);r["after"]=backend.Capture();CadEqual(q.Cad,(Dictionary<string,object>)((Dictionary<string,object>)r["after"])["cad_fingerprint"],false);backend.Boundary(false);backend.Quiet();Files(q);r["source_unchanged"]=true;r["readback_verified"]=true;r["status"]="islands_observed_ram_only";r["stage"]="finished";
  }catch(Exception e){if(active!=null){active["exception"]=new Dictionary<string,object>{{"type",e.GetType().FullName},{"hresult",e.HResult},{"message",e.Message}};}Error(r,e);
   // No mutation replay: one separate fresh lookup/header attempt after a dispatched failure.
   if(receipt&&(bool)r["mutation_attempted"]&&id>0){try{persist();backend.Boundary(false);backend.Quiet();Files(q);r["failure_readback_attempted"]=true;persist();r["failure_header"]=backend.Header(id);r["failure_snapshot"]=backend.Capture();Files(q);r["failure_readback_returned"]=true;r["source_unchanged"]=true;}catch(Exception read){r["failure_readback_error"]=new Dictionary<string,object>{{"type",read.GetType().FullName},{"hresult",read.HResult},{"message",read.Message}};}}
  }finally{try{backend.Dispose();}catch(Exception e){r["cleanup_error"]=e.Message;Error(r,e);}r["messages"]=backend.Messages;if((bool)r["readback_verified"]){var m=backend.Messages as Dictionary<string,object>;if(m==null||!m.ContainsKey("disconnected")||!Same(m["disconnected"],true)||!m.ContainsKey("event_count")||!Same(m["event_count"],0)||!Same(m["callback_error_count"],0)||!Same(m["overflow"],0)){r["status"]="uncertain";r["readback_verified"]=false;r["cleanup_error"]="FINAL_EVENT_STATE_NOT_QUIET";}}r["elapsed_ms"]=clock.Elapsed.TotalMilliseconds;if(receipt)persist();}
  return r;
 }
 internal static string Execute(ISldWorks app,int owner,string text){var r=Initial();try{var q=Parse(text);r["request_binding"]=Json().DeserializeObject(text);Status(app,owner);Require(q.Mvid==typeof(IslandAddin).Module.ModuleVersionId.ToString(),"HOST_MVID_MISMATCH");r["owner_thread_id"]=owner;r["current_thread_id"]=Thread.CurrentThread.ManagedThreadId;r["apartment"]=Thread.CurrentThread.GetApartmentState().ToString();Run(q,new NativeBackend(app,q,r),r);}catch(Exception e){Error(r,e);}return Json().Serialize(r);}
 internal sealed class NativeBackend:IBackend {
  readonly ISldWorks app;readonly Request q;IModelDoc2 model;ICWApp4 cam;ICWDoc3 doc;ICWMachine machine;ICWSetup setup;ICWBaseSetup baseSetup;Messages events;object locallyCreated;uint localId;int nextIsland;
  internal NativeBackend(ISldWorks a,Request r,Dictionary<string,object> result){app=a;q=r;receipt=result;}
  // These observations are logical-context evidence, not COM wrapper identity claims.
  readonly Dictionary<string,object> receipt;
  readonly List<Dictionary<string,object>> boundaryRows=new List<Dictionary<string,object>>();
  void FlushBoundary(){receipt["boundary_observations"]=boundaryRows;Persist(q.Receipt,receipt,false);}
  void SwBoundary(Dictionary<string,object> row){
   row["read_stage"]="process";row["process_id"]=Process.GetCurrentProcess().Id;row["application_process_id"]=app.GetProcessID();row["process_creation_time"]=Created();
   row["read_stage"]="active_document";model=app.ActiveDoc as IModelDoc2;row["active_present"]=model!=null;
   if(model!=null){row["document_type"]=model.GetType();row["path"]=model.GetPathName();row["sw_configuration"]=model.ConfigurationManager.ActiveConfiguration.Name;row["needs_save"]=model.GetSaveFlag();}
   row["read_stage"]="loaded_documents";var loaded=app.GetDocuments() as Array;row["loaded_collection_valid"]=loaded!=null&&loaded.Rank==1;row["loaded_count"]=loaded==null?-1:loaded.Length;
   var paths=new List<string>();row["loaded_paths"]=paths;
   // A second loaded source/copy could have identical CAM IDs. Reject it without reading its CAM data.
   if(loaded!=null&&loaded.Rank==1&&loaded.Length==1){var only=loaded.GetValue(0) as IModelDoc2;row["loaded_document_typed"]=only!=null;if(only!=null)paths.Add(only.GetPathName());}
   row["read_stage"]="returned";
  }
  Dictionary<string,object> ReadCamContext(object raw,Dictionary<string,object> row){
   row["present"]=raw!=null;if(raw==null)return row;
   row["read_stage"]="document_interface";var contextDoc=(ICWDoc3)raw;
   row["read_stage"]="document_type";int type=contextDoc.GetDocType();row["document_type"]=type;if(type!=1)return row;
   row["read_stage"]="configuration";var config=(ICWConfiguration)contextDoc.GetActiveConfiguration();row["configuration_present"]=config!=null;if(config==null)return row;
   row["active_configuration"]=contextDoc.GetActiveConfigurationName();row["cam_configuration"]=config.ConfigurationName;row["sw_configuration"]=config.SWConfigurationName;
   if((string)row["active_configuration"]!=q.CamConfig||(string)row["cam_configuration"]!=q.CamConfig||(string)row["sw_configuration"]!=q.SwConfig)return row;
   row["read_stage"]="machine";var contextMachine=(ICWMachine)((ICWPartDoc)raw).IGetMachine();row["machine_present"]=contextMachine!=null;if(contextMachine==null)return row;
   row["machine_type"]=contextMachine.MachType;if((int)row["machine_type"]!=1)return row;
   row["read_stage"]="setup_collection";var owners=(ICWDispatchCollection)contextMachine.IGetEnumSetups();row["setup_collection_present"]=owners!=null;if(owners==null)return row;
   row["setup_count"]=owners.Count;if((int)row["setup_count"]!=1)return row;
   object owner=owners.Item(0);row["setup_present"]=owner!=null;if(owner==null)return row;
   uint id=0;row["read_stage"]="setup_id";row["setup_id_returned"]=contextDoc.GetCWObjectID(owner,out id);row["setup_id"]=id;if(!(bool)row["setup_id_returned"]||id!=q.SetupId)return row;
   var contextSetup=(ICWBaseSetup)owner;row["read_stage"]="setup_axis";object axisRaw=contextSetup.Axis;row["axis_representation"]=axisRaw==null?"null":axisRaw.GetType().FullName;row["axis_native"]=Vec(axisRaw);row["read_stage"]="setup_origin";row["origin_reader"]="ICWSetup.GetReferencePosition";row["origin_representation"]="three_out_double";row["origin_native"]=SetupOrigin((ICWSetup)owner);
   row["read_stage"]="feature_collection";var features=(ICWDispatchCollection)contextSetup.IGetEnumFeatures();row["feature_collection_present"]=features!=null;if(features==null)return row;
   int featureCount=features.Count;row["feature_count"]=featureCount;var ids=new List<uint>();row["feature_ids"]=ids;if(featureCount<0||featureCount>1)return row;
   if(featureCount==1){object feature=features.Item(0);row["feature_present"]=feature!=null;if(feature==null)return row;id=0;row["read_stage"]="feature_id";row["feature_id_returned"]=contextDoc.GetCWObjectID(feature,out id);ids.Add(id);if(!(bool)row["feature_id_returned"]||id==0)return row;}
   row["feature_count_after"]=features.Count;
   row["read_stage"]="operation_setup_collection";var ops=(ICWDispatchCollection)contextMachine.IGetEnumOpSetups();row["operation_setup_collection_present"]=ops!=null;if(ops==null)return row;
   row["operation_setup_count"]=ops.Count;if((int)row["operation_setup_count"]!=1)return row;
   object op=ops.Item(0);row["operation_setup_present"]=op!=null;if(op==null)return row;id=0;row["read_stage"]="operation_setup_id";row["operation_setup_id_returned"]=contextDoc.GetCWObjectID(op,out id);row["operation_setup_id"]=id;if(!(bool)row["operation_setup_id_returned"]||id!=q.OpSetupId)return row;
   row["read_stage"]="operation_collection";var operations=(ICWDispatchCollection)((ICWBaseOpSetup)op).IGetEnumOperations();row["operation_collection_present"]=operations!=null;if(operations==null)return row;row["operation_count"]=operations.Count;
   row["setup_count_after"]=owners.Count;row["operation_setup_count_after"]=ops.Count;row["read_stage"]="returned";return row;
  }
  public void Boundary(bool clean){
   Require(boundaryRows.Count<64,"BOUNDARY_OBSERVATION_LIMIT");var row=new Dictionary<string,object>{{"index",boundaryRows.Count},{"clean_required",clean},{"status","pending"}};boundaryRows.Add(row);FlushBoundary();
   try{
    row["read_stage"]="sw_before";var before=new Dictionary<string,object>();row["sw_before"]=before;SwBoundary(before);ValidateSwBoundary(q,before,clean,FlushBoundary);
    if(doc!=null){
     row["read_stage"]="active_cam_document";object fresh=cam.IGetActiveDoc();row["fresh_present"]=fresh!=null;row["reference_equals_retained_telemetry"]=Object.ReferenceEquals(doc,fresh);FlushBoundary();
     var freshContext=new Dictionary<string,object>();row["fresh_cam"]=freshContext;row["read_stage"]="fresh_cam_context";ReadCamContext(fresh,freshContext);ValidateCamContext(q,freshContext,localId,FlushBoundary);
     var retainedContext=new Dictionary<string,object>();row["retained_cam"]=retainedContext;row["read_stage"]="retained_cam_context";ReadCamContext(doc,retainedContext);ValidateCamContext(q,retainedContext,localId,FlushBoundary);
    }
    row["read_stage"]="sw_after";var after=new Dictionary<string,object>();row["sw_after"]=after;SwBoundary(after);ValidateSwBoundary(q,after,clean,FlushBoundary);Quiet();row["status"]="verified";row["read_stage"]="returned";FlushBoundary();
   }catch(Exception error){row["status"]="error";row["exception"]=new Dictionary<string,object>{{"type",error.GetType().FullName},{"hresult",error.HResult},{"message",error.Message}};FlushBoundary();throw;}
  }
  static object[] Items(object value,int max){Require(value!=null,"NULL_COLLECTION");var c=(ICWDispatchCollection)value;int n=c.Count;Require(n>=0&&n<=max,"COLLECTION_BOUND");var values=new object[n];for(int i=0;i<n;i++){values[i]=c.Item(i);Require(values[i]!=null,"NULL_ITEM");}Require(c.Count==n,"COLLECTION_DRIFT");return values;}
  uint Id(object value){uint id=0;Require(value!=null&&doc.GetCWObjectID(value,out id)&&id>0,"OBJECT_ID_FAILED");return id;}
  // Axis is a public VARIANT (observed Double[]); point/normal getters return interfaces.
  // Decode only these two explicit representations, without fitting, normalization or retry.
  internal static double CoordinateScalar(object value){Require(value is double||value is float||value is decimal||value is sbyte||value is byte||value is short||value is ushort||value is int||value is uint||value is long||value is ulong,"COORDINATE_SCALAR_TYPE");double number=Convert.ToDouble(value);Require(!Double.IsNaN(number)&&!Double.IsInfinity(number),"COORDINATE_NONFINITE");return number;}
  internal static double[] CoordinateArray(object raw){var values=raw as Array;Require(values!=null&&values.Rank==1&&values.Length==3,"COORDINATE_ARRAY_SHAPE");int first=values.GetLowerBound(0);return new[]{CoordinateScalar(values.GetValue(first)),CoordinateScalar(values.GetValue(first+1)),CoordinateScalar(values.GetValue(first+2))};}
  internal static double[] Vec(object raw){if(raw is Array)return CoordinateArray(raw);var vector=raw as ICWUnitVector;Require(vector!=null,"NATIVE_VECTOR_REPRESENTATION:"+(raw==null?"null":raw.GetType().FullName));double x,y,z;vector.GetCoordinates(out x,out y,out z);return CoordinateArray(new[]{x,y,z});}
  internal static double[] Pos(object raw){if(raw is Array)return CoordinateArray(raw);var point=raw as ICWPosition;Require(point!=null,"NATIVE_POSITION_REPRESENTATION:"+(raw==null?"null":raw.GetType().FullName));double x,y,z;point.GetCoordinates(out x,out y,out z);return CoordinateArray(new[]{x,y,z});}
  // Setup origin offsets are distinct from ICWBaseSetup.IGetRefPoint reference geometry.
  internal static double[] SetupOrigin(ICWSetup mill){Require(mill!=null,"MILL_SETUP_REQUIRED_FOR_ORIGIN");double x,y,z;mill.GetReferencePosition(out x,out y,out z);return CoordinateArray(new[]{x,y,z});}
  public void Prepare(){Boundary(true);dynamic bridge=app.GetAddInObject(CamClass);Require(bridge!=null,"CAM_ADDIN_ABSENT");object raw=bridge.GetCWApp();cam=(ICWApp4)raw;object active=cam.IGetActiveDoc();Require(active!=null,"CAM_ACTIVE_DOCUMENT_ABSENT");doc=(ICWDoc3)active;machine=(ICWMachine)((ICWPartDoc)active).IGetMachine();Require(machine!=null&&machine.MachType==1,"MILL_MACHINE_REQUIRED");events=new Messages(((ICWApp)raw).IGetEventNotifier());events.Subscribe();Boundary(true);var owners=Items(machine.IGetEnumSetups(),1);Require(owners.Length==1&&Id(owners[0])==q.SetupId,"EXACT_SETUP_REQUIRED");setup=(ICWSetup)owners[0];baseSetup=(ICWBaseSetup)owners[0];Require(Same(Vec(baseSetup.Axis),q.Axis)&&Same(SetupOrigin(setup),q.Origin),"SETUP_AXIS_OR_ORIGIN_CHANGED");Require(Items(baseSetup.IGetEnumFeatures(),1).Length==0,"EMPTY_CAM_FEATURES_REQUIRED");var ops=Items(machine.IGetEnumOpSetups(),1);Require(ops.Length==1&&Id(ops[0])==q.OpSetupId&&Items(((ICWBaseOpSetup)ops[0]).IGetEnumOperations(),1).Length==0,"EMPTY_OPERATION_SETUP_REQUIRED");ReadSketches();Quiet();}
  object ReadSketches(){var result=new List<Dictionary<string,object>>();foreach(string n in new[]{q.Outer}.Concat(q.Islands)){var f=(IFeature)((IPartDoc)model).FeatureByName(n);Require(f!=null&&f.Name==n&&f.GetTypeName2()=="ProfileFeature","NAMED_SKETCH_REQUIRED");var s=(ISketch)f.GetSpecificFeature2();Require(s!=null,"SKETCH_INTERFACE_REQUIRED");var segments=s.GetSketchSegments() as Array;Require(segments!=null&&segments.Length==(n==q.Outer?1:4),"SKETCH_SEGMENT_COUNT");var transform=(IMathTransform)s.ModelToSketchTransform;var data=(double[])transform.ArrayData;Require(data.Length==16&&Near(data,new[]{1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,-0.0258,1.0,0.0,0.0,0.0},1e-10),"SKETCH_PLANE_CHANGED");var types=segments.Cast<object>().Select(x=>((ISketchSegment)x).GetType()).OrderBy(x=>x).ToArray();Require(types.SequenceEqual(n==q.Outer?new[]{1}:new[]{0,0,1,1}),"SKETCH_SEGMENT_TYPES_CHANGED");result.Add(new Dictionary<string,object>{{"name",n},{"segment_count",segments.Length},{"segment_types",types},{"model_to_sketch_transform",data}});}return result;}
  Dictionary<string,object> Cad(){var tree=new List<Dictionary<string,object>>();var f=model.FirstFeature() as IFeature;while(f!=null){Require(tree.Count<256,"CAD_TREE_LIMIT");tree.Add(new Dictionary<string,object>{{"name",f.Name},{"type",f.GetTypeName2()}});f=f.GetNextFeature() as IFeature;}var bodies=((IPartDoc)model).GetBodies2(0,false) as Array;Require(bodies!=null&&bodies.Length==1,"SINGLE_SOLID_REQUIRED");var solids=new List<Dictionary<string,object>>();foreach(IBody2 body in bodies){solids.Add(new Dictionary<string,object>{{"box_m",(double[])body.GetBodyBox()},{"mass_raw",(double[])body.GetMassProperties(1)}});}return new Dictionary<string,object>{{"feature_tree",tree},{"solids",solids}};}
  public Dictionary<string,object> Capture(){Boundary(false);var fs=Items(machine.IGetEnumSetups(),1);Require(fs.Length==1&&Id(fs[0])==q.SetupId,"SETUP_DRIFT");var features=Items(((ICWBaseSetup)fs[0]).IGetEnumFeatures(),1);var os=Items(machine.IGetEnumOpSetups(),1);Require(os.Length==1&&Id(os[0])==q.OpSetupId,"OP_SETUP_DRIFT");var operations=Items(((ICWBaseOpSetup)os[0]).IGetEnumOperations(),1);Require(operations.Length==0,"UNEXPECTED_OPERATION");if(locallyCreated==null)Require(features.Length==0,"PREEXISTING_FEATURE");else Require(features.Length==1&&Id(features[0])==localId,"UNEXPECTED_FEATURE_DELTA");return new Dictionary<string,object>{{"path",model.GetPathName()},{"needs_save",model.GetSaveFlag()},{"sw_configuration",q.SwConfig},{"cam_configuration",q.CamConfig},{"feature_count",features.Length},{"feature_ids",features.Select(Id).ToArray()},{"operation_count",0},{"cad_fingerprint",Cad()},{"sketches",ReadSketches()}};}
  public object Create(){Require(locallyCreated==null,"LOCAL_FACTORY_ALREADY_USED");locallyCreated=setup.CreateMillFeature2(0,q.Outer,false,q.Depth,false,false,false,false,0.0,-1,false,0,(CWFeatureCreationCriteriaType_e)0);return locallyCreated;}
  public int Identify(object feature){Require(Object.ReferenceEquals(feature,locallyCreated),"FACTORY_LOCAL_OBJECT_CHANGED");localId=Id(feature);return checked((int)localId);}
  public bool Add(object sameFeature,int index){Require(Object.ReferenceEquals(sameFeature,locallyCreated)&&localId>0&&index==nextIsland&&index<q.Limit,"ADD_REQUIRES_SAME_LOCAL_FACTORY_OBJECT_AND_SEQUENCE");nextIsland++;return setup.AddIslandToFeature(sameFeature,q.Islands[index]);}
  object Fresh(int id){object raw=null;Require(doc.GetCWObjectFromID((CW_OBJECT_TYPE_e)1,(uint)id,out raw)&&raw!=null&&Id(raw)==id,"FRESH_FEATURE_LOOKUP_FAILED");return raw;}
  static string[] Names(object raw){if(raw is string)return new[]{(string)raw};var a=raw as Array;Require(a!=null&&a.Rank==1&&a.Length<=5,"PROFILE_NAME_BOUND");return a.Cast<object>().Select(x=>Text(x,1024)).ToArray();}
  public Dictionary<string,object> Header(int id){Boundary(false);object raw=Fresh(id);var b=(ICWFeature)raw;var m=(ICWMillFeature)raw;var p=(ICWProfileFeature)raw;var h=new Dictionary<string,object>{{"native_id",id},{"owner_setup_native_id",Id(b.GetOwner())},{"suppressed",b.Suppressed},{"volume_type",m.VolumeType},{"shape",m.Shape},{"axis_native",Vec(b.Axis)},{"depth_native",Number(m.Depth)},{"taper_angle_native",Number(m.IGetTaperAngle())},{"island_count",m.IGetIslandCount()},{"sketch_count",p.GetSketchCount()},{"sketch_names",Names(p.GetSketchNameList())}};Quiet();return h;}
  public object Chains(int id,int count){Require(count==q.Limit+1,"FIXED_CHAIN_BOUND");var p=(ICWProfileFeature)Fresh(id);var rows=new List<Dictionary<string,object>>();for(int i=0;i<count;i++){Boundary(false);string name=i==0?q.Outer:q.Islands[i-1];Require(Same(Names(p.GetSketchNameListAt(i)),new[]{name}),"INDEXED_PROFILE_NAME_MISMATCH");var chain=(ICWSegChain)p.GetSegmentChain(i);Require(chain!=null&&chain.IGetNumChains()==1,"ONE_CHAIN_REQUIRED");int n=chain.GetNumOfCurves();Require(n==(i==0?1:4),"EXACT_CURVE_COUNT");var curves=new List<Dictionary<string,object>>();for(int j=0;j<n;j++){int index=j;var raw=chain.GetCurveAtIndex(ref index);Require(index==j&&raw!=null,"CURVE_INDEX_CHANGED");var c=(ICWCurve)raw;int kind=c.GetTypeOfCurve();var row=new Dictionary<string,object>{{"index",j},{"curve_type",kind}};if(kind==0){row["start_native"]=Pos(c.GetStart());row["end_native"]=Pos(c.GetEnd());}else if(kind==1){var arc=(ICWArc)raw;row["start_native"]=Pos(c.GetStart());row["end_native"]=Pos(c.GetEnd());row["mid_native"]=Pos(c.GetMid());row["centre_native"]=Pos(arc.CenterPoint());row["radius_native"]=Number(arc.IGetRadius());row["normal_native"]=Vec(arc.IGetNormal());row["sense_raw"]=arc.IGetSense();}else if(kind==2){var circle=(ICWCircle)raw;row["centre_native"]=Pos(circle.CenterPoint());row["radius_native"]=Number(circle.GetRadius());row["normal_native"]=Vec(circle.IGetNormal());row["direction_raw"]=circle.GetDirection();}else throw new InvalidOperationException("ANALYTIC_CURVES_ONLY");curves.Add(row);}Require(chain.GetNumOfCurves()==n&&chain.IGetNextChain()==null&&chain.IGetNumChains()==1,"CHAIN_CHANGED_OR_EXTRA");rows.Add(new Dictionary<string,object>{{"native_index",i},{"name",name},{"curves",curves},{"read_complete",true}});}Quiet();return new Dictionary<string,object>{{"indexed_chains",rows},{"read_complete",true},{"physical_geometry_verified",false},{"universal_index_base_verified",false}};}
  public void Quiet(){if(events!=null)events.Quiet();}public object Messages{get{return events==null?new Dictionary<string,object>{{"subscribed",false},{"disconnected",false}}:events.Summary();}}public void Dispose(){if(events!=null)events.Dispose();}
 }
}
[ComVisible(true),Guid("43BEBF37-6F28-4F0D-8F92-78D11261D48B"),ClassInterface(ClassInterfaceType.None)]
public sealed class IslandMessageSink:_IDialogEvents {readonly Messages owner;internal IslandMessageSink(Messages o){owner=o;}public void CWMsg(int type,int id,string text){try{owner.Record(type,id,text);}catch{owner.CallbackFailed();}}}
internal sealed class Messages:IDisposable {
 static readonly List<Messages> failedConnections=new List<Messages>();
 readonly object notifier;readonly IslandMessageSink sink;System.Runtime.InteropServices.ComTypes.IConnectionPoint point;int cookie,count,overflow,callbackErrors;bool subscribed,disconnected;string cleanup;readonly List<Dictionary<string,object>> rows=new List<Dictionary<string,object>>();
 internal Messages(object value){Qualification.Require(value!=null,"EVENT_NOTIFIER_ABSENT");notifier=value;sink=new IslandMessageSink(this);}
 internal void Subscribe(){lock(failedConnections){Qualification.Require(failedConnections.Count==0,"PRIOR_EVENT_CLEANUP_UNCERTAIN");}var iid=new Guid("7532C711-3BC4-11D6-A9AF-00062999E55F");((System.Runtime.InteropServices.ComTypes.IConnectionPointContainer)notifier).FindConnectionPoint(ref iid,out point);Qualification.Require(point!=null,"EVENT_CONNECTION_POINT_ABSENT");point.Advise(sink,out cookie);subscribed=true;}
 internal void Record(int type,int id,string text){lock(rows){count++;if(rows.Count>=100){overflow++;return;}text=text??"";rows.Add(new Dictionary<string,object>{{"message_type",type},{"message_id",id},{"message",text.Substring(0,Math.Min(1000,text.Length))},{"response","default_unknown"}});}}
 internal void CallbackFailed(){Interlocked.Increment(ref callbackErrors);}internal void Quiet(){Qualification.Require(subscribed&&!disconnected&&count==0&&overflow==0&&callbackErrors==0,"CAM_EVENT_OR_CALLBACK_ERROR");}
 internal object Summary(){return new Dictionary<string,object>{{"subscribed",subscribed},{"disconnected",disconnected},{"active",subscribed&&!disconnected},{"event_count",count},{"events",rows},{"overflow",overflow},{"callback_error_count",callbackErrors},{"cleanup_error",cleanup},{"policy","vendor_default"}};}
 public void Dispose(){if(subscribed&&!disconnected){try{point.Unadvise(cookie);disconnected=true;}catch(Exception e){cleanup=e.Message;lock(failedConnections)failedConnections.Add(this);throw;}}}
}
}