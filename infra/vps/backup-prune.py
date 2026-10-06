#!/usr/bin/env python3
"""Delete old local backups only after verified restore and encrypted off-server copy."""
import argparse
import json
import sys
from pathlib import Path
import shutil
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_evidence import verified_offsite


def candidates(root,days,keep):
    root = Path(root)
    if root.is_symlink(): raise ValueError('Backup root must not be a symlink')
    complete=sorted((p for p in root.iterdir() if not p.is_symlink() and p.is_dir() and (p/'COMPLETE').is_file()),
                    key=lambda p:p.stat().st_mtime,reverse=True)
    for backup in complete[keep:]:
        if backup.stat().st_mtime > time.time()-days*86400: continue
        try:
            restore=json.loads((backup/'restore-evidence.json').read_text())
            offsite=json.loads((backup/'offsite-evidence.json').read_text())
        except (OSError,ValueError):continue
        if restore.get('status')=='passed' and verified_offsite(backup, offsite):
            yield backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/srv/volt-debt-backups'))
    parser.add_argument('--days',type=int,default=30)
    parser.add_argument('--keep',type=int,default=7)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.days<7 or args.keep<2:raise SystemExit('Minimum retention is7days and2completed backups')
    rows=list(candidates(args.root,args.days,args.keep))
    for backup in rows:
        if args.apply:shutil.rmtree(backup)
    print(json.dumps({'applied':args.apply,'eligible_backups':len(rows)}))


if __name__=='__main__':main()
