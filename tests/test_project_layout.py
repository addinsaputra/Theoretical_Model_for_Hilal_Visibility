"""Installed imports and entry points must resolve data outside the repo cwd."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from hilal_visibility.paths import PROJECT_ROOT


class ProjectLayoutTests(unittest.TestCase):
    def run_python(self, arguments, directory, *, input=None):
        result = subprocess.run(
            [sys.executable, '-X', 'utf8', *arguments], cwd=directory,
            input=input, capture_output=True, text=True, encoding='utf-8', timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def test_package_and_resources_resolve_outside_project_working_directory(self):
        code = (
            'import json; from hilal_visibility import HilalVisibilityCalculator; '
            'from hilal_visibility.paths import PROJECT_ROOT, EPHEMERIS_PATH, OBSERVATIONS_PATH; '
            'from hilal_visibility.datasets import load_observation_rows; '
            'from hilal_visibility.locations import get_list_lokasi; '
            'from hilal_visibility.models.crumey import DEFAULT_VISUAL_FIELD_FACTOR; '
            'print(json.dumps([str(PROJECT_ROOT), EPHEMERIS_PATH.is_file(), '
            'len(load_observation_rows(OBSERVATIONS_PATH)), len(get_list_lokasi()), '
            'DEFAULT_VISUAL_FIELD_FACTOR]))'
        )
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_python(['-c', code], directory)
        self.assertEqual(json.loads(result.stdout), [str(PROJECT_ROOT), True, 278, 82, 2.0])

    def test_script_help_resolves_imports_outside_project_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('generate_single_excel_example', 'study_ifs_sensitivity',
                         'compare_crumey_observations'):
                with self.subTest(script=name):
                    result = self.run_python([str(PROJECT_ROOT / 'scripts' / (name + '.py')), '--help'], directory)
                    self.assertIn('usage:', result.stdout)

    def test_manual_cli_calculates_outside_project_working_directory(self):
        responses = ['', '0', 'Layout fixture', '-6.917', '110.348', '89',
                     '9', '1444', '1', '0', '3', '75', '25', '1013.25', '', 'n']
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_python(['-m', 'hilal_visibility'], directory,
                                     input='\n'.join(responses) + '\n')
        self.assertIn('residual F visual bersama=2.0', result.stdout)
        self.assertIn('Luminansi Hilal', result.stdout)
        self.assertIn('Input Manual', result.stdout)
