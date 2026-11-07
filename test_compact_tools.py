import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

orca = types.ModuleType('orca')
orca.base = object
orca.plugin = lambda cls: cls
orca.slicing = types.SimpleNamespace(SlicingPipelineCapabilityBase=object,
                                    Step=types.SimpleNamespace(psGCodePostProcess=1))
orca.ExecutionResult = types.SimpleNamespace(success=lambda message='': message)
sys.modules['orca'] = orca
spec = importlib.util.spec_from_file_location('compact_tools', Path(__file__).with_name('compact_tools.py'))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class CompactTests(unittest.TestCase):
    def check(self, source, expected):
        result, _ = plugin.compact(source)
        self.assertEqual(result, expected)
        self.assertEqual(plugin.compact(result)[0], result)

    def test_sorted_order_repeats_and_motion(self):
        self.check(b'T7\nG1 X3 E5.7\nT3\nT5\nT7\n', b'T2\nG1 X3 E5.7\nT0\nT1\nT2\n')

    def test_boundaries(self):
        self.check(b'T10\nT1\nM104 T10 S200\n', b'T1\nT0\nM104 T1 S200\n')

    def test_single_sparse(self):
        self.check(b'T5\n', b'T0\n')

    def test_contiguous_noop(self):
        self.check(b'T1\nT0\n', b'T1\nT0\n')

    def test_comments_strings_and_sentinels(self):
        self.check(b'; T9\r\nM117 T8\r\nG28 T300\r\nM620.1 T220\r\nT255\r\nT1000\r\nT-1\r\nT65535\r\nT3 ; T5\r\n',
                   b'; T9\r\nM117 T8\r\nG28 T300\r\nM620.1 T220\r\nT255\r\nT1000\r\nT-1\r\nT65535\r\nT0 ; T5\r\n')

    def test_initial_macro_and_qualified(self):
        self.check(b'PRINT_START TOOL=7 EXTRUDER=220 BED=60\nM109 S220 T7\nM104 T2 S0\nT3\nT7\n',
                   b'PRINT_START TOOL=1 EXTRUDER=220 BED=60\nM109 S220 T1\nM104 T2 S0\nT0\nT1\n')

    def test_metadata(self):
        self.check(b'; filament: 4,6\n; filament_density: 1,2,3,4,5,6\n;VT5\nT5\nT3\n; CONFIG_BLOCK_START\n; filament_type = A;B;C;D;E;F\n; nozzle_temperature = 100,101,102,103,104,105\n; CONFIG_BLOCK_END\n; filament used [mm] = 0, 0, 0, 20, 0, 30\n',
                   b'; filament: 1,2\n; filament_density: 4,6\n;VT1\nT1\nT0\n; ORIGINAL_CONFIG_BLOCK_START\n; original filament_type = A;B;C;D;E;F\n; filament_type = D;F\n; original nozzle_temperature = 100,101,102,103,104,105\n; nozzle_temperature = 103,105\n; ORIGINAL_CONFIG_BLOCK_END\n; filament used [mm] = 20, 30\n')

    def test_dispatch_and_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.gcode'
            path.write_bytes(b'T7\n')
            ctx = types.SimpleNamespace(step=0, gcode_path=str(path))
            plugin.CompactTools().execute(ctx)
            self.assertEqual(path.read_bytes(), b'T7\n')
            ctx.step = 1
            plugin.CompactTools().execute(ctx)
            self.assertEqual(path.read_bytes(), b'T0\n')

    def test_orca_temporary_working_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'slice.gcode.pp'
            original = Path(directory) / 'slice.gcode'
            original.write_bytes(b'T7\n')
            for output_name in ('export.gcode', ''):
                path.write_bytes(original.read_bytes())
                ctx = types.SimpleNamespace(step=1, gcode_path=str(path),
                                            output_name=output_name)
                plugin.CompactTools().execute(ctx)
                self.assertEqual(path.read_bytes(), b'T0\n')
                self.assertEqual(original.read_bytes(), b'T7\n')

    def test_archive_output_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'slice.gcode.pp'
            path.write_bytes(b'T7\n')
            ctx = types.SimpleNamespace(step=1, gcode_path=str(path),
                                        output_name='export.gcode.3mf')
            with self.assertRaises(ValueError):
                plugin.CompactTools().execute(ctx)
            self.assertEqual(path.read_bytes(), b'T7\n')

    def test_invalid_metadata_and_checksum(self):
        for data in (b'T3\n; filament_density: 1,2\n', b'N1 T3*20\nT3\n'):
            with self.assertRaises(ValueError):
                plugin.compact(data)


if __name__ == '__main__':
    unittest.main()
