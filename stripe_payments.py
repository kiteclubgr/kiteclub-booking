"""Stripe sandbox only. Online testing requires explicit email allowlisting; live keys rejected."""
import json
import os
import uuid
import math
from contextlib import contextmanager
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from flask import abort, request, session, redirect, render_template
import stripe


def setup_stripe_payments(app, db, current_user, activate, data_root, base):
    @contextmanager
    def connection():
        c=db()
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
    local = not app.config.get('IS_KITECLUB_PRODUCTION') and Path(data_root).resolve() == (Path(base)/'_local_data').resolve()
    def online():
        return os.getenv('STRIPE_ONLINE_TEST')=='1' and os.getenv('PUBLIC_BASE_URL','').rstrip('/')=='https://booking.kiteclub.gr'
    def allowed(c, uid):
        if local and not app.config.get('IS_KITECLUB_PRODUCTION'): return True
        emails={x.strip().lower() for x in os.getenv('STRIPE_TEST_STUDENT_EMAILS','').split(',') if x.strip()}
        user=c.execute('SELECT email,role,active FROM users WHERE id=?',(uid,)).fetchone()
        return bool(user and user['role']=='student' and user['active'] and user['email'].lower() in emails)
    def configured():
        deployment_ok=(local and not app.config.get('IS_KITECLUB_PRODUCTION')) or (online() and bool(os.getenv('STRIPE_TEST_STUDENT_EMAILS','').strip()))
        return deployment_ok and os.getenv('STRIPE_TEST_ENABLED')=='1' and os.getenv('STRIPE_SECRET_KEY','').startswith(('sk_test_','rk_test_')) and os.getenv('STRIPE_WEBHOOK_SECRET','').startswith('whsec_')
    def enabled():
        if not configured(): return False
        user=current_user()
        if not user: return False
        if user['role']=='admin': return True
        with connection() as c: return allowed(c,user['id'])
    app.jinja_env.globals['stripe_test_enabled'] = enabled
    def refund_info(purchase_id):
        # Read historical receipts even when the TEST feature is later disabled.
        with connection() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stripe_test_orders'").fetchone(): return None
            row=c.execute("""SELECT o.cents,COALESCE(SUM(r.applied_cents),0) refunded,
                t.review FROM stripe_test_orders o
                LEFT JOIN stripe_test_refunds r ON r.order_id=o.id
                LEFT JOIN stripe_test_refund_totals t ON t.order_id=o.id
                WHERE o.purchase_id=? GROUP BY o.id""",(purchase_id,)).fetchone()
        if not row or row['refunded']<=0: return None
        return {'full':row['refunded']>=row['cents'], 'amount':row['refunded']/100, 'review':row['review'] or ''}
    app.jinja_env.globals['stripe_refund_info'] = refund_info

    if local or online():
        with connection() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS stripe_test_orders (
                id TEXT PRIMARY KEY, student_id INTEGER NOT NULL, nonce TEXT NOT NULL,
                package_id INTEGER NOT NULL, name TEXT NOT NULL, hours REAL NOT NULL,
                package_type TEXT NOT NULL, cents INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'created',
                checkout_id TEXT UNIQUE, checkout_url TEXT, payment_intent TEXT UNIQUE,
                purchase_id INTEGER UNIQUE, created_at TEXT NOT NULL,
                UNIQUE(student_id,nonce))''')
            c.execute("""CREATE TABLE IF NOT EXISTS stripe_test_refunds (
                id TEXT PRIMARY KEY, order_id TEXT NOT NULL, cents INTEGER NOT NULL,
                status TEXT NOT NULL, applied_cents INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS stripe_test_refund_totals (
                order_id TEXT PRIMARY KEY, revoked_hours REAL NOT NULL DEFAULT 0,
                review TEXT NOT NULL DEFAULT '')""")
    def require_student():
        if not configured(): abort(503, description='Stripe sandbox is disabled. No payment was made.')
        user=current_user()
        if not user or user['role']!='student': abort(403)
        with connection() as c:
            if not allowed(c,user['id']): abort(403)
        return user['id']
    def eligible(c, uid):
        s=c.execute('SELECT lesson_type,group_id FROM students WHERE user_id=?',(uid,)).fetchone()
        if not s: return None
        kind=s['lesson_type'] or 'private'
        if kind=='private': return 'lesson'
        if kind not in ('2p','3p') or not s['group_id']: return None
        n=int(kind[0]); g=c.execute('SELECT group_size FROM student_groups WHERE id=?',(s['group_id'],)).fetchone()
        members=c.execute('SELECT s.user_id,s.lesson_type,u.active FROM students s JOIN users u ON u.id=s.user_id WHERE s.group_id=?',(s['group_id'],)).fetchall()
        return 'group_'+kind if g and g[0]==n and len(members)==n and all(x['active'] and x['lesson_type']==kind for x in members) else None
    def client():
        return stripe.StripeClient(os.environ['STRIPE_SECRET_KEY'],max_network_retries=1,http_client=stripe.RequestsClient(timeout=15))
    def create_checkout(params, key):
        return client().v1.checkout.sessions.create(params, options={'idempotency_key':key}).to_dict()
    def retrieve_checkout(sid):
        return client().v1.checkout.sessions.retrieve(sid,params={'expand':['line_items']}).to_dict()
    # Explicit seams for isolated tests; no mock switch is exposed to browsers.
    app.extensions['stripe_test_gateway']={'create':create_checkout,'retrieve':retrieve_checkout,
        'refund':lambda rid:client().v1.refunds.retrieve(rid).to_dict(),
        'intent':lambda pid:client().v1.payment_intents.retrieve(pid).to_dict()}
    @app.get('/student/buy-hours')
    def student_buy_hours():
        uid=require_student()
        with connection() as c:
            kind=eligible(c,uid)
            packages=c.execute('SELECT * FROM packages WHERE active=1 AND package_type=? AND hours>0 AND price>0 ORDER BY hours,id',(kind,)).fetchall() if kind else []
        nonce=uuid.uuid4().hex
        session['stripe_nonces']=(session.get('stripe_nonces',[])+[nonce])[-10:]
        return render_template('stripe_buy.html',packages=packages,nonce=nonce,order=None)
    @app.get('/student/package-review')
    def student_package_review():
        uid=require_student()
        with connection() as c:
            if eligible(c,uid) != 'lesson':
                abort(403, description='This package is for individual lessons. Contact the school about your group package.')
            package=c.execute("SELECT * FROM packages WHERE active=1 AND package_type='lesson' AND hours=8 AND price>0 ORDER BY id LIMIT 1").fetchone()
        if not package: abort(404)
        nonce=uuid.uuid4().hex
        session['stripe_nonces']=(session.get('stripe_nonces',[])+[nonce])[-10:]
        session['purchase_language']='en' if request.args.get('lang',session.get('purchase_language'))=='en' else 'el'
        session['purchase_reviews']={**session.get('purchase_reviews',{}),nonce:{'package_id':package['id'],'price':str(package['price'])}}
        session['purchase_reviews']={k:v for k,v in session['purchase_reviews'].items() if k in session['stripe_nonces']}
        response=app.make_response(render_template('package_review.html',package=package,nonce=nonce,language=session['purchase_language'],preview=False))
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/packages/private-8h/review-preview')
    def package_review_preview():
        with connection() as c:
            package=c.execute("SELECT * FROM packages WHERE active=1 AND package_type='lesson' AND hours=8 AND price>0 ORDER BY id LIMIT 1").fetchone()
        if not package: abort(404)
        return render_template('package_review.html',package=package,nonce='',language='en' if request.args.get('lang')=='en' else 'el',preview=True)

    @app.post('/student/buy-hours')
    def student_create_checkout():
        uid=require_student(); nonce=request.form.get('nonce','')
        if nonce not in session.get('stripe_nonces',[]): abort(400)
        try: pid=int(request.form.get('package_id',''))
        except ValueError: abort(400)
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM stripe_test_orders WHERE student_id=? AND nonce=?',(uid,nonce)).fetchone()
            if row:
                if row['package_id']!=pid: abort(400)
            else:
                p=c.execute('SELECT * FROM packages WHERE id=? AND active=1 AND package_type=?',(pid,eligible(c,uid))).fetchone()
                if not p: abort(400)
                reviewed=session.get('purchase_reviews',{}).get(nonce)
                if reviewed and (reviewed['package_id']!=pid or Decimal(reviewed['price'])!=Decimal(str(p['price']))):
                    abort(409,description='The package price has changed. Review the package again before paying.')
                price=Decimal(str(p['price']))*100
                if not price.is_finite() or price!=price.to_integral_value() or price<=0 or not math.isfinite(p['hours']) or p['hours']<=0: abort(400)
                oid=uuid.uuid4().hex
                c.execute('INSERT INTO stripe_test_orders(id,student_id,nonce,package_id,name,hours,package_type,cents,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(oid,uid,nonce,pid,p['name'],p['hours'],p['package_type'],int(price),datetime.now().isoformat()))
                row=c.execute('SELECT * FROM stripe_test_orders WHERE id=?',(oid,)).fetchone()
        if row['state']=='paid': return redirect('/student/payments/'+row['id'],303)
        if row['checkout_url']: return redirect(row['checkout_url'],303)
        # A fixed local origin avoids host-header injection into payment links.
        origin='https://booking.kiteclub.gr' if online() else 'http://127.0.0.1:5000'
        params={'locale':'en' if session.get('purchase_language')=='en' else 'el','mode':'payment','client_reference_id':row['id'],
                'metadata':{'app':'kiteclub_booking','order_id':row['id'],'student_id':str(uid)},
                'payment_intent_data':{'metadata':{'app':'kiteclub_booking','order_id':row['id'],'student_id':str(uid)}},
                'line_items':[{'quantity':1,'price_data':{'currency':'eur','unit_amount':row['cents'],'product_data':{'name':row['name']}}}],
                'success_url':origin+'/student/payments/'+row['id']+'?checkout=returned', 'cancel_url':origin+'/student/payments/'+row['id']+'?checkout=cancelled'}
        try:
            result=app.extensions['stripe_test_gateway']['create'](params,'kiteclub-test-'+row['id'])
            if result.get('livemode') is not False or not str(result.get('url','')).startswith('https://checkout.stripe.com/'): abort(502)
            with connection() as c:
                c.execute("UPDATE stripe_test_orders SET checkout_id=?,checkout_url=?,state=CASE WHEN state='paid' THEN state ELSE 'open' END WHERE id=? AND (checkout_id IS NULL OR checkout_id=?)",(result['id'],result['url'],row['id'],result['id']))
            return redirect(result['url'],303)
        except stripe.StripeError:
            abort(502,description='Stripe is temporarily unavailable. Retry the same form. No credits were added.')
    @app.get('/student/payments/<oid>')
    def student_stripe_status(oid):
        uid=require_student()
        with connection() as c:
            row=c.execute('SELECT * FROM stripe_test_orders WHERE id=? AND student_id=?',(oid,uid)).fetchone()
            refunded_cents=c.execute('SELECT COALESCE(SUM(applied_cents),0) FROM stripe_test_refunds WHERE order_id=?',(oid,)).fetchone()[0]
        if not row: abort(404)
        if request.args.get('format') == 'json':
            response=app.response_class(json.dumps({'state':row['state'],'confirmed':row['state']=='paid' and row['purchase_id'] is not None}),mimetype='application/json')
        else:
            response=app.make_response(render_template('stripe_buy.html',order=row,packages=[],nonce='',refunded_cents=refunded_cents))
        response.headers['Cache-Control']='no-store'
        return response
    def sync_refund(rid):
        gateway=app.extensions['stripe_test_gateway']
        try:
            refund=gateway['refund'](rid)
            if not refund.get('payment_intent'): return
            intent=gateway['intent'](refund['payment_intent'])
        except stripe.StripeError: abort(503)
        if refund.get('id')!=rid or intent.get('livemode') is not False or intent.get('id')!=refund.get('payment_intent'): abort(400)
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM stripe_test_orders WHERE payment_intent=?',(intent['id'],)).fetchone()
            if not row:
                metadata=intent.get('metadata') or {}
                if metadata.get('app')=='kiteclub_booking': abort(503,description='Payment fulfillment must complete before refund reconciliation.')
                return  # An unrelated e-shop refund must not affect this application.
            if not allowed(c,row['student_id']): abort(403)
            if not row['purchase_id']: abort(503)
            cents=refund.get('amount')
            if refund.get('currency')!='eur' or type(cents) is not int or not 0<cents<=row['cents']: abort(400)
            status=refund.get('status')
            if status not in ('pending','requires_action','succeeded','failed','canceled'): abort(400)
            old=c.execute('SELECT * FROM stripe_test_refunds WHERE id=?',(rid,)).fetchone()
            if old and (old['order_id']!=row['id'] or old['cents']!=cents): abort(400)
            if old and old['status'] in ('failed','canceled'):
                status=old['status']  # Terminal outcomes cannot regress on concurrent stale reads.
            if old and old['status']=='succeeded' and status in ('pending','requires_action'):
                status='succeeded'
            applied=cents if status=='succeeded' else 0
            previous=old['applied_cents'] if old else 0
            total=c.execute('SELECT COALESCE(SUM(applied_cents),0) FROM stripe_test_refunds WHERE order_id=?',(row['id'],)).fetchone()[0]+applied-previous
            if total>row['cents']: abort(400)
            now=datetime.now().isoformat()
            c.execute("INSERT INTO stripe_test_refunds(id,order_id,cents,status,applied_cents,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,applied_cents=excluded.applied_cents,updated_at=excluded.updated_at",(rid,row['id'],cents,status,applied,now))
            delta=applied-previous
            if delta:
                # Retain the original receipt; append a negative refund (or failure reversal).
                c.execute('INSERT INTO student_payments(student_id,purchase_id,amount,payment_date,method,note,created_at) VALUES(?,?,?,?,?,?,?)',(row['student_id'],row['purchase_id'],-delta/100,now[:10],'stripe_test_refund',f'Stripe refund {rid}: {status}',now))
                # Adjust the contractual net price together with net paid amount: no artificial debt.
                c.execute('UPDATE student_packages SET price=price-?,paid_amount=paid_amount-? WHERE id=?',(delta/100,delta/100,row['purchase_id']))
            c.execute('INSERT OR IGNORE INTO stripe_test_refund_totals(order_id) VALUES(?)',(row['id'],))
            totals=c.execute('SELECT * FROM stripe_test_refund_totals WHERE order_id=?',(row['id'],)).fetchone()
            target=float(Decimal(str(row['hours']))*Decimal(total)/Decimal(row['cents']))
            change=target-totals['revoked_hours']
            purchase=c.execute('SELECT * FROM student_packages WHERE id=?',(row['purchase_id'],)).fetchone()
            balance=c.execute('SELECT credits FROM students WHERE user_id=?',(row['student_id'],)).fetchone()[0]
            review=''
            if (abs(change)>1e-9 and purchase['payment_status']=='cancelled') or (change>1e-9 and (purchase['hours_remaining']+1e-9<change or balance+1e-9<change)):
                review='Οι ώρες έχουν δεσμευτεί, χρησιμοποιηθεί ή προσαρμοστεί. Απαιτείται έλεγχος credits από Admin. Δεν άλλαξαν κρατήσεις.'
            elif abs(change)>1e-9:
                c.execute('UPDATE students SET credits=credits-? WHERE user_id=?',(change,row['student_id']))
                c.execute('UPDATE student_packages SET hours_remaining=hours_remaining-?,hours_total=hours_total-? WHERE id=?',(change,change,row['purchase_id']))
                c.execute('INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)',(row['student_id'],-change,'stripe_refund',f'Stripe refund reconciliation: purchase #{row["purchase_id"]}',now))
                c.execute('UPDATE stripe_test_refund_totals SET revoked_hours=? WHERE order_id=?',(target,row['id']))
            c.execute('UPDATE stripe_test_refund_totals SET review=? WHERE order_id=?',(review,row['id']))

    def require_admin():
        if not enabled(): abort(503)
        user=current_user()
        if not user or user['role']!='admin': abort(403)

    @app.get('/admin/stripe-refunds')
    def admin_stripe_refunds():
        require_admin()
        with connection() as c:
            rows=c.execute("""SELECT r.*,o.student_id,o.purchase_id,o.hours,o.cents original_cents,u.name,
                t.revoked_hours,t.review FROM stripe_test_refunds r
                JOIN stripe_test_orders o ON o.id=r.order_id JOIN users u ON u.id=o.student_id
                LEFT JOIN stripe_test_refund_totals t ON t.order_id=o.id ORDER BY r.updated_at DESC""").fetchall()
        response=app.make_response(render_template('stripe_refunds.html',refunds=rows))
        response.headers['Cache-Control']='no-store'
        return response

    @app.post('/admin/stripe-refunds/<rid>/sync')
    def admin_sync_stripe_refund(rid):
        require_admin()
        with connection() as c:
            if not c.execute('SELECT 1 FROM stripe_test_refunds WHERE id=?',(rid,)).fetchone(): abort(404)
        sync_refund(rid)
        return redirect('/admin/stripe-refunds',303)

    @app.post('/payments/stripe/webhook')
    def stripe_webhook():
        if not configured(): abort(503)
        if request.content_length is None or request.content_length>262144: abort(400)
        try: event=stripe.Webhook.construct_event(request.get_data(),request.headers.get('Stripe-Signature',''),os.environ['STRIPE_WEBHOOK_SECRET'],tolerance=300).to_dict()
        except (ValueError,stripe.SignatureVerificationError): abort(400)
        if event.get('livemode') is not False: abort(400)
        if event['type'] in ('refund.created','refund.updated','refund.failed'):
            sync_refund(event['data']['object']['id'])
            return '',200
        if event['type'] not in ('checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.expired','checkout.session.async_payment_failed'): return '',200
        obj=event['data']['object']; meta=obj.get('metadata') or {}
        if meta.get('app')!='kiteclub_booking': return '',200
        with connection() as c: row=c.execute('SELECT * FROM stripe_test_orders WHERE id=?',(meta.get('order_id'),)).fetchone()
        if not row: return '',200
        with connection() as c:
            if not allowed(c,row['student_id']): abort(403)
        try: paid=app.extensions['stripe_test_gateway']['retrieve'](obj['id'])
        except stripe.StripeError: abort(503)
        metadata=paid.get('metadata') or {}
        if (paid.get('livemode') is not False or paid.get('mode')!='payment' or metadata.get('order_id')!=row['id'] or metadata.get('app')!='kiteclub_booking' or metadata.get('student_id')!=str(row['student_id']) or paid.get('client_reference_id')!=row['id'] or paid.get('id')!=obj['id'] or row['checkout_id'] not in (None,obj['id'])): abort(400)
        if paid.get('payment_status')!='paid' or paid.get('status')!='complete':
            with connection() as c: c.execute("UPDATE stripe_test_orders SET state=? WHERE id=? AND purchase_id IS NULL",('expired' if paid.get('status')=='expired' else 'pending',row['id']))
            return '',200
        items=paid.get('line_items',{}); lines=items.get('data',[])
        if (paid.get('currency')!='eur' or paid.get('amount_total')!=row['cents'] or paid.get('amount_subtotal')!=row['cents'] or len(lines)!=1 or items.get('has_more') or lines[0].get('quantity')!=1 or lines[0].get('amount_total')!=row['cents'] or not paid.get('payment_intent')): abort(400)
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            fresh=c.execute('SELECT * FROM stripe_test_orders WHERE id=?',(row['id'],)).fetchone()
            if fresh['purchase_id']: return '',200
            now=datetime.now().isoformat(); amount=row['cents']/100
            purchase=c.execute('''INSERT INTO student_packages(student_id,package_id,package_name,hours_total,hours_remaining,price,payment_status,purchased_at,paid_at,note,package_type,activation_rule,paid_amount,credits_activated) VALUES(?,?,?,?,0,?,'paid',?,?,?,?,'paid_only',?,0)''',(row['student_id'],row['package_id'],row['name'],row['hours'],amount,now,now,'STRIPE TEST — no real money',row['package_type'],amount)).lastrowid
            c.execute('INSERT INTO student_payments(student_id,purchase_id,amount,payment_date,method,note,created_at) VALUES(?,?,?,?,?,?,?)',(row['student_id'],purchase,amount,now[:10],'stripe_test','Sandbox '+row['id'],now))
            activate(c,c.execute('SELECT * FROM student_packages WHERE id=?',(purchase,)).fetchone(),'Stripe TEST verified payment')
            c.execute("UPDATE stripe_test_orders SET state='paid',checkout_id=?,payment_intent=?,purchase_id=? WHERE id=?",(obj['id'],paid['payment_intent'],purchase,row['id']))
        return '',200

