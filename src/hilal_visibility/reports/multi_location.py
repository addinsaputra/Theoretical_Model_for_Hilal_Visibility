"""Combined location exports and comparison plots."""
import math
import os
from datetime import datetime
from typing import Optional
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from hilal_visibility.atmosphere.provenance import atmosphere_audit_record, save_atmosphere_provenance
from hilal_visibility.ephemeris import MOON_RADIUS_KM
def _simpan_excel_multi(results: list, shared_params: dict, filepath: str) -> str:
    """
    Simpan hasil multi-lokasi ke file Excel gabungan.

    Sheet 1: "Ringkasan Multi-Lokasi" — tabel semua lokasi
    Sheet 2: "Info & Parameter" — konfigurasi yang digunakan

    Parameters:
    -----------
    results : list[dict]
        Hasil dari _run_multi_lokasi()
    shared_params : dict
        Parameter bersama
    filepath : str
        Path file Excel

    Returns:
    --------
    str
        Path file yang disimpan
    """
    from hilal_visibility.calculator import HilalVisibilityCalculator

    wb = Workbook()
    mode = shared_params['mode']
    is_opt = (mode == 'optimal')

    # --- Style definitions ---
    header_font = Font(name='Segoe UI', bold=True, size=11, color='FFFFFF')
    header_fill = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
    data_font = Font(name='Segoe UI', size=10)
    data_font_bold = Font(name='Segoe UI', size=10, bold=True)
    align_center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    align_left = Alignment(horizontal='left', vertical='center')
    thin_border = Border(
        left=Side(style='thin', color='BDD7EE'),
        right=Side(style='thin', color='BDD7EE'),
        top=Side(style='thin', color='BDD7EE'),
        bottom=Side(style='thin', color='BDD7EE')
    )
    green_fill = PatternFill(start_color='C6E0B4', end_color='C6E0B4', fill_type='solid')
    red_fill = PatternFill(start_color='F8CBAD', end_color='F8CBAD', fill_type='solid')
    yellow_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')

    # ═══════════════════════════════════════════════════════════════
    # Sheet 1: Ringkasan Multi-Lokasi
    # ═══════════════════════════════════════════════════════════════
    ws = wb.active
    ws.title = "Ringkasan Multi-Lokasi"
    ws.sheet_properties.tabColor = '1F4E79'

    headers = [
        'No', 'Lokasi', 'Lat (°)', 'Lon (°)', 'Elv (m)',
        'Sunset', 'Moon Alt (°)', 'Elongasi (°)', 'Lebar Sabit (arcmin)', 'Phase Angle (°)',
        'Semidiameter Bulan (deg)', 'Jarak Bulan (km)',
        'RH (%)', 'T (°C)', 'k_v (mag/airmass)', 'extinction_mag_v (mag)', 'transmission_v',
        'Sky Bright. (nL)', 'Lumin. Hilal (nL)',
        'Δm NE (sunset)', 'Δm Tel (sunset)',
    ]
    if is_opt:
        headers += [
            'Δm NE (optimal)', 'Δm Tel (optimal)',
            'Waktu Opt NE', 'Waktu Opt Tel',
            'Durasi NE (min)', 'Durasi Tel (min)',
            'Selisih Threshold (mag)',
            'k_v NE Optimal (mag/airmass)', 'extinction_mag_v NE Optimal (mag)', 'transmission_v NE Optimal',
            'k_v Tel Optimal (mag/airmass)', 'extinction_mag_v Tel Optimal (mag)', 'transmission_v Tel Optimal',
            'Semidiameter NE Optimal (deg)', 'Jarak Bulan NE Optimal (km)',
            'Semidiameter Tel Optimal (deg)', 'Jarak Bulan Tel Optimal (km)',
        ]
    headers += ['Status NE', 'Status Tel']

    # Write headers
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border

    # Write data rows
    for i, r in enumerate(results, 1):
        row_idx = i + 1
        lok = r['lokasi']
        nama = lok.get('nama', '')
        lat = lok.get('lat', lok.get('lintang', 0.0))
        lon = lok.get('lon', lok.get('bujur', 0.0))
        elv = lok.get('elevasi', lok.get('elv', 0.0))

        if not r['success']:
            row_data = [i, nama, lat, lon, elv]
            row_data += ['ERROR'] + [''] * (len(headers) - 7) + ['ERROR']
            for col, val in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col, value=val)
                cell.font = data_font
                cell.alignment = align_center if col != 2 else align_left
                cell.border = thin_border
                if val == 'ERROR':
                    cell.fill = red_fill
            continue

        h = r['hasil']

        # Tentukan delta_m final
        if is_opt:
            dm_ne_final = h.get('optimal_delta_m_ne', h.get('delta_m_ne', -99))
            dm_tel_final = h.get('optimal_delta_m_tel', h.get('delta_m_tel', -99))
        else:
            dm_ne_final = h.get('delta_m_ne', -99)
            dm_tel_final = h.get('delta_m_tel', -99)

        st_ne = "TERLIHAT" if dm_ne_final > 0 else "TIDAK TERLIHAT"
        st_tel = "TERDETEKSI" if dm_tel_final > 0 else "TIDAK TERDETEKSI"

        sunset_str = ''
        sunset_val = h.get('sunset_local')
        if sunset_val and hasattr(sunset_val, 'strftime'):
            sunset_str = sunset_val.strftime('%H:%M:%S')

        row_data = [
            i, nama, lat, lon, elv,
            sunset_str,
            round(h.get('moon_alt', 0), 4),
            round(h.get('elongation', 0), 4),
            round(h.get('moon_width', 0) * 60.0, 4),
            round(h.get('phase_angle', 0), 4),
            h['moon_semidiameter'],
            h['moon_distance_km'],
            round(h.get('rh', 0), 2),
            round(h.get('temperature', 0), 2),
            round(h.get('k_v', 0), 4),
            round(h['extinction_mag_v'], 4),
            h['transmission_v'],
            f"{h.get('sky_brightness_nl', 0):.4e}",
            f"{h.get('luminansi_hilal_nl', 0):.4e}",
            round(h.get('delta_m_ne', -99), 4),
            round(h.get('delta_m_tel', -99), 4),
        ]

        if is_opt:
            opt_time_ne = h.get('optimal_time_ne')
            opt_time_tel = h.get('optimal_time_tel')
            row_data += [
                round(h.get('optimal_delta_m_ne', -99), 4),
                round(h.get('optimal_delta_m_tel', -99), 4),
                opt_time_ne.strftime('%H:%M:%S') if opt_time_ne and hasattr(opt_time_ne, 'strftime') else '',
                opt_time_tel.strftime('%H:%M:%S') if opt_time_tel and hasattr(opt_time_tel, 'strftime') else '',
                h.get('visibility_duration_ne', 0),
                h.get('visibility_duration_tel', 0),
                round(h.get('optimal_telescope_gain', h.get('telescope_gain', 0)), 4),
            ]
            for result_key in ('optimal_result_ne', 'optimal_result_tel'):
                optimal = h.get(result_key) or {}
                row_data += [optimal.get('k_v'), optimal.get('extinction_mag_v'), optimal.get('transmission_v')]
            for result_key in ('optimal_result_ne', 'optimal_result_tel'):
                optimal = h.get(result_key) or {}
                row_data += [optimal.get('moon_semidiameter'), optimal.get('moon_distance_km')]

        row_data += [st_ne, st_tel]

        for col, val in enumerate(row_data, 1):
            if isinstance(val, float) and not math.isfinite(val):
                val = str(val)
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.font = data_font
            cell.alignment = align_center if col != 2 else align_left
            cell.border = thin_border

        # Warnai kolom status
        col_st_ne = len(headers) - 1
        col_st_tel = len(headers)
        ws.cell(row=row_idx, column=col_st_ne).fill = green_fill if dm_ne_final > 0 else red_fill
        ws.cell(row=row_idx, column=col_st_ne).font = data_font_bold
        ws.cell(row=row_idx, column=col_st_tel).fill = green_fill if dm_tel_final > 0 else red_fill
        ws.cell(row=row_idx, column=col_st_tel).font = data_font_bold

    # Auto-fit column widths
    for col in range(1, len(headers) + 1):
        max_len = len(str(headers[col - 1]))
        for row_idx in range(2, len(results) + 2):
            cell_val = ws.cell(row=row_idx, column=col).value
            if cell_val:
                max_len = max(max_len, len(str(cell_val)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 3, 30)
    # Kolom lokasi lebih lebar
    ws.column_dimensions['B'].width = 38

    ws.freeze_panes = 'A2'

    # ═══════════════════════════════════════════════════════════════
    # Sheet 2: Info & Parameter
    # ═══════════════════════════════════════════════════════════════
    ws2 = wb.create_sheet(title="Info & Parameter")
    ws2.sheet_properties.tabColor = 'BF8F00'
    ws2.column_dimensions['A'].width = 35
    ws2.column_dimensions['B'].width = 50

    tel = shared_params['tel_params']
    sumber_label = HilalVisibilityCalculator.SUMBER_ATMOSFER_LABEL.get(
        shared_params['sumber_atmosfer'], shared_params['sumber_atmosfer'].upper())

    info_data = [
        ('Program', 'Perhitungan Visibilitas Hilal — Multi-Lokasi'),
        ('Bulan Hijriah', f"{shared_params['bulan_hijri']}"),
        ('Tahun Hijriah', f"{shared_params['tahun_hijri']}"),
        ('Mode Perhitungan', mode),
        ('Offset Hari', f"H + {shared_params['delta_day']} hari"),
        ('Sumber Data Atmosfer', sumber_label),
        ('Geometri Semidiameter', 'Skyfield + DE440s; jarak astrometrik toposentrik'),
        ('Sudut Fase Bulan', 'phase_angle(Sun) native Skyfield pada posisi astrometrik'),
        ('Lebar Sabit', 'W = 2 r k; k = fraksi iluminasi astrometrik'),
        ('Radius Bola Bulan (km)', MOON_RADIUS_KM),
        ('Jumlah Lokasi', f"{len(results)}"),
        ('Berhasil', f"{sum(1 for r in results if r['success'])}"),
        ('', ''),
        ('--- Parameter Teleskop ---', ''),
        ('Aperture (mm)', f"{tel.get('aperture', 100.0)}"),
        ('Magnification (x)', f"{tel.get('magnification', 50.0)}"),
        ('Central Obstruction (mm)', f"{tel.get('central_obstruction', 0.0)}"),
        ('Transmission', f"{tel.get('transmission', 0.95)}"),
        ('N Surfaces', f"{tel.get('n_surfaces', 6)}"),
        ('Observer Age (pupil fallback)', f"{tel.get('observer_age', 22.0)}"),
        ('Pupil Override (mm)', tel.get('pupil_diameter_mm') or 'Age-based dark-pupil estimate'),
        ('Field Factor Teleskop (F)', f"{tel.get('field_factor', shared_params['F_naked'])}"),
        ('Field Factor Naked Eye (F)', f"{shared_params['F_naked']}"),
        ('', ''),
        ('Tanggal Eksekusi', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    ]

    for col, hdr in enumerate(['Parameter', 'Nilai'], 1):
        cell = ws2.cell(row=1, column=col, value=hdr)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border

    for i, (param, nilai) in enumerate(info_data, 2):
        cell_p = ws2.cell(row=i, column=1, value=param)
        cell_p.font = data_font_bold if param.startswith('---') else data_font
        cell_p.border = thin_border
        cell_v = ws2.cell(row=i, column=2, value=nilai)
        cell_v.font = data_font
        cell_v.border = thin_border

    ws2.freeze_panes = 'A2'

    # Save
    output_dir = os.path.dirname(filepath)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    wb.save(filepath)
    save_atmosphere_provenance(filepath, [
        atmosphere_audit_record(
            r['lokasi'].get('nama', ''), shared_params['sumber_atmosfer'],
            r['success'], r.get('hasil'), r.get('error'),
        ) for r in results
    ])
    print(f"\n  ✓ Hasil multi-lokasi disimpan ke: {filepath}")
    return filepath


def _plot_multi_lokasi(results: list, shared_params: dict,
                       save_path: Optional[str] = None) -> bool:
    """
    Plot perbandingan delta_m (visibility margin) antar lokasi.

    Lollipop chart dengan dark theme: lokasi di sumbu Y, delta_m di sumbu X.
    Gradient warna berdasarkan nilai margin. Dual panel: Naked Eye & Teleskop.

    Parameters:
    -----------
    results : list[dict]
        Hasil dari _run_multi_lokasi()
    shared_params : dict
        Parameter bersama
    save_path : str or None
        Path untuk menyimpan gambar. None = hanya tampilkan.

    Returns:
    -------
    bool
        True jika berhasil, False jika gagal.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        from matplotlib.colors import LinearSegmentedColormap
        import matplotlib.patheffects as pe
        import numpy as np
    except ImportError:
        print("  [!] matplotlib belum terinstall. Jalankan: pip install matplotlib")
        return False

    success_results = [r for r in results if r['success']]
    if not success_results:
        print("  [!] Tidak ada hasil valid untuk diplot.")
        return False

    mode = shared_params['mode']
    is_opt = (mode == 'optimal')

    # Kumpulkan data
    nama_list = []
    dm_ne_list = []
    dm_tel_list = []
    lat_list = []
    lon_list = []

    for r in reversed(success_results):  # reversed agar urutan atas→bawah sesuai input
        lok = r['lokasi']
        h = r['hasil']
        nama = lok.get('nama', '')
        if len(nama) > 30:
            nama = nama[:28] + '…'
        nama_list.append(nama)
        lat_list.append(lok.get('lat', lok.get('lintang', 0.0)))
        lon_list.append(lok.get('lon', lok.get('bujur', 0.0)))

        if is_opt:
            dm_ne_list.append(h.get('optimal_delta_m_ne', h.get('delta_m_ne', -99)))
            dm_tel_list.append(h.get('optimal_delta_m_tel', h.get('delta_m_tel', -99)))
        else:
            dm_ne_list.append(h.get('delta_m_ne', -99))
            dm_tel_list.append(h.get('delta_m_tel', -99))

    n = len(nama_list)

    # ── Warna & Style ──
    BG_COLOR = '#0f1923'
    PANEL_BG = '#162230'
    GRID_COLOR = '#1e3348'
    TEXT_COLOR = '#e8edf3'
    SUBTEXT_COLOR = '#8899aa'
    ACCENT_GREEN = '#00e396'
    ACCENT_RED = '#ff4560'
    ACCENT_AMBER = '#feb019'
    THRESHOLD_COLOR = '#3a5068'

    def valor_color(v):
        """Warna gradien berdasarkan nilai margin."""
        if v >= 5:
            return ACCENT_GREEN
        elif v >= 0:
            # Interpolasi hijau → kuning
            t = v / 5.0
            r_c = int(254 * (1 - t) + 0 * t)
            g_c = int(176 * (1 - t) + 227 * t)
            b_c = int(25 * (1 - t) + 150 * t)
            return f'#{r_c:02x}{g_c:02x}{b_c:02x}'
        elif v >= -5:
            # Interpolasi kuning → merah
            t = abs(v) / 5.0
            r_c = int(254 * (1 - t) + 255 * t)
            g_c = int(176 * (1 - t) + 69 * t)
            b_c = int(25 * (1 - t) + 96 * t)
            return f'#{r_c:02x}{g_c:02x}{b_c:02x}'
        else:
            return ACCENT_RED

    # ── Layout ──
    fig_height = max(7, n * 0.55 + 3.5)
    fig = plt.figure(figsize=(18, fig_height), facecolor=BG_COLOR)

    # Grid: header row + main row, two columns
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 12],
                          hspace=0.08, wspace=0.02,
                          left=0.14, right=0.96, top=0.92, bottom=0.08)

    # Header axes (untuk judul panel)
    ax_h1 = fig.add_subplot(gs[0, 0], facecolor='none')
    ax_h2 = fig.add_subplot(gs[0, 1], facecolor='none')
    for ax_h in [ax_h1, ax_h2]:
        ax_h.set_xlim(0, 1)
        ax_h.set_ylim(0, 1)
        ax_h.axis('off')

    ax_h1.text(0.5, 0.3, 'NAKED EYE', fontsize=14, fontweight='bold',
               color=TEXT_COLOR, ha='center', va='center',
               fontfamily='monospace', alpha=0.95)
    ax_h2.text(0.5, 0.3, 'TELESKOP', fontsize=14, fontweight='bold',
               color=TEXT_COLOR, ha='center', va='center',
               fontfamily='monospace', alpha=0.95)

    ax1 = fig.add_subplot(gs[1, 0], facecolor=PANEL_BG)
    ax2 = fig.add_subplot(gs[1, 1], facecolor=PANEL_BG, sharey=ax1)

    y_pos = np.arange(n)

    def draw_lollipop(ax, values, show_labels=True):
        """Gambar lollipop chart dengan glow effect."""
        # Threshold zone
        ax.axvspan(-0.5, 0.5, color=THRESHOLD_COLOR, alpha=0.15, zorder=0)
        ax.axvline(x=0, color=THRESHOLD_COLOR, linewidth=2, linestyle='-', zorder=1)

        for j, v in enumerate(values):
            c = valor_color(v)
            if not math.isfinite(v):
                ax.text(0, j, f'  {v}', va='center', ha='left',
                        color=ACCENT_RED, fontsize=9)
                continue
            # Garis lollipop
            ax.plot([0, v], [j, j], color=c, linewidth=2.5, alpha=0.7, zorder=2,
                    solid_capstyle='round')
            # Titik ujung dengan glow
            ax.scatter(v, j, color=c, s=120, zorder=4, edgecolors='none')
            ax.scatter(v, j, color=c, s=280, zorder=3, edgecolors='none', alpha=0.15)

            # Label nilai
            offset = 0.4 if v >= 0 else -0.4
            align = 'left' if v >= 0 else 'right'
            ax.text(v + offset, j, f'{v:+.2f}',
                    va='center', ha=align, fontsize=9, fontweight='bold',
                    color=c, fontfamily='monospace',
                    path_effects=[pe.withStroke(linewidth=2, foreground=BG_COLOR)])

            # Ikon status
            if v > 0:
                icon = '●'
                icon_color = ACCENT_GREEN
            else:
                icon = '○'
                icon_color = ACCENT_RED
            status_x = 0.03 if v >= 0 else -0.03
            # (ikon ditaruh di dekat garis 0)

        # Garis horizontal pemisah antar lokasi (subtle)
        for j in range(n):
            ax.axhline(y=j, color=GRID_COLOR, linewidth=0.5, alpha=0.5, zorder=0)

        # Styling sumbu
        ax.set_xlabel('Visibility Margin  Δm  (mag)', fontsize=10,
                       fontweight='bold', color=SUBTEXT_COLOR, labelpad=10)
        ax.tick_params(axis='x', colors=SUBTEXT_COLOR, labelsize=9)
        ax.tick_params(axis='y', colors=TEXT_COLOR, labelsize=9)
        ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(1))
        ax.grid(axis='x', which='major', color=GRID_COLOR, linewidth=0.8, alpha=0.6)
        ax.grid(axis='x', which='minor', color=GRID_COLOR, linewidth=0.3, alpha=0.3)

        # Hilangkan border
        for spine in ax.spines.values():
            spine.set_visible(False)

        if show_labels:
            ax.set_yticks(y_pos)
            ax.set_yticklabels(nama_list, fontsize=10, color=TEXT_COLOR,
                               fontfamily='sans-serif')
        else:
            plt.setp(ax.get_yticklabels(), visible=False)

    # ── Gambar kedua panel ──
    draw_lollipop(ax1, dm_ne_list, show_labels=True)
    draw_lollipop(ax2, dm_tel_list, show_labels=False)

    # Simetriskan sumbu X
    finite_dm = [v for v in dm_ne_list + dm_tel_list if math.isfinite(v)]
    x_abs_max = max((abs(v) for v in finite_dm), default=5)
    x_limit = math.ceil(x_abs_max / 5) * 5 + 2
    ax1.set_xlim(-x_limit, x_limit)
    ax2.set_xlim(-x_limit, x_limit)
    ax1.set_ylim(-0.7, n - 0.3)
    ax2.set_ylim(-0.7, n - 0.3)

    # Invert agar lokasi pertama di atas
    ax1.invert_yaxis()

    # ── Ringkasan statistik di bawah ──
    n_vis_ne = sum(1 for v in dm_ne_list if v > 0)
    n_vis_tel = sum(1 for v in dm_tel_list if v > 0)

    summary_ne = f'{n_vis_ne}/{n} terlihat'
    summary_tel = f'{n_vis_tel}/{n} terlihat'

    ax1.text(0.5, -0.08, summary_ne, transform=ax1.transAxes,
             fontsize=11, fontweight='bold', color=ACCENT_GREEN if n_vis_ne > 0 else ACCENT_RED,
             ha='center', va='top', fontfamily='monospace')
    ax2.text(0.5, -0.08, summary_tel, transform=ax2.transAxes,
             fontsize=11, fontweight='bold', color=ACCENT_GREEN if n_vis_tel > 0 else ACCENT_RED,
             ha='center', va='top', fontfamily='monospace')

    # ── Judul utama ──
    bln = shared_params['bulan_hijri']
    thn = shared_params['tahun_hijri']
    sumber = shared_params['sumber_atmosfer'].upper()
    mode_label = "OPTIMAL" if is_opt else "SUNSET"

    fig.text(0.55, 0.97,
             f'PERBANDINGAN VISIBILITAS HILAL',
             fontsize=17, fontweight='bold', color=TEXT_COLOR,
             ha='center', va='center', fontfamily='monospace')
    fig.text(0.55, 0.945,
             f'Bulan {bln}/{thn} H   ·   Mode {mode_label}   ·   Atmosfer {sumber}   ·   {n} Lokasi',
             fontsize=10, color=SUBTEXT_COLOR,
             ha='center', va='center', fontfamily='monospace')

    # ── Legenda kustom ──
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='none', markerfacecolor=ACCENT_GREEN,
               markersize=10, label='Terlihat (Δm ≥ 0)'),
        Line2D([0], [0], marker='o', color='none', markerfacecolor=ACCENT_RED,
               markersize=10, label='Tidak Terlihat (Δm < 0)'),
        Line2D([0], [0], marker='o', color='none', markerfacecolor=ACCENT_AMBER,
               markersize=10, label='Marginal (Δm ≈ 0)'),
    ]
    fig.legend(handles=legend_elements, loc='lower center', ncol=3,
               fontsize=9, frameon=False, labelcolor=SUBTEXT_COLOR,
               bbox_to_anchor=(0.55, 0.01))

    if save_path:
        os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
        fig.savefig(save_path, dpi=200, bbox_inches='tight',
                    facecolor=BG_COLOR, edgecolor='none')
        print(f"  [✓] Grafik perbandingan disimpan: {save_path}")

    plt.close(fig)
    return True
