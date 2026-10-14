using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;

// 只允许在 MCP 进程锁内调用；不启动、不保存、不关闭文档。
public static class NativeFrameCut {
 public class Spec { public double[] origin_mm,x_axis,y_axis,center_mm; public double width_mm,height_mm,radius_mm,depth_mm; public bool along_normal; public string feature_name; }
 public class Request { public int process_id; public string source; public Spec spec; }
 static JavaScriptSerializer json=new JavaScriptSerializer { MaxJsonLength=int.MaxValue };
 [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out System.Runtime.InteropServices.ComTypes.IRunningObjectTable table);
 [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out System.Runtime.InteropServices.ComTypes.IBindCtx context);
 static ISldWorks Bind(int pid) {
  if(pid<=0)throw new Exception("Explicit PID required");
  System.Runtime.InteropServices.ComTypes.IRunningObjectTable table; System.Runtime.InteropServices.ComTypes.IBindCtx context;
  GetRunningObjectTable(0,out table);CreateBindCtx(0,out context);
  System.Runtime.InteropServices.ComTypes.IEnumMoniker enumerator;table.EnumRunning(out enumerator);
  var moniker=new System.Runtime.InteropServices.ComTypes.IMoniker[1];
  while(enumerator.Next(1,moniker,IntPtr.Zero)==0){string name;moniker[0].GetDisplayName(context,null,out name);if(name!="SolidWorks_PID_"+pid)continue;object value;table.GetObject(moniker[0],out value);var app=(ISldWorks)value;if(app.GetProcessID()!=pid)throw new Exception("PID mismatch");return app;}
  throw new Exception("Requested process unavailable");
 }
 static double[] World(Spec s,double x,double y){return Enumerable.Range(0,3).Select(i=>(s.origin_mm[i]+x*s.x_axis[i]+y*s.y_axis[i])/1000).ToArray();}
 static double[] Local(IMathUtility math,MathTransform tr,Spec s,double x,double y){return (double[])((IMathPoint)((IMathPoint)math.CreatePoint(World(s,x,y))).MultiplyTransform(tr)).ArrayData;}
 static void Guard(ISldWorks sw,string path){var m=(IModelDoc2)sw.ActiveDoc;if(m==null||m.GetType()!=1||!String.Equals(Path.GetFullPath(m.GetPathName()),Path.GetFullPath(path),StringComparison.OrdinalIgnoreCase))throw new Exception("Document target mismatch");}
 static double Volume(IModelDoc2 model){return ((IMassProperty)model.Extension.CreateMassProperty()).Volume*1e9;}
 public static string Run(string input){
  var req=json.Deserialize<Request>(input);var sw=Bind(req.process_id);Guard(sw,req.source);var m=(IModelDoc2)sw.ActiveDoc;var s=req.spec;
  if(m.IsOpenedReadOnly())throw new Exception("Read-only part cannot be modified");
  if(m.GetActiveSketch2()!=null)throw new Exception("Exit active sketch first");
  if(((IPartDoc)m).FeatureByName(s.feature_name)!=null||((IPartDoc)m).FeatureByName(s.feature_name+"_PLANE")!=null)throw new Exception("Feature name already exists");
  double before=Volume(m);int bodiesBefore=((object[])((IPartDoc)m).GetBodies2(0,false)).Length;
  m.ClearSelection2(true);
  var plane=(IRefPlane)m.CreatePlaneFixed2(World(s,0,0),World(s,10,0),World(s,0,10),false);
  if(plane==null)throw new Exception("Reference plane creation failed");
  var pf=(IFeature)m.FeatureByPositionReverse(0);pf.Name=s.feature_name+"_PLANE";
  m.ClearSelection2(true);if(!pf.Select2(false,0))throw new Exception("Plane selection failed");
  var sk=m.SketchManager;sk.InsertSketch(true);var active=(ISketch)sk.ActiveSketch;if(active==null)throw new Exception("No active sketch");
  var tr=(MathTransform)active.ModelToSketchTransform;var math=(IMathUtility)sw.GetMathUtility();
  var normal=new[]{s.x_axis[1]*s.y_axis[2]-s.x_axis[2]*s.y_axis[1],s.x_axis[2]*s.y_axis[0]-s.x_axis[0]*s.y_axis[2],s.x_axis[0]*s.y_axis[1]-s.x_axis[1]*s.y_axis[0]};
  var basePoint=Local(math,tr,s,0,0);var tip=(double[])((IMathPoint)((IMathPoint)math.CreatePoint(Enumerable.Range(0,3).Select(i=>(s.origin_mm[i]+normal[i])/1000).ToArray())).MultiplyTransform(tr)).ArrayData;
  if(Math.Abs(basePoint[2])>1e-8||Math.Abs(Math.Abs(tip[2]-basePoint[2])-.001)>1e-8)throw new Exception("Sketch frame validation failed");
  double a=s.center_mm[0]-s.width_mm/2,b=s.center_mm[0]+s.width_mm/2,c=s.center_mm[1]-s.height_mm/2,d=s.center_mm[1]+s.height_mm/2,r=s.radius_mm;
  var segments=new List<ISketchSegment>();
  Action<double,double,double,double> line=(x1,y1,x2,y2)=>{var p=Local(math,tr,s,x1,y1);var q=Local(math,tr,s,x2,y2);var e=(ISketchSegment)sk.CreateLine(p[0],p[1],0,q[0],q[1],0);if(e==null)throw new Exception("Line failed");segments.Add(e);};
  Action<double,double,double,double,double,double> arc=(cx,cy,x1,y1,x2,y2)=>{var o=Local(math,tr,s,cx,cy);var p=Local(math,tr,s,x1,y1);var q=Local(math,tr,s,x2,y2);short sign=(short)((tip[2]>basePoint[2])?1:-1);var e=(ISketchSegment)sk.CreateArc(o[0],o[1],0,p[0],p[1],0,q[0],q[1],0,sign);if(e==null)throw new Exception("Arc failed");segments.Add(e);};
  sk.AddToDB=true;
  try{line(a+r,c,b-r,c);arc(b-r,c+r,b-r,c,b,c+r);line(b,c+r,b,d-r);arc(b-r,d-r,b,d-r,b-r,d);line(b-r,d,a+r,d);arc(a+r,d-r,a+r,d,a,d-r);line(a,d-r,a,c+r);arc(a+r,c+r,a,c+r,a+r,c);}
  finally{sk.AddToDB=false;}
  foreach(var segment in segments){m.ClearSelection2(true);segment.Select4(false,null);m.SketchAddConstraints("sgFIXED");}
  m.ClearSelection2(true);sk.InsertSketch(true);var sf=(IFeature)m.FeatureByPositionReverse(0);sf.Name=s.feature_name+"_PROFILE";
  m.ClearSelection2(true);if(!sf.Select2(false,0))throw new Exception("Profile selection failed");Guard(sw,req.source);
  bool dir=s.along_normal==(tip[2]>basePoint[2]);
  var cut=m.FeatureManager.FeatureCut4(true,false,dir,0,0,s.depth_mm/1000,0,false,false,false,false,0,0,false,false,false,false,false,true,true,false,false,false,0,0,false,false);
  if(cut==null)throw new Exception("Cut creation failed; inspect unsaved datum and sketch");cut.Name=s.feature_name;
  if(!m.ForceRebuild3(false))throw new Exception("Rebuild failed");
  double after=Volume(m);int bodiesAfter=((object[])((IPartDoc)m).GetBodies2(0,false)).Length;
  if(before-after<1e-6||bodiesAfter!=bodiesBefore)throw new Exception("Cut volume or solid count verification failed");
  m.ClearSelection2(true);pf.Select2(false,0);m.BlankRefGeom();m.ClearSelection2(true);m.ViewZoomtofit2();m.GraphicsRedraw2();Guard(sw,req.source);
  return json.Serialize(new{status="ok",feature_name=cut.Name,feature_type=cut.GetTypeName2(),plane_name=pf.Name,plane_definition="fixed frame",sketch_name=sf.Name,sketch_segment_count=segments.Count,fixed_constraints_requested=true,volume_before_mm3=before,volume_after_mm3=after,removed_volume_mm3=before-after,solid_count=bodiesAfter,source_saved=false,requires_export_geometry_verification=true,spec=s});
 }
}
