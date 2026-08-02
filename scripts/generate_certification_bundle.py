#!/usr/bin/env python3
"""CLI script to generate Phase 16 Certification Evidence Bundle ZIP.

Usage:
  python scripts/generate_certification_bundle.py [--output-dir <path>]
"""
import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.test")

import django
django.setup()

from apps.platform.reporting.certification_engine import CertificationEvidenceGenerator


def main():
    parser = argparse.ArgumentParser(description="Generate Phase 16 Certification Evidence Bundle")
    parser.add_argument("--output-dir", default=".", help="Directory to save the ZIP bundle")
    args = parser.parse_args()

    zip_bytes, filename = CertificationEvidenceGenerator.export_evidence_zip("CLI Automated Generator")
    out_path = Path(args.output_dir) / filename
    out_path.write_bytes(zip_bytes)
    print(f"SUCCESS: Generated Certification Evidence Bundle: {out_path.resolve()}")
    print(f"Size: {len(zip_bytes)} bytes")


if __name__ == "__main__":
    main()
