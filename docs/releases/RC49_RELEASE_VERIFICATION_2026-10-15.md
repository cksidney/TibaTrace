# rc49 and Windows POS 1.0.8 deployment verification — 15 October 2026

Status: deployed and verified at https://tibatrace.esenai.co.ke/.

HQ runtime source: `ce715f5578efc2857ba29c22850bf300697c8588`, tag `tibatrace-v1.0.0-rc49`.
Windows source: `38f8fc728f7e0866875d5eb6738e26d1c7d0f70c`, tag `pos-windows-v1.0.8`.
The original checkout and unfinished drafts were preserved in place.

## Scope and interface acceptance

People intake is reachable from the header and registry tabs; a platform-wide session selects an active pharmacy before entering scoped records. Prescription receipt and dispensing origination, fulfilment intake, commercial price-list/entry editing, role creation and imported-item/opening setup use accessible modals. Existing modal ingestion in Network, procurement, inventory, insurance, regulatory, integration and user creation remains available. Permission and independent approval gates remain enforced. Refused/uncertain saves retain drafts and retry keys. Local browser review covered form entry, modal focus, tenant selection and narrow/light/dark layouts using synthetic data.

POS 1.0.8 polishes the shared shell and Clinical, Retail, Register, Print and Sync workspaces, adds queue search, clearer scoped sale entry, print queue counts/filters and expandable operational facts. The actual Windows executable and NSIS installer icon resources match the existing TibaTrace logo. The installer/uninstaller configuration and Windows application identity use TibaTrace branding. Browser review at 1280, 1024 and 390px covered queue search, episode navigation, help, locked shortcuts, synthetic draft creation and printer selection/setup, without horizontal page overflow.

## Mandatory gates

[Production Images run 38795384691](https://github.com/cksidney/TibaTrace/actions/runs/38795384691) passed on the exact HQ source:

- Full SQLite and PostgreSQL 16.15 business suites: 2,172 tests each, zero failures/errors/skips.
- HQ 93, Windows 111, Android 41 and shared 212 application tests, with typechecks/builds.
- All 58 Python dependencies audited without vulnerabilities; both runtime image scans had zero findings.
- Release checksums, Linux amd64 labels, empty migration inventory, SBOMs and GitHub image provenance verified.

[Windows release run 38801856720](https://github.com/cksidney/TibaTrace/actions/runs/38801856720) passed on the exact Windows source: 114 POS tests, typecheck/build, actual executable/installer logo checks, Authenticode signing and timestamp, managed certificate enrollment, clean installation and installed application launch/bridge checks.

## Live server acceptance

Images deployed by verified immutable digest:

```
ghcr.io/cksidney/tibatrace-backend@sha256:7fbf806e20f79d628a9f12fffbc6ad875b589f8408a580962d6446adea81252b
ghcr.io/cksidney/tibatrace-hq-web@sha256:3001cb7dc9428b72bee2ae42ac7edd2fbe796b071a69011cbd8bd927a2ee236a
```

Fresh root-only PostgreSQL custom backup and verified restore inventory/checksum:
`/opt/tibatrace/backups/tibatrace-rc49-predeploy-20261015T202811Z`.
No migrations were pending. rc48 source/images and prior installers remain available for rollback. No restore or rollback was needed; Redis was preserved.

API/HQ health, all four runtime revision labels, Django checks, PostgreSQL/version, migrations, worker ping and public HTTPS health passed. Active pointer:
`/opt/tibatrace/releases/tibatrace-1.0.0-rc49-ce715f55-20261015`.
Deployment baseline is the accepted HQ source above.

Read-only access checks covered 21 active tenant identities and two owners. An eligible tenant passed authenticated HTTPS navigation/session checks; owner-only APIs and a foreign tenant header returned 403. An existing owner retained global/selected-pharmacy navigation. No account, password or grant was changed. This does not claim interactive acceptance by every user.

Public HTML has no-store caching. Served assets match the running image:

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `/assets/index-DWo_bC7u.js` | 831,042 | `39dfcb041477fd4eecab9dd026354025c98e9cbe33ef2a17ec252a2a30b7d8a3` |
| `/assets/index-le9VfW3L.css` | 148,912 | `789e24db0fc2b09cb707faee8455d3f4b8ea62aee756441fb16070c054818ce7` |

## Native publication and download

Published Windows **1.0.8**, build **8**, catalogue ID `08bc7b69-c96f-4aae-94e6-09e544fe6fd3`.

- Managed ZIP: 108,209,630 bytes; SHA-256 `8890cfa8beb06d21b91279e835fece8502b05a0e6c2bbe730abc3b7a3e2148e6`.
- Embedded signed installer SHA-256 `16824de83c5d8141b69b5c7109055ceb272ec4c25241160d96492c17d4c98f13`.
- Public certificate SHA-256 `4c60fdc90f8bf35c2fd698ae0962adbbc015659a7cb294595195faa992affe02`, unchanged from the prior managed release.

An eligible tenant passed authenticated HTTPS catalogue, issuance and complete streamed download with matching bytes/hash. Anonymous download was refused. Prior 1.0.7/1.0.5 metadata remains published, and minimum supported build remains 0. Only expected publication/download audit entries were created; no clinical/trading test records or access grants were added. Verification tokens remained in memory.

Refresh already-open HQ tabs for the web changes. Each Windows till needs the 1.0.8 managed installer to receive the redesign and icon changes. Physical till/printer acceptance requires customer hardware; no physical printing claim is made.

Evidence is retained locally in `/private/tmp/tibatrace-ingestion-review` and in the active production release's acceptance evidence archives. `FINAL_ACCEPTANCE.json` ties server source, tests, image provenance, public assets and native package/download facts together. Activation log: `/opt/tibatrace/releases/rc49-activation.log`.
