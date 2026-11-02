"""Isolated Google auth integration tests with fake identities and no network."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        source = Path(__file__).resolve().parent
        root = Path(self.folder.name) / 'app'
        shutil.copytree(source, root, ignore=shutil.ignore_patterns(
            '.git', '_local_data', '__pycache__', '*.db', '*.db-*',
            '.local_secret_key', 'uploads', '.venv'))
        previous_cwd = Path.cwd()
        previous_path = sys.path[:]
        self.addCleanup(os.chdir, previous_cwd)
        self.addCleanup(setattr, sys, 'path', previous_path)
        os.chdir(root)
        sys.path.insert(0, str(root))
        env = {k: v for k, v in os.environ.items() if not k.startswith(
            ('SMTP_', 'GOOGLE_', 'STRIPE_', 'RAILWAY_', 'EMAIL_', 'RESEND_'))
            and k not in ('SECRET_KEY', 'ADMIN_EMAIL', 'ADMIN_PASSWORD')}
        env.update(DATA_DIR=str(root / '_local_data'), ENABLE_DEMO_DATA='1',
                   PRODUCTION='0', COOKIE_SECURE='0', LOCAL_EMAIL_PREVIEW='1',
                   PUBLIC_BASE_URL='http://127.0.0.1:5000', GOOGLE_CLIENT_ID='test-client',
                   GOOGLE_CLIENT_SECRET='test-only-not-a-credential')
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden in Google tests')))
        spec = importlib.util.spec_from_file_location('google_test_app', root / 'app.py')
        self.application = importlib.util.module_from_spec(spec)
        self.enterContext(patch.dict(sys.modules, {spec.name: self.application}))
        spec.loader.exec_module(self.application)
        self.application.app.config['TESTING'] = True
        self.client = self.application.app.test_client()
        self.csrf()

    def csrf(self):
        with self.client.session_transaction() as session:
            session['_csrf_token'] = 'csrf'
        return {'_csrf_token': 'csrf'}

    def callback(self, sub, email, verified=True):
        with self.client.session_transaction() as session:
            session['_state_google_test-state'] = {'data': {'nonce': 'test'}, 'exp': time.time()+60}
        with patch.object(self.application.google_client, 'authorize_access_token', return_value={
            'userinfo': {'sub': sub, 'email': email, 'email_verified': verified,
                         'given_name': 'Google', 'family_name': 'Student'}}):
            return self.client.get('/auth/google/callback?state=test-state&code=test')

    def registration(self, **changes):
        m = self.application
        data = dict(self.csrf(), name='New', surname='Student', email='forged@example.test',
                    phone_prefix='+30', phone='6900000000', terms='yes', privacy='yes', waiver='yes',
                    terms_version=m.TERMS_VERSION, privacy_version=m.PRIVACY_VERSION, waiver_version=m.WAIVER_VERSION)
        data.update(changes)
        return data

    def assert_redirect(self, response, path, status=302):
        self.assertEqual(response.status_code, status)
        self.assertEqual(urlsplit(response.location).path, path)

    def test_csrf_and_state(self):
        self.assertEqual(self.client.post('/auth/google').status_code, 400)
        with patch.object(self.application.google_client, 'authorize_access_token') as exchange:
            self.assert_redirect(self.client.get('/auth/google/callback?state=wrong'), '/')
            exchange.assert_not_called()

    def test_unverified_email_rejected(self):
        self.assert_redirect(self.callback('unverified', 'unsafe@example.test', False), '/')
        with self.client.session_transaction() as session:
            self.assertNotIn('google_identity', session)
            self.assertNotIn('uid', session)

    def test_existing_user_requires_password_and_linked_login_respects_active(self):
        m = self.application
        self.assert_redirect(self.callback('student-sub', 'student@kiteclub.gr'), '/')
        with self.client.session_transaction() as session:
            self.assertNotIn('uid', session)
        self.client.post('/', data={**self.csrf(), 'email': 'student@kiteclub.gr', 'password': 'wrong'})
        con = m.db()
        self.addCleanup(con.close)
        self.assertIsNone(con.execute("SELECT * FROM oauth_identities WHERE subject='student-sub'").fetchone())
        r = self.client.post('/', data={**self.csrf(), 'email': 'student@kiteclub.gr', 'password': 'student123'})
        self.assert_redirect(r, '/home')
        with self.client.session_transaction() as session:
            uid = session['uid']
        self.assertEqual(con.execute("SELECT user_id FROM oauth_identities WHERE subject='student-sub'").fetchone()[0], uid)
        self.client = m.app.test_client()
        self.assert_redirect(self.callback('student-sub', 'student@kiteclub.gr'), '/home')
        with self.client.session_transaction() as session:
            self.assertEqual(session['uid'], uid)
            self.assertEqual(session['role'], 'student')
        con.execute('UPDATE users SET active=0 WHERE id=?', (uid,)); con.commit()
        self.assert_redirect(self.callback('student-sub', 'student@kiteclub.gr'), '/')
        with self.client.session_transaction() as session:
            self.assertNotIn('uid', session)
            self.assertNotIn('role', session)

    def test_registration_uses_verified_email_and_activates(self):
        m = self.application
        self.assert_redirect(self.callback('new-sub', 'google-new@example.test'), '/register')
        page = self.client.get('/register').get_data(as_text=True)
        self.assertIn('google-new@example.test', page)
        self.assertNotIn('id="reg-pass"', page)
        con = m.db()
        self.addCleanup(con.close)
        # A verified Google email does not bypass mobile or current legal consents.
        for changes in ({'phone': ''}, {'terms': ''}, {'privacy': ''}, {'waiver': ''},
                        {'terms_version': 'stale'}, {'privacy_version': 'stale'}, {'waiver_version': 'stale'}):
            with self.subTest(changes=changes):
                self.assert_redirect(self.client.post('/register', data=self.registration(**changes)), '/register')
                self.assertIsNone(con.execute("SELECT id FROM users WHERE email='google-new@example.test'").fetchone())
        self.assert_redirect(self.client.post('/register', data=self.registration()), '/home', 303)
        user = con.execute("SELECT u.* FROM users u JOIN oauth_identities o ON u.id=o.user_id WHERE o.subject='new-sub'").fetchone()
        self.assertEqual(user['email'], 'google-new@example.test')
        self.assertEqual(user['phone'], '+306900000000')
        self.assertEqual(user['active'], 1)
        self.assertEqual(con.execute('SELECT credits FROM students WHERE user_id=?', (user['id'],)).fetchone()[0], 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM registration_legal_acceptances WHERE user_id=?', (user['id'],)).fetchone()[0], 3)
        with self.client.session_transaction() as session:
            self.assertEqual(session['uid'], user['id'])
            self.assertNotIn('google_identity', session)
        self.assertEqual(self.client.get('/home', follow_redirects=True).status_code, 200)

    def test_google_signup_requires_phone_and_current_legal_before_oauth(self):
        with patch.object(self.application.google_client, 'authorize_redirect', return_value=('', 302)) as authorize:
            for changes in ({'phone': ''}, {'phone': 'invalid'}, {'terms': ''}, {'privacy': ''}, {'waiver': ''},
                            {'terms_version': 'stale'}, {'privacy_version': 'stale'}, {'waiver_version': 'stale'}):
                with self.subTest(changes=changes):
                    self.assert_redirect(self.client.post('/auth/google', data=self.registration(signup_google='yes', **changes)), '/register')
                    authorize.assert_not_called()
                    with self.client.session_transaction() as session:
                        self.assertNotIn('google_signup_legal', session)

    def test_google_signup_with_preconsent_activates_and_records_versions(self):
        m = self.application
        with patch.object(m.google_client, 'authorize_redirect', return_value=('', 302)) as authorize:
            self.assertEqual(self.client.post('/auth/google', data=self.registration(signup_google='yes')).status_code, 302)
            authorize.assert_called_once()
        self.assert_redirect(self.callback('preconsent-sub', 'preconsent@example.test'), '/home')
        con = m.db()
        self.addCleanup(con.close)
        user = con.execute("SELECT * FROM users WHERE email='preconsent@example.test'").fetchone()
        self.assertEqual((user['active'], user['phone']), (1, '+306900000000'))
        versions = {r['document_key']: r['version'] for r in con.execute('SELECT document_key,version FROM registration_legal_acceptances WHERE user_id=?', (user['id'],))}
        self.assertEqual(versions, dict(terms=m.TERMS_VERSION, privacy=m.PRIVACY_VERSION, waiver=m.WAIVER_VERSION))
        with self.client.session_transaction() as session:
            self.assertEqual(session['uid'], user['id'])
            self.assertNotIn('google_signup_legal', session)

    def test_expired_preconsent_requires_registration(self):
        with self.client.session_transaction() as session:
            session['google_signup_legal'] = dict(phone='+306900000000', issued_at=time.time()-901,
                terms_version=self.application.TERMS_VERSION, privacy_version=self.application.PRIVACY_VERSION,
                waiver_version=self.application.WAIVER_VERSION)
        self.assert_redirect(self.callback('expired-consent', 'expired-consent@example.test'), '/register')
        with self.client.session_transaction() as session:
            self.assertNotIn('uid', session)

    def test_expired_identity_needs_password(self):
        with self.client.session_transaction() as session:
            session['google_identity'] = {'sub': 'expired', 'email': 'expired@example.test', 'expires': time.time()-1}
        self.assertIn('id="reg-pass"', self.client.get('/register').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
