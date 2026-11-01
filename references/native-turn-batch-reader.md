# Native TURN snapshot batch

Status: built and offline tested on 2026-11-01; live performance and CAM compatibility require separate qualification. This reference supplements BUILD_MANIFEST.json and does not replace its exact artifact hashes.

## Entry point and purpose

The existing net48/x64 SOLIDWORKS add-in exposes ICamBatchReader, IID DA9D97F8-EB0E-4D7B-A741-0E1736E899A2, with ReadTurnSnapshot(string requestJson) at DISPID 1. One external COM call gathers the TURN operation inventory, bounded tool crib geometry, and optional NC values. It reduces external process transitions; it does not execute simultaneous COM calls or generate toolpaths.

The six required request keys are schema_version (1), expected_process_id, expected_document_path, cam_addin_clsid, max_operations and max_tools. Optional nc_operation_ids contains at most eight unique positive IDs. Operation and tool limits are 1–64. The CAM CLSID is fixed to the qualified installed 2026 bridge. Arbitrary interfaces, properties, methods and executable payloads are not accepted.

## Thread and document boundaries

An external COM call may arrive on a worker thread. The host dispatches the fixed reader delegate through its existing owner-thread control; the actual reader then checks the ConnectToSW thread ID and STA apartment. A busy flag rejects reentrant reader requests. This is internal add-in dispatch, not UI automation.

The reader checks the owned PID, active part path, document type and SOLIDWORKS configuration. The CAM configuration object has distinct ConfigurationName and SWConfigurationName properties. Its own name must match GetActiveConfigurationName; SWConfigurationName must match the active SOLIDWORKS configuration. The two applications may use different configuration names. Path, title, type, dirty state and configuration are compared before and after. The result is a single non-atomic observation: these checks do not lock the document or prove every getter observed an indivisible transaction.

The response identifies the loaded assembly path, module version ID, engine version and elapsed time. The caller must pin the actual installed DLL/TLB, require the expected MVID, and compare the same PID/document and its source hashes. Build success and registration are separate from a successful live read.

## Read-only scope and errors

There are no Save, GenerateToolpath, SetTool or other write calls. The reader does not call operation IGetTool. Tool dimensions are limited to fixed supported TURN holder/insert interfaces. NC requests use fixed spindle-speed and feed getters with per-operation error details.

The top-level readback_verified flag concerns document identity. It does not imply every requested NC getter succeeded. nc_parameters and nc_parameters_complete are always present; an empty requested list produces an empty result list. Preserve partial errors and HRESULTs. An unknown timeout is not an instruction to replay automatically.

## Build and verification

Use the existing scripts/sw_addin_host.ps1 Build action with explicit SolidWorksApiDir, CamWorksTlbPath, DotNetPath and NetFxToolsDir where discovery is insufficient. The builder generates a local signed CAM interop from the installed vendor TLB and caches it by input hashes. Generated vendor binaries and private development signing keys are not source deliverables.

The corrected staged build passed 53 offline tests, with zero build warnings/errors and successful TLB export. No host instance or native CAM call was made by those tests. A different runtime rebuild can have a different MVID: validate the actual runtime artifact before calling it. External comtypes ABI validation is a separate client integration check.

## Batching beyond reads

The installed SDK exposes parameterless GenerateToolpath on a TURN operation, TURN setup and part document. Setup and document scopes are broader than a selected-operation batch: do not use them as an equivalent to regenerating only new operations when existing paths must be preserved.

A later reusable write batch can iterate an explicit bounded operation list on the owner thread, retain dependency order, and emit a result for each operation. It requires its own preconditions, mutation acknowledgement, recovery and live qualification; none is granted by this read-only interface. Parallel offline analysis and preparation can proceed independently while one actor owns native changes.

The vendor Mill Tutorial describes Process Manager parallel generation for 3-axis and simultaneous 4/5-axis milling, using separate threads/processes. This is evidence for milling capability, not confirmation of TURN support or a callable parallel TURN API. Source: https://camworks.s3.amazonaws.com/Website/Docs/Manuals/Mill_Tutorial.pdf, printed page 147. The installed SDK pages for ICWTurnOpSetup/GenerateToolpath and ICWTurnOperation/GenerateToolpath are the relevant local generation-scope references.

## Next qualification

After the owned document reaches a recorded checkpoint, load the exact built add-in using the existing registration/load workflow. Compare one batch response with the saved external-reader receipt; measure both total call duration and internal elapsed time. Only a matching successful live result establishes the speedup and compatibility for this installed version. Source code, build evidence, loaded-binary identity and machining progress remain separate records.

## Configuration diagnostic and grouped readers

`solidworks_cam_read_configuration_binding` accepts a sealed request path and SHA plus an explicitly selected process ID. It validates the CAM-to-SOLIDWORKS mapping and the protected route, then reads only the requested NC values. A live bounded diagnostic on 2026-11-01 verified the mapping and unchanged route. One new operation failed at IGetTurnNCParam while the established control operation returned values; this is a partial diagnostic result, not repaired initialization. Do not replay a failing getter without a changed, identified precondition.

`solidworks_cam_read_shallow_guide_group` reads the saved two-feature guide baseline and both operation catalogues together. Existing rough-operation settings are marked as a reference; they are not defaults for uncreated guide operations. The installed reader has 55 offline tests; live execution and new-process ownership continuation require separate evidence.

`solidworks_exit_owned_empty_session` permits one ExitApp only after pinned ownership, verified save/close, exact source identity, and two live empty-session checks. No termination, save, document close or launch is performed. A failed CAM Save cannot be substituted for successful save evidence.
