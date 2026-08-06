# Git worktrees share one development database

`settings.DATABASES['default']['NAME']` resolves to an **absolute path into the
main repository**:

```
/Users/<user>/TibaTrace/backend/dawatrace.sqlite3
```

It is not relative to the working directory. Every `git worktree` therefore
points at that same file, no matter which checkout you run from.

## Why tests are safe

`DATABASES['default']['TEST']['NAME']` is `None`, so Django's sqlite backend
uses `:memory:` for the test database. `pytest` and `manage.py test` build and
tear down an isolated in-memory database and never open the development file.

Verified: the development database's mtime is unchanged across full suite runs
from two parallel worktrees.

## Why everything else is not

Any command that is **not** a test run reads and writes the shared development
database, from whichever worktree you launch it. That includes:

- `manage.py migrate`
- any `seed_*` management command
- `manage.py shell` doing writes
- integrity repair or backfill commands
- `manage.py flush`, `loaddata`, `dumpdata`

Two agents working in parallel worktrees will silently share state, and one
`migrate` or `seed_*` can overwrite the other's data with no warning and no
conflict.

`manage.py check` and `makemigrations --check --dry-run` are safe: neither
writes, and both leave the file's mtime untouched.

## Rule

**Before running any non-test command from a worktree, set an explicit
worktree-local database.**

```bash
export DAWATRACE_DATABASE_URL="sqlite:////absolute/path/to/this-worktree/backend/dev.sqlite3"
```

Or confirm the target first:

```bash
python -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','dawatrace.settings.development');django.setup();from django.conf import settings;print(settings.DATABASES['default']['NAME'])"
```

Agents must not run seed, migrate, shell-mutation or integrity-repair commands
from a worktree without verifying the database target first. A shared database
failure looks like data that changed on its own, which is the hardest kind to
attribute.
