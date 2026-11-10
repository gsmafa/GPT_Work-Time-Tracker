import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
class V21Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();app.DB=Path(self.tmp.name)/'db.sqlite3';app.init_db()
 def tearDown(self):self.tmp.cleanup()
 def test_names_ru_en(self):
  e=app.add_employee('Инна Соколова',source='ru');self.assertEqual(app.employees()[0]['name_en'],'Inna Sokolova')
  app.add_employee('Anna Petrova',source='en');self.assertTrue(app.employees()[1]['name'].startswith('Анна'))
 def test_translation_and_restart(self):
  with patch.object(app,'translate_text',return_value='Preparing a report') as tr:
   e=app.add_employee('Инна Соколова',source='ru');app.start_timer(e['id'],'Подготовка отчёта',source='ru')
   self.assertEqual(tr.call_count,1)
  app.init_db();self.assertEqual(app.employees()[0]['active_task_en'],'Preparing a report')
 def test_repeat_timer_and_empty_report(self):
  with patch.object(app,'translate_text',return_value='Report'):
   e=app.add_employee('Инна Соколова',source='ru');self.assertEqual(app.report('2020-01-01','2020-01-02')['employees'][0]['entries'],[])
   app.start_timer(e['id'],'Отчёт',source='ru')
   with self.assertRaises(RuntimeError):app.start_timer(e['id'],'Отчёт',source='ru')
   app.stop_timer(e['id'])
 def test_translation_failure_no_partial_entry(self):
  e=app.add_employee('Инна Соколова',source='ru')
  with patch.object(app,'translate_text',side_effect=ValueError('offline')):
   with self.assertRaises(ValueError):app.start_timer(e['id'],'Отчёт',source='ru')
  self.assertIsNone(app.employees()[0]['active_id'])
 def test_legacy_migration(self):
  e=app.add_employee('Инна Соколова',source='ru')
  with app.connect() as db:db.execute('INSERT INTO entries(employee_id,task,started_at,ended_at) VALUES(?,?,?,?)',(e['id'],'Старая задача','2026-11-09T10:00:00+00:00','2026-11-09T10:01:00+00:00'))
  app.init_db();self.assertEqual(app.report('2026-11-09','2026-11-09')['employees'][0]['total_seconds'],60)
if __name__=='__main__':unittest.main()
