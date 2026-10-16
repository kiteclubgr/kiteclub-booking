# Legal pages — local review draft, 16 October 2026

This package implements complete readable Greek draft pages, not a legal compliance certification.
Document versions: terms and privacy 2026-10-16-draft1. APP_VERSION v76.7.17.14.

## Implemented
- Public /terms and /privacy-policy, no login needed, responsive CSS, print/PDF button.
- Registration opens the exact displayed document versions in separate tabs.
- Separate required Terms acceptance and Privacy acknowledgment (not general processing consent).
- Independent optional lesson/marketing email checkboxes remain unchecked by default.
- New registrations store user, document, immutable version, content SHA256, event and UTC timestamp.
- Full source document snapshots retained in legal_documents; accepted versions are retrievable with ?version=.
- No retroactive acceptance records or changes to existing users, credits, bookings or financial calculations.
- No new minor/guardian workflow. The school handles participation/guardian consent outside the app.
- No automatic deletion or email preferences UI is claimed. Requests are handled by the school.

## Facts to confirm before public release
1. Booking's legal operator is the same entity as the public KiteClub.gr shop. The draft uses the published exact Latin name KARAVELA DIM. ANGELIKI THEOFANO, VAT 104196164, Veikou 22, Athens 11742, sales@kiteclub.gr, 2109211944. Confirm current accuracy and desired legal spelling.
2. Actual Railway region, contractual processor/subprocessor arrangements, SMTP provider, support access and international transfer safeguards. No secrets or hosting dashboard were inspected.
3. Approve a workable retention/deletion schedule for abandoned signups, accounts, lessons, messages, photos, security logs, consent records, financial evidence, backups and provider logs. No invented fixed retention periods or automatic cleanup were added.
4. Confirm cancellation/refund wording matches existing purchase agreements. This update introduces no fees, credit expiry or booking changes.
5. The full original English sports waiver supplied in two photos has been transcribed verbatim (wording/grammar preserved, blank-line lengths/layout adapted). Compare /waiver with the supplied scans before treating the transcription as final. Its blanket release and over-18 declaration are reproduced as source content, not certified legally effective. Registration records acknowledgment of reading, not a signed waiver, age verification or guardian consent.
6. Review the draft wording with the business's legal/privacy adviser before publication. Both pages visibly state draft status; draft1 acknowledgments are not represented as acceptance of a future final version.

## Updating documents
Create new versioned HTML files, increment the corresponding version in legal_pages.py and APP_VERSION. Do not edit text under an existing stored version: startup rejects a SHA256 mismatch. Archived documents remain in the local database. No reacceptance flow for existing users is included in this task.

## Sources consulted (16 October 2026)
- https://kiteclub.gr/terms-of-use/ — business identity only; store clauses were not copied into Booking.
- https://kiteclub.gr/contact/ — public contact details.
- https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en — transparency and rights.
- https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/legal-grounds-processing-data_en — processing bases and separate consent.
- https://europa.eu/youreurope/business/growing/digitalising/online-privacy/index_en.htm — necessary cookies.
- https://europa.eu/youreurope/business/governance-and-sustainability/digital-and-data-compliance/data-protection-gdpr/index_en.htm — recipients/transfers and safeguards.
- https://www.dpa.gr/el/polites/katagelia_stin_arxi — complaint route.

Implementation facts were checked against local Flask, Google OAuth, email, registration and booking code. Live SMTP delivery, provider contracts, live data retention and manual operating procedures were not verified.

## Original waiver integration
Version: 2026-10-16-original-en-1, status transcription, separate from Terms/Privacy draft1.
Original source order: 1000041835.jpg = page 1, 1000041838.jpg = page 2.
The supplied photographs are not included or linked in this version, at the user's request. Only the transcribed text is distributed.
A new registration requires waiver acknowledgment and its displayed version. The evidence
event is acknowledged and legacy waiver_accepted_at remains NULL; no signature is invented.
No new minor workflow, date of birth field, ID upload or signature canvas has been added.
