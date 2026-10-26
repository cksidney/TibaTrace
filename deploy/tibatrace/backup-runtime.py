#!/usr/bin/env python3
"""Coordinated, encrypted and authenticated TibaTrace backup; no automatic pruning.

Dry-run by default. Apply stops only TibaTrace API/worker/beat, captures DB,
clinical files and runtime configuration, verifies archives, and restarts writers
in a finally block. Requires an independently provisioned owner-only recovery key.
Provider connections and scan flags are never changed.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


def protected_key(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError('Backup key must be an operator-owned regular file with 0600 permissions.')
    value = path.read_bytes().strip()
    if len(value) < 43 or len(value) > 4096:
        raise ValueError('Provision a random recovery passphrase with at least 256 bits of entropy.')
    try:
        raw = base64.b64decode(value+b'='*(-len(value)%4),altchars=b'-_',validate=True)
        if len(raw) < 32 or path.read_bytes() not in (value,value+b'\n'):
            raise ValueError('Invalid passphrase encoding.')
    except ValueError:
        raise ValueError('Use a single-line base64url-encoded random recovery passphrase of at least 32 bytes.') from None
    return value


def file_auth(path, key):
    digest = hmac.new(hmac.digest(key, b'TibaTrace backup ciphertext authentication v1', 'sha256'), digestmod='sha256')
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(target, key):
    manifest = json.loads((target/'MANIFEST.json').read_text())
    signature = manifest.pop('manifest_hmac_sha256')
    canonical = json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    expected = hmac.digest(hmac.digest(key,b'TibaTrace backup manifest authentication v1','sha256'),canonical,'sha256').hex()
    if not hmac.compare_digest(signature,expected):
        raise ValueError('Backup manifest authentication failed.')
    names = {'database.dump.enc','configuration.tar.gz.enc','clinical-objects.tar.gz.enc'}
    if set(manifest['files']) != names:
        raise ValueError('Unexpected backup inventory.')
    for name,record in manifest['files'].items():
        path = target/name
        if path.is_symlink() or path.stat().st_size != record['bytes'] or not hmac.compare_digest(record['ciphertext_hmac_sha256'],file_auth(path,key)):
            raise ValueError('Backup archive authentication failed.')
    return manifest


def pipeline(source, destination, *, log, env=None, output=None):
    first = subprocess.Popen(source, stdout=subprocess.PIPE, stderr=log, env=env)
    try:
        second = subprocess.run(destination, stdin=first.stdout, stdout=output, stderr=log)
    finally:
        first.stdout.close()
    if first.wait() or second.returncode:
        raise RuntimeError('Backup or verification pipeline failed; inspect the protected operations log.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/tibatrace'))
    parser.add_argument('--recovery-key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New protected backup directory, preferably on the approved separate target.')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--verify-only', action='store_true', help='Authenticate an existing manifest and every encrypted payload before recovery.')
    args = parser.parse_args()
    os.umask(0o077)
    key = protected_key(args.recovery_key_file)
    if args.verify_only:
        verify_backup(args.output.resolve(strict=True),key)
        print('Backup manifest and every ciphertext authentication verified. No decryption or restore was performed.')
        return
    root = args.root.resolve()
    release = (root/'current').resolve(strict=True)
    config = root/'secrets/.env.production'
    if args.output.exists():
        parser.error('Backup output already exists; never overwrite a recovery point.')
    target = args.output.resolve()
    if args.recovery_key_file.resolve().is_relative_to(target):
        parser.error('Recovery key must not be inside the backup archive directory.')
    if not args.apply:
        print(json.dumps({'mode':'DRY_RUN','release':str(release),'writes':0,
            'required_approval':'Owner-approved destination, key custody, maintenance, RPO/RTO and retention schedule',
            'off_host_custody':'MUST_BE_VERIFIED_BY_OPERATIONS'}))
        return
    if os.geteuid() != 0:
        parser.error('Production backup requires the approved root operations context.')
    target.mkdir(mode=0o700,parents=True)
    compose = ['docker','compose','--env-file',str(config),'-f',str(release/'deploy/tibatrace/docker-compose.yml'),
               '-f',str(release/'deploy/tibatrace/docker-compose.server.yml')]
    env = dict(os.environ, TIBATRACE_ENV_FILE=str(config))
    runtime = json.loads(subprocess.check_output(['docker','inspect','tibatrace-api-1']))[0]
    runtime_env = dict(row.split('=',1) for row in runtime['Config']['Env'] if '=' in row)
    database = urlparse(runtime_env['DAWATRACE_DATABASE_URL'])
    if database.scheme not in ('postgres','postgresql'):
        parser.error('Only the PostgreSQL production backup workflow is supported.')
    pg_env = dict(os.environ,PGHOST=database.hostname or 'localhost',PGPORT=str(database.port or 5432),
        PGDATABASE=unquote(database.path.lstrip('/')),PGUSER=unquote(database.username or ''),
        PGPASSWORD=unquote(database.password or ''),PGSSLMODE=runtime_env.get('DAWATRACE_DATABASE_SSLMODE','require'))
    volume = Path(subprocess.check_output(['docker','volume','inspect','tibatrace_clinical-objects',
        '--format','{{.Mountpoint}}'],text=True).strip())
    clinical_bytes = sum(p.stat().st_size for p in volume.rglob('*') if p.is_file() and
                         p.relative_to(volume).parts[0] != 'pos-releases')
    if shutil.disk_usage(target).free < clinical_bytes + 512*1024*1024:
        parser.error('Insufficient destination headroom for clinical files plus database/config backup.')
    flags = ['-aes-256-cbc','-pbkdf2','-iter','200000','-pass','file:'+str(args.recovery_key_file)]
    def decrypt(name):
        return ['openssl','enc','-d',*flags,'-in',str(target/name)]
    stopped = False
    with (target/'operations.log').open('wb') as log:
        try:
            subprocess.run(compose+['config','--quiet'],env=env,stdout=log,stderr=log,check=True)
            stopped = True  # a partially failed stop must still resume every writer
            subprocess.run(compose+['stop','-t','60','beat','api','worker'],env=env,stdout=log,stderr=log,check=True)
            sources = {
                'database.dump.enc': (['pg_dump','--format=custom','--no-owner','--no-acl'],pg_env),
                'configuration.tar.gz.enc': (['tar','-czf','-','-C',str(config.parent),config.name],None),
                'clinical-objects.tar.gz.enc': (['tar','--exclude=./pos-releases','-czf','-','-C',str(volume),'.'],None),
            }
            for name,(command,source_env) in sources.items():
                pipeline(command,['openssl','enc',*flags,'-salt','-out',str(target/name)],log=log,env=source_env)
            files = {name:{'bytes':(target/name).stat().st_size,'ciphertext_hmac_sha256':file_auth(target/name,key)} for name in sources}
            for name in files:
                if not hmac.compare_digest(files[name]['ciphertext_hmac_sha256'],file_auth(target/name,key)):
                    raise RuntimeError('Backup authentication failed.')
            pipeline(decrypt('database.dump.enc'),['pg_restore','--file=/dev/null'],log=log,output=log)
            with open(os.devnull,'wb') as sink:
                for name in ('configuration.tar.gz.enc','clinical-objects.tar.gz.enc'):
                    pipeline(decrypt(name),['tar','-tzf','-'],log=log,output=sink)
            manifest = {'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'backend_image':runtime['Config']['Image'],
                'source_release':str(release),'files':files,'clinical_bytes':clinical_bytes,
                'verification':'Authenticated encrypted files, parsed database archive and decrypted tar inventories; NOT a full restore exercise',
                'excluded':'Unchanged public POS installers only','automatic_pruning':False,
                'separate_target_and_key_custody':'OPERATOR_EVIDENCE_REQUIRED'}
            canonical = json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
            manifest['manifest_hmac_sha256'] = hmac.digest(hmac.digest(key,b'TibaTrace backup manifest authentication v1','sha256'),canonical,'sha256').hex()
            (target/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
            verify_backup(target,key)
        finally:
            if stopped:
                subprocess.run(compose+['up','-d','api','worker','beat'],env=env,stdout=log,stderr=log,check=True)
    print(json.dumps({'backup_directory':str(target),'archive_verification':'passed','writers_resumed':True,
                      'full_restore_exercise':'STILL_REQUIRED'}))


if __name__ == '__main__':
    main()
