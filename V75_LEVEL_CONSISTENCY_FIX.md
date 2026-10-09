# v75 Demo Ready — Student Level Consistency Fix

Display-only fix: Admin timetable / Today, admin bookings, instructor timetable, instructor lesson and group participant cards now compute Beginner/Kiter directly from the same 18 curriculum skills used by the profile. No destructive migration or bulk update. Legacy `students.level` is untouched.

Demo data and v75 protections are retained. This archive intentionally excludes local database/cache files. Deploy through existing GitHub / Railway flow.

Important: this patch does not make existing higher levels from `students.level` authoritative; all 18 Beginner skills must be mastered for Kiter.
