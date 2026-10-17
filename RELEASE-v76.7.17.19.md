# v76.7.17.19 · Group Completion Fix

Based on main v76.7.17.18. Publication approved after user local testing on 17 October 2026.

- Group completion: per-student Level 1–4, curriculum techniques and progress state, matching the existing backend field names.
- Validation failures re-render without redirect, retaining attendance, actual duration, techniques, progress and escaped notes. Rollback remains before rendering.
- Make-up and No-show do not require curriculum selections.
- Expanded notes fields and Greek completion label.
- Instructor sidebar logout moved ahead of decorative footer; existing POST/CSRF retained.

Validation: tests_group_completion_form.py (2P/3P, no-write validation failure, retained fields, 1.5h reconciliation, mixed attendance, single instructor count and replay); tests_merge_after_edit.py; tests_mobile_logout.py; tests_reports_hours.py. All passed in temporary databases; completion emails stubbed in new tests. No production data changed.

User local testing reported functional success. Agent automated browser visual QA was unavailable; full desktop/mobile regression remains pending. No blanket stable certification.
