# v76.7.17.23 · Admin Students View

Based on published v76.7.17.22. User approved publication on 18 October 2026. No data migration or production test mutations.

- Compact student cards on mobile and desktop: initials, full name/profile, code, current level, lesson type, email and available credits.
- Neutral zero-credit badges, green positive and red negative balances.
- Search name/code/email/phone, accent-insensitive, combined with All / With credits / Without credits filters. Without credits includes non-positive balances.
- Five matching students per page, accurate result count, disabled page arrows and empty state.
- Profile links use the existing student profile. Credit dialog posts the original amount/note/CSRF to the selected student's existing adjustment endpoint. Opening another student resets the unsaved inputs; closing never saves.
- New-student form moved to a dialog while retaining existing fields and backend endpoint; no change to package values or signup behavior.
- Admin mobile timetable and removal of Day Management card from .22 retained.

QA: isolated real Admin HTML/render/no-business-write check, jsdom interactions for search/filters/pagination/empty state/credit target/CSRF/reset/create/close; mobile schedule DOM regression; completion and logout regressions. No real emails. Full browser visual/layout verification remains pending because the runtime cannot launch the browser; please check on mobile and desktop locally.
