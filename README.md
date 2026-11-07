# Compact G-code Tools

Compacts the tool numbers used in an OrcaSlicer G-code file into consecutive numbers starting at **T0**. Tools are numbered in ascending order, so gaps from unused filament slots are removed.

For example, a file using **T2, T4 and T6** is remapped to **T0, T1 and T2**:

| Original tool | Remapped tool |
| --- | --- |
| T2 | T0 |
| T4 | T1 |
| T6 | T2 |

The order of tool changes stays the same:

```gcode
; Before
T6
T2
T4
T6

; After
T2
T0
T1
T2
```

Supported tool references and filament metadata are updated to match. Movement, extrusion and tool-change order are preserved. Files whose used tools already start at T0 without gaps remain unchanged.

The plugin processes the outgoing G-code for export or upload; OrcaSlicer's original slice preview keeps its original tool numbers. When used with **AFC tool remap**, run compaction first so the lane assignments use the remapped numbers.
