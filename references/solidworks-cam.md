# SOLIDWORKS CAM native integration

The native CAM tools use the existing PID-bound SOLIDWORKS session and its operation
mutex. They do not automate windows, start another CAD process, activate a
license, or silently save a model. A saved document path (or exact unsaved
title where applicable) is mandatory for live access.
Native CAM tools never select a process themselves. The session must already have a
pinned PID; use `solidworks_connect(process_id=...)` to choose it explicitly.
The separate `solidworks_cam_save_prompt` Windows UI helper is described below;
it is not a native CAM API.

## Discovery and connection

- `solidworks_cam_installation` reads allowlisted uninstall, Addins and CLSID
  registry metadata and installed help/API file locations. Multiple versions
  remain separate candidates. Installation is not a license check.
- `solidworks_cam_status` reads an already loaded add-in and the CAM version,
  service pack, build date and demo flag. It does not auto-load CAM.
- `solidworks_cam_load_addin` explicitly loads the registry-verified DLL with
  `ISldWorks.LoadAddIn(full_path)`, then verifies the API object and document
  state. A load return code alone is not success evidence.

The verified bridge is `ISldWorks.GetAddInObject(registered_clsid)` followed by
`IMWAddin.GetCWApp()`. The latter is documented in the installed add-in's
embedded type library. Do not instantiate a guessed CWApp ProgID or register
an unregistered class to make it work.

## Turning qualification

`solidworks_cam_inspect_turning` inspects a saved part's machine type and the
turning machine catalogue. `solidworks_cam_set_turn_machine` selects an actual
catalogue object with explicit index, expected catalogue count and expected
current machine type. It refuses dirty documents or existing feature/operation
setups and verifies `MachType == 3` after assignment. It does not save the part,
generate operations or claim that a usable toolpath exists.

The CAM interface library reuses DISPIDs between interfaces (for example,
`ICWDoc3.GetDocType` and `ICWPartDoc.IGetMachine`). Do not let a generic dispatch
wrapper select an interface by the object's default type information.
`sw_cam_comtypes.query_cam_interface` transfers the existing PID-bound object
through standard in-memory COM marshaling and queries the generated native
dual interface. It accepts both pywin32 wrappers and native comtypes pointers;
it does not query the ROT, activate a server or extract raw object addresses.
The declarations come from the verified registered installation's
`camworks.tlb` (2026, type-library version 25.0).

`GetLicenseEnabled(BSTR)` requires a module token. The inspected vendor help
does not define those tokens. Do not guess them. `demo_mode=false`, a catalogue
entry, successful machine assignment and the presence of a turning DLL are
separate observations; none is a complete entitlement or simulation test.
`Module(...)` changes activation and is intentionally not exposed.

`solidworks_cam_inspect_machining` reads feature setups, operation setups,
turning operation types, generated-path flags and existing stock type.
`solidworks_cam_run_qualification_step` supports one of `subscribe`,
`extract_features` or `generate_operations` on a separately saved calibration
part. A strict JSON `qualification_only=true` and the explicit
`message_policy="vendor_default"` are required. It never saves or posts NC.

Native `_IDialogEvents` subscription is held for the whole step. Vendor help
documents that clients may omit `SetResponse`, in which case CAM continues
with its defaults. The calibration policy records that as `default_unknown`;
it is not cancellation or rollback. No numeric response codes are guessed.
Any message, callback error or disconnect failure blocks downstream steps.
A message during a native call cannot undo that call. Client batch execution
stops when a tool reports `may_continue=false`.

Preconditions require a clean saved part and exact observed feature, operation
and operation-setup counts. Extraction requires an empty CAM plan. Operation
generation uses `CW_GOP_REGENERATE=2` only with recognized features and zero
existing operations. Empty operation setups created by native extraction are
allowed only when their count was explicitly observed. Each step creates a new
exclusive JSON receipt before native changes; an existing receipt cannot be
replayed after an uncertain timeout. Source and result inventories are recorded.

GTP and simulation are not exposed by this single-step qualification tool.
The inspected API provides `IsBackgroundProcessForGTPOver` but no verified
setter disabling background GTP.

## Persistent single-operation GTP

`solidworks_cam_prepare_toolpath_job` validates a clean separate saved part,
the selected PID and creation time, registered add-in, observed feature/setup/
operation counts and the selected turning operation type. It returns a config;
it does not start generation. Save the returned config as JSON in the project.

The permanent native module consumes that config:

```text
python -m scripts.sw_cam_jobs --start-config ABS_CONFIG_JSON --job-directory NEW_ABS_DIRECTORY --foreground
```

Its worker owns the PID operation mutex, COM apartment and native event
subscription for the complete calculation. It calls only the selected
`ICWTurnOperation.GenerateToolpath`, refuses existing generated paths, and
waits for the same operation's `GetIsToolpathGenerated` transition from false
to true after the native call returns. The vendor describes this getter as
successful operation generation. The global `IsBackgroundProcessForGTPOver`
flag is diagnostic only: the vendor Process Manager help describes 3-axis and
4/5-axis simultaneous milling, and the global flag was false on an untouched
idle turning calibration. Neither false=running nor true=completion of the
selected turning operation is established. `attention_seconds` marks a long
wait; it is not a cancellation deadline. Receipt, process-query and message-
pump errors do not release the subscription while completion remains unknown.
The worker leaves that wait on verified generation, confirmed target-process
death/reuse, or an explicitly requested observer cleanup as described below.
Observer cleanup and killing the calling session are not native cancellation.

Foreground execution is the verified transport design for short-lived MCP
stdio clients: the Windows MCP SDK puts the server in a kill-on-close Job
Object. A child cannot silently detach from that ownership. The optional
background launcher requests explicit breakaway and refuses if unavailable;
it never retries without breakaway. No window automation, shell command,
arbitrary code payload, license activation or automatic model save is used.

`solidworks_cam_job_status` reads the durable state and worker PID/creation
time without acquiring the CAD lock. Source fingerprints, process identity,
registration and document target are checked again in the worker. New job
directories and exclusive claim files prevent replay. A disappeared worker
without a terminal receipt is uncertain, never a successful calculation.

Success needs the selected generated flag, nonzero path records and finite
positive feed length, plus unchanged other operations and clean message
handling. Native length units are reported as unverified rather than assumed.
Save and reopen the intended calibration separately to check persistence.
This is not proof of production machining, tool clearance or license scope.
In particular, a false generated flag is a success predicate returning false,
not a documented running state. The turning API does not provide a verified
terminal-failure or cancellation channel. Unknown results must not be retried.

`solidworks_cam_stop_observation` requires the strict boolean
`acknowledge_native_not_cancelled=true`. It writes a job-bound request, which
the worker can service only after the current COM call returns. The worker
unsubscribes normally and returns `uncertain`, `observation_stopped=true`,
`native_cancelled=false`, `may_continue=false`. This is observer cleanup,
not cancellation of CAM or proof of completion. `finished=true` in this case
means that the observer finished, not that machining completed.

`solidworks_cam_inspect_operation` reads the selected operation's generated
flag, raw GTP time string, optional object-scoped license getter and stock
parameters. It also reads suppression, linked-feature count, actual tool presence,
raw tool-type values and a bounded tool description. Unknown enum values remain
unresolved; these getters do not qualify machining. Missing interface/getter
support remains explicitly unavailable.
The diagnostic read itself does not establish a terminal CAM execution state.

Live qualification of the direct rough-face call on the simple cylinder
returned without a generated path, timing string or CAM message. A prior
worker incorrectly treated the false success flag as pending indefinitely;
its observer was stopped with the native outcome and Unadvise unconfirmed.
The cooperative stop channel was added afterwards and is unit-tested only.
The raw stock dimensions match that calibration's envelope; absent cutting
allowance is a hypothesis, not a proven cause or a license finding. That attempt
produced no simulation evidence or manufacturing release.

Closing that calibration with ordinary `needs_save=false` nevertheless raised
a CAM save prompt. CAM persistence must be handled explicitly even after a
failed generation attempt. The read-only recovery report now includes modal
text and returns blocked even if COM getters still respond.
Simulation remains a separate stage requiring valid stock and tool/holder data.

`solidworks_cam_save_prompt` is a separate, explicitly authorized Windows UI
helper, not native CAM automation. It requires an already bound matching PID,
an exact SLDPRT basename, and the unique known Russian dialog titled
`Предупреждение SOLIDWORKS CAM` with text `Сохранить изменения в <basename> ?`.
Its default `action="inspect"` is read-only. `action="discard"` additionally
requires strict `acknowledge_discard=true`; it rechecks the dialog and sends
one notification to its identified No button. It does not use COM, acquire the
possibly blocked CAM mutex, activate a window or retry a click. Dismissal and
document save state are reported separately; availability of this helper is
not evidence that a particular prompt was successfully dismissed.


## Document-wide qualification simulation

`solidworks_cam_run_simulation` invokes the native simulation for the entire
active saved calibration part, not an individual selected operation. It
requires `qualification_only=true`, the strict boolean
`acknowledge_document_wide_simulation=true`, `message_policy="vendor_default"`,
the exact saved `expected_document_path`, and observed `expected_feature_count`,
`expected_operation_count`, `expected_operation_setup_count` and
`expected_generated_operation_count`. Counts must be positive bounded integers.
A new absolute `output_dir` with an existing parent holds the exclusive receipt
and exported evidence. An existing output directory is refused; do not replay
an uncertain or timed-out request with a new directory.

The registered add-in and its `camworks.tlb` are verified through the existing
PID/document guard. The whole call uses the shared operation mutex and records
before/after document and CAM inventories. The core refuses an initially dirty
or mismatched document. Document-wide acknowledgement allows inventory changes
on the same part to be recorded while exporting evidence; it is not approval
of those changes. Native messages, callback errors or cleanup failures block
further steps under the vendor-default message policy.

The native sequence is `RunSimulationSilent(True, False, False)`, followed by
JPG and STL evidence export when its guards allow. Gouge and undercut counts
are raw vendor outputs. The typed STL result order is `(error_code, saved_bool)`;
the image exporter returns a save boolean. This tool does not launch CAD,
explicitly generate toolpaths, post NC or save the SOLIDWORKS model.

Verified exports return `status="review_required"`,
`reason="SIMULATION_OUTPUTS_REQUIRE_REVIEW"`, `export_files_verified=true` and
`may_continue=false`. `native_call_returned=true` is separate from
`native_completion_verified=false`. A returned call or exported files do not
establish completion quality, tool clearance, license scope or full DFM.
Review the image and mesh separately before any further manufacturing decision.
The MCP contract is covered by isolated mocks; implementation and passing tests
alone do not establish live native simulation qualification.


`solidworks_cam_preview_simulation` uses the same explicit saved-part,
qualification, document-wide, count and message-policy guards, plus a required
`action`. Each action needs its own new absolute output directory and exclusive
receipt. `launch_play` calls only native `ActiveDocLaunchSimulation()` and
`ActiveDocPlaySimulation()`; their return does not verify playback completion.
`export_state` separately exports the current simulation image and STL. An
image-export failure does not prevent the STL attempt while document identity
and message guards remain valid; each export retains its own result.

Only explicit `action="close"` calls native `ActiveDocCloseSimulation()`
(DISPID 43). Its return does not prove that preview closed; no completion getter
is assumed. Other actions do not close simulation automatically. The preview
tool never calls `RunSimulationSilent`, generates toolpaths, saves the model or
posts NC. Results remain `review_required` with
`may_continue=false`; completion is unverified. Image and mesh evidence require
separate review. Mock coverage is not evidence of live playback qualification.


## Document-wide CAM geometry export

`solidworks_cam_export_geometry` requires the same saved-part, exact positive
counts, strict `qualification_only=true` and vendor-default message policy,
with a separate strict `acknowledge_document_wide_export=true`. Its output
directory must be new, absolute and local after canonical path resolution;
UNC paths, including mapped drives resolving to UNC, are refused.
`export_kinds` is an ordered, unique JSON list of one to three entries from
`"wip"`, `"stock"`, `"target"`; it defaults to `["wip"]`. Only explicitly
selected kinds are called, in the supplied order; there is no default batch
of all three exports.

The typed `ICWMachine5.CreateSTLOfWIPs2(folder, "wip.stl", "", 0, 0)` exports
WIPs across all setups, not the current simulation frame. The native folder
argument includes the trailing Windows separator: the observed implementation
concatenates folder and filename directly. An omitted separator previously
created a sibling file instead of a file inside the expected WIP subdirectory.
The receipt records the actual native folder and path; the tool uses a new,
empty WIP subdirectory and refuses collisions before invocation. WIP, stock and target
export methods return a Boolean only. The empty string and zero parameters
are qualification values; their use does not verify units or coordinate
interpretation. Any failed or invalid native export result, or missing/invalid
output, immediately stops the batch. No subsequent stock/target export or CAD
readback is permitted; only event-subscription cleanup is attempted. Verified
files and hashes require separate mesh review; they do not establish simulation
completion or full DFM, and `may_continue` remains false.

Each attempted-call marker is persisted before entering native code and means
intent, not proof of entry. The returned flag and strict Boolean result are
persisted immediately after return, before any further CAD readback. A receipt
write failure blocks continuation. Failed exports stop the batch; no retry or
alternate export kind is selected automatically.

On the saved stepped calibration in SOLIDWORKS/CAM 2026 SP4, the qualified
sequence is an explicit native preview `action="close"`, then a separate
geometry call with `export_kinds=["wip"]` and a new local output directory.
No save, toolpath regeneration, UI action or NC output is part of this sequence.
Closing preview was necessary for the observed successful sequence; the call's
return does not establish a general vendor prerequisite or a closed-state getter.
The corrected WIP export returned true and wrote the expected 50,384-byte STL.
Independent mesh readback found 1,006 triangles, a watertight mesh and volume
about 6,133.567 mm3, versus about 6,275.214 mm3 for stock: roughly 141.65 mm3
removed by the one generated rough-turn operation. This is partial machining,
not the final target shape or qualification of the four remaining operations.
The corrected file and the earlier misplaced successful WIP had identical
SHA-256 `633fe162f68a54ddcc0bce35bbd67a71d859643f2d1ebcff9a6d22f6436cb248`.

An earlier WIP attempt while preview was open returned false, and SOLIDWORKS
later exited during the old multi-export sequence. A stock file proves that
stock export was entered despite the old receipt's false attempted flag; the
native return and failure origin are unknown. That failed sequence is not
qualified and is not replayed automatically. The single WIP result above does
not establish safe export from an open simulation or make simulation-frame STL
export supported.

## Evidence and tests

Application-level connection and native loading were verified with SOLIDWORKS
2026 Revision 34.4.1, CAM 2026 SP4 build 2026/0619 and Python 3.10.11. The active
document identity and dirty flag were unchanged. On a separate saved calibration
part, native reading found one turning machine. Assignment changed the machine
type from 1 (mill) to 3 (turn), confirmed by immediate readback and again after
explicit save, close and reopen. Only the calibration part was saved; the
original assembly was restored without saving it.

The CAM assignment did not set the SOLIDWORKS dirty flag in that live test.
Do not use `needs_save=false` as proof that CAM data was persisted; callers must
explicitly save an intended CAM change and verify it after reopening.
Machine selection and persistence are verified. In a subsequent calibration,
event subscription/unsubscription succeeded, native extraction produced three
features, and native operation-plan generation produced five operations
supporting `ICWTurnOperation`. All five survived save, close and reopen.
No CAM messages occurred in those live stages; actual delivery of a vendor
message remains unobserved. Callback ABI was separately tested with real
in-memory `IDispatch.Invoke`, both null and non-null result pointers.
On a separate stepped calibration in SOLIDWORKS/CAM 2026 SP4, one selected
rough-turn operation generated 36 toolpath records. Explicit save, close and
reopen confirmed the same 36 records. This verifies generation and persistence
for that selected operation, not all turning operation types.

`RunSimulationSilent` returned raw counters `(0, 0)`, but image export returned
false and produced no evidence files. Native preview launch and play then
returned with unchanged CAM inventory. A separate `export_state` produced a
real 400 x 300 JPG of 10,816 bytes, which was visually reviewed. STL export
returned false with error 7 (`CW_EC_UNKNOWN_ERROR`). Repeating only export to
a shorter project output path produced the same image hash and the same STL
error; simulation was not rerun. Preserving the requested drive-letter form
and exporting to an actual local directory also retained error 7. The path fix
is useful but did not resolve simulation-frame STL export. The supported WIP
workflow above is a different native geometry source, not a silent replacement
claim for the failed simulation exporter.

Native exports preserve the caller's explicit absolute path for native API
arguments. Canonical paths are recorded separately and used to check directory
identity and output boundaries. File existence, nonzero size and SHA-256 are
checked independently of a native success Boolean; mesh content still requires
separate review.

Image export is therefore pilot-verified. Playback completion, the underlying
simulation completion state and STL/mesh output remain unverified. Raw zero
counters and an image do not establish a complete material-removal result,
tool/holder clearance, general turning entitlement or full DFM. These results
do not qualify a production machining process.

Protocol validation checks registered tools without calling CAD. Regression
tests use mocks and in-memory COM separately from the live observations above.

The reusable `scripts/mcp_request.py` client executes JSON requests through the
standard MCP protocol against a fresh server and saves a result after each
call. It never imports server functions to perform CAD operations. Existing
output files are not overwritten; a failed call stops dependent requests.
After source changes, reconnect persistent MCP clients. Old servers reject
native operations when their source fingerprint is stale.

Primary references: installed `swcamapihelp.chm`, `camworks.tlb` and the embedded
type library in `cwaddinu.dll` supplied with SOLIDWORKS CAM 2026. Public bridge
documentation: [GetAddInObject](https://help.solidworks.com/2024/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.ISldWorks~GetAddinObject.html),
[LoadAddIn](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~LoadAddIn.html).

Vendor help and extracted type libraries are not redistributed in this repository.
