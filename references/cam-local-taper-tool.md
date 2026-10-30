# Local tapered tool qualification

These modules qualify one local flat-taper tool through the native CAM API. Historical creation evidence and subsequent configuration are separate phases. It does not insert an operation, assign a tool, generate a path, or write to the technology database.

## Before native execution

Use the saved checkpoint, model archive, current model hash, and the actual existing tool catalogue. Compare every observed tool type with the reader coverage before starting full profile reads. A passing test suite with only end-mill fixtures does not establish support for a mixed tool crib. Preserve a catalogue-shaped regression case when a new type is encountered.

Before creation or setters, resolve every required typed interface through the actual module access path. Check the pinned generated declaration, IID, property signatures, and supported-interface registration or scoped extension. A type present in the vendor library is not sufficient when the local bridge cannot resolve it. For an existing candidate, perform its guarded native interface query before the first setter.

The initial catalogue and each partial tool observation must be persisted before decoding the next tool. A rejected type must identify its native ID and type. If the attempt stopped before mutation, retain its receipt and explain the changed reader coverage before another attempt. An uncertain creator or setter must never be replayed automatically.

## Scope of preservation

Read the identity, generic fields, available native tool and shank profiles, and holder fields/profile of every existing tool. Keep the specialized end-mill and user-defined readers where applicable. For other types, the common tool interface records geometry without claiming to read all subtype parameters. A successfully observed absent legacy profile is distinct from a failed or incomplete read; neither establishes physical tool qualification.

The new tool must pass the complete cutting-profile and conservative noncutting-envelope checks. Check the document and CAM unit scope independently. API angle values are proposals until the returned native profile confirms their physical meaning. A conservative envelope must not be described as the manufacturer's exact shoulder geometry.

## Save and continuation

The operation uses a persistent once-only marker, exact owned process/document guards, and immediate scalar readback. Read the cone after its three coupled parameters have been set, then the completed tool, then its saved state. Set the protrusion after loading the holder, because loading can change it.

Save once only after the geometry and old-state checks pass. Require the native integer success return, a clean document, a changed saved hash, and unchanged protected observations. The continuation loader checks the old model through its separate immutable archive and checks the new model through its actual current hash. It must not substitute the old hash for the new file.

The terminal receipt is a scoped tool-definition qualification. Stock clearance, machining depths, cutter engagement, feeds/speeds, machine/fixture limits, and the resulting toolpath require their own evidence.

## Entry point

The addressed continuation entry configures only the existing tool identified by a completed creation receipt. It cannot create another tool. The earlier creation prototype is not a qualified fresh-creation entry: its missing interface coverage was detected after creation. Preserve its receipt and continue through the audited interface extension.

Run the permanent continuation module from the skill repository:

```console
python -m scripts.sw_cam_taper_tool_resume --request request.json --validate-only
python -m scripts.sw_cam_taper_tool_resume --request request.json
```

The request carries explicit paths and pinned inputs. The validation-only action does not connect to CAD. Do not repeat the execution command after an uncertain result; read its receipt first.
