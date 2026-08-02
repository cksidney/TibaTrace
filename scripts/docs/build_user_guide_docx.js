const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  TableOfContents, PageBreak, Footer, Header, PageNumber, LevelFormat,
  convertInchesToTwip,
} = require("docx");

// A4 with 1" margins → usable content width.
const CONTENT = 11906 - 2880; // 9026 DXA

const NAVY = "0F172A";
const TEAL = "0D9488";
const SLATE = "475569";
const RULE = "CBD5E1";
const CODE_BG = "F1F5F9";
const HEAD_BG = "0F172A";
const ZEBRA = "F8FAFC";
const CALL_BG = "FEF9E7";

const MONO = "Consolas";

const out = [];

/* ---------- helpers ---------- */

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { before: opts.before ?? 0, after: opts.after ?? 120, line: 276 },
    alignment: opts.align,
    children: [new TextRun({ text, size: opts.size ?? 21, color: opts.color ?? "1F2937", bold: opts.bold, italics: opts.italics, font: opts.font })],
  });
}

/** Inline markdown: `code`, **bold**, *italic* → runs. */
function runs(md, base = {}) {
  const parts = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0, m;
  while ((m = re.exec(md))) {
    if (m.index > last) parts.push({ t: md.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith("`")) parts.push({ t: tok.slice(1, -1), code: true });
    else if (tok.startsWith("**")) {
      // Bold may itself contain `code`; without this the backticks render literally.
      const inner = tok.slice(2, -2);
      const sub = /(`[^`]+`)/g; let li = 0, im;
      while ((im = sub.exec(inner))) {
        if (im.index > li) parts.push({ t: inner.slice(li, im.index), bold: true });
        parts.push({ t: im[0].slice(1, -1), bold: true, code: true });
        li = sub.lastIndex;
      }
      if (li < inner.length) parts.push({ t: inner.slice(li), bold: true });
    }
    else parts.push({ t: tok.slice(1, -1), italics: true });
    last = re.lastIndex;
  }
  if (last < md.length) parts.push({ t: md.slice(last) });
  return parts.map(x => new TextRun({
    text: x.t,
    size: base.size ?? 21,
    color: x.code ? "9F1239" : (base.color ?? "1F2937"),
    font: x.code ? MONO : undefined,
    bold: x.bold || base.bold,
    italics: x.italics || base.italics,
  }));
}

function para(md, opts = {}) {
  return new Paragraph({
    spacing: { before: opts.before ?? 0, after: opts.after ?? 140, line: 276 },
    children: runs(md, opts),
  });
}

function h(text, level, opts = {}) {
  return new Paragraph({
    heading: level,
    spacing: { before: opts.before ?? 320, after: opts.after ?? 140 },
    children: [new TextRun({ text, bold: true, color: opts.color ?? NAVY, size: opts.size })],
  });
}

function bullet(md, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 80, line: 276 },
    children: runs(md),
  });
}

function numbered(md, level = 0) {
  return new Paragraph({
    numbering: { reference: "steps", level },
    spacing: { after: 80, line: 276 },
    children: runs(md),
  });
}

function code(lines) {
  const rows = Array.isArray(lines) ? lines : lines.split("\n");
  return rows.map((ln, i) => new Paragraph({
    spacing: { before: i === 0 ? 100 : 0, after: i === rows.length - 1 ? 160 : 0, line: 240 },
    shading: { type: ShadingType.CLEAR, fill: CODE_BG },
    indent: { left: 220, right: 220 },
    border: {
      left: { style: BorderStyle.SINGLE, size: 12, color: TEAL, space: 8 },
    },
    children: [new TextRun({ text: ln || " ", font: MONO, size: 18, color: "0F172A" })],
  }));
}

/** Callout — shaded, bordered block for the "why this matters" notes. */
function callout(md) {
  return new Paragraph({
    spacing: { before: 140, after: 180, line: 276 },
    shading: { type: ShadingType.CLEAR, fill: CALL_BG },
    indent: { left: 200, right: 200 },
    // A single left accent bar. docx-js serialises w:pBdr children in a fixed
    // top/bottom/left/right order, which violates the schema's
    // top/left/bottom/right sequence as soon as more than one side is set --
    // so multi-side paragraph borders cannot be produced here at all.
    border: {
      left: { style: BorderStyle.SINGLE, size: 18, color: "F59E0B", space: 10 },
    },
    children: runs(md),
  });
}

function table(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const scale = CONTENT / total;
  const w = widths.map(x => Math.round(x * scale));
  // headers === null renders a headerless table. Passing empty strings instead
  // drew an empty dark band across the top of the cover metadata.
  const headRow = headers && new TableRow({
    tableHeader: true,
    children: headers.map((txt, i) => new TableCell({
      width: { size: w[i], type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: HEAD_BG },
      margins: { top: 90, bottom: 90, left: 120, right: 120 },
      children: [new Paragraph({
        spacing: { after: 0, line: 240 },
        children: [new TextRun({ text: txt, bold: true, color: "FFFFFF", size: 19 })],
      })],
    })),
  });

  const bodyRows = rows.map((cells, r) => new TableRow({
    children: cells.map((txt, i) => new TableCell({
      width: { size: w[i], type: WidthType.DXA },
      shading: r % 2 ? { type: ShadingType.CLEAR, fill: ZEBRA } : undefined,
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({ spacing: { after: 0, line: 252 }, children: runs(txt, { size: 19 }) })],
    })),
  }));

  return new Table({
    columnWidths: w,
    width: { size: CONTENT, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: headRow ? [headRow, ...bodyRows] : bodyRows,
  });
}

function spacer(after = 200) {
  return new Paragraph({ spacing: { after }, children: [] });
}

/* ---------- cover ---------- */

out.push(new Paragraph({ spacing: { before: 2600, after: 0 }, children: [
  new TextRun({ text: "TibaTrace", bold: true, size: 76, color: NAVY }),
]}));
out.push(new Paragraph({ spacing: { after: 260 }, children: [
  new TextRun({ text: "End-to-End Guide", size: 44, color: TEAL }),
]}));
out.push(new Paragraph({
  spacing: { after: 340 },
  border: { top: { style: BorderStyle.SINGLE, size: 12, color: TEAL, space: 10 } },
  children: [],
}));
out.push(p("Pharmacy and healthcare operations platform", { size: 24, color: SLATE }));
out.push(p("Install · Configure · Dispense · Report · Operate", { size: 22, color: SLATE, italics: true, after: 500 }));

out.push(table(
  null,
  [
    ["Applies to", "**v1.0.0-rc14**"],
    ["Production", "`https://tibatrace.esenai.co.ke`"],
    ["Audience", "Operations · HQ administrators · Pharmacy staff"],
    ["Publisher", "Esenai Group Ltd"],
  ],
  [2400, 6626],
));

out.push(new Paragraph({ children: [new PageBreak()] }));

/* ---------- contents ---------- */

out.push(new Paragraph({
  spacing: { before: 0, after: 180 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: TEAL, space: 6 } },
  children: [new TextRun({ text: "Contents", bold: true, size: 34, color: NAVY })],
}));
out.push(new TableOfContents("Contents", { hyperlinks: true, headingStyleRange: "1-2" }));
out.push(new Paragraph({ children: [new PageBreak()] }));

/* ---------- intro ---------- */

out.push(h("About this guide", HeadingLevel.HEADING_1, { before: 0 }));
out.push(para("This is the authoritative guide to TibaTrace. It runs the full length of the system: install it, configure it, use it at a pharmacy counter, report on it, and keep it running."));
out.push(para("Read the part that matches your role."));
out.push(spacer(120));
out.push(table(
  ["Part", "For", "Covers"],
  [
    ["1. The system", "everyone", "What the pieces are and how they fit"],
    ["2. Install and deploy", "operations", "First deployment, releases, rollback"],
    ["3. Configure", "HQ administrators", "Tenants, branches, users, catalogue, pricing"],
    ["4. The dispensing counter", "pharmacy staff", "The POS journey, start to finish"],
    ["5. HQ workspaces", "HQ operators", "Every workspace and what it is for"],
    ["6. Reporting", "everyone", "The catalogue, exports, validation receipts"],
    ["7. Keeping it running", "operations", "Health, backups, secrets, upgrades"],
    ["8. Reference", "everyone", "Capabilities, troubleshooting, deeper reading"],
  ],
  [2100, 1700, 5226],
));

out.push(new Paragraph({ children: [new PageBreak()] }));

/* ---------- 1 ---------- */

out.push(h("1. The system", HeadingLevel.HEADING_1, { before: 0 }));
out.push(para("TibaTrace is a multi-tenant pharmacy and healthcare operations platform. One deployment serves many pharmacy organisations (“tenants”), each with its own branches, staff, stock and patients, isolated from one another."));
out.push(para("Five components:"));
out.push(spacer(100));
out.push(table(
  ["Component", "What it is", "Where it runs"],
  [
    ["**Backend API**", "Django. The authority for every record and rule", "Container on the server"],
    ["**HQ web**", "The browser workspace for operators and administrators", "Container serving static assets"],
    ["**POS Windows**", "The dispensing terminal for a pharmacy counter", "Windows PC at the branch"],
    ["**POS Android**", "The mobile dispensing client", "Android device"],
    ["**Worker + scheduler**", "Background jobs and scheduled work (Celery)", "Containers on the server"],
  ],
  [2100, 4326, 2600],
));
out.push(spacer(160));
out.push(para("Backed by PostgreSQL (records), Redis (queues and cache), and an object store for uploaded documents and POS installers."));
out.push(callout("**One rule underpins everything: a tenant never sees another tenant’s data.** It is enforced in the data layer, not in the interface, and an automated audit fails the build if a query is written that could cross the boundary. Where a genuine exception exists — password recovery has to find a user before any tenant is known — it is declared explicitly and confined to the one module that needs it."));

/* ---------- 2 ---------- */

out.push(h("2. Install and deploy", HeadingLevel.HEADING_1));

out.push(h("2.1 What you need", HeadingLevel.HEADING_2));
[
  "A Linux host with Docker and Docker Compose",
  "PostgreSQL 16 with TLS, on its own database and user",
  "Redis, password-protected, on its own namespace",
  "A DNS record for your domain, with ports 80 and 443 reachable",
  "Object storage for POS installers and clinical documents",
].forEach(x => out.push(bullet(x)));

out.push(h("2.2 Where things live", HeadingLevel.HEADING_2));
out.push(...code([
  "/opt/tibatrace/",
  "├── current -> releases/<release>/   # symlink to the live release",
  "├── releases/                        # immutable release directories",
  "├── secrets/.env.production          # the only configuration file (mode 600)",
  "├── backups/                         # database dumps, one per release",
  "└── incoming/                        # transfer staging",
]));
out.push(para("The environment file lives **outside** the release directories and survives every deployment. It is never committed and never overwritten by a release."));

out.push(h("2.3 Images come from CI, never from a laptop", HeadingLevel.HEADING_2));
out.push(para("Release images are built only by GitHub Actions and published to GHCR:"));
out.push(bullet("`ghcr.io/cksidney/tibatrace-backend`"));
out.push(bullet("`ghcr.io/cksidney/tibatrace-hq-web`"));
out.push(para("Production pulls **by digest**, never by tag. No `latest` tag is published, so no reference can drift. A mutable tag cannot tell you what is running six weeks from now; a digest can.", { before: 100 }));
out.push(callout("This is not a preference. A release once passed every local check and could not be built at all, because a developer’s machine had stale build artefacts that hid a broken Dockerfile. CI has no such state."));

out.push(h("2.4 Deploying a release", HeadingLevel.HEADING_2));
out.push(para("**1. Pull the exact images by digest**"));
out.push(...code([
  "docker pull ghcr.io/cksidney/tibatrace-backend@sha256:<backend-digest>",
  "docker pull ghcr.io/cksidney/tibatrace-hq-web@sha256:<hq-digest>",
]));
out.push(para("**2. Confirm they are what you think they are**"));
out.push(...code([
  "docker image inspect ghcr.io/cksidney/tibatrace-backend@sha256:<digest> \\",
  "  --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}'",
]));
out.push(para("That revision must equal the release commit. If it prints `unknown`, stop — the image was not built by the release pipeline."));
out.push(para("**3. Back up the database before anything changes**"));
out.push(...code([
  "pg_dump --dbname=\"$DATABASE_URL\" --format=custom --no-owner \\",
  "  --no-privileges --file=/opt/tibatrace/backups/<release>/db.dump",
]));
out.push(para("**4. Review what the migrations will do, without applying them**"));
out.push(...code([
  "docker run --rm --network host \\",
  "  --env-file /opt/tibatrace/secrets/.env.production \\",
  "  ghcr.io/cksidney/tibatrace-backend@sha256:<digest> \\",
  "  sh -c 'python manage.py check && python manage.py migrate --plan'",
]));
out.push(para("**5. Apply them**"));
out.push(...code([
  "cd /opt/tibatrace/current/deploy/tibatrace",
  "docker compose --env-file /opt/tibatrace/secrets/.env.production \\",
  "  -f docker-compose.yml -f docker-compose.server.yml \\",
  "  --profile maintenance run --rm migrate",
]));
out.push(para("**6. Point `current` at the new release, atomically**"));
out.push(...code([
  "ln -sfn /opt/tibatrace/releases/<release> /opt/tibatrace/current.new",
  "mv -Tf /opt/tibatrace/current.new /opt/tibatrace/current",
]));
out.push(para("**7. Recreate only TibaTrace services**"));
out.push(...code([
  "docker compose --env-file /opt/tibatrace/secrets/.env.production \\",
  "  -f docker-compose.yml -f docker-compose.server.yml \\",
  "  up -d --remove-orphans redis api worker beat hq",
]));
out.push(callout("**Never** run `docker compose down -v` — it destroys the volumes holding your database, uploads and installers. **Never** run `git clean -fdx` in a release directory."));

out.push(h("2.5 The check that decides whether a deployment worked", HeadingLevel.HEADING_2));
out.push(para("After activation, every component must report the same revision:"));
out.push(...code([
  "for c in tibatrace-api-1 tibatrace-worker-1 tibatrace-beat-1 tibatrace-hq-1; do",
  "  docker inspect \"$c\" --format \\",
  "    '{{.Name}} {{index .Config.Labels \"org.opencontainers.image.revision\"}}'",
  "done",
]));
out.push(callout("All four must print the release commit. If they disagree, the deployment is **failed, not partial** — treat it that way. A deployment once left the web tier on one commit and the API on another for three days, and nothing reported a problem."));

out.push(h("2.6 Rolling back", HeadingLevel.HEADING_2));
out.push(para("Every release backs up the environment file before changing it."));
out.push(...code([
  "cp -a /opt/tibatrace/secrets/.env.production.pre-<release>-<timestamp> \\",
  "      /opt/tibatrace/secrets/.env.production",
  "ln -sfn /opt/tibatrace/releases/<previous> /opt/tibatrace/current.new",
  "mv -Tf /opt/tibatrace/current.new /opt/tibatrace/current",
  "# then re-run step 7 above",
]));
out.push(para("Migrations are **not** reversed automatically. Check the release’s `MIGRATIONS.json` first: if every migration is `\"destructive\": false`, the older image runs safely against the newer schema and you need do nothing. Otherwise restore from the dump taken in step 3."));
out.push(para("Keep at least one previous release directory and its images."));

/* ---------- 3 ---------- */

out.push(h("3. Configure", HeadingLevel.HEADING_1));
out.push(para("Order matters. Each step depends on the one before it."));

out.push(h("3.1 Tenants and branches", HeadingLevel.HEADING_2));
out.push(para("**Pharmacy network** creates the organisations and their locations. A tenant is a pharmacy business; a branch is a physical site with its own stock, tills and staff. Everything else attaches to one or the other."));

out.push(h("3.2 Users and roles", HeadingLevel.HEADING_2));
out.push(para("**Administration & Users** creates accounts and grants capabilities."));
out.push(para("TibaTrace does not have a small fixed set of roles. It has **29 named capabilities** that you compose into roles suited to the branch. A capability is a specific permission — `pos.payment.collect`, `prescriptions.pharmacist_verify`, `pricing.price_book.publish` — and a role is a bundle of them."));
out.push(callout("This matters at the counter. The person who *requests* a price override cannot be the person who *approves* it, because those are two capabilities, and approving below the floor price is a third. Separation of duty is enforced by the permission model, not by policy documents."));
out.push(para("**A user with no workspace assignment cannot sign in.** If someone reports “account is not assigned to a workspace”, they need a tenant assigned in Administration & Users."));

out.push(h("3.3 Medicine catalogue", HeadingLevel.HEADING_2));
out.push(para("**Medicine catalogue** governs what may be dispensed. The model deliberately separates three concerns that many systems merge:"));
out.push(bullet("**Clinical product** — the medicine as a clinician thinks of it (substance, strength, form)"));
out.push(bullet("**Manufactured product** — a specific manufacturer’s version of it"));
out.push(bullet("**Commercial SKU** — the sellable, stockable, priceable unit"));
out.push(para("A SKU cannot exist without a manufactured product and a package definition. This is enforced by non-nullable foreign keys, and it is why **you cannot price an item before its catalogue governance is complete**. If pricing rejects a code with “select an existing tenant commercial SKU”, the answer is to finish the catalogue entry, not to work around it.", { before: 100 }));

out.push(h("3.4 Pricing", HeadingLevel.HEADING_2));
out.push(para("**Pricing** manages branch price books. Prices resolve in strict order:"));
out.push(numbered("Customer price agreement (a bilateral agreement with one customer)"));
out.push(numbered("Branch price list entry"));
out.push(numbered("Tenant price list entry"));
out.push(numbered("SKU base price"));
out.push(para("Price books move through **draft → approved → published** as separate, separately-permissioned steps. Manual overrides are requested and approved by different people, and going below the floor price needs a third capability again.", { before: 120 }));

out.push(h("3.5 Suppliers and procurement", HeadingLevel.HEADING_2));
out.push(para("**Procurement & Supply** holds suppliers, purchase orders and goods received notes. Receiving is scan-driven: scan the delivery against the order, record batch and expiry, and stock enters quality-held state until released by someone with `quality.release`."));

out.push(h("3.6 Insurance", HeadingLevel.HEADING_2));
out.push(para("**Insurance & Claims** configures insurers and schemes, including SHA, and handles adjudication."));

/* ---------- 4 ---------- */

out.push(h("4. The dispensing counter", HeadingLevel.HEADING_1));
out.push(para("This is the part pharmacy staff use every day. The Windows and Android terminals follow the same journey."));

out.push(h("4.1 Starting a shift", HeadingLevel.HEADING_2));
out.push(numbered("**Sign in** with your own account. Never share a login — every clinical and cash action is attributed to the person who performed it."));
out.push(numbered("**Open your register** in Register Centre. Count the float and record it. The expected drawer starts from this number, so a wrong float becomes a variance you will have to explain at close."));
out.push(numbered("Check the **status bar**. It shows whether the terminal is online, whether clinical decision support is reachable, and whether anything is queued."));

out.push(h("4.2 Dispensing a prescription", HeadingLevel.HEADING_2));
out.push(para("An episode moves through these states, and the workflow ribbon shows where you are:"));
out.push(...code([
  "DRAFT → PREPARING → CHECKING → READY_FOR_PAYMENT → PAID",
  "      → READY_FOR_COLLECTION → SUPPLIED → CLOSED",
]));
out.push(para("with `ON_HOLD`, `PARTIALLY_SUPPLIED`, `CANCELLED`, `REJECTED`, `REVERSED` and `RETURNED` available where the situation calls for them."));

out.push(p("Prepare", { bold: true, size: 22, color: NAVY, before: 160, after: 60 }));
out.push(para("Open the prescription. Confirm the patient, then pick each item. Scan the batch — this records exactly which batch went to which patient, which is what makes a recall actionable later."));

out.push(p("Clinical screening", { bold: true, size: 22, color: NAVY, before: 140, after: 60 }));
out.push(para("Decision support runs automatically: interactions, allergies, duplicate therapy, dose sanity. Findings appear on the patient safety banner."));
out.push(callout("A blocking finding **stops** the episode. It is not a warning you can click past. A pharmacist with `prescriptions.clinical_review` must review it and either resolve it or record an explicit override with a reason. The override is stored against the episode and appears in clinical reports. This is the point of the system — do not treat it as an obstacle."));

out.push(p("Pharmacist verification", { bold: true, size: 22, color: NAVY, before: 140, after: 60 }));
out.push(para("Someone with `prescriptions.pharmacist_verify` performs the final check. On a controlled drug this is a legal act, and the system records who did it."));

out.push(p("Payment", { bold: true, size: 22, color: NAVY, before: 140, after: 60 }));
out.push(para("Take payment in Payment Panel — cash, card, mobile money, insurance or a split across several. Payment is idempotent: if the connection drops mid-transaction, retrying will **not** charge twice. The episode carries one authoritative payment state, so what you see is what settled."));

out.push(p("Counselling and collection", { bold: true, size: 22, color: NAVY, before: 140, after: 60 }));
out.push(para("Counsel the patient, record that you did, and release the medicine. The episode reaches `SUPPLIED`."));

out.push(p("Print", { bold: true, size: 22, color: NAVY, before: 140, after: 60 }));
out.push(para("Labels, receipts and the dispensing record print from Print Centre, and can be reprinted — reprints are logged."));

out.push(h("4.3 Retail sales", HeadingLevel.HEADING_2));
out.push(para("Retail Workspace handles over-the-counter sales that are not against a prescription. Same payment and till handling; no clinical gate."));

out.push(h("4.4 Working offline", HeadingLevel.HEADING_2));
out.push(para("The terminal keeps working when the network drops. Work is queued locally and syncs when the connection returns; Sync Centre shows what is pending."));
out.push(para("Two limits worth knowing:"));
out.push(bullet("**Clinical decision support needs the server.** Offline, screening cannot run. The terminal will tell you so rather than pretend the check passed."));
out.push(bullet("**Do not close a shift with unsynced work.** Reconcile first, or the cash position will not match."));

out.push(h("4.5 Closing a shift", HeadingLevel.HEADING_2));
out.push(para("Count the drawer, enter the actual figure, and close. Any difference between expected and counted is recorded as a variance with your name on it. Variances are not hidden or netted off — they surface in Finance & Cash Control and in the cash reports."));

/* ---------- 5 ---------- */

out.push(h("5. HQ workspaces", HeadingLevel.HEADING_1));
out.push(para("Grouped by what you are trying to do."));

out.push(h("5.1 Daily oversight", HeadingLevel.HEADING_2));
out.push(table(["Workspace", "Use it for"], [
  ["Overview", "The command centre. Start here"],
  ["Executive Dashboard", "18 leadership widgets across the workspace"],
], [2900, 6126]));

out.push(h("5.2 Operations", HeadingLevel.HEADING_2));
out.push(table(["Workspace", "Use it for"], [
  ["Pharmacy network", "Tenants and locations"],
  ["Patients & People", "Care records and commercial customers"],
  ["Medicine catalogue", "SKUs and product governance"],
  ["Inventory Control", "Balances, ledger and FEFO"],
  ["Procurement & Supply", "Purchase orders and goods received"],
  ["Sales & fulfilment", "Orders through to delivery"],
  ["Point of sale", "Live dispensing operations"],
], [2900, 6126]));

out.push(h("5.3 Money", HeadingLevel.HEADING_2));
out.push(table(["Workspace", "Use it for"], [
  ["Pricing", "Branch price books"],
  ["Finance & Cash Control", "Shifts, tills and variances"],
  ["Insurance & Claims", "Adjudication and SHA"],
], [2900, 6126]));

out.push(h("5.4 Assurance", HeadingLevel.HEADING_2));
out.push(table(["Workspace", "Use it for"], [
  ["Clinical governance", "Safety and standards"],
  ["Regulatory Workspace", "PPB and DHA compliance"],
  ["National Integrations", "DHA and PPB command centre"],
  ["Reports", "Enterprise and security packs"],
  ["System governance", "Audit, events and documents"],
], [2900, 6126]));

out.push(h("5.5 Administration", HeadingLevel.HEADING_2));
out.push(table(["Workspace", "Use it for"], [
  ["Administration & Users", "Roles and security"],
  ["API documentation", "Integration contracts"],
], [2900, 6126]));

out.push(h("5.6 Inventory: FEFO", HeadingLevel.HEADING_2));
out.push(para("Stock is consumed **first-expired-first-out**, not first-in-first-out. The terminal picks the batch nearest expiry that satisfies the line. You can override this, and the override is recorded."));
out.push(para("Every movement writes a ledger entry. On-hand, reserved and available are derived from the ledger, never edited directly, and database constraints prevent any of them going negative."));

out.push(h("5.7 Regulatory and national integrations", HeadingLevel.HEADING_2));
out.push(para("The Regulatory Workspace and National Integrations cover PPB and DHA compliance: premises verification, health worker registry lookups, and regulatory recalls matched against the batches you actually dispensed. That matching is why batch scanning at the counter matters."));

out.push(h("5.8 Theme", HeadingLevel.HEADING_2));
out.push(para("The sun/moon control in the header switches light and dark. Your choice is remembered on that device and applies from the moment the page loads."));

/* ---------- 6 ---------- */

out.push(h("6. Reporting", HeadingLevel.HEADING_1));
out.push(para("**Reports** holds the enterprise catalogue — 99 packs across 14 categories:"));
out.push(para("Executive · Sales & Dispensing · Procurement · Inventory · Finance · Quality · Clinical · Controlled Drug · Regulatory · Logistics · CRM · HR & Operations · Audit · Analytics & Forecasting · Security", { italics: true, color: SLATE }));

out.push(h("6.1 Running one", HeadingLevel.HEADING_2));
out.push(numbered("Open **Reports** and pick a pack from the catalogue."));
out.push(numbered("Set the **reporting window** — quick presets (Today, This Week, This Month, Last Month, This Year) or a custom range. The selected preset is highlighted."));
out.push(numbered("Scope it to branch or warehouse if you only want part of the network."));
out.push(numbered("Export as **PDF, CSV, JSON or XLSX**."));

out.push(h("6.2 Validation receipts", HeadingLevel.HEADING_2));
out.push(para("Every download embeds a unique validation QR recording who downloaded it, when, the tenant scope, the terminal identity, and an integrity code."));
out.push(callout("This is what makes an exported PDF defensible. A report handed to a regulator can be checked against the system that produced it, and a document that has been altered will not validate. Every download is also written to the audit trail."));

out.push(h("6.3 What you will and will not see", HeadingLevel.HEADING_2));
out.push(para("Reports are **tenant-scoped without exception**. You see your workspace and nothing else. Access is capability-gated, so two people running the same report may legitimately get different results — that is the isolation working."));

/* ---------- 7 ---------- */

out.push(h("7. Keeping it running", HeadingLevel.HEADING_1));

out.push(h("7.1 Health", HeadingLevel.HEADING_2));
out.push(...code(["curl -fsS https://tibatrace.esenai.co.ke/api/health/"]));
out.push(para("Expect `{\"status\": \"ok\", ...}`. Then confirm no container is restarting:"));
out.push(...code(["docker ps --filter 'name=tibatrace' --format 'table {{.Names}}\\t{{.Status}}'"]));
out.push(para("`api`, `hq` and `redis` carry health checks and should read `(healthy)`. `worker` and `beat` do not — check them directly:"));
out.push(...code(["docker exec tibatrace-worker-1 celery -A dawatrace inspect ping"]));

out.push(h("7.2 Backups", HeadingLevel.HEADING_2));
out.push(para("Take a database dump before every release, and keep them:"));
out.push(...code([
  "pg_dump --dbname=\"$DATABASE_URL\" --format=custom --no-owner \\",
  "  --no-privileges --file=/opt/tibatrace/backups/<label>/db.dump",
]));
out.push(callout("A dump that was never restored is a hope, not a backup. Practise the restore."));
out.push(para("Also back up, separately and encrypted: `/opt/tibatrace/secrets/.env.production`, and the volumes holding uploaded documents and POS installers."));

out.push(h("7.3 Secrets", HeadingLevel.HEADING_2));
out.push(para("All configuration lives in `/opt/tibatrace/secrets/.env.production`, mode `600`, owned by root. It is never committed, never printed, and never copied into a release directory."));
out.push(para("To rotate a secret: back up the file first, change every field that carries the value (a Redis password appears in **four** — `TIBATRACE_REDIS_PASSWORD` and three connection URLs), write the file atomically, then recreate the services that read it. `docker restart` is not enough — environment is fixed at container creation, so the container must be **recreated**."));
out.push(callout("Afterwards, prove the old credential no longer works. Rotation you have not tested is rotation you have not done."));

out.push(h("7.4 Disk", HeadingLevel.HEADING_2));
out.push(para("The application competes for disk with everything else on the host. Before a release, check headroom:"));
out.push(...code(["df -h /", "docker system df"]));
out.push(para("Release directories and superseded POS installers are the usual growth. Keep the running release plus one previous, and one installer per platform. **Never** prune images belonging to other applications on a shared host."));

out.push(h("7.5 POS client releases", HeadingLevel.HEADING_2));
out.push(para("POS installers are published through the release catalogue and downloaded from HQ by an authenticated operator. The Android APK is signed with the production keystore; the Windows installer is signed with Esenai’s own certificate."));
out.push(callout("**The Windows certificate is self-signed.** It gives you integrity and authenticity on a managed device where the certificate has been enrolled — which the managed-install package does for you. It will **not** clear SmartScreen on a machine that has never seen it. That is a distribution decision, not a signing failure, and the release manifest records the two separately as `cryptographically_signed` and `publicly_trusted`."));

/* ---------- 8 ---------- */

out.push(h("8. Reference", HeadingLevel.HEADING_1));

out.push(h("8.1 Capabilities", HeadingLevel.HEADING_2));
out.push(table(["Area", "Capabilities"], [
  ["Prescriptions", "`prescriptions.read` · `.write` · `.intake` · `.review` · `.clinical_review` · `.legal_validate` · `.pharmacist_verify`"],
  ["Dispensing", "`dispensing.read`"],
  ["Clinical support", "`cds.read`"],
  ["POS", "`pos.payment.collect` · `pos.shift.manage`"],
  ["Inventory", "`inventory.read` · `.manage` · `quality.release`"],
  ["Procurement", "`procurement.read` · `.write` · `.approve`"],
  ["Pricing", "`pricing.read` · `.manage` · `price_book.manage` · `.approve` · `.publish` · `manual_override.request` · `.approve` · `.approve_below_floor`"],
  ["Insurance", "`insurance.read` · `.manage`"],
  ["Patients", "`patients.identity.manage`"],
  ["Identity", "`identity.manage`"],
], [2100, 6926]));
out.push(callout("Grant the narrowest set that lets someone do their job. The separations above — request versus approve, approve versus approve-below-floor — exist to be used."));

out.push(h("8.2 Troubleshooting", HeadingLevel.HEADING_2));
out.push(table(["Symptom", "Cause", "Fix"], [
  ["“Account is not assigned to a workspace”", "No tenant on the user", "Assign one in Administration & Users"],
  ["“Select an existing tenant commercial SKU”", "Pricing an item whose catalogue entry is incomplete", "Finish the SKU: manufactured product and package definition"],
  ["Clinical screening unavailable at the counter", "Terminal is offline", "Screening needs the server. Do not dispense past a blocking finding"],
  ["Report download returns 503", "Release storage not configured", "Check `TIBATRACE_RELEASE_BACKEND` and that the artefact exists"],
  ["Installer download fails", "Artefact missing from storage", "Confirm the object exists at the configured backend"],
  ["Components report different revisions", "Partial deployment", "Failed deployment. Re-run activation for all services"],
  ["Image label reads `unknown`", "Image not built by the release pipeline", "Do not deploy it. Rebuild through CI"],
  ["Windows installer warns on launch", "Self-signed certificate not enrolled", "Install via the managed-install package, which enrols it"],
  ["Cash variance at close", "Float wrong at open, or unsynced work", "Reconcile Sync Centre before closing"],
], [2700, 2900, 3426]));

out.push(h("8.3 Deeper reading", HeadingLevel.HEADING_2));
out.push(table(["Topic", "Document"], [
  ["Release packaging", "`docs/deployment/TIBATRACE_RELEASE_PACKAGING_WORKFLOW.md`"],
  ["Medicine domain model", "`docs/domain/MEDICINE_CATALOGUE_DOMAIN_MODEL.md`"],
  ["Product/SKU/batch separation", "`docs/domain/MEDICINE_PRODUCT_SKU_BATCH_SEPARATION.md`"],
  ["Pricing model", "`docs/domain/COMMERCIAL_PRICING_MODEL.md`"],
  ["Procurement lifecycle", "`docs/domain/PROCUREMENT_LIFECYCLE.md`"],
  ["FHIR conformance", "`docs/fhir/FHIR_CONFORMANCE.md`"],
  ["Kenya data protection", "`docs/fhir/KENYA_DATA_PROTECTION_ACT_2019.md`"],
  ["Reports catalogue", "`docs/architecture/TIBATRACE_REPORTS_CATALOGUE.md`"],
  ["System architecture", "`docs/architecture/TIBATRACE_TECHNICAL_SYSTEM_DOCUMENTATION.md`"],
  ["Release notes", "`docs/releases/`"],
], [3000, 6026]));

out.push(new Paragraph({
  spacing: { before: 400 },
  border: { top: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 10 } },
  children: [],
}));
out.push(para("Corrections belong in this guide. If you find something here that does not match the system, the guide is wrong until proven otherwise — fix it.", { italics: true, color: SLATE }));

/* ---------- document ---------- */

const doc = new Document({
  creator: "Esenai Group Ltd",
  title: "TibaTrace — End-to-End Guide",
  description: "Install, configure, dispense, report and operate TibaTrace.",
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 21, color: "1F2937" } },
      heading1: { run: { font: "Calibri", size: 34, bold: true, color: NAVY },
                  paragraph: { spacing: { before: 400, after: 180 },
                               border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: TEAL, space: 6 } } } },
      heading2: { run: { font: "Calibri", size: 26, bold: true, color: TEAL },
                  paragraph: { spacing: { before: 300, after: 120 } } },
    },
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 440, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 880, hanging: 240 } } } },
      ]},
      { reference: "steps", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 440, hanging: 260 } } } },
      ]},
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: {
      default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        spacing: { after: 200 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 6 } },
        children: [new TextRun({ text: "TibaTrace — End-to-End Guide", size: 16, color: "94A3B8" })],
      })] }),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [
          new TextRun({ text: "v1.0.0-rc14   ·   ", size: 16, color: "94A3B8" }),
          new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "94A3B8" }),
        ],
      })] }),
    },
    children: out,
  }],
});

Packer.toBuffer(doc).then(b => {
  fs.writeFileSync(process.argv[2], b);
  console.log("written:", process.argv[2], b.length, "bytes");
});
