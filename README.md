# Compact G-code Tools

Install **compact_tools.py** through **Plugins > Install local plugin**, then
select **Compact G-code Tools** under **Process > Others > Slicing Pipeline Plugin**.
No dependencies or options.
Requires Orca's Python slicing-pipeline plugin API (the supplied metadata requests
Python 3.12+). This artifact follows the repository's single-file plugin example;
installation in the running Flatpak has not been smoke tested.

Only `orca.slicing.Step.psGCodePostProcess` acts. It edits `ctx.gcode_path`, the
outgoing working copy, in place. The original slice and its preview retain the
original slot numbers. No project, profile, printer configuration or source
changes are needed. Only `.gcode` is supported.

Used indices come from executable `T<number>` commands and numeric `TOOL=`,
`INITIAL_TOOL=` or `INITIAL_EXTRUDER=` parameters of `PRINT_START` / `START_PRINT`.
For example, encounter order T7, T3, T5 becomes T2, T0, T1. A lone T7 becomes T0.
The complete sorted map is built before substitution. Motion/extrusion values,
command order, line endings and non-ASCII bytes are preserved. Already contiguous
files are byte-for-byte no-ops; processing the result again is a no-op.

Explicit T parameters on M104/M109/M200/M218/M221/M572/M900 are remapped only if
their index occurs in that selection map; heater-only references do not introduce
used filaments. Other parameters, comments, quoted strings and parenthetical
comments are untouched. T-1, T255, T1000, T1100 and T65535 are treated as firmware
special commands, never filament slots. Machines using these as real slot numbers
are outside this dialect.

Metadata handling follows `GCode.cpp`'s generated output: the one-based `; filament:`
list, indexed density/diameter headers, filament usage/cost lists and `;VT` markers
are remapped. The full CONFIG_BLOCK is retained as an explicitly labelled
ORIGINAL_CONFIG_BLOCK with `; original` keys, since it describes original slicing
inputs (including macros and matrices). Active compacted copies of viewer fields
(colors, material types, diameter, density, cost and nozzle temperatures) are
emitted alongside it. This deliberately does not produce a compacted preset or a
round-trippable full configuration. Singleton metadata values remain shared.
Malformed/short lists or quoted/escaped indexed metadata raise an error before
writing. An export error should be resolved before using the output.

Custom macros beyond the two start macros above, tool names such as
`ACTIVATE_EXTRUDER EXTRUDER=extruder3`, custom lists/metadata, firmware tool aliases,
and multiple commands on a line are unsupported. Unknown syntax is left intact;
review custom start/change/end G-code before using this plugin. Bambu M620/M621 AMS
mapping and numbered/checksummed streams are rejected when compaction is needed.
This is intended for ordinary numeric tool selection, not vendor-specific AMS or
multi-nozzle virtual-to-physical mapping.

Run compaction **before AFC preflight mapping** so that AFC reads the final compact
indices. Configure that order explicitly; this plugin has no AFC dependency,
network calls, printer agent or printer commands. It does not send or print files.

Offline verification:

```sh
python3 -m unittest discover -s . -v
```

Tests mock only the Orca API and exercise the actual installed script, including
post-process dispatch and an in-place temporary-file edit. A local Orca 2.5.0-alpha
1.85 MB output was also processed in memory ({0,3} → {0,1}) and checked for
idempotence, without changing its source file or touching the shared app session.
