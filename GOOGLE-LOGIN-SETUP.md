# Google login for KiteClub

Google login is optional. Without both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET,
the Google buttons are hidden and existing email/password authentication works.

## Google Cloud / Google Auth Platform

1. Create or select a project in https://console.cloud.google.com/.
2. Configure Google Auth Platform Branding, Audience (External), and contact details.
   Use the KiteClub website, support email, privacy policy and terms pages.
3. Request only `openid`, `email`, and `profile` scopes.
4. Create an OAuth client with application type **Web application**.
5. Authorized JavaScript origin: `https://booking.kiteclub.gr`.
6. Authorized redirect URI (exact match):
   `https://booking.kiteclub.gr/auth/google/callback`
7. While the app is in Testing, add the Google accounts that will test it under
   Test users. Publish the OAuth app for general use when ready and complete any
   review Google requires. GitHub deployment does not publish the Google OAuth app.

## Railway service variables

Set these securely in the application service's Variables tab:

- GOOGLE_CLIENT_ID: the web application's client ID.
- GOOGLE_CLIENT_SECRET: the web application's client secret.
- GOOGLE_REDIRECT_URI: `https://booking.kiteclub.gr/auth/google/callback`.

Keep the existing persistent SECRET_KEY and DATA_DIR configuration. Do not put
secrets in source control, screenshots, chat, or logs. Redeploy after saving variables.
`GOOGLE_APPLICATION_CREDENTIALS` is service-account authentication, not this OAuth client.

## Behaviour and checks

- Existing linked Google identity: logs in only if the local account is active.
- Existing email without a Google link: asks for the existing password once before
  linking, rather than granting access by email alone.
- New Google identity: redirects to registration, fixes the email to Google's
  verified email, omits password fields, and still requires phone, date of birth,
  terms, risk acknowledgment and guardian details for minors.
- New registrations stay inactive with zero credits until school approval.
- Identifies Google accounts by `sub`, not by email, and stores no provider tokens.
- Uses OpenID Connect validation, state, nonce and PKCE through Authlib.
- The SQLite startup migration adds oauth_identities without replacing user data.

Local regression: `python tests_google_auth.py` (five offline integration tests).
These tests mock the provider response; they do not prove a real Google exchange works.
After Railway configuration, test cancellation, existing-account linking, repeat
Google login, new registration, school approval and subsequent Google login in a
real browser. Google connection requires HTTPS egress to accounts.google.com,
oauth2.googleapis.com and www.googleapis.com. No email-delivery setup is required.
