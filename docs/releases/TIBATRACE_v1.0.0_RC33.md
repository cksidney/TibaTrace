# TibaTrace v1.0.0-rc33 — validated governed HQ workflows

Supersedes the rc32 candidate, which was not deployed because its complete test
run found three failures. Uses the same approved [release scope and database
rollback restrictions](../deployment/RC32_RELEASE_SCOPE.md).

Adds explicit security review of the platform audit actor lookup and immutable
existence check. Catalogue references are tenant/global-scoped before identifier
resolution. Practitioner authority regression tests now use the governed licence
verification workflow and continue to reject an expired licence.

HQ, API, worker and beat deploy from one committed source revision after the full
CI business suite passes. All three migrations are rehearsed on a disposable
PostgreSQL backup copy before activation. No real clinical transactions or demo
reseeding are part of this release.

Windows POS 1.0.4 source is unchanged. Android release signing is still required;
the unfinished Stage 2D.2 draft remains preserved locally and is not shipped.
