"""Reproducible IFS input sensitivity study; production interpolation is unchanged.

Run: python -X utf8 scripts/study_ifs_sensitivity.py
Replay saved inputs: python -X utf8 scripts/study_ifs_sensitivity.py --replay PATH
Use --all to study every observation instead of the documented spot sample.
"""

import argparse
import ast
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from hilal_visibility.paths import OUTPUT_DIR, OBSERVATIONS_PATH
from hilal_visibility.datasets import load_observation_rows
from hilal_visibility.atmosphere.ifs import (
    ARCHIVE_URL, ATMOSPHERIC_VARIABLES, AtmosphericWindow, ECMWF_IFSAPIError,
    IFS_MODEL, IFS_PRODUCT_NAME, fetch_weather_with_info, normalize_utc_datetime,
)

COASTAL_SITES = (
    'POB Lhoknga - Aceh Besar', 'pantai Loang Baloq - Mataram',
    'POB Cikelet - Garut', 'Tower Hilal Sulamu - Kupang',
    'Tower Hilal Meras - Manado', 'Tower Hilal Ave Taduma - Ternate',
)
RH_FORMULA_REFERENCE = (
    'https://github.com/open-meteo/open-meteo/blob/'
    '1cd0eaa1ed97857772a6bd968bbe373bd23636f3/Sources/App/Helper/Meteorology.swift'
)


def load_cases(path):
    """Read OBSERVATIONS as literal data, without importing/running the batch."""
    source = Path(path).read_bytes()
    cases = []
    for entry in load_observation_rows(path):
        date.fromisoformat(entry[1])
        if entry[8:10] != (0, 0):
            raise ValueError('Sensitivity baseline requires zero observation biases')
        cases.append(dict(observation_no=entry[0], date=entry[1], location=entry[2],
                          latitude=entry[3], longitude=entry[4], elevation_m=entry[5]))
    return cases, hashlib.sha256(source).hexdigest()


def select_spot_cases(cases):
    """Earliest/latest dates at six coasts, plus latest at three highest sites."""
    grouped = {}
    for case in cases:
        grouped.setdefault(case['location'], []).append(case)
    selected = {}
    for name in COASTAL_SITES:
        group = sorted(grouped[name], key=lambda item: (item['date'], item['observation_no']))
        for case in (group[0], group[-1]):
            selected[case['observation_no']] = {**case, 'sample_group': 'coastal'}
    inland = sorted((group for name, group in grouped.items() if name not in COASTAL_SITES),
                    key=lambda group: max(case['elevation_m'] for case in group), reverse=True)
    for group in inland[:3]:
        case = max(group, key=lambda item: (item['date'], item['observation_no']))
        selected[case['observation_no']] = {**case, 'sample_group': 'higher_elevation'}
    return sorted(selected.values(), key=lambda item: item['observation_no'])


def rh_from_temperature_dewpoint(temperature, dewpoint):
    """Open-Meteo Magnus formula, with its [0, 100] clipping; inputs in Celsius."""
    temperature = np.asarray(temperature, dtype=float)
    dewpoint = np.asarray(dewpoint, dtype=float)
    if (not np.all(np.isfinite(temperature)) or not np.all(np.isfinite(dewpoint))
            or np.any(temperature <= -243.04) or np.any(dewpoint <= -243.04)):
        raise ValueError('Invalid temperature/dew point for the Magnus formula')
    exponent = 17.625 * dewpoint / (243.04 + dewpoint) - 17.625 * temperature / (243.04 + temperature)
    # Positive exponents represent RH > 100 and are clipped by Open-Meteo.
    return 100.0 * np.exp(np.minimum(exponent, 0.0))


def rh_diagnostics(window, targets):
    """Separate API/anchor differences from the nonlinear interpolation effect."""
    targets = [normalize_utc_datetime(target) for target in targets]
    anchors = window.hourly.set_index('date')
    if 'dew_point_2m' not in anchors:
        raise ECMWF_IFSAPIError('Dew point is required for the RH sensitivity study')
    anchor_seconds = np.array([stamp.timestamp() for stamp in anchors.index])
    target_seconds = np.array([target.timestamp() for target in targets])
    # Use the actual production interpolator, including its coverage validation.
    atmosphere = np.array([window.at_time(target) for target in targets])
    dew = np.interp(target_seconds, anchor_seconds, anchors['dew_point_2m'])
    rh_derived = rh_from_temperature_dewpoint(atmosphere[:, 1], dew)
    anchor_rh_derived = rh_from_temperature_dewpoint(anchors['temperature_2m'], anchors['dew_point_2m'])
    linear_derived = np.interp(target_seconds, anchor_seconds, anchor_rh_derived)
    return pd.DataFrame({
        'time_utc': [target.isoformat() for target in targets],
        'rh_direct_pct': atmosphere[:, 0], 'temperature_C': atmosphere[:, 1],
        'pressure_hPa': atmosphere[:, 2], 'dew_point_C': dew,
        'rh_from_T_Td_pct': rh_derived,
        'rh_T_Td_minus_direct_pp': rh_derived - atmosphere[:, 0],
        'rh_nonlinearity_only_pp': rh_derived - linear_derived,
        'rh_anchor_difference_interpolated_pp': linear_derived - atmosphere[:, 0],
    })


def standard_pressure_hpa(elevation_m):
    """Tropospheric ISA reference, not a local meteorological prediction."""
    if not math.isfinite(elevation_m) or not -500 <= elevation_m <= 11000:
        raise ValueError('Pressure sanity reference supports elevations -500..11000 m')
    return 1013.25 * (1.0 - 0.0065 * elevation_m / 288.15) ** 5.25588


def atmosphere_flags(rh, temperature, pressure, elevation_m):
    """Soft diagnostic flags; no clipping, rejection or modification of inputs.

    T must lie in [-20, 60] C and P within 80..120% of the ISA reference at
    site elevation. These broad study thresholds catch gross/unit errors;
    they are not calibrated climatological limits for any individual station.
    """
    flags = []
    if not math.isfinite(rh) or not 0 <= rh <= 100:
        flags.append('rh_invalid')
    if not math.isfinite(temperature) or not -20 <= temperature <= 60:
        flags.append('temperature_outside_study_bounds')
    reference = standard_pressure_hpa(elevation_m)
    if not math.isfinite(pressure) or not 0.8 * reference <= pressure <= 1.2 * reference:
        flags.append('pressure_outside_elevation_envelope')
    return flags


def distance_km(lat0, lon0, lat1, lon1):
    """Great-circle distance between site and returned grid-cell centre."""
    a, b = math.radians(lat0), math.radians(lat1)
    term = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon1 - lon0) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, term))))


def capture_case(case, duration_minutes):
    """Retrieve land/nearest with identical model, elevation, UTC dates and hours."""
    from hilal_visibility.ephemeris import sunrise_sunset_utc
    from skyfield.api import wgs84
    day = date.fromisoformat(case['date'])
    location = wgs84.latlon(case['latitude'], case['longitude'], elevation_m=case['elevation_m'])
    _, sunset = sunrise_sunset_utc(location, year=day.year, month=day.month, day=day.day,
                                  temperature_C=10.0, pressure_mbar=1030.0)
    if sunset is None:
        raise ValueError('No reference sunset found on the observation date')
    start = normalize_utc_datetime(sunset)
    end = start + timedelta(minutes=duration_minutes)
    lower = start.replace(minute=0, second=0, microsecond=0)
    upper = end.replace(minute=0, second=0, microsecond=0)
    if upper < end:
        upper += timedelta(hours=1)
    captured = {'case': case, 'sunset_utc': start.isoformat(), 'windows': {}, 'errors': {}}
    for selection in ('land', 'nearest'):
        try:
            table, metadata = fetch_weather_with_info(
                case['latitude'], case['longitude'], lower.date().isoformat(), upper.date().isoformat(),
                list(ATMOSPHERIC_VARIABLES), 'UTC', elevation=case['elevation_m'], cell_selection=selection,
            )
            table = table.loc[(table['date'] >= lower) & (table['date'] <= upper)]
            expected = pd.date_range(lower, upper, freq='h')
            if not pd.DatetimeIndex(table['date']).equals(expected):
                raise ECMWF_IFSAPIError('Missing bounding hourly samples for sensitivity window')
            window = AtmosphericWindow(table, {**metadata, 'window_start_utc': start.isoformat(),
                                              'window_end_utc': end.isoformat()})
            captured['windows'][selection] = window.to_record()
        except ECMWF_IFSAPIError as exc:
            captured['errors'][selection] = str(exc)
    return captured


def analyze_case(captured, duration_minutes):
    case = captured['case']
    summary = {**case, 'status': 'complete' if len(captured['windows']) == 2 else 'incomplete',
               'errors': json.dumps(captured['errors'], ensure_ascii=False)}
    if not captured['windows']:
        return summary, [], []
    start = datetime.fromisoformat(captured['sunset_utc'])
    targets = [start + timedelta(minutes=minute) for minute in range(duration_minutes + 1)]
    traces, frames, flags = [], {}, []
    for selection, record in captured['windows'].items():
        frame = pd.DataFrame(record['hourly_raw'])
        window = AtmosphericWindow(frame, {key: value for key, value in record.items() if key != 'hourly_raw'})
        data = rh_diagnostics(window, targets)
        frames[selection] = data
        data['observation_no'] = case['observation_no']
        data['cell_selection'] = selection
        data['elevation_m'] = case['elevation_m']
        data['pressure_reference_hPa'] = standard_pressure_hpa(case['elevation_m'])
        traces.extend(data.to_dict('records'))
        for stamp, row in window.hourly.set_index('date').iterrows():
            found = atmosphere_flags(row['relative_humidity_2m'], row['temperature_2m'],
                                     row['surface_pressure'], case['elevation_m'])
            if row['dew_point_2m'] > row['temperature_2m'] + 0.5:
                found.append('dewpoint_above_temperature_by_over_0.5_C')
            if found:
                flags.append({'observation_no': case['observation_no'], 'cell_selection': selection,
                              'time_utc': stamp.isoformat(), 'flags': ','.join(found)})
        summary.update({
            f'{selection}_grid_latitude': record['latitude'], f'{selection}_grid_longitude': record['longitude'],
            f'{selection}_distance_km': distance_km(case['latitude'], case['longitude'], record['latitude'], record['longitude']),
            f'{selection}_effective_elevation_m': record['elevation'],
            f'{selection}_rh_total_max_abs_pp': float(data['rh_T_Td_minus_direct_pp'].abs().max()),
            f'{selection}_rh_total_mae_pp': float(data['rh_T_Td_minus_direct_pp'].abs().mean()),
            f'{selection}_rh_nonlinearity_max_abs_pp': float(data['rh_nonlinearity_only_pp'].abs().max()),
            f'{selection}_temperature_min_C': float(data['temperature_C'].min()),
            f'{selection}_temperature_max_C': float(data['temperature_C'].max()),
            f'{selection}_pressure_min_hPa': float(data['pressure_hPa'].min()),
            f'{selection}_pressure_max_hPa': float(data['pressure_hPa'].max()),
            f'{selection}_flags': sum(item['cell_selection'] == selection for item in flags),
        })
    if len(frames) == 2:
        land_meta = captured['windows']['land']
        nearest_meta = captured['windows']['nearest']
        summary['same_grid'] = (nearest_meta['latitude'] == land_meta['latitude']
                                and nearest_meta['longitude'] == land_meta['longitude'])
        for column, suffix in (('rh_direct_pct', 'rh_pp'), ('temperature_C', 'temperature_C'), ('pressure_hPa', 'pressure_hPa')):
            delta = frames['nearest'][column] - frames['land'][column]
            summary[f'grid_delta_{suffix}_max_abs'] = float(delta.abs().max())
            summary[f'grid_delta_{suffix}_mean'] = float(delta.mean())
    return summary, traces, flags


def save_results(payload, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'raw_inputs.json').write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    summaries, traces, flags = [], [], []
    for captured in payload['cases']:
        summary, case_traces, case_flags = analyze_case(captured, payload['duration_minutes'])
        summaries.append(summary)
        traces.extend(case_traces)
        flags.extend(case_flags)
    summary = pd.DataFrame(summaries)
    samples = pd.DataFrame(traces)
    summary.to_csv(output / 'case_summary.csv', index=False, encoding='utf-8-sig')
    samples.to_csv(output / 'minute_samples.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(flags, columns=['observation_no', 'cell_selection', 'time_utc', 'flags']).to_csv(
        output / 'flagged_samples.csv', index=False, encoding='utf-8-sig')
    complete = summary.loc[summary['status'] == 'complete']
    max_rh = float(samples['rh_T_Td_minus_direct_pp'].abs().max()) if len(samples) else None
    max_nonlinear = float(samples['rh_nonlinearity_only_pp'].abs().max()) if len(samples) else None
    metrics = dict(selected_cases=len(summary), complete_cases=len(complete), failed_cases=len(summary) - len(complete),
                   minute_samples=len(samples), flagged_hourly_samples=len(flags),
                   max_rh_total_difference_pp=max_rh, max_rh_nonlinearity_pp=max_nonlinear)
    if len(complete):
        metrics.update(distinct_grid_cases=int((~complete['same_grid'].astype(bool)).sum()),
                       max_grid_rh_difference_pp=float(complete['grid_delta_rh_pp_max_abs'].max()),
                       max_grid_temperature_difference_C=float(complete['grid_delta_temperature_C_max_abs'].max()),
                       max_grid_pressure_difference_hPa=float(complete['grid_delta_pressure_hPa_max_abs'].max()))
    (output / 'metrics.json').write_text(json.dumps(metrics, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    write_report(payload, summary, metrics, output)
    if len(samples) and len(complete):
        plot_results(complete, samples, output)
    return metrics


def write_report(payload, summary, metrics, output):
    lines = [
        '# Uji sensitivitas input atmosfer IFS', '',
        f"Produk: **{payload['product_name']}**. Selector `{IFS_MODEL}`; API `{ARCHIVE_URL}`.", '',
        '## Metode', '',
        f"Sumber data: `{payload['observations_file']}`; SHA-256 `{payload['observations_sha256']}`.",
        f"Dataset berisi {payload['dataset_cases']} observasi. Pengujian memakai {len(summary)} pasangan lokasi–tanggal.",
        'Sampel default: tanggal paling awal dan akhir di enam lokasi pantai, ditambah tanggal terakhir di tiga lokasi tertinggi.',
        f"Window: sunset sampai +{payload['duration_minutes']} menit; interval satu menit, termasuk kedua ujung window.",
        'Tanggal diambil langsung dari OBSERVATIONS. Sunset referensi memakai DE440s, elevasi lokasi, T=10 °C dan P=1030 hPa untuk kedua grid.',
        'Bias suhu/RH=0. Selector model, elevasi, variabel, window UTC, dan formula sama untuk land/nearest.',
        'Seluruh anchor hourly dan metadata respons disimpan dalam raw_inputs.json; API failure dicatat sebagai incomplete.', '',
        'RH alternatif dihitung dari interpolasi T dan Td memakai formula Magnus Open-Meteo.',
        'Total perbedaan terhadap RH API dipisahkan dari efek nonlinear murni: RH(T_interp,Td_interp) minus interpolasi RH yang diturunkan dari anchor T/Td.',
        'Sisa perbedaan anchor dapat mencakup presisi/downscaling/konsistensi variabel API, sehingga tidak seluruhnya disebut efek interpolasi.', '',
        'Pemeriksaan kewajaran bersifat diagnostik: RH 0–100%, T −20..60 °C, P 80..120% tekanan ISA pada elevasi lokasi, dan Td <= T+0.5 °C.',
        'Ambang ini dipilih untuk mendeteksi kesalahan besar/unit; belum dikalibrasi sebagai batas klimatologi BMKG. Input produksi tidak diubah atau dipotong.', '',
        '## Hasil', '',
        f"- Pasangan lengkap: {metrics['complete_cases']}/{metrics['selected_cases']}; sampel menit: {metrics['minute_samples']}.",
        f"- Anchor hourly dengan flag kewajaran: {metrics['flagged_hourly_samples']}.",
    ]
    for key, label in (('max_rh_total_difference_pp', 'Maksimum absolut RH dari T/Td vs RH langsung (poin persentase)'),
                       ('max_rh_nonlinearity_pp', 'Maksimum absolut efek nonlinear murni RH (poin persentase)'),
                       ('max_grid_rh_difference_pp', 'Maksimum absolut land vs nearest, RH (poin persentase)'),
                       ('max_grid_temperature_difference_C', 'Maksimum absolut land vs nearest, T (°C)'),
                       ('max_grid_pressure_difference_hPa', 'Maksimum absolut land vs nearest, P (hPa)')):
        if metrics.get(key) is not None:
            lines.append(f'- {label}: {metrics[key]:.6f}.')
    if 'distinct_grid_cases' in metrics:
        lines.append(f"- Pasangan yang memakai grid berbeda: {metrics['distinct_grid_cases']}.")
    lines.extend(['', '| No | Lokasi | Tanggal | Elevasi (m) | Status |', '|---:|---|---|---:|---|'])
    for case in summary.to_dict('records'):
        lines.append(f"| {case['observation_no']} | {case['location']} | {case['date']} | {case['elevation_m']:g} | {case['status']} |")
    lines.extend(['', '## Interpretasi dan batas pengujian', '',
                  'Perbedaan interpolasi mengukur sensitivitas metode, bukan error terhadap pengamatan meteorologi.',
                  'Perbedaan land/nearest mengukur sensitivitas pilihan grid; jarak grid yang lebih kecil belum membuktikan akurasi lebih baik.',
                  'Sampel spot tidak mewakili semua 278 observasi, seluruh musim, atau semua versi IFS. Gunakan --all untuk memperluas pengujian.',
                  'Kelulusan sanity check tidak membuktikan akurasi cuaca. Pemilihan metode terbaik tetap membutuhkan data BMKG independen.',
                  'Dampak perubahan input terhadap Δm dan keputusan keterlihatan Y/N belum diukur dalam studi ini.',
                  'Interpolasi RH langsung, cell_selection=land, dan validator produksi dipertahankan selama evaluasi ini.', '',
                  '## Reproduksi', '',
                  '```powershell', '.\\.venv\\Scripts\\python.exe -X utf8 scripts/study_ifs_sensitivity.py',
                  '.\\.venv\\Scripts\\python.exe -X utf8 scripts/study_ifs_sensitivity.py --replay outputs/ifs_sensitivity/raw_inputs.json --output outputs/ifs_sensitivity_replay',
                  '```', '', '[Ringkasan per kasus](case_summary.csv), [sampel tiap menit](minute_samples.csv), [flag](flagged_samples.csv), [input raw](raw_inputs.json).',
                  '', '![Grafik hasil](sensitivity.png)', '', '## Referensi', '',
                  '- [Identitas produk dan endpoint](https://open-meteo.com/en/docs/historical-weather-api).',
                  f'- [Formula RH Open-Meteo pada commit yang diaudit]({RH_FORMULA_REFERENCE}).',
                  '- [Model atmosfer berdasarkan elevasi](https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html).', ''])
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def plot_results(summary, samples, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    labels = summary['observation_no'].astype(str)
    x = np.arange(len(summary))
    axes[0, 0].bar(x - .18, summary['land_rh_total_max_abs_pp'], .36, label='land')
    axes[0, 0].bar(x + .18, summary['nearest_rh_total_max_abs_pp'], .36, label='nearest')
    axes[0, 0].set(ylabel='Max absolute difference (RH percentage points)', title='RH(T, Td) vs directly interpolated RH')
    axes[0, 0].legend()
    axes[0, 1].bar(x, summary['grid_delta_rh_pp_max_abs'])
    axes[0, 1].set(ylabel='Max absolute difference (RH percentage points)', title='land vs nearest')
    for selection in ('land', 'nearest'):
        axes[1, 0].plot(x, summary[f'{selection}_distance_km'], 'o-', label=selection)
    axes[1, 0].set(ylabel='Distance (km)', title='Site to returned grid centre')
    axes[1, 0].legend()
    for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
        ax.set_xticks(x, labels, rotation=45)
        ax.set_xlabel('Observation number in source dataset')
    axes[1, 1].scatter(samples['elevation_m'], samples['pressure_hPa'] / samples['pressure_reference_hPa'], s=6, alpha=.25)
    axes[1, 1].axhspan(.8, 1.2, color='green', alpha=.08, label='Study sanity envelope')
    axes[1, 1].set(xlabel='Site elevation (m)', ylabel='P / ISA reference P', title='Surface pressure and elevation')
    axes[1, 1].legend()
    fig.savefig(output / 'sensitivity.png', dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path, default=OBSERVATIONS_PATH)
    parser.add_argument('--output', type=Path, default=OUTPUT_DIR / 'ifs_sensitivity')
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--duration-minutes', type=int, default=120)
    args = parser.parse_args()
    if args.duration_minutes <= 0:
        parser.error('--duration-minutes must be positive')
    if args.replay:
        payload = json.loads(args.replay.read_text(encoding='utf-8'))
    else:
        cases, source_hash = load_cases(args.observations)
        selected = cases if args.all else select_spot_cases(cases)
        payload = {'schema_version': 1, 'product_name': IFS_PRODUCT_NAME,
                   'observations_file': str(args.observations), 'observations_sha256': source_hash,
                   'dataset_cases': len(cases), 'duration_minutes': args.duration_minutes,
                   'retrieved_at_utc': datetime.now(timezone.utc).isoformat(), 'cases': []}
        for index, case in enumerate(selected, 1):
            print(f"[{index}/{len(selected)}] {case['location']} {case['date']}", flush=True)
            try:
                captured = capture_case(case, args.duration_minutes)
            except (ECMWF_IFSAPIError, ValueError) as exc:
                captured = {'case': case, 'windows': {}, 'errors': {'case': str(exc)}}
            payload['cases'].append(captured)
            # Preserve successful inputs even if the next request/run fails.
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'raw_inputs.json').write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    metrics = save_results(payload, args.output)
    print(json.dumps(metrics, indent=2))
    print(f"Report: {args.output / 'report.md'}")
    return 1 if metrics['failed_cases'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
