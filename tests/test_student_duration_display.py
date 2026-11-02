"""Regression checks for scheduled vs actual lesson duration in student views."""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment()


def render_duration(template_name, context, anchor):
    source = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
    line = next(line for line in source.splitlines() if anchor in line)
    expression = re.search(r"{{\s*([^}]*actual_duration[^}]*)\s*}}", line)
    assert expression, f"Missing actual-duration expression in {template_name}"
    return ENV.from_string("{{ " + expression.group(1) + " }}").render(**context)


class StudentActualDurationDisplayTests(unittest.TestCase):
    def test_completed_history_shows_actual_duration(self):
        b = SimpleNamespace(duration=2.0, actual_duration=1.5, status="completed")
        self.assertEqual(render_duration("student_profile.html", {"b": b}, "Ιστορικό ολοκληρωμένων"), "1.5")

    def test_completed_history_falls_back_if_actual_missing(self):
        b = SimpleNamespace(duration=2.0, actual_duration=None, status="completed")
        self.assertEqual(render_duration("student_profile.html", {"b": b}, "Ιστορικό ολοκληρωμένων"), "2")

    def test_booking_list_completed_shows_actual_but_upcoming_scheduled(self):
        b = SimpleNamespace(duration=2.0, actual_duration=1.5, status="completed")
        self.assertEqual(render_duration("student.html", {"b": b}, "b.spot"), "1.5")
        b.status = "confirmed"
        self.assertEqual(render_duration("student.html", {"b": b}, "b.spot"), "2")


if __name__ == "__main__":
    unittest.main()
