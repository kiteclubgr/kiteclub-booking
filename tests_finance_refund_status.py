import unittest
from types import SimpleNamespace
from jinja2 import Environment

from pathlib import Path
SOURCE = (Path(__file__).parent / 'templates' / 'admin_finance.html').read_text()
START = SOURCE.index('{% set refund = stripe_refund_info(r.id) %}')
STATUS = SOURCE[START:SOURCE.index('</span>', START)+len('</span>')]

class FinanceRefundStatusTest(unittest.TestCase):
    def test_status_labels(self):
        template = Environment(autoescape=True).from_string(STATUS)
        for status, refund, expected in [
            ('paid', {'full': True}, 'Επιστράφηκε'),
            ('paid', {'full': False}, 'Μερική επιστροφή'),
            ('paid', None, 'Paid'),
            ('pending', None, 'Pending'),
            ('cancelled', None, 'Ακυρωμένο'),
        ]:
            with self.subTest(status=status, refund=refund):
                result = template.render(r=SimpleNamespace(id=7, payment_status=status), stripe_refund_info=lambda purchase_id: refund)
                self.assertIn('>'+expected+'</span>', result)
                if refund:
                    self.assertNotIn('>Paid</span>', result)

if __name__ == '__main__':
    unittest.main()
