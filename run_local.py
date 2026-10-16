"""Isolated local demo launcher with email previews."""
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def load_local_app():
    os.chdir(ROOT)
    # A copied shell configuration must never connect this demo to production.
    for key in list(os.environ):
        if key.startswith(('SMTP_', 'GOOGLE_', 'RAILWAY_', 'EMAIL_', 'RESEND_')) or key in ('SECRET_KEY', 'ADMIN_EMAIL', 'ADMIN_PASSWORD'):
            os.environ.pop(key, None)
    os.environ.update(DATA_DIR=str(ROOT / '_local_data'), ENABLE_DEMO_DATA='1',
                      PRODUCTION='0', COOKIE_SECURE='0', FLASK_DEBUG='0')
    sys.path.insert(0, str(ROOT))
    os.environ["LOCAL_EMAIL_PREVIEW"] = "1"
    os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1:5000"
    spec = importlib.util.spec_from_file_location('kiteclub_local_app', ROOT / 'app.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    module = load_local_app()
    if '--check' in sys.argv:
        client = module.app.test_client()
        for path in ('/healthz', '/', '/register', '/static/auth.css', '/static/auth.js',
                     '/static/img/kiteclub-auth-background.png', '/terms', '/privacy-policy', '/waiver', '/static/legal.css'):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f'{path}: HTTP {response.status_code}')
        print('Local smoke check: PASS')
    else:
        print(module.APP_VERSION)
        print('LOCAL DEMO ONLY: http://127.0.0.1:5000')
        print('Admin: admin@kiteclub.gr / admin123')
        print('Student: student@kiteclub.gr / student123')
        print('Instructor: angelos@kiteclub.gr / teacher123')
        print('Emails are saved in _local_data/mail-preview; no real delivery. Google OAuth disabled. Stop with Ctrl+C.')
        module.app.run(host='127.0.0.1', port=5000, debug=False)
