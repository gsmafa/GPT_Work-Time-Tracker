import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class WorktimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DB = Path(self.tmp.name) / 'test.sqlite3'
        app.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_persist(self):
        e = app.add_employee('Анна Соколова', 'Анна Соколова', 'Анна Соколова')
        self.assertEqual(app.employees()[0]['name'], e['name'])
        app.init_db()  # same database reopened, no data loss
        self.assertEqual(len(app.employees()), 1)

    def test_start_stop_and_repeat(self):
        e = app.add_employee('Иван Петров', 'Иван Петров', 'Иван Петров')
        app.start_timer(e['id'], 'Дизайн макета', 'Дизайн макета', 'Дизайн макета')
        with self.assertRaisesRegex(RuntimeError, 'already running'):
            app.start_timer(e['id'], 'Другая задача', 'Другая задача', 'Другая задача')
        self.assertIsNotNone(app.employees()[0]['active_id'])
        app.stop_timer(e['id'])
        self.assertIsNone(app.employees()[0]['active_id'])
        with self.assertRaisesRegex(RuntimeError, 'No running'):
            app.stop_timer(e['id'])
        app.start_timer(e['id'], 'Новая задача', 'Новая задача', 'Новая задача')
        self.assertIsNotNone(app.employees()[0]['active_id'])

    def test_empty_report(self):
        app.add_employee('Мария Орлова', 'Мария Орлова', 'Мария Орлова')
        r = app.report('2020-01-01', '2020-01-31')
        self.assertEqual(r['employees'][0]['entries'], [])
        self.assertEqual(r['employees'][0]['total_seconds'], 0)

    def test_report_overlap_and_totals(self):
        e = app.add_employee('Олег Смирнов', 'Олег Смирнов', 'Олег Смирнов')
        with app.connect() as db:
            db.execute('INSERT INTO entries(employee_id,task,started_at,ended_at) VALUES(?,?,?,?)',
                (e['id'], 'Тест', '2026-01-01T23:00:00+00:00', '2026-01-02T02:00:00+00:00'))
        r = app.report('2026-01-02', '2026-01-02')
        self.assertEqual(r['employees'][0]['total_seconds'], 10800)
        self.assertEqual(len(r['employees'][0]['entries']), 1)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError): app.add_employee('  ', '  ', '  ')
        e = app.add_employee('Тест', 'Тест', 'Тест')
        with self.assertRaises(ValueError): app.start_timer(e['id'], '')
        with self.assertRaises(ValueError): app.report('2026-02-02', '2026-02-01')
        with self.assertRaises(LookupError): app.start_timer(9999, 'Задача', 'Задача', 'Задача')

    def test_bilingual_values_and_migration(self):
        e = app.add_employee('Анна Соколова', 'Anna Sokolova')
        self.assertEqual(app.employees()[0]['name_en'], 'Anna Sokolova')
        app.start_timer(e['id'], 'Отчёт', 'Report')
        self.assertEqual(app.employees()[0]['active_task_en'], 'Report')
        app.stop_timer(e['id'])
        with app.connect() as db:
            row = db.execute('SELECT task_en FROM entries').fetchone()
        self.assertEqual(row['task_en'], 'Report')
        app.init_db()
        self.assertEqual(app.employees()[0]['name_en'], 'Anna Sokolova')

    def test_running_timer_persists(self):
        e = app.add_employee('Наталья Белова', 'Наталья Белова', 'Наталья Белова')
        app.start_timer(e['id'], 'Подготовка отчёта', 'Подготовка отчёта', 'Подготовка отчёта')
        with app.connect() as db:
            db.execute('UPDATE entries SET started_at=? WHERE employee_id=?', ((datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat(), e['id']))
        app.init_db()
        self.assertEqual(app.employees()[0]['active_task'], 'Подготовка отчёта')
        today = datetime.now(timezone(timedelta(hours=5))).date().isoformat()
        self.assertEqual(len(app.report(today, today)['employees'][0]['entries']), 1)

if __name__ == '__main__': unittest.main()
