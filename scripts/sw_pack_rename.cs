using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;

// 仅由受互斥锁保护的 MCP 调用；不启动进程、不切换窗口、不保存或关闭源文件。
public static class NativeNamedCopy {
 public class Entry { public string source, target; }
 public class Request { public int process_id; public string source; public bool dry_run; public Entry[] entries; }
 static JavaScriptSerializer json=new JavaScriptSerializer { MaxJsonLength=int.MaxValue };
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out System.Runtime.InteropServices.ComTypes.IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out System.Runtime.InteropServices.ComTypes.IBindCtx context);
 static string Canon(string p) { return Path.GetFullPath(p).TrimEnd('\\'); }
 static ISldWorks Bind(int pid) {
  if(pid<=0) throw new Exception("Explicit process ID required");
  System.Runtime.InteropServices.ComTypes.IRunningObjectTable table;
  System.Runtime.InteropServices.ComTypes.IBindCtx context;
  GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);
  System.Runtime.InteropServices.ComTypes.IEnumMoniker enumerator;table.EnumRunning(out enumerator);
  var moniker=new System.Runtime.InteropServices.ComTypes.IMoniker[1];
  while(enumerator.Next(1,moniker,IntPtr.Zero)==0) {
   string name;moniker[0].GetDisplayName(context,null,out name);
   if(name!="SolidWorks_PID_"+pid)continue;
   object value;table.GetObject(moniker[0],out value);
   var app=(ISldWorks)value;
   if(app.GetProcessID()!=pid)throw new Exception("Process identity mismatch");
   return app;
  }
  throw new Exception("Requested process is unavailable");
 }
 static void Guard(ISldWorks sw,string source) {
  var active=(IModelDoc2)sw.ActiveDoc;
  if(active==null || !string.Equals(Canon(active.GetPathName()),Canon(source),StringComparison.OrdinalIgnoreCase))throw new Exception("Active document target mismatch");
 }
 public static string Run(string input) {
  var req=json.Deserialize<Request>(input);var sw=Bind(req.process_id);Guard(sw,req.source);
  var model=(IModelDoc2)sw.ActiveDoc;
  if(model.GetType()!=1 && model.GetType()!=2)throw new Exception("Saved part or assembly required");
  var pg=model.Extension.GetPackAndGo();
  pg.IncludeDrawings=false;pg.IncludeSimulationResults=false;pg.IncludeSuppressed=true;pg.IncludeToolboxComponents=true;
  pg.FlattenToSingleFolder=true;pg.AddPrefix="";pg.AddSuffix="";
  object raw;if(!pg.GetDocumentNames(out raw))throw new Exception("Native enumeration failed");
  var names=((object[])raw).Cast<string>().ToArray();
  if(names.Length!=pg.GetDocumentNamesCount())throw new Exception("Incomplete native enumeration");
  var map=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
  var targets=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  foreach(var entry in req.entries) {
   if(!Path.IsPathRooted(entry.source)||!Path.IsPathRooted(entry.target))throw new Exception("Absolute paths required");
   string src=Canon(entry.source),dst=Canon(entry.target);
   if(string.Equals(src,dst,StringComparison.OrdinalIgnoreCase)||map.ContainsKey(src)||!targets.Add(dst))throw new Exception("Duplicate or in-place mapping");
   if(!File.Exists(src)||File.Exists(dst)||!string.Equals(Path.GetExtension(src),Path.GetExtension(dst),StringComparison.OrdinalIgnoreCase))throw new Exception("Invalid source or destination");
   map.Add(src,dst);
  }
  if(names.Length!=map.Count||names.Any(n=>!map.ContainsKey(Canon(n))))throw new Exception("Native names differ from mapping: "+json.Serialize(names));
  var destinations=names.Select(n=>map[Canon(n)]).ToArray();
  var dirty=new List<string>();if(model.GetSaveFlag())dirty.Add(model.GetPathName());
  var components=new List<object>();
  if(model.GetType()==2) {
   var all=(object[])((IAssemblyDoc)model).GetComponents(false);
   foreach(Component2 c in all??new object[0]) {
    var cm=(IModelDoc2)c.GetModelDoc2();if(cm!=null&&cm.GetSaveFlag())dirty.Add(cm.GetPathName());
    components.Add(new { name=c.Name2,path=c.GetPathName(),suppression=c.GetSuppression(),transform=(double[])c.Transform2.ArrayData });
   }
  }
  var mp=(IMassProperty)model.Extension.CreateMassProperty();
  var result=new Dictionary<string,object> {
   {"status",req.dry_run?"ready":"copied"},{"source",model.GetPathName()},{"names",names},{"targets",destinations},
   {"dirty_source_documents",dirty.Distinct().ToArray()},{"components",components},{"volume_m3",mp.Volume},
   {"source_saved",false},{"native_pack_and_go",true},{"backend","csharp_pia"},{"manual_review_required",true},{"cold_open_required",!req.dry_run}
  };
  if(req.dry_run)return json.Serialize(result);
  foreach(var dest in destinations)Directory.CreateDirectory(Path.GetDirectoryName(dest));
  if(!pg.SetDocumentSaveToNames(destinations))throw new Exception("Native mapping rejected");
  Guard(sw,req.source);
  var codes=(int[])model.Extension.SavePackAndGo(pg);
  if(codes==null||codes.Length!=destinations.Length||codes.Any(c=>c!=0)||destinations.Any(p=>!File.Exists(p)))throw new Exception("Native Pack and Go did not complete: "+json.Serialize(codes));
  Guard(sw,req.source);result["status_codes"]=codes;return json.Serialize(result);
 }
}
