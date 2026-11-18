using System;
using System.Collections.Generic;
using System.Linq;
using CamWorks.Interop;
namespace CadStudio.SolidWorks.AddinHost {
// Public typed getters only. No record string marshaling, alternate accessor or mutation.
internal static class CamTurnRecordRead {
    internal sealed class Selection {
        internal int OperationId, FeatureId, OperationType, SetupIndex, OperationIndex, OperationCount, SetupCount, RecordCount;
    }
    internal static Selection Parse(object raw) {
        var d = raw as Dictionary<string, object>;
        string[] fields = { "operation_native_id", "feature_native_id", "operation_type", "setup_index", "operation_index", "expected_operation_count", "expected_setup_count", "expected_record_count" };
        CamBatchReader.Require(d != null && d.Count == fields.Length && fields.All(d.ContainsKey), "RECORD_SELECTION_FIELDS");
        var r = new Selection {
            OperationId = CamBatchReader.Integer(d["operation_native_id"], 1, int.MaxValue),
            FeatureId = CamBatchReader.Integer(d["feature_native_id"], 1, int.MaxValue),
            OperationType = CamBatchReader.Integer(d["operation_type"], 7, 8),
            SetupIndex = CamBatchReader.Integer(d["setup_index"], 0, 7),
            OperationIndex = CamBatchReader.Integer(d["operation_index"], 0, 63),
            OperationCount = CamBatchReader.Integer(d["expected_operation_count"], 1, 64),
            SetupCount = CamBatchReader.Integer(d["expected_setup_count"], 1, 8),
            RecordCount = CamBatchReader.Integer(d["expected_record_count"], 1, 256)
        };
        CamBatchReader.Require(r.SetupIndex < r.SetupCount && r.OperationIndex < r.OperationCount, "RECORD_SELECTION_POSITION"); return r;
    }
    internal static void VerifySelection(Dictionary<string, object> inventory, Selection r) {
        CamBatchReader.Require((int)inventory["operation_count"] == r.OperationCount && (int)inventory["operation_setup_count"] == r.SetupCount, "RECORD_INVENTORY_COUNT");
        var rows = (List<Dictionary<string, object>>)inventory["operations"];
        var selected = rows.Where(x => (uint)x["native_id"] == (uint)r.OperationId).ToArray();
        CamBatchReader.Require(selected.Length == 1, "RECORD_OPERATION_ID"); var row = selected[0];
        CamBatchReader.Require((int)row["setup_index"] == r.SetupIndex && (int)row["operation_index"] == r.OperationIndex && (int)row["turn_operation_type"] == r.OperationType, "RECORD_OPERATION_POSITION_TYPE");
        CamBatchReader.Require(((uint[])row["linked_feature_ids"]).SequenceEqual(new uint[] {(uint)r.FeatureId}), "RECORD_FEATURE_ID");
        CamBatchReader.Require(!(bool)row["suppressed"] && (bool)row["toolpath_generated"] && ((List<int>)row["toolpath_record_counts"]).SequenceEqual(new int[] {r.RecordCount}), "RECORD_GENERATED_PATH_COUNT");
    }
    // This small port permits testing the stop-on-first-error loop without a CAD activation.
    internal interface IRecordSource {
        int Count(); object Item(int index); int Type(object record); int Rapid(object record); double[] Point(object record);
    }
    private sealed class NativeSource : IRecordSource {
        private readonly ICWDispatchCollection collection;
        internal NativeSource(object raw) { CamBatchReader.Require(raw != null, "NULL_RECORD_COLLECTION"); collection = (ICWDispatchCollection)raw; }
        public int Count() { return collection.Count; }
        public object Item(int index) { return collection.Item(index); }
        public int Type(object record) { return ((ICWCLRecord)record).GetType(); }
        public int Rapid(object record) { return ((ICWGotoRecord)record).GetRapidLine(); }
        public double[] Point(object record) {
            object raw = ((ICWGotoRecord)record).GetToolpathPoint(); CamBatchReader.Require(raw != null, "NULL_GOTO_POINT");
            var point = (ICWPosition)raw; double x,y,z; point.GetCoordinates(out x,out y,out z); return new double[] {x,y,z};
        }
    }
    internal static Dictionary<string, object> Read(int expectedCount, Func<IRecordSource> open, Func<int> pathCount) {
        var rows = new List<Dictionary<string, object>>();
        var r = new Dictionary<string, object> { {"schema_version",1}, {"status","error"}, {"stage","RecordCount_before"}, {"records",rows}, {"expected_record_count",expectedCount}, {"accessor","GetEnumRecords"}, {"fallback_attempted",false}, {"units_verified",false}, {"frame_verified",false}, {"tool_vector_read",false}, {"complete_payload_read",false} };
        try {
            CamBatchReader.Require(expectedCount >= 1 && expectedCount <= 256, "RECORD_LIMIT");
            CamBatchReader.Require(pathCount() == expectedCount, "PATH_COUNT_BEFORE");
            r["stage"] = "GetEnumRecords"; var source = open(); CamBatchReader.Require(source != null, "NULL_RECORD_SOURCE");
            r["stage"] = "Count_before"; CamBatchReader.Require(source.Count() == expectedCount, "COLLECTION_COUNT_BEFORE");
            for(int index=0; index<expectedCount; index++) {
                r["record_index"] = index; r["stage"] = "Item"; object raw = source.Item(index); CamBatchReader.Require(raw != null, "NULL_RECORD");
                r["stage"] = "GetType"; int kind = source.Type(raw);
                var row = new Dictionary<string, object> { {"index",index}, {"type_raw",kind}, {"position_read",false} }; rows.Add(row);
                if(kind != 7) continue;
                r["stage"] = "GetRapidLine"; row["rapid_raw"] = source.Rapid(raw);
                r["stage"] = "GetToolpathPoint/GetCoordinates"; var xyz = source.Point(raw);
                CamBatchReader.Require(xyz != null && xyz.Length == 3, "POINT_DIMENSION");
                row["point_native"] = xyz.Select(CamBatchReader.Number).ToArray(); row["position_read"] = true;
            }
            r["stage"] = "Count_after"; CamBatchReader.Require(source.Count() == expectedCount, "COLLECTION_COUNT_AFTER");
            r["stage"] = "RecordCount_after"; CamBatchReader.Require(pathCount() == expectedCount, "PATH_COUNT_AFTER");
            r["status"] = "observed"; r["stage"] = "finished";
        } catch(Exception error) { r["hresult"] = error.HResult; r["error_type"] = error.GetType().Name; r["message"] = error.Message; }
        return r;
    }
    internal static Dictionary<string, object> ReadOperation(ICWOperation operation, Selection selection) {
        // The enumeration accessor is called at most once; no remote or indexed fallback.
        ICWToolpath path = null;
        return Read(selection.RecordCount, () => new NativeSource(path.GetEnumRecords()), () => {
            if(path == null) {
                var paths = CamBatchReader.Items(operation.IGetEnumToolpaths(), 1);
                CamBatchReader.Require(paths.Length == 1, "EXACTLY_ONE_PATH"); path = (ICWToolpath)paths[0];
            }
            return path.RecordCount;
        });
    }
}
}
