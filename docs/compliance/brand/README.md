# TibaTrace and Esenai Group document branding

The 26 October 2026 edition covers all 27 Markdown documents in
`docs/compliance/system/` and all eight Markdown documents in
`docs/compliance/dha/`. The historical YAML requirements catalogue carries matching
product/operator attribution and is included as source material. It is not
converted into a new authority-approved requirements document.

The supplied TibaTrace and Esenai Group logos are retained without pixel edits.
Word uses a native crop rectangle to remove excess whitespace around the TibaTrace
mark. The Esenai asset is the owner's current supplied artwork from the local
Document Branding folder. The SVG architecture diagram is an editable rendition
of the Mermaid graph in the system architecture document; the original graph is
retained in the Markdown source and SVG metadata.

The document system uses A4 pages, black Carlito headings, navy table headers,
light gray borders, alternating row shading, repeated table headings, company
metadata, document IDs and eight-point page fields. Page layout and content
preservation must be rechecked after each change. Do not replace technical
`dawatrace` package paths, environment variables, URLs or historical evidence
identifiers with a display brand name.

This branding edition changes presentation and public product attribution. It does
not approve a policy, grant a certification, change a historical finding or enable
an integration. The DPIA remains Not Approved. Original evidence dates and release
boundaries remain controlling; the current server record is rc75 in the register
and technical delivery documents. Branded exports are review copies.

## Rebuild the package

Use the Node and Python executables and package directory returned by Codex's
workspace dependency loader. Required bundled packages are `marked`,
`python-docx`, `Pillow`, `lxml`, `pdfplumber` and `pypdf`. Run commands from the
repository root. Do not install artifact dependencies into the application.

1. Set `CODEX_WORKSPACE_NODE_MODULES` to the bundled Node package directory. Run
   `scripts/docs/tokenize_compliance_pack.mjs` with the bundled Node executable.
2. Run `scripts/docs/build_compliance_pack.py` with the bundled Python executable.
   It creates 35 DOCX files under `output/docx/TibaTrace_Esenai_Group_2026-10-26/`.
3. Run `scripts/docs/render_compliance_pack.py --renderer ABSOLUTE_SKILL_RENDERER_PATH`
   with the same Python executable. Supply the document skill's `render_docx.py`.
   It resolves the bundled LibreOffice and Poppler; do not use desktop LibreOffice.
4. Run `scripts/docs/validate_compliance_pack.py`. Check every rendered page image,
   correct defects, rebuild and render again. Only after visual review, record
   `result: PASS` and the actual `pages_reviewed` in
   `tmp/document-branding/VISUAL_QA.json`; this record is an engineering layout
   check, not a document or DPIA approval.
5. Run `scripts/docs/package_compliance_pack.py`. It checks content/layout review
   records, produces matching PDF links without altering page content streams,
   and writes a ZIP containing Word, PDF, source files, logos, an HTML index,
   manifest and SHA-256 inventory. Temporary renders and restricted production
   evidence are excluded.

The reviewed edition contains 35 Word files, 35 PDF files and 110 rendered pages.
Generated files are ignored by Git; the source documents, brand assets and builders
are versioned. The old `TibaTrace_System_Documentation_Word.zip` remains a separate
historical export.
