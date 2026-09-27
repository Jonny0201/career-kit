# Career Kit

An on-demand, agent-assisted job-search toolkit. Keep your career evidence in a
private local workspace, evaluate jobs against confirmed facts, generate
documents with **your own templates and tools**, and retain an auditable record
of reviews, applications and outcomes.

Career Kit is not an unattended application bot. The agent reasons and explains;
the CLI manages evidence, revisions and bounded I/O. You review documents,
register accounts and submit applications yourself. Sending email requires a
separate, explicit authorization for the exact message.

## What is included

- Blank onboarding inputs and a detailed, project-specific interview guide.
- User-owned company-list import (JSON/CSV/text), preference-led discovery,
  blacklist-aware batch proposals and resumable group review; no starter registry.
- Confirmed facts, source references and per-purpose disclosure controls.
- Company admission, official-source job intake and evidence-bound matching.
- Duplicate-safe application records and optional user-defined company quotas.
- A reviewed local document-backend interface, PDF/text reconciliation and
  exact-artifact human review. There is **no bundled production template**.
- On-demand IMAP/SMTP with a provider-supported app password, one-shot sending
  and uncertain-send recovery. OAuth-only providers need another adapter.
- Private password handoff for manual account registration, outcome records and
  an immutable, hash-chained local journal.
- Read-only parsers for Greenhouse, Lever, Ashby, SmartRecruiters, Workday and
  generic job pages. Parsing alone does not verify a company or complete a crawl.

The public toolkit does not contain a private deployment's data, renderer,
templates, preferences, historical applications or Git history. It is not a
drop-in migration of a separately configured deployment. There is no built-in
browser autofill, live job crawler, scheduler, CAPTCHA solver or automatic Submit.

## Start here

Requirements: Python 3.11+, Git and a POSIX shell. The development tests run on
macOS; other platforms need their own verification. Document tools are needed
only after you choose a backend.

```sh
git clone <repository-url> career-kit
cd career-kit
./tools/bootstrap
./tools/careerkit init
```

Then read the [complete getting-started guide](document/getting-started.md).
`init` creates empty, ignored inputs; it does not invent a candidate or overwrite
existing data. A healthy base environment is not proof that email or document
generation is configured.

For an agent, start with [AGENTS.md](AGENTS.md) and the repository's
[Career Kit skill](.agents/skills/career-kit/SKILL.md). The guide tells the agent
what to ask, what to save and how to reach the first real application without
having to reverse-engineer the source.

For company setup, read [preferences and initial lists](document/company-onboarding.md).
For continuation, run `./tools/careerkit status`; it lists existing work and
next-step hints without resetting the workspace or exposing contact details.
Before the user submits, `application readiness <id>` checks current evidence,
documents and their reviews. It is not authorization or an automated Submit.

## Your workspace stays yours

| Directory | Purpose | Published by this repository? |
| --- | --- | --- |
| `src/`, `tools/`, `tests/`, `document/` | Generic code, synthetic tests and guides | Yes |
| `local/` | User inputs, review exports, templates and renderer code | No |
| `data/` | Confirmed records, journal and final documents | No |
| `credentials/` | Private email/account secrets | Never |
| `runtime.nosync/`, `tmp/` | Local execution state and disposable work | Never |

No initial personal information is shipped. All examples and tests are
deliberately fictional. `.gitignore` is a convenience, not encryption or a
security sandbox. Keep your own data backup separate from this public checkout;
never force-add private files. See [data and security](document/data-and-security.md).

## Documents are deliberately pluggable

Bring a resume template and, if an application requests it, a cover-letter
template. Tell the agent your preferred tool, language, page limits and design.
The agent builds a private backend under `local/document-profiles/`, reviews the
code and dependencies with you, and registers its exact hash. No proprietary
application, particular typesetting engine, font, column layout, degree
selection or career preference is required by the core.

See the [backend protocol](document/document-backends.md) and
[workflow command reference](document/workflows.md).

## Development and publication

```sh
./tools/test
./tools/audit-public
```

Publication additionally requires a fresh, exact-tree semantic privacy review,
including all reachable history and the actual push targets. See
[CONTRIBUTING.md](CONTRIBUTING.md). Automated checks do not prove that arbitrary
prose contains no personal information; source inspection remains mandatory.

Licensed under [Apache-2.0](LICENSE).
