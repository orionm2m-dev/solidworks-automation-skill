# CAM owner-STA explicit island qualification

Status: pilot. Offline contract tests and saved-source admission do not establish native execution or machining suitability. Runtime evidence must be assessed separately.

The reusable MCP endpoints are:

- `solidworks_cam_load_owner_sta_island_host`: one explicit native `LoadAddIn`, followed by typed `GetHostStatus`. It checks the actual loaded PID, process lifetime, DLL location, MVID and owner STA; it compares the current document before and after. No CAM getter is invoked.
- `solidworks_cam_qualify_owner_sta_islands`: consumes a sealed request with an exact SHA-256. The fixed command creates one pocket and adds either the first declared island or all four, as selected by strict `island_count_limit` equal to 1 or 4. The initial native qualification uses 1. A subsequent four-island run requires another fresh copy and sealed request.

The separate permanent native add-in is `CadStudio.SolidWorks.CamIslandQualification`, CLSID `F69869EF-C175-4A06-9426-E1502BFA8921`. It does not replace the existing AddInHost. Its interface IID is `36B207A9-AF3A-4F89-B211-5755E7CF6327`; LIBID is `91FE2D85-D19A-4DBB-8BB0-B6D02A948FA5`. `GetHostStatus` is DispId 1; `QualifyCreatePocketAndIslands` is DispId 2.

All document and evidence paths are request data. Python resolves native document paths before dispatch so mapped drive paths and the application's UNC paths have a consistent identity. The host receives one bounded JSON object and returns JSON. The native factory result remains inside the host's owner STA and is passed directly to each declared island addition. Python never receives or returns the CAM feature object.

Before dispatch, the client verifies the saved four-sketch producer, outer-circle creator, completed five-sketch Save, immutable source hashes, feature plan, and a separate exclusive copy receipt. The expected saved CAD fingerprint comes from the completed producer chain. A failed previous CAM operation is not source authority. An unchanged file hash alone does not describe the current RAM state.

The fixed action name in the sealed request is `qualify_create_pocket_islands_owner_sta`. Its `params` object contains `native_request`, DLL/TLB paths and hashes, the exact installed wrapper hash, client output path, copy/producer/plan paths and hashes, and the two explicit flags `qualification_only=true` and `acknowledge_ram_only=true`. The exact schema is enforced by `scripts/sw_cam_owner_sta_island.py`.

The per-copy client marker records dispatch intent before the host call. The separate native marker records the declared native action sequence before mutation. Existing markers, receipts, aliasing, source drift and dirty initial copies block execution. A receipt reports actual native entry/return separately from client dispatch intent. There is no automatic retry. An exception after dispatch leaves status `uncertain`; diagnostic readback does not turn the failed operation into a successful one.

Successful admission independently checks the native request binding, actual owner STA and lifetime, one feature delta, zero operations, each header and ordered sketch list, exact bounded action results, analytic chain readback, unchanged CAD fingerprint and source sketches, quiet event cleanup, native marker binding and byte-content-equivalent parsed durable receipt. The result remains `islands_observed_ram_only`: Save, GOP, GTP, AFR, persistence, physical depth, world profile placement and machining qualification are not provided.

The registration/build script `scripts/sw_cam_island_host.ps1` installs only this separate fixed class and typelib and does not enable automatic startup. Build/registration/load must remain separate observed stages; a file hash or `LoadAddIn=0` alone is insufficient.

Offline tests use synthetic backends and create no application. The existing SW runtime Python environment is required for producer-proof imports; the default Store Python may lack the already installed COM dependencies. Do not install a second dependency set merely because that unrelated interpreter cannot import the runtime package.

