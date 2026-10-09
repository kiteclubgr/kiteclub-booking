"""Consistent SQLite backup + uploads snapshot. Run on a schedule from the persistent server volume."""
import argparse
import os
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def backup(data_dir, output_dir):
    data = Path(data_dir).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = data / 'kiteclub.db'
    if not source.is_file():
        raise FileNotFoundError(f'Database not found: {source}')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = out / f'kiteclub-backup-{stamp}.tar.gz'
    temporary_db = out / f'.kiteclub-{stamp}.db'
    try:
        with sqlite3.connect(str(source)) as origin, sqlite3.connect(str(temporary_db)) as dest:
            origin.backup(dest)
            status = dest.execute('PRAGMA integrity_check').fetchone()[0]
            if status != 'ok':
                raise RuntimeError(f'Database integrity check failed: {status}')
        with tarfile.open(target, 'w:gz') as archive:
            archive.add(temporary_db, arcname='kiteclub.db')
            uploads = data / 'uploads'
            if uploads.is_dir():
                archive.add(uploads, arcname='uploads')
        return target
    finally:
        temporary_db.unlink(missing_ok=True)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=os.getenv('DATA_DIR', str(ROOT)))
    ap.add_argument('--output-dir', required=True, help='Choose an off-volume backup destination')
    args = ap.parse_args()
    print(backup(args.data_dir, args.output_dir))
