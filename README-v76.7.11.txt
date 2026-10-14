KiteClub v76.7.11 · Cancel

Staff Cancel from Admin > Bookings and Instructor > Lesson.
Each charged group member gets exact reserved credits back, once. All linked slots
are set Closed with manual_override=closed to survive automatic rebalance.
No instructor hours or progress are created. Atomic database transaction and audit.
Existing student self-cancellation remains unchanged. UI label is Cancel.

Deployment: do NOT upload db/.env/.local_secret_key. Deploy patch only after QA.
