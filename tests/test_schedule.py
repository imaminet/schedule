import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_market_data as morning
import verify_and_learn as evening
import settings


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / '.github/scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context = script('select_context')
finder = script('find_morning_artifact')


def prices(dates, closes=None):
    values = closes or [100.0] * len(dates)
    return pd.DataFrame({key: values for key in ('Open', 'High', 'Low', 'Close')},
                        index=pd.DatetimeIndex(dates, tz='Asia/Tokyo'))


class ScheduleTests(unittest.TestCase):
    def test_delayed_runs_preserve_target_date(self):
        cases = [
            ('30 22 * * 0-4', '2026-10-08T22:30:00Z', 'morning', '2026-10-09'),
            ('30 22 * * 0-4', '2026-10-09T02:27:00Z', 'morning', '2026-10-09'),
            ('0 8 * * 1-5', '2026-10-09T08:00:00Z', 'evening', '2026-10-09'),
            ('0 8 * * 1-5', '2026-10-09T15:00:00Z', 'evening', '2026-10-09'),
            ('30 22 * * 0-4', '2026-10-11T22:30:00Z', 'morning', '2026-10-12'),
        ]
        for schedule, created, mode, target in cases:
            with self.subTest(created=created):
                self.assertEqual(context.select_context('schedule', schedule, '', '', created), (mode, target))

    def test_manual_historical_evening(self):
        self.assertEqual(context.select_context('workflow_dispatch', '', 'evening', '2026-10-09',
                                               '2026-10-09T19:00:00Z'), ('evening', '2026-10-09'))

    def test_bad_context_rejected(self):
        for date in ('2026-10-11', '2026-2-3', 'bad'):
            with self.subTest(date=date), self.assertRaises(ValueError):
                context.select_context('workflow_dispatch', '', 'evening', date, '2026-10-09T19:00:00Z')
        with self.assertRaises(ValueError):
            context.select_context('schedule', 'unexpected', '', '', '2026-10-09T15:00:00Z')

    def test_select_context_writes_shared_target(self):
        response = Mock()
        response.json.return_value = {'created_at': '2026-10-09T15:00:00Z'}
        with tempfile.TemporaryDirectory() as tmp:
            env = {'GITHUB_EVENT_NAME': 'schedule', 'SCHEDULE': '0 8 * * 1-5',
                   'GITHUB_REPOSITORY': 'imaminet/schedule', 'GITHUB_RUN_ID': '5',
                   'GITHUB_TOKEN': 'test', 'GITHUB_OUTPUT': tmp+'/out', 'GITHUB_ENV': tmp+'/env'}
            with patch.dict(os.environ, env), patch.object(context.requests, 'get', return_value=response):
                context.main()
            self.assertIn('date=2026-10-09', Path(tmp+'/out').read_text())
            self.assertEqual(Path(tmp+'/env').read_text(), 'TARGET_DATE_JST=2026-10-09\n')

    def test_finder_uses_frozen_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {'TARGET_DATE_JST': '2026-10-09', 'GITHUB_REPOSITORY': 'imaminet/schedule',
                   'GITHUB_TOKEN': 'test', 'GITHUB_REF_NAME': 'main', 'GITHUB_OUTPUT': tmp+'/out'}
            with patch.dict(os.environ, env), patch.object(finder, 'find_run', return_value=4) as find:
                finder.main()
            self.assertEqual(find.call_args.args[2], 'morning-2026-10-09')

    def test_missing_morning_stops(self):
        response = Mock()
        response.json.return_value = {'artifacts': []}
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(RuntimeError, 'No successful morning-2026-10-09'):
            finder.find_run(session, 'api', 'morning-2026-10-09', 'main')

    def test_history_uses_target_not_latest(self):
        ticker = Mock()
        ticker.history.return_value = prices(['2026-10-08', '2026-10-09', '2026-10-12'], [100, 110, 999])
        with patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}):
            h = evening.history_for_target(ticker)
        self.assertEqual(h['Close'].iloc[-1], 110)
        self.assertEqual(ticker.history.call_args.kwargs['end'], '2026-10-10')

    def test_missing_or_invalid_target_prices_stop(self):
        for frame in (prices(['2026-10-07', '2026-10-08']),
                      prices(['2026-10-08', '2026-10-09'], [100, float('nan')])):
            with self.subTest(frame=frame), patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}):
                with self.assertRaises(RuntimeError):
                    evening.history_for_target(SimpleNamespace(history=lambda **kwargs: frame))

    def test_us_data_missing_stops(self):
        ticker = Mock()
        ticker.history.return_value = prices([])
        with patch.object(morning.yf, 'Ticker', return_value=ticker), self.assertRaises(RuntimeError):
            morning.get_us_market_data()

    def test_stock_failure_stops_before_review(self):
        summary = {'japan_market': {'stop_high_stocks': [{'code': '6323', 'market': '東P'}]}}
        with patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}), \
             patch.object(evening, 'history_for_target', side_effect=[prices(['2026-10-08', '2026-10-09']), RuntimeError('missing')]):
            with self.assertRaisesRegex(RuntimeError, 'stock data unavailable'):
                evening.fetch_evening_actual_results(summary)

    def test_metadata_mismatch_stops_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'morning_context.json').write_text(json.dumps({'date_jst': '2026-10-08'}))
            with patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}), \
                 patch.object(evening, 'BASE_DIR', Path(tmp)), patch.object(evening, 'require_settings'), \
                 patch.object(evening, 'DIFY_APP_API_KEY', 'test'), patch.object(sys, 'argv', ['verify', '--non-interactive']), \
                 patch.object(evening, 'upload_learning_to_dify') as upload:
                with self.assertRaisesRegex(RuntimeError, 'target date'):
                    evening.main()
                upload.assert_not_called()

    def test_report_survives_upload_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'morning_context.json').write_text(json.dumps({'date_jst': '2026-10-09'}))
            with patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}), \
                 patch.object(evening, 'BASE_DIR', Path(tmp)), patch.object(evening, 'require_settings'), \
                 patch.object(evening, 'DIFY_APP_API_KEY', 'test'), patch.object(sys, 'argv', ['verify', '--non-interactive']), \
                 patch.object(evening, 'load_morning_context', return_value=('brief', {'target_date_jst': '2026-10-09'})), \
                 patch.object(evening, 'fetch_evening_actual_results', return_value={}), \
                 patch.object(evening, 'generate_review_with_llm', return_value='review'), \
                 patch.object(evening, 'upload_learning_to_dify', side_effect=RuntimeError('upload')):
                with self.assertRaisesRegex(RuntimeError, 'upload'):
                    evening.main()
                self.assertIn('2026-10-09', Path(tmp, 'evening_review_2026-10-09.md').read_text())

    def test_stop_high_dates_and_explicit_empty(self):
        html = '<h1>ストップ高銘柄</h1>株価：2026年10月9日 11:12現在<table><thead><a href="?order=stock_code">コード</a></thead><tbody><tr><td>該当銘柄はありません</td></tr></tbody></table>'
        with patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}):
            self.assertEqual(morning.parse_japan_stop_high(html)['stop_high_count'], 0)
            for bad in (html.replace('10月9日', '10月10日'), html.replace('10月9日', '9月1日'), html.replace('該当銘柄はありません', '')):
                with self.assertRaises(RuntimeError):
                    morning.parse_japan_stop_high(bad)

    def test_stale_prior_session_rejected(self):
        response = Mock(text='html')
        ticker = Mock()
        ticker.history.return_value = prices(['2026-10-08'])
        with patch.dict(os.environ, {'TARGET_DATE_JST': '2026-10-09'}), \
             patch.object(morning.requests, 'get', return_value=response), \
             patch.object(morning, 'parse_japan_stop_high', return_value={'data_period': 'prior_session', 'source_date_jst': '2026-10-07'}), \
             patch.object(morning.yf, 'Ticker', return_value=ticker), self.assertRaisesRegex(RuntimeError, 'prior trading session'):
            morning.get_japan_stop_high()


if __name__ == '__main__':
    unittest.main()
