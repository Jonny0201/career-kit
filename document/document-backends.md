# Private document backends

The public core has no resume or cover-letter template, font choice or rendering
application. The user supplies a template or asks an agent to design one. The
agent implements a **private**, individually reviewed adapter. This interface
does not imply that Word, a typesetter or a proprietary design application is
already supported by a shipped adapter.

## Profile directory and manifest

Create `local/document-profiles/<profile-id>/` with all template assets and an
entrypoint. These files are ignored by Git. The profile is a user artifact,
not something to contribute to the public toolkit. Example manifest shape:

```json
{
  "schema_version": 1,
  "id": "my-documents",
  "document_types": ["resume", "cover_letter"],
  "languages": ["en"],
  "output": "pdf",
  "entrypoint": "render.py",
  "required_commands": [],
  "identity_fields": ["display_name", "email"],
  "static_text": ["Experience", "Education"],
  "maximum_pages": 2
}
```

These are illustrative choices, not defaults. Choose languages, page limits and
labels with the user. Use separate profiles if resume and letter need different
limits or modalities. `output` is `pdf` or `text`. Allowed identity fields are
`display_name`, `email`, `phone`, `location`, `links`; the renderer receives only
those requested. Values are nonempty strings or exact requested-language
values from a user-authored map. No silent translation or language fallback.

`required_commands` lists executable names only, never shell expressions.
Dependencies must be installed and trusted separately. `entrypoint` is a Python
file within the profile; it may invoke the user's chosen local tool. No symlinks
or parent-relative paths. All files, including templates and code, are hashed.
After changing any of them, register and approve the new exact profile again.

## Executable protocol

The core invokes the approved entrypoint with its own Python interpreter:

```text
render.py --input <private-input-json> --output-dir <private-work-directory>
```

Input has `schema_version`, `document_type`, `language`, `claims`, `identity`,
`static_text` and the selected job's `title`/`description`. Identity injection
happens locally after candidate-fact selection, not through a model prompt.
The renderer must produce `document.pdf` or `document.txt` in the output
directory. Do not log the input, send telemetry, fetch remote assets or embed
unapproved personal metadata. Close only applications this task opened.

The process has a bounded timeout and a reduced environment. **This is not an
OS security sandbox:** approved code can still access files allowed by the
operating system. Review imports, filesystem/network access, commands and
dependencies before executing a backend. Hash approval detects changes; it
cannot make malicious code safe. For stronger isolation use an independently
configured OS sandbox/container appropriate to the chosen tool.

## Content contract

Create a private content input under `local/inputs/`, `data/drafts/` or runtime
work. A fictional shape:

```json
{
  "application_id": "app-example",
  "facts_revision": "<current-confirmed-facts-revision>",
  "document_type": "resume",
  "language": "en",
  "claims": [
    {"text": "User-confirmed claim, phrased for this job.", "fact_refs": ["fact-example"]}
  ]
}
```

The agent supplies wording, sequencing and optional extra layout fields to its
private backend. The core verifies references and text preservation; it cannot
prove that a paraphrase is semantically faithful. The user must inspect truth,
ownership and visual quality. A `fact_ref` must not be used to launder an
unsupported claim. Do not force facts into output if they are not permitted for
that document type.

For cover letters, `kind: "company"` claims require
`company_evidence_refs` to structured official company evidence
(`id`, `url`, `excerpt`) in the company record. Candidate claims still require
facts. `kind: "interest"` and `kind: "closing"` are explicitly non-factual
letter statements; do not hide career or culture assertions there.

An optional review translation is a separate artifact, not the upload letter.
Set `purpose: "review_only"` and
`translation_of: {"id": "<submission-letter-id>", "revision": "<exact-revision>"}`
in its content input. Use a profile that supports the translation language.
It is attached under `cover_letter:review_only:<language>`; the normal
`cover_letter` reference stays unchanged. The translation binds the source
artifact hash; if the submission letter changes, refresh the companion. Human
review checks meaning/parity; reference equality is not proof of translation
quality. Normal documents default to `purpose: "submission"`.

## Register, verify, publish and review

```sh
./tools/careerkit documents register my-documents
./tools/careerkit documents approve-profile my-documents --revision <reviewed-revision>
./tools/careerkit documents check my-documents
./tools/careerkit documents render <application-id> --profile my-documents --content local/inputs/content.json
```

The last command independently extracts PDF text using pypdf (or reads text),
checks page limits and requires every declared claim/identity field to survive.
Unexpected alphanumeric content fails; declare legitimate fixed headings in
`static_text`, but never put candidate claims there to avoid evidence checks.
Inspect layout, cropping, reading order, original publication titles and
ligatures in the actual final file. Extraction is not an ATS vendor guarantee.

Successful rendering preserves final bytes, the exact content snapshot, source
and profile hashes under `data/`. It attaches a **pending-review** document to
the existing application. User approval targets its exact revision:

```sh
./tools/careerkit documents review <document-id> --revision <revision> --decision approved --feedback "Actual user review"
```

Use `revise`/`rejected`/`skipped` when that is what the user said. Revisions do
not change old bytes. If the artifact was saved but attaching it was interrupted,
`documents attach <application-id> <document-id>` recovers without rerendering.
Do not recreate the application. Changed candidate sources invalidate approval
of stale content; refresh affected documents rather than relabeling them.
Documents also bind the JD content, separately from its observation timestamp.
Reviewing a superseded artifact does not silently replace the current selection;
use an explicit `documents attach` if the user deliberately selects it again.
Once a submission is reported, its document references remain a historical
snapshot and cannot be replaced through render/attach/review.
For a separately requested post-submission update, use `purpose: "correspondence"`
and a nonempty `request_ref` pointing to the actual user/HR request. This creates
new artifacts under `correspondence_documents`, preserving the original
`documents`, JD and submission timestamp. A requested correspondence letter
does not depend on the old form's letter slot; its review-only translation binds
that exact correspondence artifact and stays in the same separate container.
Review is still required, and sending it needs a distinct mail authorization.
Do not create a duplicate application or fake a second submission for a follow-up.
Older artifacts without a JD-content binding are reported as unbound by
readiness. Do not assign them today's job hash without evidence; prepare and
review a bound version for a still-unsubmitted application. Historical submitted
artifacts remain preserved and are not rewritten during an upgrade.

## Test before real use

Use synthetic names and facts in an isolated directory. Test missing tools,
altered code, unsupported references, renderer failure, timeouts, extracted
text and multipage limits. Clean generated test documents on success/failure.
The repository's tiny text/PDF test renderers are fixtures only: neither is a
production resume template or an endorsement of its visual quality.
