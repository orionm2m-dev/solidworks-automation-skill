# Saved caps in the current pocket context

The existing compact current-context serializer now retains three fields only for a saved_cam_caps definition: request.source_variant, creator.circle_readback, and origin_kind. These are required by the already installed definition.capture reader. The current observed circle remains separate from its historical specification receipt; genuine recovery remains recovery. Legacy compact payloads are unchanged.

No native getter, setter, Save, event, lifetime, file, inventory, or geometry guard changes. No server endpoint or request schema changes. This patch enables the existing saved pair -> tool assignment/Save -> seven-field first GTP/Save/CL route to keep its already verified current-circle authority. It does not qualify world mapping, tool clearance, feeds, or machining.

Portable tests reuse installed test_current_pocket_context.py fixtures. They exercise full versus compact definition.capture, reject a changed live circle, preserve current versus historical geometry through Save/serialization/load, reject missing current authority fields, and preserve legacy serialization. All native interfaces are mocked in those tests.
