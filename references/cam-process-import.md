# Isolated native CAM process import (pilot)

`solidworks_cam_import_process_data` makes one `ICWApp4.ImportCAMData(path, 0, false)` call into an already-open, clean, isolated byte-copy of a pinned native part. It then observes the resulting RAM state. It does not save the copy, create or open documents, activate another document, explicitly rebuild, generate toolpaths, change TechDB, or retry.

## Authority and entry conditions

Supply the exact owned process ID and creation time; the active copy path and SHA; the separate original part path and identical SHA; a successful `solidworks_cam_export_process_data` receipt path/SHA; and a fresh result receipt path. The exporter receipt supplies the pinned `.prtcam`, historical CAM source and complete ordered archive operation inventory. Original part, CAM source, archive, receipt and copy disk bytes must remain unchanged. The original and copy must be different physical files in different directories.

The target is created externally with exclusive creation; this endpoint verifies separate physical files, identical disk bytes and current file identities. It does not create or open the target. Two matching empty native observations are required before dispatch.

The public schema also requires the actual registered `addin_clsid`. `qualification_only`, `acknowledge_isolated_copy` and `allow_vendor_default_import_rebuild` must all be exactly true. `message_policy` is `vendor_default`; an expected title is not accepted in place of a saved path.

The reused pre-import reader accepts an existing CAM document/machine with type UNKNOWN, MILL or TURN, zero features and zero operations. A null workpiece is allowed. No machine assignment or CAM initialization is performed. A genuinely null CAM active-document or machine object is a concrete reader limitation: the endpoint stops before import. This is not asserted to be an ImportCAMData API requirement. The post-import reader records generic MILL identities, feature type/name, setup vectors, operation links/flags, tool scalars and cached counts; it does not decode feature contours or CL records. It requires bounded data (up to 8 setups, 64 features, 32 operations and 100000 total cached records).

## Native effects and evidence

The caller explicitly permits vendor-default effects inside the import, including any import-end rebuild response. The endpoint records CAM messages and does not set a response or automate a window. There is no documented suppression guarantee. No explicit Save/GTP/GOP/AFR/Rebuild call is made by this module.

File-only authority is prepared once into a private invocation-local bundle. Before application access and before dispatch, request, pinned files, output freshness, process, document and runtime are checked. A canonical target-path one-shot marker (independent of archive hash and source revision) and pending receipt are durable before the single native call; its primitive return is written before readback. The consumed mutation guard is closed before adopting the complete recorded import-event baseline and entering a fresh read-only guard. New messages during that readback are rejected; recorded messages are never cleared. Any import message also prevents terminal acceptance: the after-state remains diagnostic evidence and the result is uncertain with no automatic retry.

Success is `review_required`, `phase=finished`, with `import_observed` and `readback_verified` true. The copy remains unsaved. The archive comparison reports actual target IDs separately from historical IDs, ordered descriptor observations and cached record counts. Matching counts are not proof of feature association or CL equivalence. Vendor help explicitly excludes stock parameters from the process export, so stock must be separately verified. Stock transfer, machine/controller suitability, holder geometry, full BRep equality, machining validity and complete CAM migration remain unqualified. Native CAD body bounds/mass are only a preservation fingerprint.

Any import exception, uncertain result or post-read mismatch leaves the one-shot marker and all available evidence. There is no automatic replay or Save. Root/user decides the next separate inspection or cleanup action.

## Installation and qualification

The package is software-tested staging only. Merge the two named AST nodes from `server.fragment.py` into the then-current server; do not replace it with an older server copy. Install the single module and portable tests under an exclusive runtime lease, register the pilot capability/reference, and use a new runtime fingerprint. Do not install while another native call is active.

A real request can be sealed only after a completed current-source export and exclusive byte-copy/open evidence exist. A metadata ABI check and fake-backend tests are not a successful native import. No native import has been performed by this package.
