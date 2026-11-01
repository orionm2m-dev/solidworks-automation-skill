using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
class NativeReaderTests {
    static int passed; static MethodInfo parse; static JavaScriptSerializer json = new JavaScriptSerializer();
    static Dictionary<string, object> Base() { return new Dictionary<string, object> { {"schema_version",1},{"expected_process_id",47168},{"expected_document_path",@"C:\qualified\part.SLDPRT"},{"cam_addin_clsid","{CCAC6208-0E19-6455-2022-2026CEB541FA}"},{"max_operations",64},{"max_tools",64} }; }
    static void Check(bool value,string name) { if(!value) throw new Exception(name); passed++; }
    static void Reject(string input,string name) { bool rejected=false;try { parse.Invoke(null,new object[]{input}); } catch(TargetInvocationException){rejected=true;} Check(rejected,name); }
    static int Main(string[] args) {
      try {
        string folder=Path.GetDirectoryName(Path.GetFullPath(args[0])); AppDomain.CurrentDomain.AssemblyResolve+=(s,e)=> { string p=Path.Combine(folder,new AssemblyName(e.Name).Name+".dll"); return File.Exists(p)?Assembly.LoadFrom(p):null; };
        var assembly=Assembly.LoadFrom(args[0]); var type=assembly.GetType("CadStudio.SolidWorks.AddinHost.CamBatchReader",true); parse=type.GetMethod("Parse",BindingFlags.NonPublic|BindingFlags.Static);
        Check(parse.Invoke(null,new object[]{json.Serialize(Base())})!=null,"valid request");
        var nc=Base();nc["nc_operation_ids"]=new[]{322,129};Check(parse.Invoke(null,new object[]{json.Serialize(nc)})!=null,"valid NC subset");
        Reject(null,"null");Reject("","empty");Reject(new string('x',16385),"size");Reject("[]","array");Reject("null","json null");
        foreach(var key in Base().Keys) {var r=Base();r.Remove(key);Reject(json.Serialize(r),"missing "+key);}
        foreach(var v in new object[]{false,"47168",0,-1,1.5,2147483648L}) {var r=Base();r["expected_process_id"]=v;Reject(json.Serialize(r),"pid "+v);}
        foreach(var key in new[]{"max_operations","max_tools"}) foreach(var v in new object[]{0,65,true,"8"}) {var r=Base();r[key]=v;Reject(json.Serialize(r),"limit "+key+v);}
        foreach(var v in new object[]{2,true,"1"}) {var r=Base();r["schema_version"]=v;Reject(json.Serialize(r),"schema "+v);}
        foreach(var v in new object[]{"relative.SLDPRT","",null}) {var r=Base();r["expected_document_path"]=v;Reject(json.Serialize(r),"path");}
        var extra=Base();extra["method"]="Save";Reject(json.Serialize(extra),"unknown field");
        var cls=Base();cls["cam_addin_clsid"]="{8EE76E8D-9B47-4DE0-AFA2-B2E36621A134}";Reject(json.Serialize(cls),"foreign COM class");
        foreach(var v in new object[]{new[]{322,322},new[]{0},new[]{-1},new[]{1,2,3,4,5,6,7,8,9},new[]{"322"},true}) {var r=Base();r["nc_operation_ids"]=v;Reject(json.Serialize(r),"NC ids");}
        var iface=assembly.GetType("CadStudio.SolidWorks.AddinHost.ICamBatchReader",true);
        Check(iface.GUID==new Guid("DA9D97F8-EB0E-4D7B-A741-0E1736E899A2"),"interface GUID");
        Check(iface.GetMethods().Length==1 && iface.GetMethods()[0].Name=="ReadTurnSnapshot","one exported reader");
        Check(((DispIdAttribute)iface.GetMethods()[0].GetCustomAttributes(typeof(DispIdAttribute),false)[0]).Value==1,"DISPID");
        var execute=type.GetMethod("Execute",BindingFlags.NonPublic|BindingFlags.Static);
        var failed=(Dictionary<string,object>)json.DeserializeObject((string)execute.Invoke(null,new object[]{null,0,json.Serialize(Base())}));
        Check((string)failed["status"]=="error" && (string)failed["message"]=="HOST_NOT_CONNECTED","not connected rejects before native");
        Check((bool)failed["read_only"] && !(bool)failed["mutation_attempted"] && !(bool)failed["readback_verified"],"error semantics");
        Check((string)failed["host_module_version_id"]==assembly.ManifestModule.ModuleVersionId.ToString(),"MVID");
        Check((string)failed["engine_version"]=="turn-reader-1","engine");
        Console.WriteLine(json.Serialize(new {status="passed",passed=passed,failed=0,native_called=false,host_instantiated=false,module_version_id=assembly.ManifestModule.ModuleVersionId.ToString()}));return 0;
      } catch(Exception e) { Console.Error.WriteLine(e);return 1; }
    }
}
