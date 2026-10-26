#!/usr/bin/env python3
"""Isolated synthetic DB + clinical-object + identifier/MFA-key recovery exercise.

Creates its own PostgreSQL cluster on a private Unix socket with TCP disabled.
Never accepts a database URL, production environment file, or real backup.
This proves the tested engineering path, not production recovery or off-site custody.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]

HELPER = r'''
import json,os,hashlib,time
from pathlib import Path
from django.conf import settings
keys=json.loads(Path(os.environ['TIBATRACE_REHEARSAL_KEYS']).read_text())
settings.DATABASES['default']={'ENGINE':'django.db.backends.postgresql','NAME':os.environ['PGDATABASE'],
    'USER':os.environ['PGUSER'],'HOST':os.environ['PGHOST'],'PORT':'5432','OPTIONS':{'sslmode':'disable'}}
settings.MEDIA_ROOT=Path(os.environ['TIBATRACE_REHEARSAL_OBJECTS'])
settings.DAWATRACE_PATIENT_IDENTIFIER_KEYS={'rehearsal-id':keys['identifier']}
settings.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID='rehearsal-id'
settings.DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS={'rehearsal-lookup':keys['lookup']}
settings.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID='rehearsal-lookup'
settings.DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS=[]
settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS={'rehearsal-object':keys['object']}
settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID='rehearsal-object'
settings.TIBATRACE_MFA_ENCRYPTION_KEYS={'rehearsal-mfa':keys['mfa']}
settings.TIBATRACE_MFA_ACTIVE_KEY_ID='rehearsal-mfa'
settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED=False
settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=False
import django
django.setup()
from django.core.management import call_command
from apps.tenancy.models import Tenant
from apps.identity.models import User
from apps.identity import mfa
from apps.patients.models import Patient,PatientIdentifier
from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage as storage
import pyotp
phase=os.environ['TIBATRACE_REHEARSAL_PHASE']
if phase=='seed':
    call_command('migrate',verbosity=0,interactive=False)
    tenant=Tenant.objects.create(name='Synthetic recovery source',slug='recovery-source')
    Tenant.objects.create(name='Synthetic recovery boundary',slug='recovery-boundary')
    actor=User.objects.create_user(username='synthetic-recovery',tenant=tenant,is_platform_admin=True)
    patient=Patient.all_objects.create(tenant=tenant,internal_reference_id='synthetic-recovery-patient',sex='UNKNOWN')
    PatientIdentifier(tenant=tenant,patient=patient,system='urn:synthetic:recovery',identifier_type='HOSPITAL_NUMBER',value='Synthetic Ab 42').save()
    storage.store(tenant_id=tenant.pk,patient=patient,actor=actor,original_name='synthetic.txt',content_type='text/plain',content=b'Synthetic recovery fixture only; no patient data.')
    setup=mfa.begin_enrollment(actor,'synthetic-recovery-nonce')
    assert mfa.verify(actor,pyotp.TOTP(setup['secret']).now(),enrollment_nonce='synthetic-recovery-nonce')
tenant=Tenant.objects.get(slug='recovery-source')
other=Tenant.objects.get(slug='recovery-boundary')
identifier=PatientIdentifier.all_objects.get(tenant=tenant)
assert identifier.value=='' and identifier.value_for_exchange()=='Synthetic Ab 42'
assert PatientIdentifier.matching_value(tenant_id=tenant.pk,value='Synthetic Ab 42',system='urn:synthetic:recovery').count()==1
assert PatientIdentifier.matching_value(tenant_id=other.pk,value='Synthetic Ab 42',system='urn:synthetic:recovery').count()==0
doc=StoredClinicalDocument.all_objects.get(tenant=tenant)
content,key=storage._decrypt_path(storage._path(doc.object_key),object_key=doc.object_key)
assert key=='rehearsal-object' and hashlib.sha256(content).hexdigest()==doc.hash_sha256
assert doc.malware_scan_status=='NOT_SCANNED'
credential=mfa.MfaCredential.objects.get(user__username='synthetic-recovery')
secret=mfa._unseal(credential)
assert pyotp.TOTP(secret).verify(pyotp.TOTP(secret).now())
assert credential.enabled_at and len(credential.recovery_hashes)==10
print(json.dumps({'identifier_read_lookup_and_boundary':'passed','clinical_object_hash_and_decrypt':'passed',
    'mfa_key_readback':'passed','mfa_seed_hash':hashlib.sha256(secret.encode()).hexdigest(),
    'scanner_state':'NOT_SCANNED','provider_requests':0},sort_keys=True))
'''


def run(args, *, env, log, input_data=None):
    result = subprocess.run(args, cwd=ROOT/'backend', env=env, input=input_data,
                            stdout=subprocess.PIPE, stderr=log)
    if result.returncode:
        raise RuntimeError('Synthetic rehearsal step failed; see its protected log.')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--expected-major', type=int, default=16)
    parser.add_argument('--output', type=Path, required=True, help='New dedicated rehearsal directory; never an existing directory.')
    args = parser.parse_args()
    os.umask(0o077)
    version = subprocess.check_output([str(args.postgres_bin/'postgres'),'--version'], text=True)
    major = int(re.search(r'PostgreSQL\)\s+(\d+)', version).group(1))
    if major != args.expected_major:
        parser.error('PostgreSQL major differs from the explicit expected major. Production acceptance requires 16.')
    if args.output.exists():
        parser.error('Output directory already exists; use a new isolated directory.')
    args.output.mkdir(mode=0o700, parents=True)
    workspace = args.output.resolve()
    archives, custody = workspace/'archives', workspace/'synthetic-key-custody'
    archives.mkdir()
    custody.mkdir()
    objects, restored_objects = workspace/'source-objects', workspace/'restored-objects'
    objects.mkdir()
    restored_objects.mkdir()
    key_config = custody/'synthetic-keys.json'
    key_config.write_text(json.dumps({name:base64.urlsafe_b64encode(os.urandom(32)).decode()
                                     for name in ('identifier','lookup','object','mfa')}))
    recovery_key = Fernet.generate_key()
    (custody/'synthetic-archive.key').write_bytes(recovery_key)
    cipher = Fernet(recovery_key)
    # Deliberately allowlist the child environment: no inherited provider or live DB credentials.
    env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'PYTHONPATH':os.environ.get('PYTHONPATH',''), 'LC_ALL':'C',
        'PYTHONDONTWRITEBYTECODE':'1','DJANGO_SETTINGS_MODULE':'dawatrace.settings.test',
        'DAWATRACE_REDIS_URL':'locmem://','DAWATRACE_SECRET_KEY':'synthetic-recovery-only-32-byte-secret-key',
        'TIBATRACE_RX_CONNECTIONS':'{}','TIBATRACE_CHECKOUT_CONNECTIONS':'{}',
        'PGUSER':getpass.getuser(),'PGDATABASE':'tibatrace_rehearsal_source',
        'TIBATRACE_REHEARSAL_KEYS':str(key_config),'TIBATRACE_REHEARSAL_OBJECTS':str(objects)}
    started = time.monotonic()
    # Secure random 0700 directory. A short parent keeps Unix socket paths
    # within PostgreSQL's limit on macOS; it is never a predictable temp file.
    with tempfile.TemporaryDirectory(prefix='tt-recovery-',dir='/private/tmp' if sys.platform=='darwin' else '/tmp') as temporary:  # nosec B108
        scratch = Path(temporary)
        cluster = scratch/'pgdata'
        socket = scratch/'socket'
        socket.mkdir()
        env['PGHOST'] = str(socket)
        def pg(command):
            return str(args.postgres_bin/command)
        running = False
        with (workspace/'rehearsal.log').open('wb') as log:
            try:
                run([pg('initdb'),'-D',str(cluster),'-A','trust','--no-locale'],env=env,log=log)
                run([pg('pg_ctl'),'-D',str(cluster),'-l',str(workspace/'postgres.log'),'-o',
                     f"-F -k {socket} -c listen_addresses=''",'-w','start'],env=env,log=log)
                running = True
                run([pg('createdb'),env['PGDATABASE']],env=env,log=log)
                env['TIBATRACE_REHEARSAL_PHASE'] = 'seed'
                before = json.loads(run([sys.executable,'-c',HELPER],env=env,log=log).splitlines()[-1])
                database = run([pg('pg_dump'),'--format=custom','--no-owner','--no-acl'],env=env,log=log)
                if len(database) > 64*1024*1024:
                    raise RuntimeError('Synthetic backup unexpectedly exceeds the rehearsal-only bound.')
                import io
                tar_bytes = io.BytesIO()
                with tarfile.open(fileobj=tar_bytes,mode='w:gz') as tar:
                    tar.add(objects,arcname='objects')
                payloads = {'database.dump':database,'objects.tar.gz':tar_bytes.getvalue(),'keys.json':key_config.read_bytes()}
                for name,data in payloads.items():
                    (archives/(name+'.enc')).write_bytes(cipher.encrypt(data))
                # Recovery cannot accidentally read the source DB or original key configuration.
                run([pg('dropdb'),env['PGDATABASE']],env=env,log=log)
                key_config.unlink()
                shutil.rmtree(objects)
                recovery_started = time.monotonic()
                restored_keys = custody/'restored-keys.json'
                restored_keys.write_bytes(cipher.decrypt((archives/'keys.json.enc').read_bytes()))
                encrypted = (archives/'database.dump.enc').read_bytes()
                for bad_cipher,bad_data in ((Fernet(Fernet.generate_key()),encrypted),(cipher,encrypted[:-8]+b'corrupt!')):
                    try:
                        bad_cipher.decrypt(bad_data)
                    except InvalidToken:
                        pass
                    else:
                        raise RuntimeError('Backup authentication failure was not detected.')
                # Only this process's synthetic archive is accepted; no arbitrary input tar is allowed.
                with tarfile.open(fileobj=io.BytesIO(cipher.decrypt((archives/'objects.tar.gz.enc').read_bytes())),mode='r:gz') as tar:
                    for member in tar.getmembers():
                        target = (restored_objects/member.name).resolve()
                        if not (member.isdir() or member.isfile()) or not target.is_relative_to(restored_objects):
                            raise RuntimeError('Unsafe synthetic object archive entry.')
                    for member in tar.getmembers():
                        target = restored_objects/member.name
                        if member.isdir():
                            target.mkdir(mode=0o700,parents=True,exist_ok=True)
                        else:
                            target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                            with tar.extractfile(member) as source, target.open('xb') as output:
                                shutil.copyfileobj(source,output)
                env['PGDATABASE'] = 'tibatrace_rehearsal_restored'
                run([pg('createdb'),env['PGDATABASE']],env=env,log=log)
                run([pg('pg_restore'),'--no-owner','--no-privileges','--exit-on-error','--dbname',env['PGDATABASE']],
                    env=env,log=log,input_data=cipher.decrypt(encrypted))
                env.update(TIBATRACE_REHEARSAL_KEYS=str(restored_keys),TIBATRACE_REHEARSAL_OBJECTS=str(restored_objects/'objects'),TIBATRACE_REHEARSAL_PHASE='verify')
                after = json.loads(run([sys.executable,'-c',HELPER],env=env,log=log).splitlines()[-1])
                assert before == after, 'Recovered synthetic invariants differ.'
                result = {'scope':'SYNTHETIC ENGINEERING REHEARSAL; NO PRODUCTION DATA',
                    'postgresql_major':major,'matches_production_major':major==16,
                    'database_objects_identifier_and_mfa_key_restore':'passed','before_after_checks_match':True,
                    'wrong_key_and_tampered_archive_rejected':True,'providers_disabled':True,'malware_scanning_deferred':True,
                    'recovery_elapsed_seconds':round(time.monotonic()-recovery_started,3),
                    'total_elapsed_seconds':round(time.monotonic()-started,3),
                    'production_rpo_rto':'NOT_MEASURED','off_host_or_separate_custody':'NOT_PROVEN',
                    'independent_witness_and_owner_acceptance':'REQUIRED',
                    'archive_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in archives.iterdir()}}
                (workspace/'REPORT.json').write_text(json.dumps(result,indent=2)+'\n')
                print(json.dumps(result,indent=2))
            finally:
                if running:
                    run([pg('pg_ctl'),'-D',str(cluster),'-m','fast','-w','stop'],env=env,log=log)


if __name__ == '__main__':
    main()
