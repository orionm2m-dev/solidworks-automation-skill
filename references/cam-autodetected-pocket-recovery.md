# Read a consumed pocket definition

Pilot endpoint `solidworks_cam_read_detected_pocket_recovery` continues a completed creation whose local comparison rejected an appended CAD Attribute suffix. The immutable creator receipt retains `uncertain` and its false acceptance flags. This endpoint never calls CreateMillFeature2, import, GOP, GTP, rebuild or Save.

The request supplies the exact PID/lifetime, document/source hash, CAD/CAM configuration, consumed creator receipt/hash, returned feature ID, explicitly reviewed ordered Attribute suffix and a fresh output receipt. Only that exact suffix is admitted. Existing tree rows, analytic sketch, solid fingerprint, other CAM rows and zero operations remain protected. Attribute payload and feature association are not inspected or qualified. No island geometry getter is attempted.

The backend reuses the existing bounded generic inventory, scalar header getters and analytic circle reader. Two fresh inventory/header captures must agree with the pinned observed after-state, with zero CAM events and successful cleanup, process/source/runtime guards. Success is `definition_only`; physical depth, island geometry, material, stock and machining/production acceptance remain false.

`verify_recovery_receipt(path,sha)` checks durable evidence for a later explicitly guarded Save transition. It deliberately does not claim that historical mutable document bytes remain current; its caller must validate the new saved source transition and every immutable input pin. Live use always calls `prepare`, which verifies the current source and all protected pins.

Software tests and metadata preflight do not qualify native execution. Native acceptance is pending until a separate actual receipt records both fresh reads and cleanup. No automatic creation retry is allowed.
