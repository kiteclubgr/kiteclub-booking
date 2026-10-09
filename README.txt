KiteClub Booking v59
- Instructor Financial / Reports redesign with period filter, weekly hours, lesson breakdown, earnings, paid/balance, lessons and payment history tabs.
- Admin student list remains alphabetical by first name and now has live search by name, surname, Student ID, email or phone.
- Student profile polish: inactive Crew card is neutral grey and redundant top Edit button removed.


KITECLUB BOOKING MVP
====================

Τι περιλαμβάνει
---------------
- 3 ρόλοι: Admin / Student / Instructor
- Credits μαθητών
- 1h ή 2h συνεχόμενη κράτηση
- Pending payment για μαθητές χωρίς credits
- Manual "Payment Received" από admin
- Instructor timetable + automatic standby activation based on booked-hour threshold
- Completion μαθημάτων
- Καταγραφή instructor hours
- Follow-up skill επιλογή
- SMTP hooks για confirmation/follow-up emails
- SQLite database για άμεσο local test

Local setup
-----------
1. Εγκατάσταση Python 3.11+
2. Άνοιξε terminal μέσα στον φάκελο
3. python -m venv .venv
4. Windows: .venv\Scripts\activate
   macOS/Linux: source .venv/bin/activate
5. pip install -r requirements.txt
6. python app.py
7. Άνοιξε http://127.0.0.1:5000

Demo users
----------
Admin: admin@kiteclub.gr / admin123
Student: student@kiteclub.gr / student123
Instructor: angelos@kiteclub.gr / teacher123

Production checklist
--------------------
- Replace SQLite with PostgreSQL/Supabase
- Set a strong SECRET_KEY
- Connect SMTP or transactional email service
- Add password reset / magic links
- Configure SSL + book.kiteclub.gr
- Add real payment-provider payment links
- Add GDPR/privacy text and retention policy
- Backups and audit log
- Replace placeholder YouTube skill URLs with KiteClub training videos

SMTP environment variables
--------------------------
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=booking@kiteclub.gr
SECRET_KEY=


Railway test deployment
-----------------------
1. Upload this project to a GitHub repository.
2. In Railway choose New Project > Deploy from GitHub repo.
3. Select the repository.
4. Start command: gunicorn app:app
5. Add SECRET_KEY in Variables.
6. Generate a public domain under Settings > Networking.

IMPORTANT:
This MVP currently uses SQLite. It is suitable for functional testing only.
For persistent shared testing/production, migrate to PostgreSQL before relying on stored bookings.

V3: Admin timetable changed to grid (times x instructors) with inline slot status controls.

V3.1: Fixed timetable sticky header so the 11:00 row is fully visible.

V4:
- Day schedule is generated from start/end time.
- Each generated hour has instructor dropdown.
- Only instructors not already assigned to that hour appear in the dropdown.
- Multiple instructors can be added to the same hour.

V5:
- Admin grid uses logical Slot 1 / Slot 2 / Slot 3 columns.
- Instructor is selected once in the column header.
- Selecting an instructor creates open slots for all generated hours that day.
- Leaving a column unassigned keeps all its cells empty.

V6:
- Manual slot state control: Available / Closed / Pending payment.
- Manual Pending payment blocks the slot from student booking.
- Same instructor cannot be selected in two logical Slot columns on the same day.

V7:
- Added manual Booked state.
- Closed now explicitly means instructor unavailable (late arrival, early departure, or break).
- Available / Booked / Pending payment / Closed are separate operational states.

V8:
- All displayed dates use DD/MM/YYYY.
- All displayed times use 24-hour HH:MM.
- Database keeps ISO dates internally for reliability.

V9:
- Fixes legacy duplicate instructor assignments across Slot columns.
- Instructor dropdown hides instructors already used in another column.
- Status selector is always visible inside open/manual-status cells.
- Legend includes Closed.

V10:
- Replaces browser-native date/time controls in Admin with locale-independent controls.
- Visible date input is always DD/MM/YYYY.
- Time selection is always 24-hour HH:MM (30-minute increments), with no AM/PM.

V11:
- Adds weekly calendar above Add Slots.
- Each day shows only its assigned spot.
- Clicking a day opens its management view.
- Exactly one spot is allowed per date.
- Changing a day's spot updates all generated hours and slots for that date.

V12:
- Student weekly calendar reads the admin schedule.
- Only days with an assigned spot and open slots are actionable.
- Each day shows its single spot and current number of available slots.
- Student selected-day list shows only open/bookable slots.
- Closed, Booked and Pending-payment slots are hidden from student booking.

V13:
- Student view restored to the agreed mobile-first timetable design.
- Weekly calendar above timetable.
- Hours on the left, instructors as columns.
- 1h / 2h duration toggle.
- Consecutive 2-hour selection requires same instructor and both slots open.
- Selection confirmation sheet before booking.
- Own bookings shown separately from unavailable slots.

V14:
- Admin slot status is now the canonical status source for the student grid.
- Student view maps Available / Booked / Pending payment / Closed consistently.
- Active booking rows are restricted to confirmed, pending-payment and completed states.

V15:
- Fixes legacy standby/open mismatch between Admin and Student.
- Selecting an instructor in a day column converts legacy standby slots to open.
- Explicit manual Closed / Booked / Pending payment statuses are preserved.
- Admin and Student now read the same actual slot state.

V16:
- Student view now runs the same rebalance/activation logic as Admin.
- Standby instructors are not bookable by students.
- When threshold/manual activation opens them, student availability updates consistently.

V17:
- Manual instructor selection now always means ACTIVE / Available.
- Rebalance no longer pushes manually selected instructors back to Standby.
- Closed / Booked / Pending payment remain preserved per hour.
- Admin instructor cards show ACTIVE only when that instructor is selected in a day column.

V18:
- Added booking_slots relation so one booking can own multiple hourly slots.
- Two-hour booking now marks both consecutive slots as the student's booking.
- Legacy 2-hour bookings are backfilled automatically on startup.
- Admin and Student both resolve booking ownership through booking_slots.

V19:
- Fixes Student view for 2-hour bookings.
- Student slot ownership now always resolves through booking_slots.
- Existing legacy 2-hour bookings self-repair when Admin/Student opens the date.
- Both occupied hours of the student's booking render as "Η κράτησή μου".

V20:
- Fixes duplicate SQL column name in Student multi-slot booking lookup.
- booking_slots.slot_id is now aliased as occupied_slot_id.
- Both hours of a 2-hour booking render as "Η κράτησή μου".

V21:
- Student cancellation allowed until 6 hours before lesson start.
- On valid cancellation, all booking slots reopen.
- Credits are automatically refunded for confirmed credit bookings.
- Credit ledger records the refund.
- Cancellation is blocked inside the 6-hour window.

V22:
- Instructor weekly dashboard with selected-day lessons.
- Instructor sees only their own bookings.
- Completed action records booking completion and instructor hours.
- Hour recording is idempotent: the same booking cannot be counted twice.
- Daily completed hours and lifetime completed hours are shown.
- Existing follow-up skill/email workflow is preserved.

V23:
- Instructor UI redesigned to closely match approved mockup.
- Full lessons table with student, level, duration, spot, status, actions, next skill.
- Daily activity metrics.
- Weekly completed-hours summary table.

V24:
- day_spots is now the canonical source for a date's spot.
- Student booking history uses the canonical day spot.
- Instructor bookings use the canonical day spot.
- Opening Admin/Student/Instructor automatically synchronizes all slots/day_hours to the day's selected spot.

V25:
- Added Admin Instructor Report.
- Weekly completed lessons and hours per instructor.
- Daily breakdown Monday-Sunday.
- Calculates total pay using each instructor's hourly_rate.

V26: Student and Instructor profiles; compact Admin Instructor Report.

V27:
- Admin reorganized into 3 tabs:
  1. Διαχείριση ημέρας
  2. Διαχείριση instructors
  3. Διαχείριση μαθητών
- Existing functionality is unchanged; sections are only reorganized.
- Active Admin tab is remembered locally in the browser across page reloads.

V28:
- Instructor management added to Admin > Διαχείριση instructors.
- Admin can add instructors with name, email, phone, password, hourly rate and threshold.
- Admin can remove instructors.
- Removal is blocked if the instructor has future confirmed/pending lessons.
- Historical completed data is preserved when removing old instructors.

V29:
- Fixed Admin > Add Instructor database error.
- New instructor passwords are now stored correctly in users.password_hash.
- New instructors can log in with the password entered by Admin.

V30:
- Admin instructor cards now open a dedicated Instructor Profile/Edit screen.
- Admin student entries can open a dedicated Student Profile/Edit screen.
- Added profile photo upload (JPG/PNG/WEBP) for instructors and students.
- Instructor profile supports editing name, email, phone, password, hourly rate and threshold.
- Student profile supports editing name, email, phone, password and level.
- Photos are stored under static/uploads and are ready to be reused in the future booking UI.

V31:
- Fixed Admin page crash caused by student profile link using s.user_id.
- Student profile links now use the correct student/user id exposed by the Admin query.

V32:
- Fixed profile photo upload NameError by importing pathlib.Path.

V33:
- Instructor admin profile now includes surname and IG account.
- Added bookings report and completed lessons report.
- Added total completed hours and total earned money.
- Added instructor payments ledger with amount/date/note.
- Outstanding balance is calculated as earned money minus recorded payments.

V34:
- Fixed literal \n text appearing throughout Admin Instructor Profile.
- Instructor financials, bookings report, completed report and payment history remain unchanged.

V35:
- Student Admin Profile upgraded to match the Instructor Profile structure.
- Added surname and Instagram fields.
- Added photo/profile editing.
- Added total booked hours and completed hours.
- Added all-bookings report and completed-lessons report.
- Added credit history with additions, reservations and refunds.
- Added credit adjustment form directly in the student profile.

V36:
- Student booking page redesigned to match the approved mobile-first mockup.
- Added instructor profile photos to booking column headers and confirmation sheet.
- Added compact week/date selector and selected spot info.
- Added student summary card with profile photo and credit balance.
- Added responsive booking grid and mobile bottom navigation.
- Added booking confirmation bottom sheet with instructor/photo/date/time/spot/duration/credit impact.
- Existing 1h/2h booking, cancellation and credit logic preserved.

V37:
- Mobile booking UI polish based on approved before/after mockup.
- Replaced device-dependent calendar emoji with a consistent CSS calendar icon.
- Compact weekly day cards so more days are visible on mobile.
- Narrower sticky time column.
- Smaller instructor avatars/headers and tighter timetable spacing.
- Reduced mobile booking-table width to expose more instructor columns at once.
- Existing booking, 1h/2h, credits, cancellation and confirmation logic unchanged.

V39 — Instructor Mobile Dashboard
- New mobile-first Instructor daily schedule with week selector, lesson cards and daily/weekly hour/pay summary.
- New Instructor > Students screen with search and student history.
- New lesson detail screen with student photo, phone, spot, duration and previous completed lessons.
- New lesson completion screen with next technique and instructor notes.
- Instructor notes are stored on completed bookings.
- Instructor profile redesigned for mobile with today/week/month lessons, hours and estimated pay.
- Mobile bottom navigation: Πρόγραμμα / Μαθητές / Προφίλ.
- Official KiteClub logo from v38 retained.

V40:
- Sequential instructor activation follows Admin Slot column order.
- First selected instructor is ACTIVE immediately.
- Slot 2 opens after Slot 1 reaches 4 booked/reserved hours; Slot 3 opens after Slot 2 reaches its threshold.
- 2-hour bookings count as 2 booked hours.
- Confirmed, pending-payment and completed bookings count toward the threshold.
- Manual Booked/Pending slots also count if they are not linked to a booking.
- Manual Available/Closed/Booked/Pending overrides are preserved.
- Cancellation recalculates the cascade immediately.
- Admin shows ACTIVE/STANDBY and booked-hour progress for each daily column.


V41:
- Standby slots are now editable directly by Admin.
- Admin can change Standby to Available, Closed, Pending payment or Booked before activation.
- Only slots that remain in automatic Standby are opened when the previous instructor reaches 4 booked hours.
- Manual Admin choices remain unchanged after the instructor column activates.
- Choosing Standby (auto) returns a slot to automatic cascade management.

V42:
- Added per-day Manual Activate / Manual Standby controls for Slot 2 and Slot 3.
- Auto mode still follows the 4 booked-hour cascade from the previous instructor.
- Automatic activation is now sticky: once a later instructor opens automatically, a later cancellation on the previous instructor does not close them again.
- Existing bookings are never closed by Manual Standby.
- Existing per-hour Admin overrides (Available / Closed / Pending payment / Booked) remain untouched.
- Admin header shows booked-hour progress, remaining hours, current activation mode and AUTO LOCKED state.
- Changing the instructor assigned to a Slot resets that column's activation override/history for the selected day.

v43 — No-show
- Instructor can mark a confirmed lesson as No-show / Δεν προσήλθε.
- No-show does not refund student credits; reserved hours remain charged.
- No-show stays blocked in the schedule and continues to count as booked hours for sequential instructor activation.
- Student/Admin/Instructor views show No-show separately from Completed and Cancelled.
- No-show is not added to instructor completed-hours/pay totals.

V44 — Admin Today Dashboard
---------------------------
- Νέα αρχική οθόνη Admin «Σήμερα» με σύνοψη μαθητών, booked ωρών, completed, pending, no-show και cancelled.
- Νέα κάρτα κατάστασης instructors με ACTIVE / STANDBY και πρόοδο προς το 4h threshold.
- «Μαθήματα Σήμερα» σε timetable: instructors στις επάνω στήλες, ώρες στη δεξιά πλευρά και οι κρατήσεις μέσα στα cells.
- Οι κρατήσεις εμφανίζουν μαθητή, επίπεδο, διάρκεια και status.
- Νέο desktop admin sidebar με Σήμερα / Ημερολόγιο / Μαθητές / Instructors και responsive mobile navigation.
- Η προηγούμενη Διαχείριση Ημέρας και όλη η v43 λειτουργικότητα παραμένουν διαθέσιμες.

v45 changes
-----------
- Admin Today dashboard visual polish: full-width layout, larger counters, instructor cards/photos, clearer booking cards.
- Student and instructor surnames are shown together with first names in the main booking/admin views.
- Admin manual Booked now opens a searchable student picker and creates a real booking linked to that student.
- If the selected student has at least 1 package hour, 1 hour is deducted automatically; otherwise the booking becomes Pending payment.

V46 — Admin Edit / Move / Cancel Booking
- Click "Επεξεργασία" on an active Booked / Pending booking in Admin Today or Ημερολόγιο.
- Admin can search/change student, change instructor, start time, duration (1h/2h), and Booked/Pending state.
- Destination hours are checked for conflicts; 2h requires two consecutive slots with the same instructor.
- Package credits are refunded/recharged automatically when student/duration/payment state changes.
- Admin cancellation has no 6-hour restriction and refunds package credit when the booking used package hours.
- Completed and No-show lessons stay locked in history and cannot be moved accidentally.

V47 — Stability rules + demo students
--------------------------------------
- Prevents the same student from having two active lessons at the same date/time, even with different instructors.
- Prevents duplicate instructor lessons at the same date/time, including protection against duplicate timetable rows.
- Admin move/edit keeps Completed and No-show locked and refuses moves onto occupied times.
- Existing credit checks remain in place for student bookings and Admin bookings/edits.
- Adds surnames only to the built-in demo accounts; user-created accounts are not renamed.
- Adds 6 extra demo students for Admin search/testing. Demo password: student123.

=== v48 Packages / Payments + session reliability ===
- Admin package catalog: package name, hours, price, active/inactive.
- Assign a package from each student profile as Paid or Pending.
- Paid package automatically adds its hours to student credits.
- Pending package adds no credits until Admin marks it Paid.
- Student/admin profile shows package purchase history and per-package remaining hours.
- Package remaining hours are reduced when package credit is used for a booking and restored on booking refund/cancellation/edit.
- Student can see package history from Profile.
- Login sessions are refreshed for 30 days and legacy sessions recover role information.
- If a logged-in user reaches the login URL from a stale/wrong-role tab, the app redirects to that user's home instead of showing another login form.

Testing multiple roles:
A browser profile has one shared login session across all its tabs. If you log in as Admin and then log in as Instructor in another tab of the same Chrome profile, the Instructor login replaces the Admin session for all those tabs. For simultaneous testing use separate browser profiles/browsers/incognito windows (e.g. Chrome=Admin, Edge=Instructor, phone=Student).

=== v49 Admin Bookings + Packages sidebar fix ===
- New Admin sidebar section «Κρατήσεις» with one central list of up to 250 recent bookings.
- Search students by first name, surname, email or phone.
- Filters for date, instructor, spot and booking status (Booked / Pending / Completed / No-show / Cancelled).
- Summary cards show result count, hours, completed, pending and no-show totals.
- Active bookings can be edited directly from the central bookings page using the existing safe edit/move rules.
- Active bookings can also be cancelled from the same modal; package-credit refunds keep working.
- Completed and No-show entries remain locked.
- Packages & Payments now uses the same full Admin sidebar/layout instead of dropping back to the old top navigation.
- «Κρατήσεις» is also available from the main Admin sidebar.

=== v50 Fixed Groups + Student IDs ===
- Every student now receives a permanent visible Student ID (STU-0001, STU-0002, ...).
- Admin student profile now supports lesson type: Private / 2P Group / 3P Group.
- For 2P Group the Admin selects one fixed partner; for 3P Group two fixed partners.
- No visible Group A/B naming is required. The relationship is stored internally and is synchronized automatically across every member profile.
- A student can belong to only one fixed group at a time; members already linked to another group are protected from accidental mixing.
- When any group member books a lesson, one instructor slot is reserved and the same booking is attached automatically to every fixed member.
- Group bookings display all participant names in Student, Instructor and Admin booking views.
- Credits/package hours are checked and charged independently for every participant while instructor capacity is counted only once.
- A conflicting booking for any member blocks the group booking at that time.
- Admin manual booking and Admin edit/move also preserve the complete fixed group.
- Cancelling a shared group booking currently cancels it for all members and refunds every participant credit that was charged.
- Instructor completion / No-show currently applies to the whole group. Per-member attendance and Make-up are intentionally left for the next group-attendance phase.
- Fixed the white sidebar block on the separate Admin «Κρατήσεις» and «Πακέτα» pages by isolating the sidebar from the global navigation styling.


=== v51 Per-member Group Attendance ===
- Group lessons are now completed per participant instead of applying one result to the whole group.
- Instructor chooses Completed / Make-up / No-show separately for each fixed group member.
- Completed members can have their own next skill and instructor note.
- Make-up and No-show members keep their own attendance result and note.
- The shared instructor slot is still counted only once. If at least one member completed the lesson, one instructor hour is recorded; if nobody attended, no completed instructor hour is created.
- Student Profile, Admin Student Profile and Instructor Student Detail use each participant's own result, so one group lesson may appear as Completed for one student, Make-up for another and No-show for another.
- Make-up hours are shown separately in Student/Admin/Instructor student views. They are stored for the next Make-up booking phase; they cannot yet be redeemed automatically.
- Private lesson Completed / No-show behavior remains unchanged, with participant attendance kept synchronized.


v56 — Instructor status polish
- Όλες οι ενεργές/μελλοντικές κρατήσεις στην καρτέλα instructor εμφανίζονται ως «Επόμενο» αντί για «Σε αναμονή».
- Completed και No-show παραμένουν όπως πριν.


Version v57: Crew Membership basic system (active/expired/scheduled, dates, annual fee, badges).

v60 — School Reports + Crew Package
- Νέα καρτέλα Admin «Αναφορές» με φίλτρο περιόδου, booked/completed/shared ώρες, έσοδα, instructor payments, top students και breakdown μαθημάτων.
- Νέος τύπος package «Crew Member». Δεν προσθέτει lesson credits.
- Crew season: 01/05 έως 30/04 της αντίστοιχης περιόδου.
- Paid Crew package ενεργοποιεί αυτόματα τα υπάρχοντα Crew fields στο student profile. Pending ενεργοποιείται με Mark paid.
- Η Crew card στο student profile παραμένει διαθέσιμη όπως πριν.

v64 - Student lesson photo gallery
- Admin student profile: new Photos tab with multi-photo upload, optional date/caption and delete.
- Student profile: read-only personal lesson gallery with enlarged photo preview.
- Allowed gallery formats: JPG/JPEG, PNG, WEBP; max 10MB per file.

============================================================
V70 - ONLINE / RAILWAY TEST SETUP
============================================================

Local Windows use is unchanged:
  python -m venv .venv
  .venv\\Scripts\\activate
  pip install -r requirements.txt
  python app.py

Railway test deployment:
1. Put this project in a GitHub repository (app.py must be in the project root).
2. In Railway create a New Project -> Deploy from GitHub Repo.
3. Add a persistent Volume and mount it at: /data
4. In Railway Variables add:
     DATA_DIR=/data
     SECRET_KEY=<a long random value>
     COOKIE_SECURE=1
     FLASK_DEBUG=0
5. Railway supplies PORT automatically. Do not create your own PORT variable there.
6. Deploy. Railway will use railway.toml / Procfile and Gunicorn.
7. Open /healthz on the public URL. It should return {"status":"ok"}.
8. Test Admin, Instructor and Student accounts from different browsers/devices.

Persistent data:
- SQLite database: /data/kiteclub.db
- Uploaded profile/gallery images: /data/uploads
The app keeps the existing /static/uploads/... URLs through a Linux symlink.

Custom domain later:
- Keep kiteclub.gr at Papaki.
- In Railway add booking.kiteclub.gr as a Custom Domain.
- Railway will show the DNS record that must be copied into Papaki DNS.
- Wait for DNS/SSL to become active, then use https://booking.kiteclub.gr

IMPORTANT:
- Keep SECRET_KEY private and stable once real users start using the app.
- Do not run production with FLASK_DEBUG=1.
- Before real launch, create/verify a Railway volume backup policy.

v71 - Beginner Progress System
- 4 Beginner lesson levels with 18 techniques total.
- Instructor/Admin can mark each technique: Not started / Practicing / Mastered.
- Student sees read-only progress in profile.
- When all 18 techniques are Mastered, Beginner changes automatically to Kiter.
- Existing higher levels are preserved; Intermediate/Expert progression will be defined later.

v73 — Unified Student Portal + Lesson Progress
- Student Home, Booking, Lessons/Photos/Profile and Messages use the same portal shell, sidebar, content width and spacing.
- Instructor lesson completion shows the real Beginner/Kiter level from the progress system.
- "Τι δουλέψατε σήμερα;" now starts with Level 1/2/3/4 selection and then shows only that Level's techniques.
- Instructor can mark one or more techniques as Practicing or Mastered during lesson completion.
- Saving a completed lesson updates Student Progress automatically and promotes Beginner -> Kiter when all 18 skills are Mastered.
