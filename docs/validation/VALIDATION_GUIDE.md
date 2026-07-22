# DawaTrace Enterprise Validation & Quality Assurance Guide

## Overview

The DawaTrace repository uses a unified, multi-layered enterprise validation engine to guarantee build, runtime, security, contract, and deployment integrity across every application, service, and package.

---

## Validation Engine Commands

The primary entry point is `./scripts/validate_repository.sh`. Convenience wrappers are provided in `Makefile` and `package.json`.

### 1. Fast Local Mode (`--fast`)
Used during active local development for rapid feedback:
```bash
./scripts/validate_repository.sh --fast
# or
make validate-fast
# or
npm run validate:fast
```
*Executes:* Backend linting, Django system checks, migration drift, migration rollbacks, runtime startup smoke test, OpenAPI contract drift, safety audits, Pytest unit tests, Bandit security scans, secret scans, and TypeScript type checking. Heavy Docker image builds are skipped.

### 2. Full Enterprise Mode (`--full` / `--ci`)
Used for CI, sprint completion, and release candidate verification:
```bash
./scripts/validate_repository.sh --full
# or
make validate-full
# or
npm run validate:full
```
*Executes:* All steps in `--fast` mode plus Docker image builds, Docker Compose configuration verification, containerized runtime smoke tests, and evidence manifest generation.

---

## Machine-Readable Validation Evidence Artifacts

Validation output is automatically saved in `artifacts/generated/`:

1. **`artifacts/generated/validation/repository-validation-manifest.json`**:
   Comprehensive JSON manifest recording execution timestamps, operating system, tool versions, git commit SHA, SHA-256 evidence checksums, exit status, and overall completion decision (`PHASE_3_0_COMPLETE` or `PHASE_3_0_COMPLETE_WITH_EXTERNAL_SECURITY_GATES_PENDING`).

2. **`artifacts/generated/validation/migration-reversibility.json`**:
   Classification matrix documenting reversibility, tested rollback boundaries, and status across all 20 Django applications.

3. **`artifacts/contracts/openapi.json`**:
   Committed reference OpenAPI schema against which backend schema drift is automatically evaluated.

4. **`artifacts/generated/security/`**:
   - `bandit.json`: Static security analysis report.
   - `dawatrace-backend.cdx.json`: CycloneDX SBOM artifact.
   - `secret-scan.json`: Credential scan report.

5. **`artifacts/generated/tests/backend.xml`**:
   JUnit XML test execution report.

---

## CI Enforcement

GitHub Actions CI (`.github/workflows/ci.yml`) executes `./scripts/validate_repository.sh --full` on every pull request and push to `main`. Merging is strictly prohibited if any step fails.
