"""One-shot UD specimen probe state machine; caller owns all guarded native access."""
from copy import deepcopy


def verify_one_new_tool(before, after, new_id):
    if type(new_id) is not int or new_id <= 0:
        raise ValueError('Positive actual new tool ID required')
    old = {x['native_id']: x for x in before}
    current = {x['native_id']: x for x in after}
    if len(old) != len(before) or len(current) != len(after) or new_id in old:
        raise ValueError('Duplicate or reused tool identity')
    if set(current) != set(old) | {new_id} or any(current[k] != v for k,v in old.items()):
        raise ValueError('Expected exactly one new local tool and unchanged siblings')
    if current[new_id]['tool_type_raw'] != 14:
        raise ValueError('Created tool is not UD14')


def run_single_probe(*, report, guard, persist, create, load, identify,
                     read_tool, context, tools, specimen_path):
    """At most one AddNewTool3 and one SetToolName. No catch, retry or cleanup."""
    before_context = deepcopy(context())
    before_tools = deepcopy(tools())
    report.update(before_context=before_context, before_tools=before_tools)
    guard()
    report.update(phase='create_pending', mutation_attempted=True,
                  creation_attempted=True, creation_pending=True)
    persist()  # Must durably complete before the sole constructor call.
    guard()
    tool = create()
    report.update(creation_returned=True, phase='identify_created_tool')
    persist()  # Pending remains true until actual ID was retained.
    new_id = identify(tool)
    report.update(new_tool_native_id=new_id, creation_pending=False)
    persist()
    guard()
    verify_one_new_tool(before_tools, tools(), new_id)
    if context() != before_context:
        raise ValueError('Protected context changed while creating local tool')
    report.update(phase='load_pending', load_attempted=True, load_pending=True)
    persist()
    guard()
    load(tool, specimen_path)
    report.update(load_returned=True, load_pending=False, phase='readback')
    persist()
    for index in range(2):
        guard()
        diagnostic = {}
        report.setdefault('tool_read_diagnostics', []).append(diagnostic)
        row = read_tool(tool, diagnostic)
        if row['native_id'] != new_id or row['tool_type_raw'] != 14:
            raise ValueError('UD identity changed during readback')
        report.setdefault('tool_reads', []).append(row)
        if context() != before_context:
            raise ValueError('Protected context changed during profile readback')
        after_tools = tools()
        verify_one_new_tool(before_tools, after_tools, new_id)
        report['after_tools'] = after_tools
        persist()
    if report['tool_reads'][0] != report['tool_reads'][1]:
        raise ValueError('Repeated raw UD observations differ')
    guard()
    report.update(raw_readback_stable=True,
                  full_profiles_complete=all(x.get('profile_complete') is True for x in report['tool_reads']),
                  protected_context_unchanged=True,
                  exact_one_tool_created=True, phase='observed')
    persist()
    return report