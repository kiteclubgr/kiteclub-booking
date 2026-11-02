"""Exercise the actual shared mobile logout form on isolated Student/Instructor pages."""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path
from html.parser import HTMLParser

class MobileForm(HTMLParser):
    """Find logout by action inside the rendered role's mobile account chrome."""
    VOID_TAGS = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self):
        super().__init__()
        self.stack=[]; self.forms=[]; self.current=None

    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form' and a.get('action')=='/logout':
            mobile=any(classes & {'kc-student-mobile-header','kc-mobile-session-bar'} for _,classes in self.stack)
            if mobile:
                self.current=dict(attrs=a,token=None,buttons=0)
                self.forms.append(self.current)
        if self.current is not None:
            if tag=='input' and a.get('name')=='_csrf_token': self.current['token']=a.get('value')
            if tag=='button' and a.get('type')=='submit': self.current['buttons']+=1
        if tag not in self.VOID_TAGS: self.stack.append((tag,set(a.get('class','').split())))

    def handle_endtag(self,tag):
        if tag=='form': self.current=None
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:]
                break

source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)/'app'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','*.db-*','uploads','.local_secret_key','.git'))
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('launcher',root/'run_local.py')
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    m=launcher.load_local_app();m.app.config['TESTING']=True
    con=m.db()
    sid=con.execute('SELECT user_id FROM students ORDER BY user_id').fetchone()[0]
    iid=con.execute('SELECT user_id FROM instructors ORDER BY user_id').fetchone()[0]
    aid=con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    spot=con.execute('SELECT id FROM spots LIMIT 1').fetchone()[0]
    slot=con.execute("INSERT INTO slots(lesson_date,start_time,instructor_id,spot_id) VALUES('2026-10-17','12:00',?,?)",(iid,spot)).lastrowid
    bid=con.execute("INSERT INTO bookings(slot_id,student_id,duration,status) VALUES(?,?,1,'confirmed')",(slot,sid)).lastrowid
    con.execute("INSERT INTO booking_participants(booking_id,student_id,created_at) VALUES(?,?,'2026-10-16T12:00:00')",(bid,sid))
    con.commit()
    before={t:[tuple(r) for r in con.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('bookings','slots','students','student_payments','student_packages')}
    cases=[('student',sid,'student@kiteclub.gr','student123',['/student/home','/student','/student/profile','/student/profile/edit','/messages']),
           ('instructor',iid,'angelos@kiteclub.gr','teacher123',['/instructor','/instructor/profile','/instructor/students',f'/instructor/students/{sid}',f'/instructor/lesson/{bid}',f'/instructor/lesson/{bid}/complete'])]
    count=0
    for role,uid,email,password,paths in cases:
        for path in paths:
            c=m.app.test_client()
            # Real password login, then use the form rendered by the requested page.
            c.get('/')
            with c.session_transaction() as sess:token=sess['_csrf_token']
            assert c.post('/',data={'_csrf_token':token,'email':email,'password':password}).status_code==302
            r=c.get(path);assert r.status_code==200,(role,path,r.status_code)
            parser=MobileForm();parser.feed(r.get_data(as_text=True))
            assert len(parser.forms)==1,(path,parser.forms)
            form=parser.forms[0]
            assert form['attrs']['method'].lower()=='post' and form['token'] and form['buttons']==1,path
            with c.session_transaction() as sess: sess['logout_test_marker']='must-clear'
            # Invalid logout must leave the session intact.
            assert c.get('/logout').status_code==405
            assert c.post('/logout').status_code==400
            assert c.post('/logout',data={'_csrf_token':'invalid'}).status_code==400
            with c.session_transaction() as sess:assert sess['uid']==uid
            r=c.post(form['attrs']['action'],data={'_csrf_token':form['token']});assert r.status_code==302
            with c.session_transaction() as sess: assert not dict(sess),dict(sess)
            r=c.get(path);assert r.status_code==302,(path,r.status_code)
            from urllib.parse import urlsplit
            assert urlsplit(r.headers['Location']).path=='/'
            count+=1
    # Admin and signed-out pages retain their existing chrome.
    c=m.app.test_client();assert 'kc-mobile-logout-form' not in c.get('/').get_data(as_text=True)
    with c.session_transaction() as sess:sess['uid']=aid
    assert 'kc-mobile-logout-form' not in c.get('/admin').get_data(as_text=True)
    for t,rows in before.items():assert [tuple(r) for r in con.execute(f'SELECT * FROM {t} ORDER BY 1')]==rows,t
    for template in m.app.jinja_env.list_templates():m.app.jinja_env.get_template(template)
    con.close()
print(f'PASS: actual mobile logout form on {count} Student/Instructor pages, password login, CSRF, safe GET, session clearing and protected-page refresh; booking/credit/payment rows unchanged')
