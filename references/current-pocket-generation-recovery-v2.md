# Observed generation Save/CL recovery V2

This fixed endpoint continues a genuine terminal V2 generation failure only when the existing verifier proves one explicitly recorded XYFeed change, alongside the selected operation's first generated path. It preserves the uncertain original receipt and every original evidence pin. The observed feed and its cause remain unqualified.

The new module uses the existing V2 full capture and dispatch guards with 128 evidence pins. Legacy modules, endpoints and receipts retain their original scope and bytes. Canonical deduplication preserves the complete Save authority union; the Save bundle is recomputed after adding the ABI pins. Marker receipt paths use the producer's exact str(Path(...)) serialization, while every marker field, hash and scope remains exact.

Before any Save, a fresh full generated snapshot must equal the immutable observed state. A second full snapshot is both independent confirmation and the existing Save-before check. Exactly one existing native Save is followed by its full after capture. Exactly one CL export uses the unchanged existing export primitive and its two full captures, then strict CL parsing and count checks. Thus the route has five full captures. No setter, tool assignment or GTP replay is allowed. Failed or pending actions are never retried.

The resulting generated-context payload has its own V2 scope. Generic saved-context loaders deliberately reject it. Saving and exporting do not qualify feed, physical depth, geometry sweep, cutting conditions, tool access or production readiness. The caller must separately review the actual exported CL against the original engineering geometry.

Offline validation uses a byte-identical genuine V2 partial fixture and the existing pure reconciliation and Save-flow tests, plus explicit 128-pin preservation and unchanged-native-sequence checks. Native execution remains separately owned and is not claimed by these tests.
