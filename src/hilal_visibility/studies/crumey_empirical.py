"""Reproducible, explicitly exploratory crescent observation comparison.

The BMKG labels shipped by ``core_multi_location`` were confirmed by the user
as CCD/digital imaging through telescopes, not visual eyepiece observations.
No production
default is changed by this study. Formula verification and label agreement
are separate results. Capture uses real pinned IFS hourly data; replay never
contacts an API and never replaces failed weather with assumed weather.

Run from the repository root:
    python -X utf8 scripts/compare_crumey_observations.py --capture-only
    python -X utf8 scripts/compare_crumey_observations.py --replay validation/crumey_empirical/raw_inputs.json
"""

import argparse
import ast
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import contextlib
from datetime import date, datetime, timezone
import hashlib
import io
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import sys
import time

# Skyfield uses small matrix operations. Eight BLAS threads in each of four
# replay processes cause severe oversubscription; use one unless configured.
for _thread_setting in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_thread_setting, '1')

import numpy as np
import pandas as pd
from hilal_visibility.paths import PROJECT_ROOT, EPHEMERIS_PATH, OBSERVATIONS_PATH, OUTPUT_DIR
from hilal_visibility.datasets import load_observation_rows
from hilal_visibility.models.crumey import DEFAULT_VISUAL_FIELD_FACTOR


F_REF = DEFAULT_VISUAL_FIELD_FACTOR
TELESCOPE = dict(aperture=100.0, magnification=50.0, transmission=0.95,
                 n_surfaces=6, central_obstruction=0.0, observer_age=22.0,
                 field_factor=F_REF)
AREA_FRACTIONS = (1.0, 0.5, 0.25, 0.1)
F_BOUNDS = (0.5, 20.0)
ROOT = PROJECT_ROOT
SOURCE_FILES = (
    'calculator.py', 'models/crumey.py', 'models/kastner.py', 'models/schaefer.py',
    'models/telescope.py', 'ephemeris.py', 'atmosphere/ifs.py', 'models/geometry.py',
    'paths.py', 'datasets.py',
)


def source_hashes():
    package = ROOT / 'src' / 'hilal_visibility'
    return {name: sha256_file(package / name) for name in SOURCE_FILES}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observations_digest(cases):
    """Hash observational data separately from executable code and comments."""
    keys = ('observation_no', 'date', 'location', 'latitude', 'longitude', 'elevation_m',
            'hijri_month', 'hijri_year', 'observed')
    canonical = [{key: case[key] for key in keys} for case in cases]
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def calculation_fingerprint():
    """Invalidate replay caches on numerical evaluator, inputs or library changes.

    Use the predictor AST, not its file's prose/statistical-report code, as
    the evaluator's numerical identity. Whole-file hash remains provenance.
    """
    tree = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    predictor = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'predict_case')
    semantics = ast.dump(predictor, include_attributes=False).encode('utf-8')
    return dict(schema_version=2, predictor_ast_sha256=hashlib.sha256(semantics).hexdigest(),
                source_sha256=source_hashes(),
                ephemeris_sha256=sha256_file(EPHEMERIS_PATH),
                package_versions={name: version(name) for name in ('numpy', 'pandas', 'skyfield', 'jplephem', 'pytz')},
                python_version=sys.version,
                F_ref=F_REF, telescope=TELESCOPE, area_fractions=list(AREA_FRACTIONS))


def load_observations(path):
    """Read literal tuples as data, without executing the batch module."""
    cases, seen = [], set()
    for entry in load_observation_rows(path):
        if len(entry) != 11 or type(entry[10]) is not bool:
            raise ValueError('Expected 11 columns and explicit Boolean labels')
        day = date.fromisoformat(entry[1])
        if entry[0] in seen or entry[8:10] != (0, 0):
            raise ValueError('Observation IDs must be unique and biases zero')
        seen.add(entry[0])
        if not all(math.isfinite(v) for v in entry[3:6]):
            raise ValueError('Nonfinite observation coordinates')
        if not -90 <= entry[3] <= 90 or not -180 <= entry[4] <= 180:
            raise ValueError('Observation coordinates outside their domain')
        cases.append(dict(observation_no=entry[0], date=day.isoformat(),
                          location=entry[2], latitude=entry[3], longitude=entry[4],
                          elevation_m=entry[5], hijri_month=entry[6], hijri_year=entry[7],
                          observed=entry[10], label_method='ccd',
                          visual_attempt_verified=False, actual_attempt_window=None,
                          actual_telescope=None))
    return cases


def inspect_source_workbook(path, cases):
    """Record source metadata and verify its labels, dates, and coordinates."""
    from openpyxl import load_workbook
    path = Path(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows = list(workbook['Sheet1'].values)
    by_id = {row[0]: row for row in rows[1:] if row[0] is not None}
    mismatches, extra = [], []
    for case in cases:
        row = by_id.get(case['observation_no'])
        if row is None:
            mismatches.append(dict(observation_no=case['observation_no'], field='missing'))
            continue
        expected = (case['location'], case['latitude'], case['longitude'], case['elevation_m'],
                    case['date'], 'v' if case['observed'] else 'x')
        actual = (row[1], row[2], row[3], row[4], row[6].date().isoformat(), row[8])
        if actual != expected:
            mismatches.append(dict(observation_no=case['observation_no'], field='row_values'))
        extra.append(dict(observation_no=case['observation_no'],
                          time_annotation=row[5], observing_institution=row[9]))
    workbook.close()
    return dict(path=str(path.resolve()), sha256=sha256_file(path), sheet='Sheet1',
                rows=len(by_id), headers=list(rows[0]), mismatches=mismatches,
                observation_metadata=extra,
                annotation_warning='Day offsets are not actual detection or attempt times; instrument/method and cloud conditions are absent.')


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                    allow_nan=False) + '\n', encoding='utf-8')
    # Windows readers/indexers may briefly hold the destination without
    # FILE_SHARE_DELETE. Preserve the last good checkpoint and retry replace.
    for attempt in range(6):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * 2**attempt)


def prediction_json_record(result):
    """Preserve legitimate -infinite zero-increment margins in strict JSON.

    Only prediction records use explicit strings for nonfinite values; raw
    weather continues to reject nonfinite samples. Numeric fields containing
    tokens are listed, so consumers never mistake them for measured numbers.
    """
    nonfinite = {}
    def encode(value, path=''):
        if isinstance(value, dict):
            return {key: encode(item, f'{path}.{key}' if path else str(key)) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item, f'{path}[{index}]') for index, item in enumerate(value)]
        if isinstance(value, (float, np.floating)) and not math.isfinite(value):
            token = 'NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity'
            nonfinite[path] = token
            return token
        return value
    record = encode(result)
    if nonfinite:
        record['nonfinite_numeric_fields'] = nonfinite
        record['nonfinite_encoding'] = 'Explicit string tokens; -Infinity means a zero-increment visibility margin, not a missing weather measurement.'
    return record


def decoded_margin(value):
    """Decode the one nonfinite margin representing zero detectable signal."""
    if value == '-Infinity':
        return float('-inf')
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.floating)):
        raise ValueError('Margin must be numeric or the explicit -Infinity snapshot token')
    value = float(value)
    if math.isnan(value) or value == float('inf'):
        raise ValueError('NaN and positive-infinite visibility margins are invalid')
    return value


def capture_weather(case):
    from hilal_visibility.atmosphere.ifs import fetch_weather_with_info, AtmosphericWindow, ATMOSPHERIC_VARIABLES
    frame, metadata = fetch_weather_with_info(
        case['latitude'], case['longitude'], case['date'], case['date'],
        list(ATMOSPHERIC_VARIABLES), 'UTC', elevation=case['elevation_m'], cell_selection='land')
    return AtmosphericWindow(frame, metadata).to_record()


def capture_inputs(cases, output, source, workbook=None):
    """Checkpoint each case and allow a failed request to be inspected/retried."""
    from hilal_visibility.atmosphere.ifs import ARCHIVE_URL, IFS_MODEL, IFS_PRODUCT_NAME
    path = output / 'raw_inputs.json'
    source_digest = sha256_file(source)
    data_digest = observations_digest(cases)
    if path.exists():
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload['observations_sha256'] != source_digest:
            expected = {case['observation_no']: case for case in cases}
            if any(item['case'] != expected.get(item['case']['observation_no']) for item in payload['cases']):
                raise ValueError('Observation data changed: use a new output directory')
            payload.setdefault('source_file_sha256_history', []).append(payload['observations_sha256'])
            payload['observations_sha256'] = source_digest
            payload['source_change_note'] = 'Source bytes changed; every previously captured literal observation was compared unchanged before resuming.'
    else:
        payload = dict(schema_version=1, observations_file=str(source.resolve()),
                       observations_sha256=source_digest, dataset_cases=len(cases),
                       product_name=IFS_PRODUCT_NAME, atmosphere_model=IFS_MODEL,
                       atmosphere_endpoint=ARCHIVE_URL, cell_selection='land',
                       bias_t=0.0, bias_rh=0.0, label_method='ccd',
                       label_method_provenance='User confirmed all 278 labels are CCD/digital imaging through telescope; 2026-10-05',
                       observation_source_url='https://hilal.bmkg.go.id/gallery', cases=[])
        if workbook and workbook.exists():
            payload['source_workbook'] = inspect_source_workbook(workbook, cases)
    existing = {item['case']['observation_no']: item for item in payload['cases']}
    payload['observation_data_sha256'] = data_digest
    for index, case in enumerate(cases, 1):
        if case['observation_no'] in existing and existing[case['observation_no']].get('atmosphere'):
            continue
        try:
            captured = dict(case=case, atmosphere=capture_weather(case), error=None)
        except Exception as exc:
            captured = dict(case=case, atmosphere=None, error=f'{type(exc).__name__}: {exc}')
        existing[case['observation_no']] = captured
        payload['cases'] = [existing[item['observation_no']] for item in cases
                            if item['observation_no'] in existing]
        payload['captured_at_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(path, payload)
        print(f'Weather {index}/{len(cases)}: #{case["observation_no"]} '
              f'{"OK" if captured["atmosphere"] else captured["error"]}', flush=True)
    write_json(path, payload)
    return payload


def predict_case(captured):
    """Evaluate the repaired production scan on the supplied observation date.

    Stored hourly anchors support exactly the same atmospheric interpolation
    as production. Date is fixed to the observation, not inferred from the
    Hijri month. The scan is an opportunity prediction; actual attempt/detection
    times are unknown. All fractions examine the same valid sampled scenes.
    """
    from hilal_visibility.atmosphere.ifs import AtmosphericWindow, ObservingLocation
    from hilal_visibility.calculator import HilalVisibilityCalculator, tentukan_timezone_indonesia
    from hilal_visibility.ephemeris import sunrise_sunset_utc, convert_utc_to_localtime
    from hilal_visibility.models.crumey import (contrast_threshold, crescent_area_arcmin2,
                                   arcmin2_to_sr, nL_to_cd_m2, visibility_margin_mag)

    case = captured['case']
    if not captured.get('atmosphere'):
        return dict(case=case, status='weather_failed', error=captured.get('error'), samples=[])
    record = captured['atmosphere']
    window = AtmosphericWindow(pd.DataFrame(record['hourly_raw']),
                               {k: v for k, v in record.items() if k != 'hourly_raw'})
    samples = []

    class ReplayCalculator(HilalVisibilityCalculator):
        def _fetch_atmosfer_window(self, observing_location, start_utc, end_utc, verbose=True):
            window.at_time(start_utc)
            window.at_time(end_utc)
            return window

        def hitung_visibilitas_pada_waktu(self, *args, **kwargs):
            result = super().hitung_visibilitas_pada_waktu(*args, **kwargs)
            if result['valid'] and result['moon_alt'] >= 2.0:
                area = arcmin2_to_sr(crescent_area_arcmin2(result['elongation'], result['moon_semidiameter']))
                point = {key: value.isoformat() if isinstance(value, datetime) else value
                         for key, value in result.items()}
                point['A_sr'] = area
                point['margin_by_area_fraction'] = {}
                for fraction in AREA_FRACTIONS:
                    threshold = contrast_threshold(area * fraction * TELESCOPE['magnification']**2,
                                                   nL_to_cd_m2(result['sky_brightness_tel_nl']),
                                                   F=math.sqrt(2) * F_REF, mode='auto')
                    margin = visibility_margin_mag(result['rasio_kontras_tel'], threshold)
                    point['margin_by_area_fraction'][str(fraction)] = margin
                samples.append(point)
            return result

    tz = tentukan_timezone_indonesia(case['longitude'])
    calc = ReplayCalculator(case['location'], case['latitude'], case['longitude'],
                            case['elevation_m'], tz, case['hijri_month'], case['hijri_year'],
                            sumber_atmosfer='ecmwf_ifs', bias_t=0.0, bias_rh=0.0)
    day = date.fromisoformat(case['date'])
    try:
        # First sunset locates an atmospheric sample; then use its actual T/P
        # to obtain apparent sunset. Repeat once and record the final atmosphere.
        _, sunset = sunrise_sunset_utc(calc.location, year=day.year, month=day.month,
                                      day=day.day, temperature_C=10.0, pressure_mbar=1030.0)
        if sunset is None:
            raise ValueError('No sunset on observation date')
        for _ in range(2):
            rh, temperature, pressure = window.at_time(sunset)
            _, sunset = sunrise_sunset_utc(calc.location, year=day.year, month=day.month,
                                          day=day.day, temperature_C=temperature, pressure_mbar=pressure)
        local = convert_utc_to_localtime(tz, utc_datetime=sunset)
        calc.hasil['tanggal_pengamatan'] = local
        loc = ObservingLocation(case['location'], case['latitude'], case['longitude'],
                                case['elevation_m'], tz)
        with contextlib.redirect_stdout(io.StringIO()):
            optimal = calc.cari_visibilitas_optimal(local, loc, F_naked=F_REF,
                                                    interval_menit=1, min_moon_alt=2.0,
                                                    start_delay_menit=1, **TELESCOPE)
        if not samples:
            return dict(case=case, status='no_eligible_scene', error='No scene above 2 deg', samples=[])
        # Full-area sampling is supplied by the production scan/refinement.
        # Other area fractions use those identical samples, no label-driven timing.
        maxima = {str(f): max(p['margin_by_area_fraction'][str(f)] for p in samples)
                  for f in AREA_FRACTIONS}
        production_margin = optimal['optimal_delta_m_tel']
        if not math.isclose(maxima['1.0'], production_margin, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError('Full-area replay differs from repaired production threshold')
        unique = {p['waktu_local']: p for p in samples}
        return dict(case=case, status='complete', error=None, sunset_utc=sunset.isoformat(),
                    optimal_time=optimal['optimal_time_tel'].isoformat(),
                    margin_ref=production_margin, margin_by_area_fraction=maxima,
                    samples=list(unique.values()))
    except Exception as exc:
        return dict(case=case, status='calculation_failed', error=f'{type(exc).__name__}: {exc}', samples=[])


def binary_metrics(labels, predictions, weights=None):
    labels = boolean_array(labels, 'labels')
    predictions = boolean_array(predictions, 'predictions')
    if labels.shape != predictions.shape or labels.ndim != 1 or not len(labels):
        raise ValueError('Expected equal nonempty one-dimensional labels and predictions')
    weights = np.ones(len(labels)) if weights is None else np.asarray(weights, dtype=float)
    if weights.shape != labels.shape or not np.all(np.isfinite(weights)) or np.any(weights <= 0):
        raise ValueError('Weights must be finite and positive')
    counts = {(bool(y), bool(p)): float(weights[(labels == y) & (predictions == p)].sum())
              for y in (False, True) for p in (False, True)}
    tn, fp, fn, tp = counts[False, False], counts[False, True], counts[True, False], counts[True, True]
    sensitivity = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    return dict(n=len(labels), tp=tp, tn=tn, fp=fp, fn=fn,
                accuracy=(tp + tn) / weights.sum(), sensitivity=sensitivity, specificity=specificity,
                balanced_accuracy=(sensitivity + specificity) / 2
                if sensitivity is not None and specificity is not None else None)


def boolean_array(values, name='labels'):
    """Reject strings, numbers, NaN and missing labels instead of coercing."""
    array = np.asarray(values, dtype=object)
    if array.ndim != 1 or not len(array) or any(not isinstance(v, (bool, np.bool_)) for v in array):
        raise ValueError(f'{name} must be a nonempty sequence of explicit Boolean values')
    return array.astype(bool)


def event_weights(events):
    counts = Counter(events)
    return np.asarray([1 / counts[event] for event in events])


def campaign_key(case):
    """Prefer one Hijri lunation/campaign over its potentially multiple dates."""
    if case.get('hijri_year') is not None and case.get('hijri_month') is not None:
        return f'{case["hijri_year"]}-{case["hijri_month"]:02d}'
    return case['date']


def calibration_eligibility(case):
    """A CCD label cannot calibrate the human Crumey threshold.

    A negative visual label must also verify an actual visual attempt. For
    an opportunity-over-time model, an actual attempt window is required so
    predictions can be restricted to the attempted conditions. Telescope
    labels additionally require actual optical and observer configuration.
    """
    reasons = []
    if not isinstance(case.get('observed'), (bool, np.bool_)):
        reasons.append('observation_label_is_not_boolean')
    method = case.get('label_method')
    if method not in ('naked_eye', 'visual_telescope'):
        reasons.append('labels_are_not_verified_human_visual_observations')
    if case.get('visual_attempt_verified') is not True:
        reasons.append('actual_visual_attempt_is_unverified')
    attempt = case.get('actual_attempt_window')
    if not isinstance(attempt, dict) or not all(key in attempt for key in ('start_utc', 'end_utc')):
        reasons.append('actual_attempt_time_window_is_missing')
    else:
        try:
            start, end = (datetime.fromisoformat(attempt[key]) for key in ('start_utc', 'end_utc'))
            if any(stamp.tzinfo is None or stamp.utcoffset() is None for stamp in (start, end)) or end < start:
                raise ValueError('Invalid attempt window')
            from pytz import timezone as observing_timezone
            zone = case.get('timezone_str')
            if not zone:
                reasons.append('actual_time_zone_is_missing')
            else:
                observer_zone = observing_timezone(zone)
                if start.astimezone(observer_zone).date().isoformat() != case.get('date'):
                    reasons.append('actual_attempt_window_does_not_match_observation_date')
                if (end - start).total_seconds() > 24 * 3600:
                    reasons.append('actual_attempt_window_exceeds_one_day')
        except (TypeError, ValueError):
            reasons.append('actual_attempt_time_window_is_invalid')
        except KeyError:
            reasons.append('actual_time_zone_is_invalid')
    if method == 'visual_telescope':
        optical = case.get('actual_telescope')
        required = ('aperture', 'magnification', 'transmission', 'n_surfaces',
                    'central_obstruction', 'observer_age')
        if not isinstance(optical, dict) or not all(key in optical for key in required):
            reasons.append('actual_optical_and_observer_configuration_is_missing')
        else:
            try:
                from hilal_visibility.models.telescope import TelescopeVisibilityModel
                TelescopeVisibilityModel().calculate_factors(
                    D=optical['aperture'], Ds=optical['central_obstruction'],
                    M=optical['magnification'], age=optical['observer_age'],
                    t1=optical['transmission'], n=optical['n_surfaces'])
            except (TypeError, ValueError):
                reasons.append('actual_optical_and_observer_configuration_is_invalid')
    return dict(eligible=not reasons, reasons=reasons)


def fit_field_factor(margins, labels, events, *, observation_methods=None,
                     f_ref=F_REF, bounds=F_BOUNDS):
    """Fit one effective F by event-weighted balanced accuracy on training only.

    Margin(F) = margin(F_ref) - 2.5 log10(F/F_ref), so the fit cannot
    independently identify observer, crescent shape, luminance, or optics.
    Ties favour the reference F. F bounds are predeclared study bounds, not
    measured optical/observer constraints.
    """
    try:
        if len(bounds) != 2:
            raise ValueError('F bounds must be exactly one finite lower/upper pair')
    except TypeError as exc:
        raise ValueError('F bounds must be exactly one finite lower/upper pair') from exc
    labels = boolean_array(labels)
    if observation_methods is None or len(observation_methods) != len(labels):
        raise ValueError('Verified human visual observation methods are required for calibration')
    if len(set(observation_methods)) != 1 or observation_methods[0] not in ('naked_eye', 'visual_telescope'):
        raise ValueError('CCD, imaging, mixed or unknown labels cannot calibrate a human visual field factor')
    margins = np.asarray(margins, dtype=float)
    if margins.ndim != 1 or len(margins) != len(labels) or len(events) != len(labels) or not len(labels):
        raise ValueError('Training margins, labels and events must have matching nonempty lengths')
    if (not np.all(np.isfinite(margins)) or not math.isfinite(f_ref)
            or not all(math.isfinite(v) for v in bounds)
            or not 0 < bounds[0] <= f_ref <= bounds[1]):
        raise ValueError('Invalid margins, F reference, or F study bounds')
    if len(set(labels)) < 2:
        return dict(field_factor=f_ref, shift_mag=0.0, status='single_class_training', objective=None)
    lower, upper = [2.5 * math.log10(f / f_ref) for f in bounds]
    values = np.unique(margins)
    candidates = np.unique(np.concatenate(([lower, 0.0, upper], values,
                                            (values[:-1] + values[1:]) / 2)))
    candidates = candidates[(candidates >= lower) & (candidates <= upper)]
    weights = event_weights(events)
    scored = [(binary_metrics(labels, margins > shift, weights)['balanced_accuracy'],
               -abs(float(shift)), -float(shift), float(shift)) for shift in candidates]
    score, _, _, shift = max(scored)
    return dict(field_factor=f_ref * 10 ** (shift / 2.5), shift_mag=shift,
                status='complete', objective=score,
                at_bound=math.isclose(shift, lower) or math.isclose(shift, upper))


def grouped_validation(rows, area_fraction='1.0'):
    """Hold out an entire lunation (date fallback); its labels never fit F."""
    for row in rows:
        suitability = calibration_eligibility(row['case'])
        if not suitability['eligible']:
            raise ValueError('Ineligible calibration observation: ' + ', '.join(suitability['reasons']))
        if row.get('prediction_time_window_verified') is not True:
            raise ValueError('Predictions must be restricted to the actual visual attempt window')
        if row['case']['label_method'] == 'visual_telescope' and row.get('prediction_optics_verified') is not True:
            raise ValueError('Predictions must use the actual telescope and observer configuration')
    labels = boolean_array([row['case']['observed'] for row in rows])
    methods = [row['case']['label_method'] for row in rows]
    events = [campaign_key(row['case']) for row in rows]
    margins = np.array([row['margin_by_area_fraction'][area_fraction] for row in rows])
    if len(set(events)) < 2:
        raise ValueError('Grouped validation requires at least two campaign/date groups')
    folds, predictions = [], np.zeros(len(rows), dtype=bool)
    corrected = np.zeros(len(rows))
    for event in sorted(set(events)):
        test = np.array([key == event for key in events])
        train = ~test
        fit = fit_field_factor(margins[train], labels[train],
                               [key for key, keep in zip(events, train) if keep],
                               observation_methods=[key for key, keep in zip(methods, train) if keep])
        corrected[test] = margins[test] - fit['shift_mag']
        predictions[test] = corrected[test] > 0
        folds.append(dict(held_out_event=event, train_events=sorted(set(key for key in events if key != event)),
                          held_out_dates=sorted(set(row['case']['date'] for row, keep in zip(rows, test) if keep)),
                          train_n=int(train.sum()), test_n=int(test.sum()), **fit,
                          test_metrics=binary_metrics(labels[test], predictions[test])))
    weights = event_weights(events)
    return dict(area_fraction=float(area_fraction), baseline=binary_metrics(labels, margins > 0),
                out_of_sample=binary_metrics(labels, predictions),
                event_weighted_baseline=binary_metrics(labels, margins > 0, weights),
                event_weighted_out_of_sample=binary_metrics(labels, predictions, weights),
                descriptive_full_sample_fit=fit_field_factor(margins, labels, events,
                                                               observation_methods=methods), folds=folds,
                held_out_predictions=[dict(observation_no=row['case']['observation_no'],
                                            event=event, observed=bool(label), baseline_margin=float(margin),
                                            corrected_margin=float(delta), predicted=bool(pred))
                                      for row, event, label, margin, delta, pred in
                                      zip(rows, events, labels, margins, corrected, predictions)])


def clustered_interval(predictions, draws=2000, seed=20261005):
    """Percentile event bootstrap, conditional on already fitted CV predictions.

    This measures date-cluster sampling variation, not uncertainty from a new
    training fit, method ambiguity, weather-model bias, or dataset selection.
    """
    grouped = {}
    for row in predictions:
        grouped.setdefault(row['event'], []).append(row)
    keys = list(grouped)
    rng, baseline, calibrated, differences = np.random.default_rng(seed), [], [], []
    for _ in range(draws):
        sampled = [item for key in rng.choice(keys, size=len(keys), replace=True) for item in grouped[key]]
        labels = [row['observed'] for row in sampled]
        a = binary_metrics(labels, [row['baseline_margin'] > 0 for row in sampled])['balanced_accuracy']
        b = binary_metrics(labels, [row['predicted'] for row in sampled])['balanced_accuracy']
        if a is not None and b is not None:
            baseline.append(a)
            calibrated.append(b)
            differences.append(b - a)
    def interval(values):
        return np.quantile(values, [.025, .975]).tolist() if values else None
    return dict(method='observation-date cluster percentile bootstrap; conditional on held-out predictions',
                draws=draws, valid_draws=len(baseline), seed=seed,
                baseline_balanced_accuracy_95pct=interval(baseline),
                calibrated_balanced_accuracy_95pct=interval(calibrated),
                difference_balanced_accuracy_95pct=interval(differences))


def descriptive_cluster_interval(predictions, draws=2000, seed=20261005):
    """Sampling interval for cross-method agreement, not a visual model CI."""
    grouped = {}
    for row in predictions:
        grouped.setdefault(row['event'], []).append(row)
    events = list(grouped)
    rng, scores = np.random.default_rng(seed), []
    for _ in range(draws):
        sampled = [row for event in rng.choice(events, size=len(events), replace=True) for row in grouped[event]]
        score = binary_metrics([row['observed'] for row in sampled],
                               [row['predicted'] for row in sampled])['balanced_accuracy']
        if score is not None:
            scores.append(score)
    return dict(method='date-cluster percentile bootstrap of descriptive CCD agreement', draws=draws,
                valid_draws=len(scores), seed=seed,
                balanced_accuracy_95pct=np.quantile(scores, [.025, .975]).tolist() if scores else None,
                interpretation='Conditional sampling interval; excludes unknown optics/timing, method mismatch, cloud/atmosphere bias and curated-dataset selection.')


def save_analysis(predictions, output):
    if predictions['cases']:
        boolean_array([item['case']['observed'] for item in predictions['cases']])
    rows = [item for item in predictions['cases'] if item['status'] == 'complete']
    failed = [dict(observation_no=item['case']['observation_no'], date=item['case']['date'],
                   status=item['status'], error=item['error'])
              for item in predictions['cases'] if item['status'] != 'complete']
    summary = dict(status='descriptive_cross_method_comparison_only',
                   empirical_visual_validation=False, naked_eye_validation=False,
                   default_calibration_applied=False, observations=len(predictions['cases']),
                   complete=len(rows), observation_dates=len(set(item['case']['date'] for item in predictions['cases'])),
                   hijri_campaigns=len(set(campaign_key(item['case']) for item in predictions['cases'])),
                   modeled_observation_dates=len(set(item['case']['date'] for item in rows)),
                   status_counts=dict(Counter(item['status'] for item in predictions['cases'])),
                   metric_denominator_policy='Only complete modeled cases enter descriptive confusion matrices. No-eligible-scene and failed cases remain explicitly listed and are not counted as predicted negative.',
                   cluster_independence_verified=False,
                   observed_visible=sum(item['case']['observed'] for item in rows), failures=failed,
                   field_factor_ref=F_REF, field_factor_bounds=list(F_BOUNDS), telescope=TELESCOPE,
                   label_method='ccd', area_fraction_comparisons=[],
                   visual_calibration_eligibility=[dict(observation_no=item['case']['observation_no'],
                                                       **calibration_eligibility(item['case']))
                                                    for item in predictions['cases']],
                   limitations=['CCD/imaging labels do not measure human visual contrast thresholds.',
                                'Actual telescope optics, observer parameters and attempt/detection times are missing.',
                                'Reference optics are assumed for descriptive predictions.',
                                'No field factor or crescent-shape correction is fitted to CCD labels.',
                                'IFS atmospheric inputs are model values, not onsite transparency/cloud observations.',
                                'No naked-eye visual labels are present.'])
    if rows:
        labels = [row['case']['observed'] for row in rows]
        events = [row['case']['date'] for row in rows]
        for fraction in AREA_FRACTIONS:
            margins = [decoded_margin(row['margin_by_area_fraction'][str(fraction)]) for row in rows]
            descriptive_predictions = [dict(observation_no=row['case']['observation_no'], event=event,
                                            observed=label, baseline_margin=margin, predicted=margin > 0)
                                       for row, event, label, margin in zip(rows, events, labels, margins)]
            evaluation = dict(area_fraction=fraction, interpretation='descriptive CCD agreement; not visual validation',
                              cross_method_agreement=binary_metrics(labels, np.array(margins) > 0),
                              event_weighted_agreement=binary_metrics(labels, np.array(margins) > 0, event_weights(events)),
                              predictions=descriptive_predictions)
            evaluation['cluster_bootstrap'] = descriptive_cluster_interval(descriptive_predictions)
            summary['area_fraction_comparisons'].append(evaluation)
    write_json(output / 'metrics.json', prediction_json_record(summary))
    csv_rows = []
    for evaluation in summary['area_fraction_comparisons']:
        csv_rows.extend(dict(area_fraction=evaluation['area_fraction'], **row)
                        for row in evaluation['predictions'])
    pd.DataFrame(csv_rows).to_csv(output / 'descriptive_predictions.csv', index=False, encoding='utf-8-sig')
    write_report(summary, predictions, output)
    return summary


def write_report(summary, predictions, output):
    eligible = sum(item['eligible'] for item in summary['visual_calibration_eligibility'])
    lines = ['# Pemeriksaan empiris hilal: label CCD dan threshold visual Crumey', '',
             '**Status: perbandingan deskriptif lintas metode; bukan validasi empiris visual.**', '',
             f'Dataset memuat {summary["observations"]} observasi pada '
             f'{summary["observation_dates"]} tanggal dan {summary["hijri_campaigns"]} '
             'campaign/lunasi (tahun dan bulan Hijri). Pengguna mengonfirmasi '
             'bahwa seluruh label berasal dari CCD/citra digital melalui teleskop. '
             'Konfigurasi optik dan waktu percobaan/deteksi aktual tidak tersedia. '
             f'Observasi yang memenuhi syarat kalibrasi visual: **{eligible}**. '
             'Tidak ada field factor atau koreksi bentuk hilal yang dipasang ke label CCD; '
             'default produksi tidak diubah.', '',
             f'Perhitungan lengkap: {summary["complete"]}/{summary["observations"]}. '
             f'Label terlihat pada kasus lengkap: {summary["observed_visible"]}. '
             'Baris lokasi pada tanggal yang sama dikelompokkan sebagai satu event; '
             'jumlah baris tidak diperlakukan sebagai jumlah event independen. '
             'Jumlah tanggal/lunasi tidak membuktikan independensi statistik; '
             'korelasi antarlaporan dari pengamat/lokasi yang sama masih mungkin.', '',
             'Denominator tabel mencakup hanya kasus berstatus `complete`. '
             'Kasus `no_eligible_scene` (tidak ada scene scan pada altitude Bulan ≥2°) '
             'serta kegagalan cuaca/kalkulasi tetap dicatat terpisah dan tidak '
             'dianggap prediksi negatif. Karena itu, angka tabel tidak mewakili '
             'semua baris dataset bila ada pengecualian.', '',
             'Prediksi memakai tanggal observasi eksplisit, atmosfer IFS HRES yang dipilih '
             'melalui `ecmwf_ifs`, hourly anchors UTC asli, interpolator produksi, dan bias '
             'T/RH nol. Tidak ada cuaca manual pengganti. Snapshot API mempertahankan '
             'model ID, lokasi grid, elevasi, satuan, dan waktu pengambilan.', '',
             'Konfigurasi referensi yang **diasumsikan**, bukan metadata instrumen aktual: '
             'aperture 100 mm, pembesaran 50×, transmisi per permukaan 0,95, '
             '6 permukaan, obstruksi 0 mm, usia 22 tahun, F=1,8. '
             'Scan produksi memakai interval 1 menit, refinement 15 detik, mulai '
             '1 menit setelah sunset, dan altitude Bulan minimum 2°. '
             'Karena waktu percobaan aktual tidak diketahui, hasil adalah kesempatan '
             'visibilitas dalam scan model, bukan rekonstruksi kondisi saat laporan.', '',
             '| Fraksi area target | TP | TN | FP | FN | Kesepakatan seimbang | Interval bootstrap event 95% |',
             '| ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for evaluation in summary['area_fraction_comparisons']:
        metric = evaluation['cross_method_agreement']
        interval = evaluation['cluster_bootstrap']['balanced_accuracy_95pct']
        ci = f'{100*interval[0]:.1f}–{100*interval[1]:.1f}%' if interval else 'tidak tersedia'
        score = f'{100*metric["balanced_accuracy"]:.1f}%' if metric['balanced_accuracy'] is not None else 'tidak tersedia'
        lines.append(f'| {evaluation["area_fraction"]:g} | {metric["tp"]:g} | {metric["tn"]:g} | '
                     f'{metric["fp"]:g} | {metric["fn"]:g} | {score} | {ci} |')
    lines.extend(['', 'TP/TN/FP/FN di tabel hanya menggambarkan kesepakatan prediksi visual '
                  'dengan label CCD. Angka tersebut tidak mengukur sensitivitas/spesifisitas '
                  'visibilitas mata manusia. Interval bootstrap tanggal menggambarkan variasi '
                  'sampling pada dataset ini; ketidakpastian metode, instrumen, waktu, '
                  'awan/transparansi atmosfer, dan seleksi dataset tidak tercakup.', '',
                  'Bootstrap cluster tanggal mengasumsikan independensi antartanggal; '
                  'ia belum mengatasi korelasi dalam satu lunasi bila suatu dataset '
                  'memiliki lebih dari satu tanggal per lunasi. Dataset ini memiliki '
                  f'{summary["observation_dates"]} tanggal dan {summary["hijri_campaigns"]} campaign unik. Kalibrasi visual mendatang memakai '
                  'campaign/lunasi sebagai unit holdout bila metadata tersebut tersedia.', '',
                  'Fraksi area 1, 0,5, 0,25, 0,1 ditetapkan sebelum melihat hasil. '
                  'Luminansi lokal hilal dipertahankan; area yang lebih kecil mewakili '
                  'subset cahaya yang dicari, bukan pemampatan total flux ke area kecil. '
                  'Semua fraksi menggunakan scene scan/refinement yang sama, sehingga '
                  'ini pemeriksaan sensitivitas area pada scene tersebut, bukan pencarian '
                  'waktu optimal independen untuk setiap asumsi bentuk. Tidak ada fraksi '
                  'yang dipilih sebagai hasil kalibrasi produksi.', '',
                  'Kalibrasi visual yang disediakan dalam kode menolak CCD, imaging, '
                  'metode campuran, dan metode tak diketahui. Ia memerlukan label '
                  '`naked_eye` atau `visual_telescope` yang terverifikasi, bukti percobaan '
                  'visual, jendela waktu aktual, serta konfigurasi optik/pengamat aktual '
                  'untuk teleskop. Prediksi kalibrasi harus menggunakan jendela dan '
                  'konfigurasi tersebut. Holdout dilakukan per campaign/lunasi '
                  '(fallback per tanggal jika metadata campaign tidak tersedia); label '
                  'event yang diuji tidak masuk fitting. Satu F efektif hanya '
                  'mengidentifikasi koreksi gabungan; bentuk, luminansi, pengamat, '
                  'dan optik tidak dapat dipisahkan dari satu parameter tersebut.', '',
                  'Tes unit pada data sintetis memeriksa guard metode, domain statistik, '
                  'identitas perubahan F, dan isolasi holdout. Kelulusan tes tersebut '
                  'adalah verifikasi perangkat lunak, bukan validasi empiris hilal.', '',
                  'Berkas: `raw_inputs.json` (dataset dan atmosfer asli), `predictions.json` '
                  '(protokol, hash implementasi, indeks prediksi), '
                  '`case_predictions/*.json` (C_obj, C_th, margin, area, atmosfer dan '
                  'posisi untuk scene), `metrics.json`, dan `descriptive_predictions.csv`.', '',
                  'Jalankan ulang tanpa jaringan:', '', '```powershell',
                  '.venv\\Scripts\\python.exe -X utf8 scripts/compare_crumey_observations.py --replay validation/crumey_empirical/raw_inputs.json --output outputs/crumey_empirical_replay --workers 4',
                  '```', '', 'Sumber label BMKG: [Galeri BMKG](https://hilal.bmkg.go.id/gallery). '
                  'Identifikasi seluruh label sebagai CCD berasal dari konfirmasi pengguna '
                  'pada 2026-10-05; halaman galeri saat ini tidak mengautentikasi satu per satu '
                  '278 laporan historis dalam spreadsheet.', ''])
    if summary['failures']:
        lines.extend(['Kasus yang tidak menghasilkan prediksi:', '',
                      *[f'- #{item["observation_no"]} ({item["date"]}): {item["status"]}; {item["error"]}'
                        for item in summary['failures']], ''])
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT_DIR / 'crumey_empirical')
    parser.add_argument('--observations', type=Path, default=OBSERVATIONS_PATH)
    parser.add_argument('--source-workbook', type=Path,
                        default=Path(r'd:\bismillah call paper\data_keterlihatan_hilal_core.xlsx'))
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--capture-only', action='store_true')
    parser.add_argument('--analysis-only', action='store_true',
                        help='Rebuild descriptive reports from saved predictions; no numerical cache is silently adopted')
    parser.add_argument('--workers', type=int, default=4, help='Independent replay processes (1..8)')
    parser.add_argument('--limit', type=int, help='Development subset; never presented as complete validation')
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error('--workers must be in 1..8')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.analysis_only:
        projections = json.loads((args.output / 'predictions.json').read_text(encoding='utf-8'))
        projections['analysis_provenance'] = dict(
            evaluated_at_utc=datetime.now(timezone.utc).isoformat(),
            evaluator_source_sha256=sha256_file(__file__),
            runtime_package_versions=calculation_fingerprint()['package_versions'],
            python_version=sys.version,
            cache_note='Legacy numerical snapshots lacking schema-v2 calculation fingerprint remain valid historical artifacts but are not reused automatically by a new numerical replay.')
        write_json(args.output / 'predictions.json', projections)
        save_analysis(projections, args.output)
        return
    if args.replay:
        payload = json.loads(args.replay.read_text(encoding='utf-8'))
    else:
        cases = load_observations(args.observations)
        if args.limit:
            cases = cases[:args.limit]
        payload = capture_inputs(cases, args.output, args.observations, args.source_workbook)
    if args.capture_only:
        return
    projections = dict(schema_version=1, raw_inputs_sha256=sha256_file(args.replay or args.output / 'raw_inputs.json'),
                       source_sha256=source_hashes(),
                       calculation_fingerprint=calculation_fingerprint(),
                       evaluator_source_sha256=sha256_file(__file__),
                       projection_started_at_utc=datetime.now(timezone.utc).isoformat(),
                       protocol=dict(mode='optimal', observation_date='explicit dataset date',
                                     interval_minutes=1, refinement_seconds=15, min_moon_alt_deg=2.0,
                                     start_delay_minutes=1, F_ref=F_REF, telescope=TELESCOPE,
                                     area_fractions=list(AREA_FRACTIONS), label_method='ccd'),
                       cases=[])
    results = {}
    manifest = args.output / 'predictions.json'
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding='utf-8'))
        if all(previous.get(key) == projections[key] for key in ('raw_inputs_sha256', 'calculation_fingerprint', 'protocol')):
            if 'resume_provenance' in previous:
                projections['resume_provenance'] = previous['resume_provenance']
            results = {item['case']['observation_no']: item for item in previous['cases']
                       if item['status'] == 'complete'
                       and (args.output / item['scene_snapshot_file']).exists()}
    pending = [captured for captured in payload['cases'] if captured['case']['observation_no'] not in results]
    executor = ProcessPoolExecutor(max_workers=args.workers)
    try:
        futures = {executor.submit(predict_case, captured): captured for captured in pending}
        for future in as_completed(futures):
            captured = futures[future]
            result = future.result()
            number = captured['case']['observation_no']
            snapshot = Path('case_predictions') / f'{number:05d}.json'
            record = prediction_json_record(result)
            write_json(args.output / snapshot, record)
            index_entry = {key: value for key, value in record.items() if key != 'samples'}
            index_entry['scene_snapshot_file'] = snapshot.as_posix()
            index_entry['scene_samples'] = len(result['samples'])
            results[number] = index_entry
            projections['cases'] = [results[item['case']['observation_no']] for item in payload['cases']
                                     if item['case']['observation_no'] in results]
            write_json(manifest, projections)
            print(f'Prediction {len(results)}/{len(payload["cases"])}: '
                  f'#{number} {result["status"]} '
                  f'{result.get("margin_ref", result.get("error"))}', flush=True)
    except BaseException:
        # Export failure must not silently wait for every queued observation.
        if hasattr(executor, 'terminate_workers'):
            executor.terminate_workers()
        else:
            executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    projections['cases'] = [results[item['case']['observation_no']] for item in payload['cases']]
    write_json(manifest, projections)
    summary = save_analysis(projections, args.output)
    print(json.dumps({key: summary[key] for key in ('status', 'observations', 'complete', 'observation_dates', 'hijri_campaigns')}, indent=2))


if __name__ == '__main__':
    main()
