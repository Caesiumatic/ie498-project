"""Create a portable delivery with a consistent DB snapshot and no credentials."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ie498.storage import Store, atomic_json
from ie498.backup import snapshot, restore, file_hash
from ie498.runner import coordinator_lock


def main():
    store=Store(ROOT/'data/runs/live')
    with coordinator_lock(store):
        pending=store.rows("SELECT COUNT(*) n FROM api_attempts WHERE status='pending'")[0]['n']
        if pending:raise ValueError('Reconcile interrupted requests before final packaging')
        snap=snapshot(store,ROOT/'data/backups/batches')
        verified=ROOT/'data/restored'/snap.name
        restore(snap,verified)
        receipt=ROOT/'reports/restore_verification.json'
        atomic_json(receipt,{'snapshot':str(snap),'restored_to':str(verified),
            'verified_files':len(json.loads((snap/'manifest.json').read_text())['files']),
            'all_file_checksums_matched':True,'sqlite_integrity':'ok','independent_backup':False})
        bundle=ROOT/'reports/repository.bundle'
        subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
        tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        dest=ROOT.parent/'IE498_project.zip'
        temporary=dest.with_suffix('.zip.tmp')
        checksums={}
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            def add(path,name):
                if Path(name).name=='.env' or Path(name).name.startswith('.env.') and Path(name).name!='.env.example':
                    raise ValueError('Secret file cannot be packaged')
                digest=hashlib.sha256();carry=b''
                with path.open('rb') as source, archive.open('ie498/'+name,'w',force_zip64=True) as target:
                    for chunk in iter(lambda:source.read(1024*1024),b''):
                        if re.search(rb'sk-proj-[A-Za-z0-9_-]{32,}',carry+chunk):
                            raise ValueError(f'Possible secret in {name}')
                        digest.update(chunk);target.write(chunk);carry=chunk[-128:]
                checksums[name]=digest.hexdigest()
            for rel in tracked:
                if rel and (ROOT/rel).is_file():add(ROOT/rel,rel)
            for path in (ROOT/'reports/live').rglob('*'):
                rel=str(path.relative_to(ROOT))
                if path.is_file() and rel not in tracked:add(path,rel)
            if 'reports/repository.bundle' not in tracked:add(bundle,'reports/repository.bundle')
            if 'reports/restore_verification.json' not in tracked:add(receipt,'reports/restore_verification.json')
            for path in snap.rglob('*'):
                if path.is_file():add(path,'data/runs/live/'+str(path.relative_to(snap)))
            archive.writestr('ie498/DELIVERY_MANIFEST.json',json.dumps(checksums,indent=2))
        temporary.replace(dest)
        manifest={'archive':str(dest),'sha256':file_hash(dest),
                  'snapshot':str(snap),'verified_restore':str(verified),'files':len(checksums),
                  'credential_files_included':False,'independent_backup':False}
        atomic_json(ROOT/'reports/delivery_manifest.json',manifest)
        print(json.dumps(manifest,indent=2))
    store.close()


if __name__=='__main__':main()
