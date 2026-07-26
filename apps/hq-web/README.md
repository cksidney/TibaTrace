# TibaTrace HQ Web

Standalone React headquarters application for platform and tenant operations.
It uses the authenticated Django session and loads live dashboard data from
`/api/hq/overview/`.

## Local development

Start the Django backend on port `8000`, then run:

```bash
npm --prefix apps/hq-web run dev
```

Open `http://127.0.0.1:5173/`. The development server proxies `/api`, `/admin`,
and `/static` to Django. An unauthenticated user is directed through the Django
admin sign-in and returned to the HQ application.

## Validation

```bash
npm --prefix apps/hq-web run typecheck
npm --prefix apps/hq-web run test
npm --prefix apps/hq-web run build
```

## Production

Build `apps/hq-web/Dockerfile` as an immutable image and set
`TIBATRACE_HQ_IMAGE` in the production environment. The checked-in Caddy
configuration routes backend paths to Django and all other requests to this
application.
