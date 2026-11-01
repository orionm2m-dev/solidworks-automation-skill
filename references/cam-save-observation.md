# CAM save error observation

`solidworks_cam_observe_save_errors` reads existing windows for one exact process ID and creation time. It does not call COM, send window commands, change focus, dismiss a dialog or retry a save. It can run while a native save owns the COM lock.

Use an explicit `save_attempt_key` for a save attempt and carry its returned `previous_observation` into subsequent observations of that same attempt. An observed error remains latched after the window disappears. Unknown CAM dialogs or incomplete ownership/readback yield an inconclusive result.

An HRESULT of zero, a clean in-memory document and changed SLDPRT bytes do not override an observed CAM data-save failure. Preserve the current document and the previous saved checkpoint, then independently establish the CAM state on disk. Absence of a dialog does not establish persistence.

The observer is a bounded diagnostic tool, not a background service. Call it explicitly during save monitoring. Current matching recognizes the observed Russian CAM save failure; other CAM dialogs require interpretation before accepting the save.
