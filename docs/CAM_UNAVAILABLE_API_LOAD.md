# One explicit CAM load after GetCWApp E_POINTER

Status: offline qualified; no native call performed by this staging package.

The existing `solidworks_cam_load_addin` tool gains an optional `initialize_unavailable_api` branch. Its normal behavior and the status tool remain unchanged. The new branch requires an exact already selected PID and creation time, `expected_no_documents:true`, the registry-selected DLL SHA-256, E_POINTER (-2147467261), and a fresh absolute JSON receipt.

The native contract permits `ISldWorks.LoadAddIn` with the fully qualified add-in DLL path and returns an integer status. The official 2026 enum distinguishes `swSuccess=0` from `swAddinAlreadyLoaded=2`. Neither this contract nor the previously successful loads establishes that an existing unusable CAM object will be initialized again. This is one bounded qualification, not a documented recovery guarantee.

Primary sources checked 2026-11-04:

- [ISldWorks.LoadAddIn](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~LoadAddIn.html)
- [2026 swLoadAddinError_e](https://help.solidworks.com/2026/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swLoadAddinError_e.html)

The 2026 method web URL returned only the site shell when checked; the accessible 2025 method contract and the explicit 2026 enum are distinguished here.

The core rereads process lifetime, all documents (including hidden), active document, and DLL bytes. An existing bridge and a fresh GetCWApp E_POINTER are mandatory. E_POINTER may be the direct HRESULT or the numeric EXCEPINFO scode nested under DISP_E_EXCEPTION. Raw COM text is not retained. A ready API instead produces an `already_ready` receipt with zero load calls and no marker.

Before the single LoadAddIn call, a durable exclusive once marker and pending receipt are written. The marker key includes scope, PID, creation time and CLSID, and excludes user output names and DLL spelling, preventing replay through a renamed receipt. A second process/document/DLL guard runs after claim and before dispatch. Markers are never removed by this path. Failure to persist pre-dispatch state prevents dispatch. A failed final write never reports verified success.

Only integer return 0 plus a readable API, unchanged exact process, empty session and unchanged DLL bytes yields verified initialization. Boolean false is not integer success. Return 2 and other nonzero values remain recorded failure outcomes even if subsequent getters work; there is no retry, alternate argument, unload, UI, restart, license call, model open/close/save or CAM generation.

The previous successful sequence for PID55536 was connect, explicit CAM load with no documents, then opening the part. The preserved `READ_ACTUAL_RECIPE_RESULT.json` shows load attempted, result0, API available, demo false, no issues and no documents before/after. The 2026-11-04 failure occurred before any capture at GetCWApp. These facts motivate the bounded test but do not prove its cause or expected success.

Install only the new core module, new test and this document. Add `SolidWorksCamLoadInput` and replace only `solidworks_cam_load_addin` from `SERVER_NODES.py`; preserve all other current server nodes. The staged whole server is an offline test snapshot predating the independently installed append tool and must never replace the installed server. No registry tool-count change is needed.
