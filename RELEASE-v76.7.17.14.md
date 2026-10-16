# v76.7.17.14 — Registration and Email Delivery

New student registration no longer asks for birth date or routine Fani approval.
Password signups activate after a one-use 24-hour email confirmation; verified new Google
identities activate directly. All start at zero credits. Old accounts are not mass-activated.
Country mobile prefixes include 49 local SVG flags. Full English waiver text is included,
without the supplied source photographs. Terms and Privacy are separate versioned review
pages with transaction-bound acknowledgment records. Guardian paperwork remains manual.

Transactional email now supports Resend HTTPS API and existing TLS SMTP configuration.
The local demo launcher forces .eml previews and clears inherited delivery/OAuth secrets.
Production defaults do not seed demo users. No database reset or data repair script is run.
Email settings are documented in EMAIL-SETUP.md and blank examples in env.example.

Offline tests and a disposable production-mode upgrade passed; see LOCAL-QA.txt.
Live DNS/provider configuration, a controlled recipient inbox test, mobile visual QA and
business confirmation of legal/provider/retention details remain pending.
