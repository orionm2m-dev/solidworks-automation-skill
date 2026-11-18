# DFMXpress native API research

Evidence date: 11 November 2026. Exact-build API research; no general DFMXpress
runner is qualified. The exact-build owner-STA path below has completed both
Injection Molding wall rules on current R15 with minimum-thickness findings.

## Qualified owner-STA native analysis of current R15

Live execution completed for the exact reviewed build in the task-owned SW
owner thread: one Initialize/process, qualified derived DFMIMDocument, engine
update to Injection Molding, registered rules6001/6002, full bounded result/entity
readback, normal result-set destructors, Terminate with null document, stable
post-binding/source hashes and native_return0. Minimum2mm:74 eligible checks,
74 findings. Maximum3mm:77 eligible checks, zero findings. These are rule counts,
not face counts or production acceptance. Persistent face references, area and
boxes are saved for every reported entity; refs are exact-copy/config/hash scoped.

Static units are now qualified for these exact calls: ITessellation public
IGetVertexPoint slot0x130/DISPID22 returns API metre coordinates; shipped
GetVerticesFromSWFacet multiplies XYZ by1000 before backend vertex creation.
Both min and max comparison bodies convert source length-unit0 to the engine
unit. Unit0 is mm and configured target0 yields identity. Engine setters2/3 with
flags0/0 therefore mean2/3mm. The direct unregistered factory rule's separate
updateRule defaults0.002/0.003 do not justify changing registered engine inputs.
The code/data evidence and official API units source are pinned in UNIT_CONTRACT_REVIEW.

Shared core was deliberately reused only in this task-created process with no
live analysis/results, verified exact physical DLL/hash. That absence is a caller
precondition backed by task history, not a general native busy-state detector.
Recognizer/view/rules had to be absent before load. The exported engine update
intentionally replaced our prior transient milling state; no restoration is
required for this scoped task. No global loader defaults or registry edits.
Temporary own AddDllDirectory cookies were removed; vendor modules and core
singleton remain loaded until normal process lifetime ends. Two bounded native
reference objects also remain process-lifetime; do not claim full library unload.

The host is one-shot and future replay is denied by its attempt latch and module
preconditions. Do not rerun this consumed macro or force-unload vendor modules.
General reusable runner lifecycle still needs qualification before broad MCP
execution exposure. No UI input, license manipulation, file patch, CAD save or
geometry creation was used. Current raw evidence supersedes older external-host
failure descriptions below; historical receipts are retained.

## Discovery and evidence levels

Search the existing project knowledge index through `solidworks_query_knowledge_index`
for `DFMXpress`, then get a topic with `detail=true, verify_sources=true`.
Topic IDs start with `swfork.dfmxpress.`. The project owns exact paths, hashes,
evidence IDs, receipts and its authoritative continuation checkpoint.

Distinguish exported metadata, static interpretation, isolated native preflight,
live CAD execution and engineering acceptance. DLL load, successful COM return
or a constructed rule does not establish the other levels.

REA is used for API understanding and assigned native integration development.
No binary patching, licensing/activation/access-control or other protection
bypass is part of this workflow. Preserve negative results and exact arguments.

## Public COM route

The installed class is `DFMAddin.DFMEngine.1`, CLSID
`{55AD5940-7906-458D-897F-5508B2891DC5}`, IID
`{3915914A-DB23-4DBB-89B6-1E4ECEC0B02F}`.
Observed dispatch IDs: InvokeValidator=1, DisplayPMP=2, StartConfigurator=3,
StartDFMExpress=9, SetPartType=10. The type library describes SetPartType(BSTR)
with mill/turn examples.

Tested English/Russian injection labels and the documented turn control all
left the observed process at milling. A separate idle/readback boundary also
remained milling. GUID and ProgID resolved to the same object identity.
Do not repeat label guessing or infer selection from a successful return.

DisplayPMP opened a sample property manager, not analysis; it was cancelled by
native application command. InvokeValidator has not been called. Read-only
settings showed 2/3 mm generic thresholds, not material-specific approval.
Registry writes were not used.

## Library roles and version binding

The add-in is dfmaddinu.dll; dfmcoreu.dll owns rule/document/result classes;
DFMIMRulesu.dll implements injection wall checks; DFMIMFeatureRecognizeru.dll
builds the derived injection document. dfmresultu.ocx was inventoried only.

All addresses below are static virtual addresses for the studied x64 build,
not stable callable entry points. Resolve verified export names and exact hashes.
The copied inputs and installed originals are pinned in INPUTS_VERIFIED.json.
Do not call an arbitrary address because a decompiler displayed it.

RuleEngine::update(const wchar_t*, DFMPartType_e, long, long) selects injection
rules for enum3 (sheet metal is2). The loader installs rules6001 and6002.
This is static evidence, not live process selection. Engine execute returns
false on the inspected normal completion path, so its boolean is not acceptance.

## Rule contracts: static, native qualification pending

getRule at0x180004530 is interpreted as `int getRule(int,void**)`.
IDs6001/6002 allocate minimum/maximum wall rules. It sets output null first,
returns0 for a non-null allocation, otherwise-1. Verify the actual returned ID.

setRule at0x180004620 is called by core with rule reference, selector, double
pointer, length unit and angle unit. The inspected implementation consumes the
first three; units arguments are unused there. It dereferences the rule before
a later null check. Never supply a null rule. The five-argument signature is
caller-derived, not a recovered vendor header.

updateRule(long,long) establishes module-local units, loads resources and resets
threshold data. Length conversion code identifies0=mm,1=cm,2=m,3=inch.
After qualification, an explicit setRule must follow updateRule; verify the
threshold readback. Recognized wall thickness is converted from mm to selected
units. A constructor's raw threshold field alone is not a physical value.

Version-bound read-only object offsets are in NATIVE_CONTRACTS.json.
Do not write readiness/enabled flags or object internals to force execution.

Minimum execute is0x180016830, maximum0x18000ef10. The demangled method is
`long execute(const DFMDocument*&,DFMResultSet*&) const` plus this.
Inspected returns: -5 missing document/result, -3 uninitialized rule guard,
-4 invalid document,0 after the rule call. Zero is not PASS.

## Recognizer contracts and lifetime

C exports in DFMIMFeatureRecognizeru.dll:

- Initialize() at0x180001910 clears a module-global retained recognizer list.
  Do not call it as a blind reset in an existing host.
- process at0x1800015d0 has inferred void signature
  `process(CComPtr<ISldWorks>&,CComPtr<IBody>&,long,DFMIMDocument*&,IFeatureRecognizerCallback*)`.
  It obtains the application's active document, allocates the derived document
  when output is null, calls recognition and retains its recognizer.
  It does not propagate the member recognition error.
- Terminate(DFMIMDocument*&) at0x1800017f0 destroys and nulls the document,
  destroys retained recognizers and clears the module-global list.
  Prove exclusive ownership before initialization or cleanup.

The member process at0x180004650 creates a wall manager and stores ribs,
nominal thickness and wall-thickness data in DFMIMDocument. Some null/empty-body
paths return0 without creating useful data.

A base DFMDocument is insufficient: wall checks cast to DFMIMDocument and access
ribs and wall data. Never substitute a hand-built base wrapper.

The C entry implicitly reads active CAD. Before/after recognition prove the same
owned process, body, active document, configuration and file identity.
The long parameter's full semantics remain unknown. Null callback handling is
statically supported and live body QI/active-document binding are verified below.
The standalone recognizer host contract and full allocator/cleanup lifecycle
remain unqualified after the first native exception.

## Results and false-pass prevention

Core exports provide DFMResultSet constructor/destructor, getNumRuns,
getNumResults, getResult, getRule and entity getters. Observed result-set size:
48 bytes. A passed check adds null; a failure adds a geometry-bearing result.
Use proper getters; result count and checked-run count are different.

The rule can silently skip an absent wall object. A report must prove non-null
recognized wall data, eligible geometry, meaningful positive run count,
rule IDs, units, thresholds and stable document binding.
Zero failures with zero checks is incomplete, never PASS.
Per-face measurement/entity extraction and cross-module ownership need validation.

Min/max wall checks do not cover draft, undercuts, parting line, ejection,
gate geometry, weld lines, packing, cooling, warpage or mesh convergence.
They do not close full injection-moulding DFM.

## Host, startup and continuation

The general AddinHost exposes fixed CAM JSON calls, not a DFM export bridge.
An owner-STA qualification module demonstrates invisible Control.Invoke,
busy gating, PID creation-time, document hash, config and host identity guards.
It is a design reference, not an implemented DFM route.
The old macro/native sample has hardcoded jobs and lacks required case guards.

The inspected environment has x64 MSVC and ATL; MFC development headers/libs
were not found. Installed MFC runtime presence is a separate fact.
The bounded standalone preflight checks the exact DLL SHA before loading,
constructs only two rules and reads raw fields; no COM/CAD/setters/execute.
Compilation and runtime are separate receipts. The two bounded objects are
reclaimed by process exit until the destructor ABI is independently qualified.

A prior .NET error and a separate Plastics import crash are distinct events.
Independent .NET execution passed; a later ordinary Windows launch loaded CLR
and DFMXpress. Root cause is not proven. No global reinstall or registry repair
is justified by these observations. Reuse exact registered paths:
a forward-slash/alias attempt returned FileNotFound.

Before native work read the project checkpoint through MCP. Pin owned PID and
creation time, executable identity, exact document/config/hash, operation lock
and the one visible owned document. Do not replay an unknown-outcome mutation.

For every finding save input, arguments, return/readback, library identity,
evidence file and limitations. Update the knowledge topic and verify search/get
through real MCP. Hash matching is not live qualification.
REA bundles/snapshots preserve evidence; a .gzf-looking name here does not prove
a persisted native Ghidra database. Export evidence before closing the session.

Related: [Plastics](plastics-native-api-research.md),
[knowledge index](fork-knowledge-index.md).

## Isolated native preflight and initialization correction

The bounded standalone helper was actually executed on11 November2026 and exited0.
Both getRule calls returned0 with IDs6001/6002. Both raw initialization guards
at+0x104 and thresholds at+0x110 were0. There were no COM, setter, validator or
execute calls. This qualifies creation/readback in that isolated environment only.
The first launcher attempt failed before process creation because a PowerShell
provider-qualified path was passed to ProcessStartInfo; using the file's FullName
fixed the path. Both the prelaunch failure and actual run receipts are retained.

Subsequent static tracing found the normal initialization path:
RuleEngine.update -> loader0x180016ee0 -> factory0x180012c70 ->
registration0x180012ab0. Registration invokes virtual initialization and
updateRule, then the vendor code itself sets+0x104=1 and registers the rule by
its CString title. Thus the field is an initialization guard; do not describe it
as a checkbox or license flag. Direct getRule/updateRule/setRule omits engine
registration and is not a complete runner.

RuleEngine.setState at0x180017560 modifies a different selection map; it does not
initialize that guard. CDfmRule.initializeParamStorage and base updateRule are
no-ops in the studied base implementation. Uppercase UpdateRule copies parameter
data and differs from lowercase updateRule. The pointer assignment operator does
not establish readiness either. No direct internal-field writes are permitted.

Additional exported contracts studied: RuleEngine.getEngine() returns the
singleton; update(L"",3,0,0) selects injection and runs registration;
getRule(const wchar_t*) looks up the registered title, returning null if absent.
SetMinimumWallThicknessValue(double,long,long) and its maximum counterpart call
the rules DLL setter with five ABI arguments. The engine constructor establishes
Metric Unit/DocumentUnit/mm defaults. Engine-internal type+0x20 becomes4 for the
injection group; input enum3 and that internal field must not be conflated.

Next qualification is the public native engine lifecycle and parameter readback,
followed by recognizer/CAD binding. Do not skip from successful construction to
an actual rule run. The project preserves the new static records and exact
runtime preflight receipts in its knowledge index.

The installed server exposes the knowledge tool (verified by real stdio
discovery/search/get). A previously connected client may need refreshed tool
discovery; tool availability in a particular client's old list is not implied.

## Native engine lifecycle qualified in an isolated process

The separate engine probe completed on11 November2026, with receipt plus observed
process exit0 after normal teardown. Both pinned DLL hashes and physical loaded
file identities matched. No COM/CAD, execute, validator, setState or direct native
memory writes occurred.

The tested sequence is getEngine -> update(L"",3,0,0) -> native minimum setter2
and maximum setter3 -> exported getRule by observed native title.
Both engine-owned rules had their expected IDs6001/6002, initialization guard1
and raw thresholds2/3. Titles read from separate native reference rules were
"Минимальная толщина стенки" and "Максимальная толщина стенки".
Lookup succeeded with copied bounded strings; no guessed localized label was used.

The separate title-reference rules retained guard0; their lowercase updateRule
readbacks were0.002 and0.003. These defaults must not be mistaken for the later
explicit engine-set threshold representation. Unit semantics remain grounded in
the retained conversion/comparison evidence; actual CAD measurement comparison
has not yet completed; the first guarded attempt failed as documented below.

This qualifies the normal engine preparation path on the exact installed build.
It does not qualify the recognizer, body/active-document binding, rule execution,
report geometry or engineering acceptability. Reuse this sequence without
repeating the constructor-only probe or the failed COM selector labels.

The parameter-only helper was also compiled and documented, but was not run:
the engine probe supplies the relevant normal lifecycle evidence.

## Exact result-reader contracts: static follow-up

DFMResultSet.add increments getNumRuns for every call; only a non-null result is
appended to the result vector. In the studied thickness-rule context this gives
checked runs versus failures. getResult(index) and getEntity(index) need explicit
caller bounds; their inspected bodies do not establish a safe out-of-range API.

DFMResult.getEntity returns a reference to DFMEntityId. Its getEntity returns
CComPtr<IUnknown> by value using a hidden output buffer in RDX (x64 observed
decompilation), copying the CComPtr stored at entity+8. Do not declare this as a
plain IUnknown* return. Ownership/AddRef and this ABI still need live qualification
before mapping native result entities to CAD persistent references.

## Recognizer binding and callback evidence

A read-only live binding check confirmed the exact current owned process and
creation time, executable file identity, read-only document/configuration/hash,
one visible document and one solid body. Both legacy IBody and IBody2
QueryInterface calls succeeded. No recognizer or rule execution occurred in this
check. Stored process IDs are historical evidence, never reusable authority.

The exact installed type-library inventory pins ISldWorks, IModelDoc2, IPartDoc,
IBody/IBody2, configuration and extension interfaces. IsOpenedReadOnly is a
method (DISPID65914), not an assumed property. PartDoc.GetBodies2(0,false)
is the selected one-body path. Metadata is read using comtypes
LoadTypeLibEx(REGKIND_NONE); pywin32 pythoncom has no LoadTypeLibEx in this
environment. The unsuccessful metadata attempt did not activate a COM class.

The callback scope stores the supplied callback at module state and clears it
on exit. Its cancel helper returns a false low byte when callback is null; the
progress helper skips null. This statically supports nullptr for this build.
The inspected member process does not use its long argument; zero is a bounded
qualification value, not a documented general enum interpretation.

ProcessWallThickness invokes native tessellation and wall recognition. Retained
raw defaults include tessellation50, minimum-edge0.75, minimum-area0 and
sharp-angle45, followed by Run(mode2, nominal-output). These are inspected
implementation values, not qualified user-facing mesh controls or quality claims.

GetWallThickness(DFMIMDocument*,out&) reads the wall object; nominal getter reads
the native double. A non-null document alone is insufficient. The separate
getSWDoc export returns CComPtr<IModelDoc2> by value: observed x64 this in RCX,
hidden output buffer in RDX, copied from document+8, returned buffer in RAX.
The native stored document must match the expected canonical COM identity/path.
isValid only establishes a non-null stored document, not that identity.

A future full runner must retain the recognized DFMIMDocument for both wall
rules in the same process, save results before destructor/Terminate, then verify
native cleanup and process exit. Avoid discarding a completed recognition merely
to repeat it in another helper. No live recognizer run has yet been qualified.

Result localization uses the pinned document's public Extension.GetPersistReference3
with a VT_DISPATCH entity argument (DISPID98), returning a VARIANT byte array.
IFace2 area/box getters are recorded for optional geometry locations. Such
metadata is not a live proof of result-entity ABI or a persistent reference
valid after model/configuration changes. Bounds and missing mappings must remain
explicit in reports; do not turn an incomplete readback into a pass.

## First guarded recognizer attempt: failure retained

The first combined helper reached the exact live read-only R15 document/body
with stable canonical COM identities. Hash-pinned native libraries loaded and
Initialize returned. The single recognizer.process call raised native
0xC0000005 inside the separate helper; the helper caught it and exited1.
It left a non-null partial document. Neither wall-rule execute was called.
This is not a managed .NET exception and is not a successful DFM analysis.

After the caught exception, the same SOLIDWORKS process answered read-only
binding checks; model, configuration, dirty flag, body identities and source
SHA256 matched. No source was saved. Geometry immutability was not independently
established by a geometry fingerprint. The last helper guards were observed
before helper process exit, whose exit1 was separately recorded.

The output field cleanup_and_post_binding_complete only means the attempted
post-check branch returned. Native Terminate was deliberately NOT called on
the unknown partial object; native_cleanup_qualified is false in the derived
qualification receipt. Process teardown reclaimed the helper. Do not describe
this as successful recognizer lifecycle qualification.

Fault address/module/access target were not captured by this version. A non-null
partial document narrows the likely failure interval only under normal memory
integrity; it does not establish the failing function or prove that all COM
geometry methods support external-process use. MFC host/thread context,
body/backend marshaling and geometric dependencies remain hypotheses.
Do not replay the unchanged executable, patch internal flags, or assume
that moving it inside SOLIDWORKS is a proven fix.

Next: preserve the first receipt and use static evidence plus a separately
reviewed diagnostic/host contract to locate the missing precondition.
The passed constructor-only and engine-preparation runs remain reusable.

## Failure diagnosis and diagnostic-only build

FAILED_ROUTE_DIAGNOSIS.json preserves observations, bounded inferences and ranked
hypotheses with exact evidence IDs. The non-null partial document weakens a
completely wrong entry argument-layout hypothesis, but does not prove that
downstream geometry operations support external COM proxies. The inspected
entry already establishes MFC module state. Neither blanket MFC initialization
nor changing IBody IID is a confirmed fix.

A separate diagnostic-only build captures EXCEPTION_POINTERS (exception address,
read/write/execute kind and target, module/base/RVA, instruction and argument
registers). It was compiled with zero warnings and was NOT executed. The original
failed source/EXE and run receipts remain unchanged. Build success is not
authorization or evidence for an unchanged replay. Next work is the missing
MOD_BODY/IMViewManager/backend host contract and a reviewed diagnostic plan.

## Located tessellation fault: diagnostic execution

The separately reviewed fault-capture build was subsequently executed once
(diagnostic_run_001, observed helper exit1). It caught a read from null in
DFMIMViewu.dll at RVA0x2d1b6. The helper's saved post-checks retained the same
owned process, read-only R15 document/configuration/body identities and source
SHA256; no wall rules ran.

Matching REA assembly locates the exception in
IMViewWallThickness::GetBodyTessellation (entry RVA0x2d0c0). It calls IBody2
vtable offset0x3e0 with NumOfFaces0, null FaceList and output pointer, stores
but does not check HRESULT, then dereferences the null ITessellation before
calling put_MaxFacetWidth. Installed SW2026 TLB identifies offset0x3e0 as
IBody2.IGetTessellation, DISPID116. The dispatch alternative GetTessellation
is DISPID115/offset0x3d8.

This establishes the immediate failure mechanism, not why IGetTessellation
returned no object. The preceding HRESULT is not retained by the first diagnostic.
The official IGetTessellation page says null FaceList selects the whole body;
the inspected page does not establish an in-process-only restriction. Do not
infer a geometry defect or an external COM restriction without comparison.

Next independent probe compares exact native IGetTessellation HRESULT/nullness
with dispatch GetTessellation(VT_EMPTY), with the same process/source/body guards.
No DFM DLL, recognizer or Tessellate call is needed for that getter comparison.
A possible owner-STA host route is being prepared separately; a compiled route
must not be described as a tested solution.

## External accessor comparison: RPC null-reference failure

The COM-only getter probe completed and the observer recorded process exit0.
On the same exact guarded R15 body, native IGetTessellation(0,nullptr,out)
returned HRESULT0x800706F4 with null output and no SEH. The dispatch alternative
GetTessellation(VT_EMPTY) returned S_OK, a nonnull object and successful
ITessellation QueryInterface. Document/body identities and source hash remained
stable after both calls. No DFM library, recognizer, Tessellate, setter or CAD
save was invoked.

The HRESULT contains Win32 error1780 (0x6F4), RPC_X_NULL_REF_POINTER.
Microsoft's error table and local Windows message identify a null-reference
pointer passed to the RPC stub. Combined with the shipped DFM caller's unchecked
result, this explains the external-host failure for this exact null-FaceList
invocation. It does not establish a universal restriction on all IGet calls.

The next qualification compares the same public getters inside the owned
SOLIDWORKS owner STA. A new own sidecar may supply that execution context.
The PID mutex belongs inside the owner-thread command; an external caller must
not hold the same mutex while synchronously waiting for that command.
Registration, actual loaded GUID/MVID, PID/create time, native DLL hash,
current read-only document/configuration/body and source hash must be checked
independently. A successful load return or compiled host does not qualify DFM.

Source: https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--1700-3999-

## Owner-STA getter comparison: live qualified

A single RunMacro2 call executed the reviewed ASCII SWBasic macro and its own
native DLL inside the pinned SOLIDWORKS process. Both IGetTessellation(0,null,out)
and GetTessellation(VT_EMPTY) returned S_OK, nonnull ITessellation and successful
QI. The same native getter previously failed externally with 0x800706F4/null.
The in-process result qualifies this execution context for this exact call.

Owner context was independently established through ISldWorks.Frame,
IFrame.GetHWndx64 and GetWindowThreadProcessId, matching the current native
thread and pinned PID/lifetime. STA, exact source/configuration/body identity,
read-only flag, initial dirty flag and source SHA remained stable. No DFM DLL,
recognizer, Tessellate, rule, CAD save, UI input or registry write was invoked.

GetMacroMethods(path,1) returned null for this SWB. The single source-reviewed
main was then invoked with module OwnerStaTessellation1, procedure main using
the filename+1 convention of the existing native macro bridge. RunMacro2=true,
error0 AND the independently checked native report/native_return=0 establish
this specific route; null method enumeration alone does not prove bad syntax,
and the general SWB metadata contract remains unproven. The PID mutex is owned
inside the DLL; the external synchronous caller must release it before RunMacro2.

Next: adapt recognizer and two wall rules to the same owner context. Inspect
already-loaded vendor modules and shared RuleEngine state first. Never transplant
EXE process-global loader changes or process-exit cleanup assumptions into an
in-process DLL. Getter success is not a completed DFMXpress analysis.
