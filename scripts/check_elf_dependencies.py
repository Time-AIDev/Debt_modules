#!/usr/bin/env python3
"""Verify all ELF files in the custom PostgreSQL installation resolve safely."""
import argparse
from pathlib import Path
import re
import subprocess


def verify(root):
    count=0
    for path in sorted(Path(root).rglob('*')):
        if not path.is_file() or path.is_symlink():continue
        with path.open('rb') as file:
            if file.read(4)!=b'\x7fELF':continue
        result=subprocess.run(['ldd',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              text=True,timeout=30)
        if result.returncode or re.search(r'libxml|libxslt|LLVM|not found',result.stdout,re.I):
            raise RuntimeError('PostgreSQL ELF dependency validation failed: '+path.name)
        count+=1
    if count==0:raise RuntimeError('No PostgreSQL ELF files were checked')
    return count


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    args=parser.parse_args()
    print('Verified %d PostgreSQL ELF files; no XML/XSLT/LLVM or missing dependencies' % verify(args.root))
