# SOLIDWORKS CAM native integration

The CAM tools use the existing PID-bound SOLIDWORKS session and its operation
mutex. They do not automate windows, start another CAD process, activate a
license, or silently save a model. A saved document path (or exact unsaved
title where applicable) is mandatory for live access.
CAM tools never select a process themselves. The session must already have a
pinned PID; use `solidworks_connect(process_id=...)` to choose it explicitly.

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

GTP and simulation are not exposed by this qualification tool. The inspected
API provides `IsBackgroundProcessForGTPOver` but no verified setter disabling
background GTP. A future tool must keep its COM apartment and event sink alive
until generation actually ends; a timeout is not cancellation. Successful GTP
must be checked by generated-path state and nonzero path records. Simulation
also needs valid stock and tool/holder geometry with separately checked results.

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
Turning entitlement, generated toolpaths and material-removal simulation
remain unqualified. These calibration observations do not qualify a production
machining process or certify all turning operation types.

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
