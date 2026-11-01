# Saved finish-operation diagnostics

`solidworks_cam_read_finish_diagnostics` reads restrictions from a saved CAM route through native interfaces. It does not modify settings, generate a path, export, or save a model. Its current adapter is intentionally limited to the qualified MILL operation/feature pairs `144/79` and `248/244`; it is not a general operation selector.

Use an explicit owned process connection and a completed saved-configuration receipt. Pass `process_id`, `expected_document_path`, `expected_source_sha256`, `addin_clsid`, `checkpoint_receipt_path`, `checkpoint_receipt_sha256`, a fresh local `receipt_path`, and the current reader `module_sha256` under `arguments.params`. Paths and hashes come from the current checkpoint; do not embed a workstation path in a reusable request. `response_format` is optional.

The reader validates the saved configuration, generated interface definitions, document identity, operation IDs, features, tools and existing path counts. It checks those bindings before and after a bounded read batch, retaining the observed values in the receipt. It opens no document and launches no new application instance. A non-atomic read remains non-atomic despite stable before/after bindings.

The qualified v3 fields cover rest-machining settings, lead/gouge restrictions, air/corner options, raw toolpath/CNC compensation values, contain/avoid areas, operation text and feature rebuild status. Raw enum values are not automatically decoded. Read the receipt's actual field list before reusing results from a later reader version.

## Result interpretation

- `readback_verified=true` establishes the guarded observation and unchanged selected bindings, not a correct machining recipe or an acceptable toolpath.
- `supported_fields_read_complete=true` means every supported field in that reader version was observed. `read_complete=false` remains intentional because `ICWObject.GetLock` was not observed: its native interface query previously returned `DISP_E_BADVARTYPE` (`-2147352568`). The reader excludes that interface without retry. This is a qualified limitation of this path, not proof that every object or installation lacks the interface.
- `GetText` returns raw operation text. It is not documented as a What's Wrong error message. A bounded public SDK/type-library search found no native equivalent that retrieves the historical What's Wrong explanation. Event messages observed during a call do not constitute a historical error-log getter.
- `GetRebuildOk=false` alone is not a diagnosis: it was observed both for the empty target and for a comparison operation with an existing path. `geometry_accepted` and `production_qualified` remain false.

## Native qualification

The saved R119 configuration was read on 2026-11-01. Receipt `finish_diagnostics_v3.json`, SHA256 `22acde36022e55d5b5b63176b77b1a5960e493e18c669748f416439fe4bfdf39`, records two operations, 20 bounded diagnostic reads each, 96 total getters and 32 interface queries including binding checks. The batch took 5.897 seconds; this is not the total MCP command duration. No setter, GTP or save was attempted. Source paths and checkpoint pins are in that receipt and the project knowledge index.

Receipt `finish_diagnostics_v4.json` (SHA256 `b4b255b2742486cf777782656e4b06939ce8c90ef60a0a26575a98597de1fbb3`) additionally confirms the single-depth flag, depth-processing mode and the first/max/side-cut value/percentage pairs. It preserves the same read-only limits; observed modes matched, while the configured numeric increments differed.
