using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;

// 原生 Pack and Go（PIA 早绑定）：pywin32 IDispatch 拿不到 IPackAndGo 时使用。
// 只绑定显式 PID 的实例；不启动进程、不切换窗口、不保存或关闭源文件。
public static class NativePackAndGo {
 public class Request {
  public int process_id; public string source; public string target;
  public bool include_drawings, include_simulation_results, include_toolbox_components, include_suppressed, flatten;
 }
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
   if(name!="SolidWorks_PID_"+pid&&name!="!SolidWorks_PID_"+pid)continue;
   object value;table.GetObject(moniker[0],out value);
   var app=(ISldWorks)value;
   if(app.GetProcessID()!=pid)throw new Exception("Process identity mismatch");
   return app;
  }
  throw new Exception("Requested process is unavailable");
 }
 static IModelDoc2 Guard(ISldWorks sw,string source) {
  var active=(IModelDoc2)sw.ActiveDoc;
  if(active==null || !string.Equals(Canon(active.GetPathName()),Canon(source),StringComparison.OrdinalIgnoreCase))throw new Exception("Active document target mismatch");
  return active;
 }
 public static string Run(string input) {
  var req=json.Deserialize<Request>(input);
  if(!Path.IsPathRooted(req.source)||!Path.IsPathRooted(req.target))throw new Exception("Absolute paths required");
  var sw=Bind(req.process_id);var model=Guard(sw,req.source);
  if(model.GetType()!=1 && model.GetType()!=2)throw new Exception("Saved part or assembly required");
  var pg=model.Extension.GetPackAndGo();
  if(pg==null)throw new Exception("GetPackAndGo returned null");
  pg.IncludeDrawings=req.include_drawings;pg.IncludeSimulationResults=req.include_simulation_results;
  pg.IncludeToolboxComponents=req.include_toolbox_components;pg.IncludeSuppressed=req.include_suppressed;
  pg.FlattenToSingleFolder=req.flatten;
  object raw;var names=new string[0];
  if(pg.GetDocumentNames(out raw)&&raw!=null)names=((object[])raw).Cast<string>().ToArray();
  if(!pg.SetSaveToName(true,Canon(req.target)+"\\"))throw new Exception("SetSaveToName rejected the target folder");
  Guard(sw,req.source);
  var codes=(int[])model.Extension.SavePackAndGo(pg);
  Guard(sw,req.source);
  var result=new Dictionary<string,object> {
   {"backend","csharp_pia"},{"process_id",req.process_id},{"source",model.GetPathName()},
   {"document_count",pg.GetDocumentNamesCount()},{"names",names},{"status_codes",codes??new int[0]}
  };
  return json.Serialize(result);
 }
}
