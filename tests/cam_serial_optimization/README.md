# Saved CAM verification and local operation optimization tests

These tests exercise saved-state verification, complete receipt loading, bounded parameter changes, single-dispatch generation, protected CL streams and the MCP wrapper. Connections and CAM interfaces are synthetic; no native CAD operation is performed.

From the repository root:

```sh
python -B -m pytest tests/cam_serial_optimization -p no:cacheprovider
```

The repository is the default implementation root. Set `SOLIDWORKS_SKILL_ROOT` only to test another installed checkout. Imports must come entirely from that checkout; there is no staged implementation fallback.

These checks validate software behavior. They do not establish geometry, cutting-load or manufacturing acceptance.
