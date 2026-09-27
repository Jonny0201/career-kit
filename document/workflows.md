# Command reference and workflow connections

Run commands from this independent checkout. `tools/careerkit --help` and each
subcommand's `--help` are authoritative for flags. File inputs are relative paths
under `local/inputs/`, `data/drafts/` or `runtime.nosync/work/`; never credentials.
IDs and revisions below are placeholders; use actual CLI results. JSON input is
data, not shell code. Never put passwords or private text into command arguments.

## Start or resume

`init` creates missing blank private inputs without overwriting anything.
`status` returns IDs, revisions, missing setup and current pending work; use it
instead of guessing file names or asking the user to reconstruct prior steps.
Its suggestions are advisory, not a new authorization gate. `doctor` checks the
base environment; `verify` checks local record integrity. A user who defers
company discovery is not asked to supply someone else's sample list.

## Candidate data

```sh
./tools/careerkit init
./tools/careerkit candidate import history --file local/inputs/history.json
./tools/careerkit candidate approve history --revision <draft-revision>
```

Repeat for profile, facts and preferences. See [onboarding](getting-started.md)
for field shapes and detailed interviews. First import has no `--expected`;
updates require `--expected <current-revision>`. Import is a draft, never an
implicit approval. `candidate bundle resume` returns only explicitly
model-visible, resume-permitted technical facts and their current revision.
It omits identity. `match`, `cover_letter` and `interview` are separate purposes.

For private inspection use:

```sh
./tools/careerkit export-local candidate_history history --output local/review/history.json
```

The CLI prints the export path, not its values. Open it locally for the user;
do not route identity, unapproved narrative or credentials into a model.

## Company and job

For the full preference interview and both with-list/without-list paths, read
[company onboarding](company-onboarding.md). Batch CLI connections are:

```sh
./tools/careerkit company seeds-import --file local/inputs/company-seeds.json
./tools/careerkit company seeds-show <seed-batch-id>
./tools/careerkit company propose-batch --file local/inputs/researched-companies.json
./tools/careerkit export-local company_batch <batch-id> --output local/review/company-batch.json
./tools/careerkit company review-batch <batch-id> --revision <presented-revision> --decision approved
```

Import supports JSON/CSV/text. Normalize spreadsheets locally first. No company
is approved by import or by finding a public URL. Blacklisted canonical names,
aliases and original seed labels are excluded from proposals; preexisting
registry decisions are not overwritten. A partially reviewed batch resumes
with the original presented revision and same decision from `status`.

Company input needs `name`, HTTPS `official_url` and `evidence`. Optional
`verified_careers_hosts` contains verified hostnames, not arbitrary URLs. For
culture prose, evidence must be a list of `{id, url, excerpt}` from official
sources. Research does not prove candidate facts or grant registry admission.

```sh
./tools/careerkit company propose --file local/inputs/company.json
./tools/careerkit company review <id> --revision <revision> --decision approved
./tools/careerkit company list
./tools/careerkit company enrich <id> --revision <revision> --file local/inputs/official-evidence.json
```

Enrichment accepts `verified_careers_hosts`, `aliases` and `evidence`, with evidence required.
Verified aliases are added without removing prior aliases; the same URL under
different names requires explicit identity resolution, not a silent merge.
It cannot change admission or identity. Company IDs use the supplied official
URL; the agent must resolve aliases/parent groups before proposing duplicates.
This initial core does not automate corporate ownership research or group merging.

Normalize a current official job into a private temporary object:

```json
{
  "company_id": "cmp-example",
  "requisition_id": "example-role",
  "title": "Fictional role",
  "description": "Actual current official text belongs here privately.",
  "source_url": "https://employer.invalid/job",
  "checked_at": "<current-UTC-ISO8601-observation>",
  "active": true,
  "requirements": [
    {"id": "responsibility-example", "text": "The central work", "role_defining": true, "hard": false}
  ]
}
```

Each responsibility, required qualification and preferred qualification needs a
distinct ID. `hard` is a genuine non-negotiable condition, not every keyword.
Use `hash-input --file runtime.nosync/work/job.json` to obtain the exact canonical
JSON SHA-256 as `job_hash` in the mapping; pretty-printing bytes is not that hash.
The command returns only the hash, not the input values.

```json
{
  "job_hash": "<canonical-job-hash>",
  "facts_revision": "<confirmed-facts-revision>",
  "decision": "apply",
  "rationale": "Main agent's evidence-based choice within the user request.",
  "requirements": [
    {"id": "responsibility-example", "coverage": "transferable", "fact_refs": ["fact-example"], "reason": "Explain the actual transfer and gap."}
  ]
}
```

Coverage is `direct`, `transferable`, `unsupported` or `unknown`. Gaps have no
fact refs. Skills labels alone do not establish production ownership. Every
requirement must be mapped once. The validator checks references and declared
hard/central gaps, not semantic truth. The primary agent must actually reason
and the user reviews documents; do not game fields to force an apply result.

```sh
./tools/careerkit job evaluate --job runtime.nosync/work/job.json --mapping runtime.nosync/work/mapping.json
./tools/careerkit application create --job runtime.nosync/work/job.json --mapping runtime.nosync/work/mapping.json --reason "User-requested search; main-agent evidence-based selection"
```

The official observation must be recent; a closed job or unsupported central
work cannot be made eligible by a fabricated timestamp. Same company/requisition
reuses the application. Unselected jobs need not become permanent records.

`ats-parse <adapter> --file runtime.nosync/work/feed.json --source-url <official-url>`
parses a supplied public payload. It does not fetch pages or pagination, prove
official ownership, authenticate, execute scripts or assert scan completeness.

## Documents, form advice and submission

Read [backend setup](document-backends.md). After creating the application,
render its resume, inspect it and record actual user review.

`application requirements <id> --file <input>` expects `cover_letter` set to
`required`, `optional`, `not_supported` or `single_file_resume_only`, plus
`page_evidence` describing the observed form. Only required/optional permits a
letter. Optional does not make it mandatory. A unique resume upload slot does
not justify creating an extra letter attachment.

`application show <id>` gives safe status and document references. Human users
register, fill, upload and submit using their browser. Agent inspection/advice
is not browser automation. After an actual user submission report:

```sh
./tools/careerkit application report-submitted <id> --reason "Actual user's completion report"
```

It is idempotent and preserves discrepancies if local preparation was incomplete;
it does not fabricate missing approvals. Never call it to pass a test or because
the browser reached the final page.

Before the user submits, check the actual upload set:

```sh
./tools/careerkit application readiness <id>
./tools/careerkit application refresh <id> --job runtime.nosync/work/current-job.json --mapping runtime.nosync/work/current-mapping.json
./tools/careerkit application readiness <id>
```

Refresh only when needed, after observing the real official page and reevaluating
its current facts. It preserves the same company/requisition and application ID.
A changed observation timestamp alone keeps unchanged document approvals; a
changed JD body or candidate source is reported as stale. Readiness checks job
freshness, company admission/exclusions, the user's optional quota, exact file
bytes and current document reviews. A missing optional letter is fine; an optional
letter selected for upload still needs review. `submission_documents` excludes
review-only companions and letters unsupported by the observed form. The result
is local advice, not browser execution or authority to submit.

After a real submission report, its preparation snapshot cannot be replaced by
new renders, refreshed JDs or rewritten requirements. Preserve it for outcomes;
do not regenerate an old application to make its historical warnings disappear.
If the user or HR requests an updated document later, generate a separately
bound `correspondence` document with `request_ref`, review it, then prepare a
separately authorized mail draft. `application show` lists these under
`correspondence_documents`; they never replace the original submission set or
consume another application quota. See the document-backend protocol.

## Manual registration handoff

```sh
./tools/careerkit account prepare <account-id> --registration-url <verified-official-URL>
```

This creates/reuses an owner-only file under `credentials/registration/`. The
password is cryptographically random, 12 ASCII upper/lower/digit characters with
all three classes. Use `--passwordless` only when that is the real flow. The
user opens the returned path locally, registers and saves the actual password
used if the site requires a different policy. The agent must not read the file
into chat or automatically submit registration. The existing handoff is reused,
not regenerated on continuation. Report with `account report <id> --status
registered|awaiting_verification|cancelled` using exactly the user's observation.

The public core has no automated OTP extraction, login or reset integration.
Use the service UI and a reviewed local secret-filling tool if available; never
pretend this toolkit has tested an unimplemented provider-specific flow.

## Mail

Create `credentials/mail.json` in a local editor (directory 0700, file 0600):

```json
{
  "auth_kind": "app_password",
  "username": "person@example.invalid",
  "password": "<provider-generated-app-password>",
  "imap": {"host": "imap.example.invalid", "port": 993},
  "smtp": {"host": "smtp.example.invalid", "port": 465, "tls": "ssl"}
}
```

Replace values locally with the provider's official settings. IMAP uses TLS;
SMTP accepts `ssl` or `starttls`. Never use the primary account password or
claim all providers support this. OAuth is not implemented in this adapter.

`mail status` validates shape/permissions without exposing credentials or
claiming connectivity. `mail sync --limit 10` reads INBOX read-only without
marking read or deleting mail. It returns redacted plain-text summaries, never
persists raw MIME and does not extract attachments or execute links. Names and
arbitrary prose can still be identifying: use only within the user's scoped
mail request, not as a general anonymization guarantee.

Draft input: `to` list, `subject`, `body`, optional `in_reply_to`, `references`
and `attachments` containing `path` and `sha256`. Attachments must reside in
`data/documents/` or `local/attachments/`. Present the exact draft in a local
review export before authorization; do not infer permission from prior review.

```sh
./tools/careerkit mail draft --file local/inputs/reply.json
./tools/careerkit export-local mail_draft <id> --output local/review/reply.json
./tools/careerkit mail authorize <id> --revision <reviewed-draft-revision>
./tools/careerkit mail send <authorization-id>
```

Authorization expires after 15 minutes and is claimed durably before SMTP.
Confirmed means accepted by SMTP, not read by the recipient. Uncertainty blocks
replay. Inspect provider Sent state and use `mail reconcile <id> --outcome
confirmed|not_sent|unknown --evidence <nonsecret-observation>`. Unknown remains
blocked. Only confirmed non-delivery plus a new explicit user authorization can
justify a new draft/send. Do not alter wording to bypass duplicate protection.

## Outcomes and recovery

`outcome <application-id> --file <input>` records `kind`, `source`, `text`.
Kinds: acknowledgement, rejection, question, interview, offer, no_response,
hypothesis. Separate observations from interpretations. No automatic fact or
permanent strategy update follows.

`verify` checks committed records and detects orphans. Read
[data and security](data-and-security.md) before recovering a lock, orphan or
uncertain action. Do not reinitialize or silently edit current state.
