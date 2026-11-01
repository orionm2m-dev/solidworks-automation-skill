using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using CamWorks.Interop;
using SolidWorks.Interop.sldworks;

namespace CadStudio.SolidWorks.AddinHost {
[ComVisible(true), Guid("DA9D97F8-EB0E-4D7B-A741-0E1736E899A2"), InterfaceType(ComInterfaceType.InterfaceIsDual)]
public interface ICamBatchReader {
    [DispId(1)] string ReadTurnSnapshot(string requestJson);
}
// Fixed typed getters only: no creation, settings, generation, Save or tool lookup.
[ComVisible(false)]
internal static class CamBatchReader {
    internal const string EngineVersion = "turn-reader-1";
    internal const string CamClass = "{CCAC6208-0E19-6455-2022-2026CEB541FA}";
    private static readonly string[] Fields = { "schema_version", "expected_process_id", "expected_document_path", "cam_addin_clsid", "max_operations", "max_tools" };
    internal sealed class Request { internal int ProcessId, MaxOperations, MaxTools; internal string DocumentPath; internal int[] NcOperationIds = new int[0]; }
    internal static void Require(bool condition, string code) { if (!condition) throw new InvalidOperationException(code); }
    internal static int Integer(object v, int min, int max) { Require(v is int && (int)v >= min && (int)v <= max, "INTEGER_RANGE"); return (int)v; }
    internal static Request Parse(string text) {
        Require(text != null && text.Length > 0 && text.Length <= 16384, "REQUEST_SIZE");
        var serializer = new JavaScriptSerializer { MaxJsonLength = 16384, RecursionLimit = 4 };
        var value = serializer.DeserializeObject(text) as Dictionary<string, object>;
        Require(value != null && (value.Count == Fields.Length || (value.Count == Fields.Length + 1 && value.ContainsKey("nc_operation_ids"))) && Fields.All(value.ContainsKey), "REQUEST_FIELDS");
        Require(value["schema_version"] is int && (int)value["schema_version"] == 1, "SCHEMA_VERSION");
        var r = new Request { ProcessId = Integer(value["expected_process_id"], 1, int.MaxValue), MaxOperations = Integer(value["max_operations"], 1, 64), MaxTools = Integer(value["max_tools"], 1, 64), DocumentPath = value["expected_document_path"] as string };
        Require(!String.IsNullOrWhiteSpace(r.DocumentPath) && r.DocumentPath.Length <= 32767 && Path.IsPathRooted(r.DocumentPath), "DOCUMENT_PATH");
        Require(value["cam_addin_clsid"] is string && String.Equals((string)value["cam_addin_clsid"], CamClass, StringComparison.OrdinalIgnoreCase), "CAM_CLASS");
        if (value.ContainsKey("nc_operation_ids")) {
            var ids = value["nc_operation_ids"] as object[];
            Require(ids != null && ids.Length <= 8, "NC_IDS_LIMIT");
            r.NcOperationIds = ids.Select(x => Integer(x, 1, int.MaxValue)).ToArray();
            Require(r.NcOperationIds.Distinct().Count() == r.NcOperationIds.Length, "NC_IDS_DUPLICATE");
        }
        return r;
    }
    internal static void ValidateConfigurationBinding(string camName, string objectName, string associatedSwName, string expectedSwName) {
        Require(!String.IsNullOrEmpty(camName) && !String.IsNullOrEmpty(objectName) && !String.IsNullOrEmpty(associatedSwName) && !String.IsNullOrEmpty(expectedSwName), "CONFIGURATION_NAME_REQUIRED");
        Require(camName == objectName, "CAM_CONFIGURATION_OBJECT_MISMATCH");
        Require(associatedSwName == expectedSwName, "CAM_SW_CONFIGURATION_MISMATCH");
    }
    private static string Key(string p) { return Path.GetFullPath(p).TrimEnd('\\', '/').Replace('/', '\\').ToUpperInvariant(); }
    private static double Number(double v) { Require(!Double.IsNaN(v) && !Double.IsInfinity(v), "NONFINITE_NUMBER"); return v; }
    private static string Text(string v) { Require(v != null && v.Length <= 4096, "NATIVE_TEXT_LIMIT"); return v; }
    private static Dictionary<string, object> Document(ISldWorks app, Request request) {
        Require(Process.GetCurrentProcess().Id == request.ProcessId && app.GetProcessID() == request.ProcessId, "PROCESS_MISMATCH");
        var doc = app.ActiveDoc as IModelDoc2; Require(doc != null, "NO_ACTIVE_DOCUMENT");
        string path = doc.GetPathName(); Require(!String.IsNullOrEmpty(path) && Key(path) == Key(request.DocumentPath), "DOCUMENT_MISMATCH");
        Require(doc.GetType() == 1, "PART_REQUIRED");
        return new Dictionary<string, object> { { "path", path }, { "title", doc.GetTitle() }, { "type", doc.GetType() }, { "needs_save", doc.GetSaveFlag() }, { "configuration", Text(doc.ConfigurationManager.ActiveConfiguration.Name) } };
    }
    private static object[] Items(object raw, int limit) {
        Require(raw != null, "NULL_COLLECTION"); var collection = (ICWDispatchCollection)raw; int count = collection.Count;
        Require(count >= 0 && count <= limit, "COLLECTION_LIMIT"); var result = new object[count];
        for (int i = 0; i < count; i++) { result[i] = collection.Item(i); Require(result[i] != null, "NULL_COLLECTION_ITEM"); }
        return result;
    }
    private static uint Identity(ICWDoc3 doc, object value) { uint id; Require(doc.GetCWObjectID(value, out id) && id > 0, "NATIVE_ID"); return id; }
    private static Dictionary<string, object> Inventory(ICWMachine machine, ICWDoc3 doc, Request request, Dictionary<uint, ICWTurnOperation> handles) {
        var setups = Items(machine.IGetEnumOpSetups(), 8); var operations = new List<Dictionary<string, object>>(); var ids = new HashSet<uint>();
        for (int si = 0; si < setups.Length; si++) {
            var rawOps = Items(((ICWBaseOpSetup)setups[si]).IGetEnumOperations(), request.MaxOperations - operations.Count);
            for (int oi = 0; oi < rawOps.Length; oi++) {
                var raw = rawOps[oi]; var op = (ICWOperation)raw; var turn = (ICWTurnOperation)raw;
                uint id = Identity(doc, raw); Require(ids.Add(id), "DUPLICATE_OPERATION_ID"); handles.Add(id, turn);
                bool generated = op.GetIsToolpathGenerated(); var counts = new List<int>();
                if (generated) foreach (var rawPath in Items(op.IGetEnumToolpaths(), 64)) { int c = ((ICWToolpath)rawPath).RecordCount; Require(c >= 0, "NEGATIVE_RECORD_COUNT"); counts.Add(c); }
                var features = Items(op.IGetAllFeatures(), 16).Select(x => Identity(doc, x)).ToArray(); Require(features.Distinct().Count() == features.Length, "DUPLICATE_FEATURE_LINK");
                operations.Add(new Dictionary<string, object> { { "setup_index", si }, { "operation_index", oi }, { "native_id", id }, { "turn_operation_type", (int)turn.OpernType }, { "linked_feature_ids", features }, { "suppressed", op.Suppressed }, { "toolpath_generated", generated }, { "toolpath_record_counts", counts } });
            }
        }
        return new Dictionary<string, object> { { "machine_type", 3 }, { "operation_setup_count", setups.Length }, { "operation_count", operations.Count }, { "operations", operations } };
    }
    private static List<Dictionary<string, object>> Tools(ICWMachine machine, ICWDoc3 doc, Request request) {
        var crib = (ICWToolcrib4)machine.IGetToolcrib(); var rows = new List<Dictionary<string, object>>(); var ids = new HashSet<uint>();
        foreach (var raw in Items(crib.GetAllTools(), request.MaxTools)) {
            var tool = (ICWTool)raw; uint id = Identity(doc, raw); Require(ids.Add(id), "DUPLICATE_TOOL_ID");
            var row = new Dictionary<string, object> { { "complete", true }, { "native_id", id }, { "tool_type_raw", tool.ToolType }, { "info_raw", Text(tool.GetToolInfoString()) }, { "candidate", false } }; rows.Add(row);
            if ((int)row["tool_type_raw"] != 15) { row["reason"] = "not_turn_tool"; continue; }
            var turn = (ICWTurnTool)raw; row["turn_tool_type_raw"] = (int)turn.ToolType;
            if ((int)row["turn_tool_type_raw"] != 1) { row["reason"] = "not_insert_holder_no_subtype_probe"; continue; }
            row["insert_type_raw"] = (int)turn.InsertType; object rawHolder = turn.IGetTurnToolHolder(); row["holder_present"] = rawHolder != null;
            if (rawHolder == null) { row["reason"] = "holder_absent"; continue; }
            var holder = (ICWTurnToolHolder)rawHolder; row["holder_type_raw"] = (int)holder.GetHolderType(); row["holder_id_raw"] = holder.GetHolderId();
            bool candidate = (int)row["insert_type_raw"] == 1 && (int)row["holder_type_raw"] == 2; row["candidate"] = candidate;
            if (!candidate) { row["reason"] = "not_diamond_boring_bar"; continue; }
            row["insert_dimensions_native"] = new Dictionary<string, object> { { "Thickness", Number(turn.Thickness) }, { "IncludedAngle", Number(turn.IncludedAngle) }, { "NoseRadius", Number(turn.NoseRadius) }, { "InscribedCircle", Number(turn.InscribedCircle) } };
            row["holder_dimensions_native"] = new Dictionary<string, object> { { "BoringBarDiameter", Number(holder.BoringBarDiameter) }, { "ShankLength", Number(holder.ShankLength) }, { "LeadAngle", Number(holder.LeadAngle) }, { "BackClearAngle", Number(holder.BackClearAngle) }, { "FrontClearAngle", Number(holder.FrontClearAngle) }, { "ZInsertOffset", Number(holder.ZInsertOffset) }, { "XInsertOffset", Number(holder.XInsertOffset) }, { "Protrusion", Number(holder.Protrusion) }, { "HolderShape", holder.HolderShape } };
            row["reason"] = "diamond_boring_bar_requires_physical_and_geometric_qualification";
        }
        return rows;
    }
    private static List<Dictionary<string, object>> NcParameters(Request request, Dictionary<uint, ICWTurnOperation> handles) {
        var rows = new List<Dictionary<string, object>>();
        foreach (int id in request.NcOperationIds) {
            var row = new Dictionary<string, object> { { "operation_native_id", id }, { "status", "error" }, { "stage", "operation_identity" } }; rows.Add(row);
            try {
                Require(handles.ContainsKey((uint)id), "NC_OPERATION_NOT_PRESENT");
                row["stage"] = "IGetTurnNCParam"; object raw = handles[(uint)id].IGetTurnNCParam();
                Require(raw != null, "NC_PARAMETER_OBJECT_ABSENT");
                row["stage"] = "ICWTurnNCParam"; var nc = (ICWTurnNCParam)raw;
                row["stage"] = "GetSpndlSpeed"; row["spindle_speed_native"] = Number(nc.GetSpndlSpeed());
                row["stage"] = "GetFeedRateIPM"; row["feed_rate_ipm_native"] = Number(nc.GetFeedRateIPM());
                row["stage"] = "finished"; row["status"] = "observed";
            } catch (Exception error) { row["hresult"] = error.HResult; row["error_type"] = error.GetType().Name; row["message"] = error.Message; }
        }
        return rows;
    }
    internal static string Execute(ISldWorks app, int ownerThreadId, string requestJson) {
        var clock = Stopwatch.StartNew(); var serializer = new JavaScriptSerializer { MaxJsonLength = 1048576, RecursionLimit = 32 };
        var result = new Dictionary<string, object> {
            { "schema_version", 1 }, { "scope", "TURN_INPROCESS_READ_V1" }, { "engine_version", EngineVersion }, { "status", "error" }, { "read_only", true }, { "mutation_attempted", false }, { "readback_verified", false },
            { "process_id", Process.GetCurrentProcess().Id }, { "host_module_version_id", typeof(SwAddin).Module.ModuleVersionId.ToString() }, { "host_assembly_location", typeof(SwAddin).Assembly.Location }, { "stage", "request" },
            { "limitations", new [] { "Single bounded non-atomic snapshot; document identity checked at entry and exit.", "No operation tool lookup, settings write, generation or Save.", "Tool candidate classification does not qualify physical access or production.", "Source file hashes and expected route comparison belong to the caller." } }
        };
        try {
            var r = Parse(requestJson); Require(app != null && ownerThreadId != 0, "HOST_NOT_CONNECTED");
            Require(Thread.CurrentThread.ManagedThreadId == ownerThreadId && Thread.CurrentThread.GetApartmentState() == ApartmentState.STA, "HOST_THREAD_MISMATCH");
            result["stage"] = "document_before"; var before = Document(app, r); result["document_before"] = before;
            result["stage"] = "cam_context";
            // Fixed vendor bridge call. The following CAM calls use pinned TLB interfaces.
            dynamic bridge = app.GetAddInObject(CamClass); Require(bridge != null, "CAM_ADDIN_NOT_LOADED");
            var camApp = (ICWApp4)bridge.GetCWApp(); object active = camApp.IGetActiveDoc(); Require(active != null, "NO_ACTIVE_CAM_DOCUMENT");
            var doc = (ICWDoc3)active; Require(doc.GetDocType() == 1, "CAM_PART_REQUIRED");
            string camConfiguration = Text(doc.GetActiveConfigurationName()); result["cam_configuration"] = camConfiguration;
            var configuration = (ICWConfiguration)doc.GetActiveConfiguration(); Require(configuration != null, "CAM_CONFIGURATION_ABSENT");
            string associatedSwConfiguration = Text(configuration.SWConfigurationName);
            result["cam_associated_sw_configuration"] = associatedSwConfiguration;
            ValidateConfigurationBinding(camConfiguration, Text(configuration.ConfigurationName), associatedSwConfiguration, (string)before["configuration"]);
            var machine = (ICWMachine)((ICWPartDoc)active).IGetMachine(); Require(machine != null && machine.MachType == 3, "TURN_MACHINE_REQUIRED");
            result["stage"] = "inventory"; var handles = new Dictionary<uint, ICWTurnOperation>(); result["inventory"] = Inventory(machine, doc, r, handles);
            result["stage"] = "tools"; result["tools"] = Tools(machine, doc, r);
            result["stage"] = "nc_parameters"; var ncRows = NcParameters(r, handles); result["nc_parameters"] = ncRows;
            result["nc_parameters_complete"] = ncRows.All(x => (string)x["status"] == "observed");
            result["stage"] = "document_after"; var after = Document(app, r); result["document_after"] = after;
            Require(serializer.Serialize(before) == serializer.Serialize(after), "DOCUMENT_CHANGED_DURING_READ");
            var configurationAfter = (ICWConfiguration)doc.GetActiveConfiguration(); Require(configurationAfter != null, "CAM_CONFIGURATION_ABSENT_AFTER");
            ValidateConfigurationBinding(Text(doc.GetActiveConfigurationName()), Text(configurationAfter.ConfigurationName), Text(configurationAfter.SWConfigurationName), (string)after["configuration"]);
            Require(Text(configurationAfter.ConfigurationName) == camConfiguration && Text(configurationAfter.SWConfigurationName) == associatedSwConfiguration, "CAM_CONFIGURATION_CHANGED_DURING_READ");
            result["status"] = "observed"; result["readback_verified"] = true; result["stage"] = "finished";
        } catch (Exception error) { result["hresult"] = error.HResult; result["message"] = error.Message; result["error_type"] = error.GetType().Name; }
        clock.Stop(); result["elapsed_ms"] = clock.Elapsed.TotalMilliseconds; return serializer.Serialize(result);
    }
}
}
