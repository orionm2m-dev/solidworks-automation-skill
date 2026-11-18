# Plastics native API research and saved qualification

Evidence date:11 November2026. Search project knowledge topics
`swfork.plastics.api` and `swfork.plastics.fill` with source verification.
No general solver-control API is qualified.

## Interfaces and binding

The initial inventory missed SimpoeWrapperx64.exe. The earlier external-SDK-only
conclusion was corrected: ISimpoeWrapper exposes typed settings, material search,
batch-manager and export methods. Signatures do not prove working semantics.

Static SetHandle(handle,pid) analysis found both a current global handle and
per-PID records. Missing/zero entries in the file-list path fall back to the
global handle. Several SWPAPI data/settings calls use the global handle directly.
A PID argument alone does not establish isolation. The native add-in chain
associates its active-document object with GetCurrentProcessId.
Exact GUID/vtable mapping and binary hashes are retained in project evidence.

The studied SetSolverSetting recognizes five keys: Flow algorithm, Warp quality
mesh, Warp solver type, AMG cycles and CPU count. Unknown keys map to0.
Use saved exact-key/type evidence; never guess arbitrary strings.
General material, mesh and gate setters remain separate qualification work.

## Five read-only MCP tools

The bridge exposes plastics_inspect_native_api, plastics_read_fill_report,
plastics_inspect_batch_job, plastics_read_study_attributes and
plastics_read_native_study_context. Its README is canonical for arguments.

Type libraries are read without COM activation. Saved files require exact path
and SHA256. Live reads pin PID, creation time, executable, document path/hash and
configuration. The context diagnostic also pins exact vendor builds, reads at
most16KiB of memory, verifies native CAD path/wrapper ownership and compares two
stable snapshots. It is an exact-build diagnostic, not a public vendor SDK.
No memory writes, private calls, setters or solver calls are exposed.

Real stdio MCP exercised the five tools. Software regression, exact-case live
readback and deployment into a client's discovery are different facts.
The process observer is not a sixth registered MCP tool.

## Native Fill pilot and applicability

A separately authorized public ToolbarCB_RunF call completed one protected
historical model's Fill. Evidence pins fresh queue, solver identity/command line,
new KD3 completion summary, exit0 and stable post-exit study snapshots.
The launch is a case-qualified project script, not a reusable MCP control tool.
Its one-run authorization is consumed; do not replay the script or shared queue.

Pressure-limit warnings remain part of the result. Exit0 and rounded100% cell
count do not prove production acceptability or exact filled-volume fraction.
NO PACK is explicit. Pack/Cool/Warp, mesh convergence and current-model DFM remain
open. Current CAD geometry differs, so do not transfer historical mesh or fields.
Material/process settings and a gate coordinate are candidates only after current
readback; old face IDs and gate boundary mapping do not transfer automatically.

The observed run used CPU24. Three samples showed no solver GPU engine/memory
records; a documented GPU launch contract for this desktop Fill was not found.
This is not a claim about every Plastics product.

## Failure lessons

A previous solver crash established KLG3 append-open sharing violation; the holder
is unknown. Later success without log polling does not prove polling caused it.
Observe the owned process during solving and read stable outputs after exit.

Literal drive-letter mismatch interrupted observation after the callback.
Recovery proved physical executable identity, PID creation time and full command
line on the same running process; no callback was repeated. Do not confuse an
observer failure with a failed launch or remove identity guards for aliases.

Read checkpoint/receipts first, preserve CAD/sidecar hashes and distinguish old
outputs from fresh ones. Plastic Costing calculates cost, not Fill/Pack/Cool/Warp.
The project retains the official-document evidence for this distinction.

REA is for assigned API/integration study, including DFMXpress; no protection
bypass. Project API/SDK-support emails are prohibited.
Related: [DFMXpress](dfmxpress-native-api-research.md).
