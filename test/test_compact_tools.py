import importlib.util
import zipfile
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
spec = importlib.util.spec_from_file_location('compact_tools', Path(__file__).resolve().parents[1] / 'plugin' / 'compact_tools.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class CompactTests(unittest.TestCase):
    def check(self, source, expected):
        result, _ = plugin.compact(source)
        self.assertEqual(result, expected)
        self.assertEqual(plugin.compact(result)[0], result)

    def test_wheel_loads_packaged_plugin(self):
        root = Path(__file__).resolve().parents[1]
        build_spec = importlib.util.spec_from_file_location('build_plugin', root / 'build_plugin.py')
        builder = importlib.util.module_from_spec(build_spec)
        build_spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            wheel = builder.build(directory)
            source = (root / 'plugin/compact_tools.py').read_text()
            version = next(line.split('"')[1] for line in source.splitlines()
                           if line.startswith('# version = '))
            self.assertEqual(wheel.name, f'compact_tools-{version}-py3-none-any.whl')
            with zipfile.ZipFile(wheel) as archive:
                self.assertIsNone(archive.testzip())
                metadata = archive.read(f'compact_tools-{version}.dist-info/METADATA').decode()
                self.assertIn('Author: Sims\n', metadata)
                self.assertIn(f'Version: {version}\n', metadata)
                self.assertIn('Name: Compact-tools\n', metadata)
                self.assertEqual(archive.read('compact_tools/__init__.py'),
                                 (root / 'plugin/compact_tools.py').read_bytes())
                archive.extractall(Path(directory) / 'extracted')
            entry = Path(directory) / 'extracted/compact_tools/__init__.py'
            spec = importlib.util.spec_from_file_location('packaged_compact_tools', entry)
            packaged = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(packaged)
            self.assertEqual(packaged.compact(b'T2\nT4\nT6\n')[0], b'T0\nT1\nT2\n')

    def test_sorted_order_repeats_and_motion(self):
        self.check(b'T7\nG1 X3 E5.7\nT3\nT5\nT7\n', b'T2\nG1 X3 E5.7\nT0\nT1\nT2\n')

    def test_boundaries(self):
        self.check(b'T10\nT1\nM104 T10 S200\n', b'T1\nT0\nM104 T1 S200\n')

    def test_single_sparse(self):
        self.check(b'T5\n', b'T0\n')

    def test_additional_reserved_commands(self):
        self.check(b'T3\nT1001\nT65279\n', b'T0\nT1001\nT65279\n')
        self.check(b'T1001\nT65279\n', b'T1001\nT65279\n')

    def test_compact_parameters(self):
        self.check(b'T3\nM104T3S200\nM109S210T3\nm900k0.1t3\n',
                   b'T0\nM104T0S200\nM109S210T0\nm900k0.1t0\n')

    def test_compact_parameter_boundaries(self):
        self.check(b'T3\nM104 T30 S200\nM109 T3.5 S200\nM104 TARGET3 S200\n',
                   b'T0\nM104 T30 S200\nM109 T3.5 S200\nM104 TARGET3 S200\n')

    def test_conflicts_and_ams_rejected_without_writing(self):
        sources = [b'T3\nM104 T0 S0\n', b'T3\nT5\nM109S200T1\n']
        sources += [b'T3\n' + command + b'\n' for command in
                    (b'M620S3', b'M621S3', b'm620s3', b'M620; comment', b'M621 S3')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'slice.gcode.pp'
            ctx = types.SimpleNamespace(step=1, gcode_path=str(path), output_name='export.gcode')
            for source in sources:
                with self.subTest(source=source):
                    path.write_bytes(source)
                    with self.assertRaises(ValueError):
                        plugin.CompactTools().execute(ctx)
                    self.assertEqual(path.read_bytes(), source)

    def test_contiguous_tools_with_qualified_reference_noop(self):
        self.check(b'T0\nM104T1S0\n', b'T0\nM104T1S0\n')

    def test_contiguous_noop(self):
        self.check(b'T1\nT0\n', b'T1\nT0\n')

    def test_comments_strings_and_sentinels(self):
        self.check(b'; T9\r\nM117 T8\r\nG28 T300\r\nM620.1 T220\r\nT255\r\nT1000\r\nT-1\r\nT65535\r\nT3 ; T5\r\n',
                   b'; T9\r\nM117 T8\r\nG28 T300\r\nM620.1 T220\r\nT255\r\nT1000\r\nT-1\r\nT65535\r\nT0 ; T5\r\n')

    def test_masked_prefixes_and_tool_parameters(self):
        self.check(b'(intro T9) T3\r\n"T8" T5\r\nM104 (T7) T3 S210\r\nM109 "T9" T5 S220\r\n',
                   b'(intro T9) T0\r\n"T8" T1\r\nM104 (T7) T0 S210\r\nM109 "T9" T1 S220\r\n')

    def test_tool_references_among_unmodified_lines(self):
        self.check(b'G1 X2 E0.4\n; raw \xff\x00 T9\n\nT5\n  g1 X3 E0.5\nM104T5S200\n;VT5\nT3',
                   b'G1 X2 E0.4\n; raw \xff\x00 T9\n\nT1\n  g1 X3 E0.5\nM104T1S200\n;VT1\nT0')

    def test_motion_checksums_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'slice.gcode.pp'
            ctx = types.SimpleNamespace(step=1, gcode_path=str(path), output_name='export.gcode')
            for motion in (b'G1 X2*12', b'g1 X2*12', b'  G1 X2*12'):
                source = b'T3\n' + motion + b'\n'
                with self.subTest(motion=motion):
                    path.write_bytes(source)
                    with self.assertRaisesRegex(ValueError, 'Numbered/checksummed'):
                        plugin.CompactTools().execute(ctx)
                    self.assertEqual(path.read_bytes(), source)
        self.check(b'T3\nG1 X2 ; *12 T9\n', b'T0\nG1 X2 ; *12 T9\n')

    def test_indented_config_markers(self):
        self.check(b'T3\r\n  ; CONFIG_BLOCK_START\r\n; filament_type = A;B;C;D\r\n  ; CONFIG_BLOCK_END\r\n; filament_density: 1,2,3,4\r\n',
                   b'T0\r\n  ; ORIGINAL_CONFIG_BLOCK_START\r\n; original filament_type = A;B;C;D\r\n; filament_type = D\r\n  ; ORIGINAL_CONFIG_BLOCK_END\r\n; filament_density: 4\r\n')

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
