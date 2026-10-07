"""Scientific symbols survive CLI, workbook, chart and byte-stream output."""

import contextlib
import io
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.text import Text

from hilal_visibility.calculator import HilalVisibilityCalculator, deg_to_dms
from hilal_visibility.console import configure_console_encoding
from hilal_visibility import batch, cli
from hilal_visibility.reports.multi_location import _simpan_excel_multi, _plot_multi_lokasi


BROKEN_TEXT = re.compile(
    r'\u00c2[\u00b0\u00b1\u00b2\u00b7]|\u00ce\u201d|'
    r'\u00e2[\u0080-\u00ff\u0153\u2010-\u202f\u20ac]|\u00f0\u0178|\ufffd'
)


class OutputEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calc = HilalVisibilityCalculator(
            'Uji simbol Semarang', -6.917, 110.348, 89, 'Asia/Jakarta', 9, 1444,
            sumber_atmosfer='manual', manual_rh=75, manual_t=25,
        )
        cls.capture = io.StringIO()
        with contextlib.redirect_stdout(cls.capture):
            cls.hasil = cls.calc.jalankan_perhitungan_lengkap(mode='optimal', interval_menit=5)
        cls.multi = [dict(success=True, lokasi=dict(nama=cls.calc.nama_tempat,
                         lat=-6.917, lon=110.348, elv=89), hasil=cls.hasil)]
        cls.shared = dict(mode='optimal', bulan_hijri=9, tahun_hijri=1444,
                          delta_day=0, sumber_atmosfer='manual', tel_params={}, F_naked=2.0)
        observation = dict(no=1, nama=cls.calc.nama_tempat, tanggal='2023-03-22',
                           lat=-6.917, lon=110.348, elv=89, bulan_hijri=9,
                           tahun_hijri=1444, bias_t=0, bias_rh=0, observed=True)
        with (patch.object(batch, 'HilalVisibilityCalculator') as calculator,
              contextlib.redirect_stdout(io.StringIO())):
            calculator.return_value.jalankan_perhitungan_lengkap.return_value = cls.hasil
            cls.batch = batch.run_single_observation(observation, verbose=False)
        if not cls.batch['success']:
            raise AssertionError(cls.batch)

    def assert_clean_text(self, text):
        self.assertNotRegex(text, BROKEN_TEXT)

    def test_cli_and_degree_labels_are_real_unicode(self):
        text = self.capture.getvalue()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli._print_tabel_ringkasan_multi(self.multi, self.shared)
            batch.print_results_table([self.batch])
        self.assert_clean_text(text + output.getvalue())
        self.assertIn('°C', text)
        self.assertIn('Δm', output.getvalue())
        self.assertEqual(deg_to_dms(-6.25), '-6° 15\' 0.00"')

    def test_single_multi_and_batch_workbook_xml_is_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('single.xlsx', 'multi.xlsx', 'batch.xlsx')]
            with contextlib.redirect_stdout(io.StringIO()):
                self.calc.simpan_ke_excel(str(paths[0]))
                _simpan_excel_multi(self.multi, self.shared, str(paths[1]))
                batch.save_to_excel([self.batch], str(paths[2]))
            for path in paths:
                with self.subTest(path=path.name), ZipFile(path) as archive:
                    strings = []
                    for name in archive.namelist():
                        if name.endswith('.xml'):
                            tree = ET.fromstring(archive.read(name))
                            strings.extend(tree.itertext())
                            for element in tree.iter():
                                strings.extend(element.attrib.values())
                    text = '\n'.join(strings)
                    self.assert_clean_text(text)
                    self.assertIn('°', text)
                    self.assertIn('Δm', text)

    def test_single_and_multi_plot_labels_are_clean(self):
        labels = []
        save = Figure.savefig
        def inspect_and_save(figure, *args, **kwargs):
            labels.extend(obj.get_text() for obj in figure.findobj(match=Text))
            return save(figure, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            with (patch.object(Figure, 'savefig', autospec=True, side_effect=inspect_and_save),
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertTrue(self.calc.plot_visibility_margin(str(Path(directory) / 'single.png')))
                self.assertTrue(_plot_multi_lokasi(self.multi, self.shared, str(Path(directory) / 'multi.png')))
        text = '\n'.join(labels)
        self.assert_clean_text(text)
        self.assertIn('Δm', text)

    def test_console_reconfigures_legacy_byte_stream_to_utf8(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252')
        with patch('sys.stdout', stream), patch('sys.stderr', io.StringIO()):
            configure_console_encoding()
            stream.write('Δm = 0; suhu 25 °C; luas 1 arcmin²')
            stream.flush()
        self.assertEqual(raw.getvalue().decode('utf-8'), 'Δm = 0; suhu 25 °C; luas 1 arcmin²')
        stream.close()
