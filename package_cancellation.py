"""Audited cancellation of unpaid lesson purchases; no booking or cash mutations."""
import hashlib
import hmac
import json
import math
from datetime import datetime, timezone
from flask import abort, flash, redirect, render_template, request, url_for


class CancellationError(ValueError):
    pass


def setup_package_cancellation(app, db, current_user):
    con = db()
    try:
        con.execute('''CREATE TABLE IF NOT EXISTS package_cancellations (
            purchase_id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL, cancelled_at TEXT NOT NULL, reason TEXT NOT NULL,
            original_price REAL NOT NULL, removed_credits REAL NOT NULL,
            manual_ledger_id INTEGER UNIQUE, replacement_purchase_id INTEGER,
            details_json TEXT NOT NULL)''')
        con.commit()
    finally:
        con.close()

    def admin_user():
        user = current_user()
        if not user or user['role'] != 'admin':
            abort(403)
        return user

    def number(value):
        result = float(value or 0)
        if not math.isfinite(result):
            raise CancellationError('Μη έγκυρα αριθμητικά δεδομένα. Απαιτείται έλεγχος.')
        return result

    def plan(con, purchase_id, form):
        p = con.execute('SELECT * FROM student_packages WHERE id=?', (purchase_id,)).fetchone()
        if not p:
            abort(404)
        if p['payment_status'] == 'cancelled' or con.execute(
                'SELECT 1 FROM package_cancellations WHERE purchase_id=?', (purchase_id,)).fetchone():
            raise CancellationError('Η αγορά έχει ήδη ακυρωθεί. Δεν έγινε νέα μεταβολή.')
        if p['payment_status'] not in ('unpaid', 'pending') or number(p['paid_amount']) != 0 or con.execute(
                'SELECT 1 FROM student_payments WHERE purchase_id=?', (purchase_id,)).fetchone():
            raise CancellationError('Η αγορά έχει πληρωμές ή κατάσταση που απαιτεί ξεχωριστό οικονομικό έλεγχο. Δεν ακυρώθηκε.')
        if (p['package_type'] or 'lesson') not in ('lesson', 'group_2p', 'group_3p'):
            raise CancellationError('Η ακύρωση Crew δεν υποστηρίζεται από αυτή την ενέργεια.')
        reason = (form.get('reason') or '').strip()
        if not 5 <= len(reason) <= 1000:
            raise CancellationError('Συμπλήρωσε αιτιολογία 5–1000 χαρακτήρων.')
        st = con.execute('SELECT credits FROM students WHERE user_id=?', (p['student_id'],)).fetchone()
        if not st:
            raise CancellationError('Ο μαθητής δεν βρέθηκε.')
        credits = number(st['credits'])
        remaining = number(p['hours_remaining'])
        total = number(p['hours_total'])
        if total <= 0 or remaining < 0 or remaining > total + 1e-8:
            raise CancellationError('Ασυνεπείς ώρες πακέτου. Δεν έγινε ακύρωση.')
        usages = [dict(r) for r in con.execute('''SELECT booking_id, SUM(amount) net
            FROM package_usage WHERE student_package_id=? GROUP BY booking_id
            ORDER BY booking_id''', (purchase_id,))]
        if any(r['booking_id'] is None or number(r['net']) > 1e-8 for r in usages):
            raise CancellationError('Το ιστορικό κατανάλωσης απαιτεί έλεγχο.')
        used = sum(-number(r['net']) for r in usages)
        active = int(p['credits_activated'] or 0) == 1
        if active and abs(remaining + used - total) > 1e-8:
            raise CancellationError('Οι ώρες πακέτου δεν συμφωνούν με το ιστορικό κατανάλωσης.')
        if not active and (used > 1e-8 or remaining > 1e-8):
            raise CancellationError('Μη ενεργοποιημένη αγορά με κινήσεις ωρών. Απαιτείται έλεγχος.')
        mode = form.get('mode', 'normal')
        manual = replacement = None
        if mode == 'manual':
            try:
                mid = int(form.get('manual_ledger_id', ''))
            except (TypeError, ValueError):
                raise CancellationError('Επίλεξε την προηγούμενη χειροκίνητη αφαίρεση.')
            manual = con.execute('SELECT * FROM credit_ledger WHERE id=?', (mid,)).fetchone()
            if not active or not manual or manual['student_id'] != p['student_id'] or manual['kind'] != 'manual_adjustment' or manual['booking_id'] is not None or abs(number(manual['amount']) + total) > 1e-8:
                raise CancellationError('Η επιλεγμένη κίνηση πρέπει να είναι χειροκίνητη αφαίρεση όλων των ωρών αυτής της αγοράς, του ίδιου μαθητή.')
            if not manual['created_at'] or manual['created_at'] < p['purchased_at']:
                raise CancellationError('Η χειροκίνητη αφαίρεση προηγείται της αγοράς.')
            if con.execute('SELECT 1 FROM package_cancellations WHERE manual_ledger_id=?', (mid,)).fetchone():
                raise CancellationError('Η χειροκίνητη αφαίρεση έχει ήδη συνδεθεί με άλλη ακύρωση.')
            if form.get('manual_ack') != 'yes':
                raise CancellationError('Επιβεβαίωσε ότι η επιλεγμένη κίνηση διορθώνει τη συγκεκριμένη αγορά.')
            if used > 1e-8:
                try:
                    rid = int(form.get('replacement_purchase_id', ''))
                except (TypeError, ValueError):
                    raise CancellationError('Επίλεξε το σωστό πακέτο για τη μεταφορά της κατανάλωσης.')
                replacement = con.execute('SELECT * FROM student_packages WHERE id=?', (rid,)).fetchone()
                if not replacement or rid == purchase_id or replacement['student_id'] != p['student_id'] or replacement['payment_status'] == 'cancelled' or not int(replacement['credits_activated'] or 0) or (replacement['package_type'] or 'lesson') not in ('lesson', 'group_2p', 'group_3p') or number(replacement['hours_remaining']) + 1e-8 < used:
                    raise CancellationError('Το πακέτο αντικατάστασης δεν διαθέτει επαρκείς ενεργές ώρες του ίδιου μαθητή.')
            removed = 0.0
        elif mode == 'normal':
            if used > 1e-8:
                raise CancellationError('Η αγορά έχει χρησιμοποιηθεί σε κρατήσεις. Η απλή ακύρωση δεν επιτρέπεται. Εάν πρόκειται για ήδη χειροκίνητα διορθωμένη αγορά, χρησιμοποίησε τη σχετική επιλογή.')
            removed = remaining if active else 0.0
            if credits + 1e-8 < removed:
                raise CancellationError('Το υπόλοιπο credits δεν επαρκεί. Έλεγξε αν έχει προηγηθεί χειροκίνητη αφαίρεση.')
        else:
            raise CancellationError('Μη έγκυρη επιλογή ακύρωσης.')
        return dict(purchase=dict(p), reason=reason, mode=mode, credits=credits,
                    remaining=remaining, used=used, removed=removed,
                    manual=dict(manual) if manual else None,
                    replacement=dict(replacement) if replacement else None, usages=usages)

    def signature(data):
        payload = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        key = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    @app.route('/admin/package-purchases/<int:purchase_id>/cancel', methods=['GET', 'POST'])
    def admin_package_purchase_cancel(purchase_id):
        user = admin_user()
        con = db()
        try:
            p = con.execute('SELECT * FROM student_packages WHERE id=?', (purchase_id,)).fetchone()
            if not p:
                abort(404)
            preview = error = None
            if request.method == 'POST':
                con.execute('BEGIN IMMEDIATE')
                try:
                    preview = plan(con, purchase_id, request.form)
                    if request.form.get('action') == 'confirm':
                        if not hmac.compare_digest(request.form.get('preview_token', ''), signature(preview)):
                            raise CancellationError('Τα δεδομένα άλλαξαν. Ζήτησε νέα προεπισκόπηση πριν την ακύρωση.')
                        p = preview['purchase']
                        now = datetime.now(timezone.utc).isoformat()
                        sid = p['student_id']
                        note = f"Ακύρωση αγοράς #{purchase_id}: {preview['reason']}"
                        if preview['manual']:
                            # Keep the original manual movement; explicitly reverse it and
                            # withdraw the original grant. Net student balance is unchanged.
                            total = float(p['hours_total'])
                            for amount, kind in ((total, 'manual_correction_reversal'), (-total, 'package_cancel')):
                                con.execute('INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)',
                                            (sid, amount, kind, note + f" · manual #{preview['manual']['id']}", now))
                            if preview['replacement']:
                                rid = preview['replacement']['id']
                                for usage in preview['usages']:
                                    amount = -float(usage['net'])
                                    if amount <= 1e-8:
                                        continue
                                    for pid, change in ((purchase_id, amount), (rid, -amount)):
                                        con.execute('INSERT INTO package_usage(student_package_id,student_id,booking_id,amount,kind,created_at) VALUES(?,?,?,?,?,?)',
                                                    (pid, sid, usage['booking_id'], change, 'cancellation_transfer', now))
                                con.execute('UPDATE student_packages SET hours_remaining=hours_remaining-? WHERE id=?', (preview['used'], rid))
                        elif preview['removed']:
                            con.execute('UPDATE students SET credits=credits-? WHERE user_id=?', (preview['removed'], sid))
                            con.execute('INSERT INTO credit_ledger(student_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)',
                                        (sid, -preview['removed'], 'package_cancel', note, now))
                        # Keep original price for historical evidence. Cancelled debt is excluded.
                        con.execute("UPDATE student_packages SET payment_status='cancelled',hours_remaining=0,note=COALESCE(note,'') || ? WHERE id=?", (' | ' + note, purchase_id))
                        con.execute('INSERT INTO package_cancellations VALUES(?,?,?,?,?,?,?,?,?,?)',
                                    (purchase_id, sid, user['id'], now, preview['reason'], p['price'], preview['removed'],
                                     preview['manual']['id'] if preview['manual'] else None,
                                     preview['replacement']['id'] if preview['replacement'] else None,
                                     json.dumps(preview, ensure_ascii=False, sort_keys=True)))
                        con.commit()
                        flash('Η αγορά ακυρώθηκε. Δεν καταχωρίστηκε πληρωμή. Οι κρατήσεις δεν άλλαξαν.')
                        return redirect(url_for('admin_student_profile', student_id=sid) + '#payments')
                    if request.form.get('action') != 'preview':
                        raise CancellationError('Ζήτησε πρώτα προεπισκόπηση.')
                    con.rollback()
                except CancellationError as exc:
                    con.rollback()
                    error = str(exc)
                    preview = None
            manual_rows = con.execute("SELECT * FROM credit_ledger WHERE student_id=? AND kind='manual_adjustment' AND amount<0 ORDER BY id DESC", (p['student_id'],)).fetchall()
            replacements = con.execute("SELECT * FROM student_packages WHERE student_id=? AND id<>? AND payment_status<>'cancelled' AND credits_activated=1 AND hours_remaining>0 ORDER BY purchased_at,id", (p['student_id'], purchase_id)).fetchall()
            audit = con.execute('SELECT pc.*,u.name actor_name FROM package_cancellations pc LEFT JOIN users u ON u.id=pc.actor_id WHERE pc.purchase_id=?', (purchase_id,)).fetchone()
            return render_template('package_cancel.html', purchase=p, preview=preview, error=error,
                                   preview_token=signature(preview) if preview else None,
                                   manual_rows=manual_rows, replacements=replacements, audit=audit)
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
