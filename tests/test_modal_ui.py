import unittest
from pathlib import Path

class ModalUiTests(unittest.TestCase):
    def test_centered_modal_and_bilingual_labels(self):
        html = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('place-items:center', html)
        self.assertIn('role="alertdialog"', html)
        self.assertIn("confirmTitle:'Подтвердите удаление'", html)
        self.assertIn("confirmTitle:'Confirm deletion'", html)
        self.assertIn("askDelete('person'", html)
        self.assertIn("askDelete('entry'", html)
        self.assertNotIn('if(!confirm(', html)

if __name__ == '__main__': unittest.main()
