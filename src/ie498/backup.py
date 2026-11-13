import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone
from .storage import atomic_json


def file_hash(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):
            h.update(part)
    return h.hexdigest()


def snapshot(store, destination):
    dest = Path(destination) / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest.mkdir(parents=True)
    target = sqlite3.connect(dest / 'experiments.sqlite')
    store.db.backup(target); target.close()
    # Copy only immutable records referenced by the consistent SQLite snapshot.
    db = sqlite3.connect(dest/'experiments.sqlite'); db.row_factory=sqlite3.Row
    for row in db.execute('SELECT id,raw_path FROM api_attempts'):
        for rel in [row['raw_path'],f"requests/{row['id']}.json"]:
            if rel and (store.root/rel).exists():
                (dest/rel).parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(store.root/rel,dest/rel)
    commits={r[0] for r in db.execute('SELECT DISTINCT commit_hash FROM runs')}
    if db.execute("SELECT name FROM sqlite_master WHERE name='execution_epochs'").fetchone():
        commits.update(r[0] for r in db.execute('SELECT DISTINCT commit_hash FROM execution_epochs'))
    commits=sorted(commits);db.close()
    manifest={"source":str(store.root.resolve()),"code_commits":commits,"independent_backup":False,
              "files":{str(p.relative_to(dest)):file_hash(p) for p in dest.rglob('*') if p.is_file()}}
    atomic_json(dest/'manifest.json',manifest)
    return dest


def restore(source, destination):
    src=Path(source);dest=Path(destination)
    if dest.exists():
        raise ValueError('Restore destination must be new')
    manifest=json.loads((src/'manifest.json').read_text())
    for rel,sha in manifest['files'].items():
        path=(src/rel).resolve()
        if not path.is_relative_to(src.resolve()) or file_hash(path)!=sha:
            raise ValueError(f'Backup integrity failure: {rel}')
    dest.mkdir(parents=True)
    for rel in manifest['files']:
        (dest/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src/rel,dest/rel)
    db=sqlite3.connect(dest/'experiments.sqlite')
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0];db.close()
    if integrity!='ok':raise ValueError(integrity)
    return dest
