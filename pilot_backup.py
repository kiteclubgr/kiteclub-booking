"""Temporary, expiring, read-only pilot inventory and backup access."""
import os, time, hmac, sqlite3, tempfile, tarfile, json, hashlib
from pathlib import Path
from flask import request, abort, jsonify, send_file

def setup_pilot_backup(app, database, uploads):
    def authorized():
        token = os.getenv("PILOT_BACKUP_TOKEN", "")
        try:
            expires = int(os.getenv("PILOT_BACKUP_EXPIRES", "0"))
        except ValueError:
            abort(404)
        if len(token) < 48 or time.time() > expires:
            abort(404)
        if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            abort(404)

    def connect():
        path = Path(database).resolve(strict=True)
        return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)

    def inventory(con):
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        quote = lambda s: '"' + s.replace('"', '""') + '"'
        counts = {t: con.execute("SELECT COUNT(*) FROM " + quote(t)).fetchone()[0] for t in tables}
        users = []
        if "users" in tables:
            cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
            selected = [c for c in ("id", "email", "name", "role", "active") if c in cols]
            users = [dict(zip(selected, row)) for row in con.execute("SELECT " + ",".join(map(quote, selected)) + " FROM users ORDER BY id")]
        files = [p for p in Path(uploads).rglob("*") if p.is_file()] if Path(uploads).exists() else []
        return {"database":str(Path(database).resolve()), "uploads":str(Path(uploads).resolve()),
                "counts":counts, "users":users, "upload_files":len(files),
                "upload_bytes":sum(p.stat().st_size for p in files),
                "integrity_check":[r[0] for r in con.execute("PRAGMA integrity_check")],
                "foreign_key_check":[list(r) for r in con.execute("PRAGMA foreign_key_check")]}

    @app.get("/_pilot_backup/inventory")
    def pilot_backup_inventory():
        authorized()
        with connect() as con:
            result = inventory(con)
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/_pilot_backup/download")
    def pilot_backup_download():
        authorized()
        tmp = tempfile.TemporaryDirectory(prefix="kiteclub-backup-")
        try:
            root = Path(tmp.name)
            snapshot = root / "kiteclub.db"
            with connect() as source, sqlite3.connect(snapshot) as dest:
                source.backup(dest)
                report = inventory(dest)
                if report["integrity_check"] != ["ok"]:
                    raise RuntimeError("Backup integrity failed")
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            manifest = {"created_unix":time.time(), "inventory":report, "sha256":{"kiteclub.db":digest(snapshot)}}
            archive = root / "KiteClub-production-backup.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(snapshot, arcname="kiteclub.db")
                upload_root = Path(uploads).resolve()
                if upload_root.exists():
                    for p in sorted(upload_root.rglob("*")):
                        if p.is_symlink():
                            raise RuntimeError("Upload symlink requires manual review")
                        if p.is_file():
                            name = "uploads/" + str(p.relative_to(upload_root))
                            before = digest(p)
                            tar.add(p, arcname=name, recursive=False)
                            if digest(p) != before:
                                raise RuntimeError("Uploads changed during backup; retry")
                            manifest["sha256"][name] = before
                manifest_path = root / "manifest.json"
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                tar.add(manifest_path, arcname="manifest.json")
            response = send_file(archive, as_attachment=True, download_name=archive.name)
            response.headers["Cache-Control"] = "no-store"
            response.call_on_close(tmp.cleanup)
            return response
        except Exception:
            tmp.cleanup()
            raise
