"""Read-only analysis of installed line-only MT specimens; never a serializer."""
from pathlib import Path
import hashlib
import math
import re


def read_mt_specimen(path, expected_sha256):
    """Preserve raw coordinates without assuming their unit or cutting boundary."""
    p = Path(path)
    if (not p.is_absolute() or p.suffix.lower() != '.mt' or not p.is_file()
            or p.is_symlink() or not 0 < p.stat().st_size <= 65536):
        raise ValueError('Pinned absolute regular MT specimen up to 64 KiB required')
    if type(expected_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Exact MT SHA256 required')
    data = p.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('MT specimen hash mismatch')
    lines = data.decode('ascii').splitlines()
    if not lines or lines[0].strip() != 'Version Clouds':
        raise ValueError('Only the observed Version Clouds specimen format is accepted')
    segments = []
    for number, text in enumerate(lines[1:], 2):
        parts = text.strip().split()
        if not parts or text.lstrip().startswith('#'):
            continue
        if len(parts) != 5 or parts[0] != 'line' or len(segments) >= 256:
            raise ValueError('Unsupported or unbounded specimen record at line ' + str(number))
        points = [float(x) for x in parts[1:]]
        if any(not math.isfinite(x) or abs(x) > 1e6 for x in points):
            raise ValueError('Finite bounded raw coordinates required')
        if points[:2] == points[2:]:
            raise ValueError('Degenerate specimen line')
        if segments and any(abs(a-b) > 1e-7 for a,b in zip(segments[-1]['end_raw'], points[:2])):
            raise ValueError('Disconnected specimen profile')
        segments.append(dict(line_number=number, start_raw=points[:2], end_raw=points[2:]))
    if not segments or segments[0]['start_raw'] != [0., 0.]:
        raise ValueError('Specimen contour must start at the declared tip origin')
    return dict(path=str(p), sha256=expected_sha256, bytes=len(data), version='Version Clouds',
                segments=segments, coordinate_units='unqualified', cutting_partition='unqualified',
                profile_writer_used=False, official_format_specification=False)