# Read a consumed CAM process import (pilot)

solidworks_cam_read_imported_process reads RAM after one successful ImportCAMData return whose subsequent local reader stopped at the missing ICWConfiguration allowlist entry. It never imports again, saves, rebuilds, generates paths or changes settings.

Supply the exact process/lifetime, target path/source SHA, active CAD and CAM configuration names, pinned original import receipt, and a fresh output path. The original receipt must remain terminal uncertain, with strict integer HRESULT0, no pending call, no Save/GTP or other mutation, and clean disconnected events. Its existing target-only attempt marker, original sources, archive and export evidence are checked without modification. This recovery is observation, not retroactive rewriting of the original outcome.

File authority is validated once before application access. An invocation-local prepared bundle is consumed once after checking its request, pins and output. The live context holds the same owned-process lock and event guard as the importer. Two complete bounded inventories must agree on actual IDs, types, links, tools, setups and cached counts. The reader also checks CAD configuration and body fingerprint against the pre-import capture. The original importer and its capture code remain unchanged.

The public helper adds exactly ICWConfiguration IID {F74643C0-2AE2-4446-BE21-8C43F7881882}. Before reading an application, preflight resolves all 15 inventory interface names through the installed allowlist and public type library. No fallback interface is guessed.

A successful report is review_required, with seven observation/preservation flags true, before and after inventories, source hashes, imported receipt and consumed-marker pins, and clean event cleanup. It retains import_receipt_status=uncertain, model_saved=false, association/stock/production qualification false. CAD needs_save=false does not establish that CAM has been saved. A later separately authorized save must bind this successful recovery receipt and re-observe the same RAM state.

This endpoint remains a pilot until actual native readback succeeds. Software tests, static public ABI proof and a no-application constructor check are not native qualification.
