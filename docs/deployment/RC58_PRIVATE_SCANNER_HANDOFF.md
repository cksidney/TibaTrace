# rc58 private scanner deployment handoff

18 October 2026. Candidate source: `db4528ef0b95c71fa2c13732ec189953c9ee932a`.
Production remains rc57 (`71cb40917a053d5b2f9cae13f345e631e627624d`).

The operator confirmed that no private malware scanner endpoint is currently
available. RX intake is fail-closed until a scanner returns CLEAN, including the
generated intake document. Do not activate rc58 expecting manual RX intake to
work without this prerequisite. No scanner bypass is approved or implemented.

## Observed production capacity

The existing shared VPS has 3,819 MiB total RAM, approximately 1,272 MiB
available, and 3,786 MiB of its 4,095 MiB swap in use. Root storage has about
2.3 GiB free of 38 GiB. These are point-in-time observations, not reserved
capacity. Multiple production applications share the host.

ClamAV's [official Docker guidance](https://docs.clamav.net/manual/Installing/Docker.html)
recommends at least 3 GiB RAM, preferably 4 GiB; database reloads can temporarily
double engine memory. Adding it to the existing host is not recommended under
the observed pressure.

## Proposed provision

Use a dedicated private scanner with 4 GiB RAM. An initial allocation of two
vCPUs and 20 GiB storage is a planning estimate and should be checked against
actual scan volume and signature storage. Select an approved hosting location;
no third-party public scanning service or patient-data transfer is approved by
this plan. Provisioning paid capacity requires the owner's choice of host or
approval to add it; no new server has been purchased.

Run a supported, vulnerability-scanned ClamAV image pinned by digest, with a
persistent signature database and FreshClam updates. Keep port 3310 private and
restricted to the TibaTrace API host. INSTREAM does not itself provide TLS or
authentication: use an encrypted private tunnel between separate hosts, exposing
only a local tunnel endpoint to the backend. Do not publish 3310 to the internet.

The deployed adapter expects host/port settings:

```text
DAWATRACE_MALWARE_SCANNER_HOST=<private-or-local-tunnel-endpoint>
DAWATRACE_MALWARE_SCANNER_PORT=<port>
```

These are deployment placeholders, not a configured endpoint. The protected
candidate file `/opt/tibatrace/secrets/.env.production.rc58` has a valid document
keyring prepared on the VPS. The active `.env.production` was not modified.
Never copy key material into Git, chat, release assets or diagnostic logs.

## Commissioning and activation

1. Confirm private connectivity from the API runtime, fresh signatures, bounded
   scan resources and service health. Use a non-patient benign file and the
   standard EICAR test to verify CLEAN and rejection; test timeout/unavailability
   too. Monitor stale signatures and scanner availability.
2. Require successful rc58 production-image gates, including SQLite/PostgreSQL
   business suites, dependency/runtime scans, immutable digests and provenance.
   Require the signed POS 1.0.13 package's clean-install acceptance.
3. Take protected database/object/environment backups before activation; retain
   rc57 images, its release metadata and the document keyring for recovery.
4. Populate the verified scanner endpoint in the candidate environment, pin the
   passing image digests, apply migrations 0019 and 0020, then activate the server.
   Verify service/worker health, schema, source identity and protected document
   upload/readback without using a real patient's information for a test.
5. Publish the verified managed POS installer in the tenant download catalogue
   after the compatible backend is active. Tenant EMR/DHA/card/Daraja providers
   remain disabled until separately commissioned.

rc57 cannot read newly encrypted clinical objects. If rc58 has accepted writes,
use a compatible forward fix or a specifically reviewed recovery plan. Do not
automatically restore an older database and lose newer transactions.
