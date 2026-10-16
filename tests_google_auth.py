"""Offline Google auth integration tests; no provider credentials or live requests."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=_tmp.name, ENABLE_DEMO_DATA='1', GOOGLE_CLIENT_ID='test-client',
                  GOOGLE_CLIENT_SECRET='test-only-not-a-credential', COOKIE_SECURE='0')
import app as application


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = application.app.test_client()
        with self.client.session_transaction() as s:
            s['_csrf_token'] = 'csrf'

    def callback(self, sub, email, verified=True):
        with self.client.session_transaction() as s:
            s['_state_google_test-state'] = {'data': {'nonce': 'test'}, 'exp': time.time()+60}
        with patch.object(application.google_client, 'authorize_access_token', return_value={
            'userinfo': {'sub': sub, 'email': email, 'email_verified': verified,
                         'given_name': 'Google', 'family_name': 'Student'}}):
            return self.client.get('/auth/google/callback?state=test-state&code=test')

    def test_csrf_and_state(self):
        self.assertEqual(self.client.post('/auth/google').status_code, 400)
        with patch.object(application.google_client, 'authorize_access_token') as exchange:
            self.assertEqual(self.client.get('/auth/google/callback?state=wrong').status_code, 302)
            exchange.assert_not_called()

    def test_unverified_email_rejected(self):
        self.callback('unverified', 'unsafe@example.test', False)
        with self.client.session_transaction() as s:
            self.assertNotIn('google_identity', s)
            self.assertNotIn('uid', s)

    def test_existing_user_requires_password_and_linked_login_respects_active(self):
        r = self.callback('student-sub', 'student@kiteclub.gr')
        self.assertTrue(r.location.endswith('/'))
        with self.client.session_transaction() as s:
            self.assertNotIn('uid', s)
            s['_csrf_token'] = 'csrf'
        self.client.post('/', data={'email': 'student@kiteclub.gr', 'password': 'wrong', '_csrf_token': 'csrf'})
        con = application.db()
        self.assertIsNone(con.execute("SELECT * FROM oauth_identities WHERE subject='student-sub'").fetchone())
        con.close()
        self.client.post('/', data={'email': 'student@kiteclub.gr', 'password': 'student123', '_csrf_token': 'csrf'})
        with self.client.session_transaction() as s:
            self.assertIn('uid', s)
            uid = s['uid']
        self.client = application.app.test_client()
        r = self.callback('student-sub', 'student@kiteclub.gr')
        self.assertTrue(r.location.endswith('/home'))
        con = application.db()
        con.execute('UPDATE users SET active=0 WHERE id=?', (uid,)); con.commit(); con.close()
        self.callback('student-sub', 'student@kiteclub.gr')
        with self.client.session_transaction() as s:
            self.assertNotIn('uid', s)
        con = application.db(); con.execute('UPDATE users SET active=1 WHERE id=?',(uid,)); con.commit(); con.close()

    def test_registration_uses_verified_email_and_activates(self):
        self.callback('new-sub', 'google-new@example.test')
        page = self.client.get('/register').get_data(as_text=True)
        self.assertIn('google-new@example.test', page)
        self.assertNotIn('id="reg-pass"', page)
        with self.client.session_transaction() as s:
            s['_csrf_token'] = 'csrf'
        r = self.client.post('/register', data={'_csrf_token':'csrf', 'name':'New', 'surname':'Student',
            'email':'forged@example.test', 'phone':'6900000000','birth_date':'1995-01-01', 'terms':'yes','privacy':'yes','terms_version':application.TERMS_VERSION,'privacy_version':application.PRIVACY_VERSION,'waiver_version':application.WAIVER_VERSION,'waiver':'yes'})
        self.assertIn('Η εγγραφή καταχωρήθηκε',r.get_data(as_text=True))
        con=application.db()
        user=con.execute("SELECT u.* FROM users u JOIN oauth_identities o ON u.id=o.user_id WHERE o.subject='new-sub'").fetchone()
        self.assertEqual(user['email'],'google-new@example.test')
        self.assertEqual(user['active'],1)
        self.assertEqual(con.execute('SELECT credits FROM students WHERE user_id=?',(user['id'],)).fetchone()[0],0)
        con.close()

    def test_expired_identity_needs_password(self):
        with self.client.session_transaction() as s:
            s['google_identity']={'sub':'expired','email':'expired@example.test','expires':time.time()-1}
        page=self.client.get('/register').get_data(as_text=True)
        self.assertIn('id="reg-pass"',page)


if __name__ == '__main__':
    unittest.main()
