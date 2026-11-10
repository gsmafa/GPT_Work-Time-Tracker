import unittest
from pathlib import Path
HTML=(Path(__file__).resolve().parents[1]/'static'/'index.html').read_text(encoding='utf-8')
class SpaUITests(unittest.TestCase):
 def test_four_views_and_no_anchor_navigation(self):
  for view in ('dashboard','staff','timers','reports'):
   self.assertIn('data-view="'+view+'"',HTML)
   self.assertIn('data-view-panel="'+view+'"',HTML)
   self.assertNotIn('href="#'+view+'"',HTML)
 def test_only_one_panel_visible_by_default(self):
  self.assertIn('id="dashboard" class="app-view"',HTML)
  for view in ('staff','timers','reports'):
   self.assertRegex(HTML,r'id="'+view+r'"[^>]* hidden>')
 def test_spa_switcher_and_translation(self):
  self.assertIn('function showView(view,focus=false)',HTML)
  self.assertIn('showView(currentView)',HTML)
  self.assertIn('aria-current',HTML)
 def test_warm_sand_theme_and_storage(self):
  self.assertIn('--bg:#f7f2ea',HTML)
  self.assertIn('--bg:#302b2a',HTML)
  self.assertIn("localStorage.setItem('worktime_theme',theme)",HTML)
 def test_compatibility_controls(self):
  for item in ('id="confirmOverlay"','id="weeklyChart"','id="employeeChart"','id="lang"','id="export"'):
   self.assertIn(item,HTML)
