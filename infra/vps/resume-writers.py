#!/usr/bin/env python3
"""Recover writers paused by a killed backup, without interrupting an active capture."""
import fcntl
import json
from pathlib import Path
import subprocess


def main():
    marker=Path('/etc/volt-debt/backup-paused-writers.json')
    if not marker.exists(): return
    with open('/run/volt-debt-backup.lock','a+') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        if marker.is_symlink(): raise ValueError('Writer recovery marker must not be a symlink')
        identifiers=json.loads(marker.read_text())
        if not isinstance(identifiers,list) or len(identifiers)>2 or len(set(identifiers)) != len(identifiers):
            raise ValueError('Invalid writer recovery list')
        for uid in identifiers:
            if not isinstance(uid,str) or len(uid)!=64 or any(c not in '0123456789abcdef' for c in uid):
                raise ValueError('Invalid writer recovery marker')
            info=json.loads(subprocess.check_output(['docker','inspect',uid],timeout=30))[0]
            labels=info['Config']['Labels']
            if labels.get('com.docker.compose.project')!='volt-debt' or labels.get('com.docker.compose.service') not in ('api','worker'):
                raise ValueError('Recovery marker does not identify an application writer')
            subprocess.run(['docker','start',uid],check=True,stdout=subprocess.DEVNULL,timeout=120)
        marker.unlink()
        print('Recovered application writers from interrupted backup')


if __name__=='__main__':main()
