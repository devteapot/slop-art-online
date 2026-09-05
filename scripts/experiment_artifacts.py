#!/usr/bin/env python3
"""Freeze runnable local implementations and verify them before an experiment.

Bundles contain source and executable artifacts, never local credentials or live sessions.
They are snapshots of a working tree, including uncommitted implementation changes.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLES = ('target/debug/sao-dev-client', 'target/debug/sao-agent-mcp',
               'target/debug/examples/participant_live_agent',
               'target/wasm32-unknown-unknown/release/server_module.wasm')
SOURCE_ROOTS = ('simulation', 'server', 'client', 'shared', 'configs', 'scenarios', 'scripts', 'docs')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def verify(folder):
    manifest=json.loads((folder/'implementation.json').read_text())
    if manifest.get('format')!='sao-implementation-v1':raise ValueError('Unknown implementation bundle format')
    for name,expected in manifest['files'].items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or digest(path)!=expected:
            raise ValueError(f'Implementation artifact missing or changed: {name}')
    for name in EXECUTABLES:
        if name not in manifest['files']:raise ValueError(f'Implementation lacks {name}')
    return manifest


def freeze(out,label):
    if out.exists():raise ValueError('Choose a new implementation directory')
    for name in (*EXECUTABLES,'client/dist-participant/index.html'):
        if not (ROOT/name).is_file():raise ValueError(f'Build required artifact first: {name}')
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    sources=[]
    for name in names:
        p=Path(name)
        if not name or any(part.startswith('.') for part in p.parts):continue
        if name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml') or any(name==r or name.startswith(r+'/') for r in SOURCE_ROOTS):
            if (ROOT/name).is_file():sources.append(name)
    out.mkdir(parents=True)
    files={}
    try:
        for name in sorted(set([*sources,*EXECUTABLES])):
            source=ROOT/name;target=out/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
            if name in EXECUTABLES and not name.endswith('.wasm') and shutil.which('strip'):
                subprocess.run(['strip','--strip-debug',str(target)],check=True,capture_output=True)
            files[name]=digest(target)
        for source in (ROOT/'client/dist-participant').rglob('*'):
            if not source.is_file():continue
            name=str(source.relative_to(ROOT));target=out/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target);files[name]=digest(target)
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        manifest=dict(format='sao-implementation-v1',label=label,base_commit=revision,
                      source_state='frozen working tree; file hashes include uncommitted source',files=files)
        write(out/'implementation.json',manifest)
        verify(out)
    except Exception:
        # Keep incomplete artifacts inspectable; no manifest means they cannot launch.
        (out/'implementation.json').unlink(missing_ok=True)
        raise
    print(f'Frozen {label}: {out} ({len(files)} hashed artifacts)')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('freeze','verify'));parser.add_argument('directory',type=Path)
    parser.add_argument('--label',default='working-tree')
    args=parser.parse_args();folder=args.directory.resolve()
    if args.command=='freeze':freeze(folder,args.label)
    else:print(verify(folder)['label']+': artifact hashes verified')
