import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')

class DashboardUITests(unittest.TestCase):
    def test_theme_persistence(self):
        self.assertIn("localStorage.setItem('worktime_theme',theme)", HTML)
        self.assertIn('data-theme="light"', HTML)
    def test_dashboard_and_charts(self):
        for item in ['id="dashboard"', 'id="weeklyChart"', 'id="employeeChart"', 'id="metricActive"']:
            self.assertIn(item, HTML)
    def test_two_language_ui_and_existing_modal(self):
        self.assertIn('English', HTML)
        self.assertIn('Русский', HTML)
        self.assertIn('id="confirmOverlay"', HTML)
        self.assertIn('askDelete(', HTML)
