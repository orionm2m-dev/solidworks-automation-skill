Saved CAM WIP export regression tests
====================================

Run from the repository root: `python -m pytest tests/cam_saved18_wip -q`.

These 59 tests use synthetic fixtures and the installed modules. They verify direct saved-state binding, strict export completion, before/after identity, native length readback, cleanup, exclusive export markers and rejection of route mutations. They do not connect to CAD or establish machining safety.
