"""Offline regression checks. Run: python tests_v75.py"""
import ast
import re
import sqlite3
import tempfile
from pathlib import Path
from backup import backup

root=Path(__file__).parent
source=(root/'app.py').read_text()
ast.parse(source)
forms=0
for path in (root/'templates').glob('*.html'):
    body=path.read_text()
    for match in re.finditer(r'<form\b(?=[^>]*\bmethod\s*=\s*["\']post["\'])[^>]*>',body,re.I):
        forms+=1
        assert 'name="_csrf_token"' in body[match.end():match.end()+130], (path.name,match.group())
assert forms >= 40, forms
assert 'def enforce_csrf' in source
assert 'def login_locked' in source
assert 'SELECT * FROM users WHERE lower(email)=? AND COALESCE(active,1)=1' in source
assert 'request.form.get("password","student123")' not in source
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    data=root/'data'; data.mkdir(); (data/'uploads').mkdir()
    (data/'uploads'/'proof.txt').write_text('backup-ok')
    with sqlite3.connect(str(data/'kiteclub.db')) as con:
        con.execute('CREATE TABLE check_table (id INTEGER)')
        con.execute('INSERT INTO check_table VALUES (42)')
    archive=backup(data,root/'backups')
    import tarfile
    with tarfile.open(archive) as zipped:
        assert 'kiteclub.db' in zipped.getnames()
        assert 'uploads/proof.txt' in zipped.getnames()
        zipped.extract('kiteclub.db',root/'restore')
    with sqlite3.connect(str(root/'restore'/'kiteclub.db')) as con:
        assert con.execute('SELECT id FROM check_table').fetchone()[0]==42
print(f'PASS: app syntax; CSRF in {forms} POST forms; login guards; backup + restore integrity')
