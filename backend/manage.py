#!/usr/bin/env python
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.development")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
