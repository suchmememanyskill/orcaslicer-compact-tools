# /// script
# requires-python = ">=3.12"
# [tool.orcaslicer.plugin]
# name = "Compact G-code Tools"
# description = "Compacts used tool indices in the outgoing G-code working copy."
# author = "Sims"
# version = "1.0.1"
# type = "slicing-pipeline"
# ///
"""Standalone post-processor; see README.md for its deliberately bounded dialect."""
import re
from pathlib import Path

import orca

# Values reserved by common Marlin/RRF/Bambu dialects are never filament slots.
SPECIAL = {255, 1000, 1001, 1100, 65279, 65535}
COMMAND = re.compile(r'^\s*(T-?\d+|M\d+(?:\.\d+)?|[A-Z_]+)(?=\s|[A-Z]|$)', re.I)
TOOL = re.compile(r'T(\d+)\Z', re.I)
PARAM = re.compile(r'(?<![A-Za-z_])T(\d+)(?=\s|[A-Z]|$)', re.I)
INITIAL = re.compile(r'(?<!\S)(?:TOOL|INITIAL_TOOL|INITIAL_EXTRUDER)=(\d+)(?=\s|$)', re.I)
VIEWER_KEYS = {'filament_colour', 'extruder_colour', 'filament_type',
               'filament_diameter', 'filament_density', 'filament_cost',
               'nozzle_temperature', 'nozzle_temperature_initial_layer'}
QUALIFIED = {'M104', 'M109', 'M200', 'M218', 'M221', 'M572', 'M900'}


def references(line):
    """Return exact numeric spans; strings and parenthetical comments are masked."""
    code = line.split(';', 1)[0]
    code = re.sub(r'"(?:\\.|[^"\\])*"|\([^)]*\)', lambda m: ' ' * len(m[0]), code)
    match = COMMAND.match(code)
    if not match:
        return []
    command = match[1].upper()
    tool = TOOL.fullmatch(command)
    if tool:
        return [(match.start(1) + 1, match.end(1), int(tool[1]), True)]
    pattern = PARAM if command in QUALIFIED else INITIAL if command in {'PRINT_START', 'START_PRINT'} else None
    if pattern is None:
        return []
    return [(m.start(1), m.end(1), int(m[1]), command in {'PRINT_START', 'START_PRINT'})
            for m in pattern.finditer(code, match.end())]


def compact(data):
    # latin-1 is a byte-preserving transport, not an encoding conversion.
    lines = data.decode('latin-1').splitlines(keepends=True)
    refs = [references(line) for line in lines]
    used = sorted({value for row in refs for _, _, value, selection in row
                   if selection and value not in SPECIAL})
    mapping = {old: new for new, old in enumerate(used)}
    if all(old == new for old, new in mapping.items()):
        return data, mapping
    # An unchanged reference to an unselected tool must not acquire the meaning
    # of a selected tool after compaction (for example, M104 T0 S0 after T3).
    targets = set(mapping.values())
    for row in refs:
        for _, _, value, selection in row:
            if not selection and value not in mapping and value in targets:
                raise ValueError(f'Unselected tool T{value} conflicts with compacted tool indices')
    # Numbered/checksummed streams require checksum regeneration; reject atomically.
    if any(re.match(r'\s*N\d+', line, re.I) or '*' in line.split(';', 1)[0] for line in lines):
        raise ValueError('Numbered/checksummed G-code is unsupported')
    if any(re.match(r'\s*M62[01](?=\s|[A-Z;(]|$)', line, re.I) for line in lines):
        raise ValueError('Bambu AMS M620/M621 mapping is unsupported')
    output = []
    in_config = False
    for line, row in zip(lines, refs):
        if line.strip() == '; CONFIG_BLOCK_START':
            in_config = True
            output.append(line.replace('CONFIG_BLOCK_START', 'ORIGINAL_CONFIG_BLOCK_START'))
            continue
        if line.strip() == '; CONFIG_BLOCK_END':
            in_config = False
            output.append(line.replace('CONFIG_BLOCK_END', 'ORIGINAL_CONFIG_BLOCK_END'))
            continue
        if in_config:
            match = re.match(r'(;\s*)(\w+)(\s*=\s*)([^\r\n]*)(.*)', line, re.S)
            if match:
                # The complete config is historical slice input, not remapped presets.
                output.append('; original ' + line[2:])
                if match[2] in VIEWER_KEYS:
                    value = subset(match[4], used)
                    output.append(''.join((match[1], match[2], match[3], value, match[5])))
                continue
        for start, end, value, _ in reversed(row):
            if value in mapping:
                line = line[:start] + str(mapping[value]) + line[end:]
        vt = re.match(r'(;VT)(\d+)(?=\s|$)', line)
        if vt and int(vt[2]) in mapping:
            line = line[:vt.start(2)] + str(mapping[int(vt[2])]) + line[vt.end(2):]
        meta = re.match(r'(;\s*)(filament_density|filament_diameter|filament)(:\s*)([^\r\n]*)(.*)', line, re.S)
        stats = re.match(r'(;\s*)(filament used \[(?:mm|cm3|g)\]|filament cost)(\s*=\s*)([^\r\n]*)(.*)', line, re.S)
        match = meta or stats
        if match:
            if match[2] == 'filament':
                values = [int(x.strip()) - 1 for x in match[4].split(',')]
                if any(x not in mapping for x in values):
                    raise ValueError('Header filament has no executable tool selection')
                value = ','.join(str(mapping[x] + 1) for x in values)
            else:
                value = subset(match[4], used)
            line = ''.join((match[1], match[2], match[3], value, match[5]))
        output.append(line)
    return ''.join(output).encode('latin-1'), mapping


def subset(value, used):
    # Orca string vectors use semicolons; numeric vectors use commas. Quoted
    # separators are outside this small metadata dialect and fail before writing.
    if '"' in value or '\\' in value:
        raise ValueError('Quoted/escaped indexed metadata is unsupported')
    separator = ';' if ';' in value else ','
    values = value.split(separator)
    if len(values) == 1:
        return value  # Orca permits a shared singleton value.
    if max(used) >= len(values):
        raise ValueError('Indexed metadata is shorter than the used tool range')
    return separator.join(values[index].strip() if position == 0 else values[index]
                          for position, index in enumerate(used))


class CompactTools(orca.slicing.SlicingPipelineCapabilityBase):
    def get_name(self):
        return 'Compact G-code Tools'

    def execute(self, ctx):
        if ctx.step != orca.slicing.Step.psGCodePostProcess or not ctx.gcode_path:
            return orca.ExecutionResult.success()
        path = Path(ctx.gcode_path)
        # Orca appends .pp to its outgoing working copy. The requested output
        # name identifies the format; only gcode_path is ever opened.
        output_name = getattr(ctx, 'output_name', '')
        format_path = Path(output_name) if output_name else (
            path.with_suffix('') if path.suffix.lower() == '.pp' else path)
        if format_path.suffix.lower() != '.gcode':
            raise ValueError('Compact G-code Tools supports .gcode only')
        original = path.read_bytes()
        result, mapping = compact(original)
        if result != original:
            path.write_bytes(result)
        return orca.ExecutionResult.success('Compact tools: ' + ', '.join(
            f'T{old}->T{new}' for old, new in mapping.items()))


@orca.plugin
class Package(orca.base):
    def register_capabilities(self):
        orca.register_capability(CompactTools)
