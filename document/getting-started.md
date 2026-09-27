# From a blank checkout to a first application

This guide is for both a new user and an agent meeting that user for the first
time. No personal data, resume/letter template or document-generation tool is
provided by the public repository. Do not read the source to guess the workflow:
follow these stages and consult the linked command reference as needed.

## 1. Decide whether this is really a new setup

Ask: is this a new candidate, an existing workspace, or a move to another
machine? For an existing workspace run `doctor`/`verify` and resume exact records;
do not call empty inputs confirmed or overwrite previous history. Never inherit
parent-directory settings, a contributor's preferences or test identities.

Run the README bootstrap commands. Python dependencies live in this checkout's
`runtime.nosync/venv`. `init` creates five blank JSON inputs under
`local/inputs/`: profile, facts, history, preferences and company-seeds. Only the
first four are candidate sections; the seed list uses the company intake below. User files are ignored
by Git. Back them up privately; a public source clone cannot restore them.

## 2. Complete private identity and career basics

The user enters contact details in their local editor, not by pasting secrets
into a chat. The agent can explain each field without reading private values.
`profile.json` uses `display_name`, `email`, `phone`, `location`, `links`. Each
document field is a string, or a language-to-string map such as
`{"en": "Example Candidate", "zh-Hans": "虚构候选人"}`. Names and location
translations must be user-confirmed. `null` means not provided; never guess it.
Do not add birthdays, sensitive identity or other unnecessary attributes to
public examples or the model bundle.

Ask for the following career basics, then preserve the answers in history:

- Employment: employer names/language variants, role, start/end month, current
  employment, location/work mode, scope and responsibility changes over time.
- Education: institution, actual degree and field, dates, status and confirmed
  translations. Do not turn a convenient form category into a false degree.
- Languages/skills: actual use and proficiency; distinguish learning, personal
  demonstration and production ownership. Preserve limitations.
- Publications, public projects and awards: original title, authorship, dates,
  links, individual contribution and disclosure permission.

`history.json` has `employment`, `education`, `projects` and `publications`
arrays. History intentionally permits detailed user-specific fields. The
agent must explain their local schema and keep stable IDs; the core only
validates the project narrative/interview boundary. It does not certify every
possible career field or employment-law answer.

## 3. Interview each actual project, not a generic checklist

The user first describes one project in their preferred source language. Ask
whether they want a grouped interview now or to add more narrative first.
Extract what is already known, including rejected questions. Do not ask them
to repeat it. A basic STAR outline is a starting point, not a finished bank.

For this specific project, group follow-up questions covering:

1. **Problem and constraints:** what failed before, who was affected, why it
   mattered, alternative approaches and constraints such as compatibility,
   schedule, safety or existing architecture.
2. **Responsibility:** what the person proposed, designed, implemented,
   reviewed, tested, shipped and maintained; what others owned; whether they
   led by authority, influence or individual contribution.
3. **Technical depth:** the actual hardest design decision, its trade-offs,
   invariants, edge cases and diagnostics. Ask domain-specific questions.
   For a fictional message queue, ask about ordering, retries, failure recovery
   and backpressure; for a fictional forecasting experiment, ask about leakage,
   baselines, evaluation windows and the person's experimental contribution.
   These are examples of reasoning, not mandatory claims for all candidates.
4. **Outcome:** measured versus estimated results, denominator, before/after
   window, data source, uncertainty, actual adoption and whose result it was.
   Do not convert an estimate into an exact percentage or promise that an
   internal benchmark represents an industry-wide ranking.
5. **Lifecycle and status:** dates, review, deployment, rollout, monitoring,
   support and whether a planned capability was actually enabled. A planned
   promotion or release is not an achieved fact.
6. **Disclosure:** which names, numbers, designs, code and customer details
   may leave the machine; what may enter a model; what may be in a resume,
   cover letter or interview only.

Do not demand confidential implementation details. Macro-level output can show
ownership, system scope, production delivery and outcomes without exposing
internals. If an answer is unknown, disputed or deliberately withheld, keep
that status instead of manufacturing a stronger answer.

### Save answers so another agent can continue

Give projects stable IDs, and questions stable IDs within that project. Example
fictional history entry:

```json
{
  "id": "project-example",
  "narrative": "Fictional project summary supplied by the user.",
  "interview": [
    {
      "id": "q-ownership",
      "question": "Which part did you personally design and deliver?",
      "answer": "Fictional confirmed answer.",
      "status": "confirmed",
      "disclosure": "resume_and_cover_letter"
    }
  ],
  "fact_refs": ["fact-example"],
  "tags": ["reliability"],
  "unresolved": []
}
```

Use `unknown`, `declined`, `corrected` or `confidential` explicitly when relevant.
Preserve original language and superseded answers in immutable revisions. A
source reference can point to `history/projects/project-example/q-ownership`.
Question IDs are indexes, not a way to bypass disclosure limits.

`facts.json` separates approved reusable claims from raw detailed history:

```json
{
  "facts": [
    {
      "id": "fact-example",
      "text": "Fictional statement; replace only with the user's actual evidence.",
      "language": "en",
      "source_ref": "history/projects/project-example/q-ownership",
      "category": "technical",
      "model_visible": true,
      "allowed_outputs": ["match", "resume", "cover_letter", "interview"],
      "qualifiers": "Individual scope and uncertainty remain part of the claim."
    }
  ]
}
```

Never import the example as the user's fact. Facts that cannot enter model
context must set `model_visible` false; output permissions are separate. Neither
a model suggestion nor a website establishes a candidate fact.

Use `candidate import` to save a draft, show the user their exact local version,
then `candidate approve` with the returned revision only after confirmation.
Update with `--expected` using the current revision; a conflict means reread,
not overwrite. Confirm history, facts, profile and preferences separately.

## 4. Establish job and company preferences

Ask role families, level, acceptable transitions, geography, work authorization,
remote/on-site constraints, employment type, compensation/negotiability,
working conditions, exclusions and prioritization. Ask what is a hard limit,
what is unknown and what may be discussed. Do not impose any contributor's
company grading, geographic definition, blacklist or quota.

Explicitly ask whether the user has an initial company list. Accept their
spreadsheet, CSV, text, pasted names or URLs; ask about source age and recruiter
rows. If they have no list, ask whether to discover firms from their confirmed
preferences. Do not supply a contributor's list, require a list to proceed with
authorized discovery, or repeatedly ask after a deferral. An existing registry
or direct JD does not require restarting company onboarding.

Store this in `preferences.json`; empty arrays are unknown/unset, not universal
consent. `quota` may be null or `{"maximum": 2, "window_days": 90}` if that
fictional rule is explicitly chosen by the user. The tool counts actual
reported submissions, not prepared applications. Ask for existing applications
and active interviews rather than pretending this is the person's first search.

A supplied company list is a lead, not proof of current identity or a job.
Clean duplicates and recruitment-agency ambiguity, verify official sources,
propose admissions and record the user's decision. Batch authorization is
possible only when its scope is explicit; never fabricate individual approvals.
Follow [company onboarding](company-onboarding.md) for the exact preference
fields, private list formats, duplicate handling, official research, batch
proposal/review and interruption recovery. Raw lists and confirmed registries
are separate: `company seeds-import` saves leads, not approved companies.

## 5. Configure the user's document generator

Ask for resume and, when needed, cover-letter templates. Ask which tool is
available/licensed, what the user likes about the layout, languages, page limits,
font/readability preferences and whether they need a review-only translation.
If no template exists, offer to design one with the user. Do not silently copy
a template or make an arbitrary proprietary application mandatory.

The agent implements a private backend and assets in `local/document-profiles/`.
Use [the protocol](document-backends.md), approve its exact reviewed
code, test only synthetic material first, inspect output and clean test files.
Only then render the user's documents. A backend's own success flag does not
replace the independent text and human visual checks.

## 6. Find one worthwhile job and prepare its documents

Read current official careers pages. Normalize each responsibility and
qualification with a distinct ID. The agent maps confirmed facts to actual work,
not just keywords; describe transferable evidence and honest gaps. Use
`job evaluate` to validate the exact mapping. Keep unselected jobs temporary.

Within a user request to find/apply for suitable jobs, choose an eligible one
and use `application create`. It reuses the same company/requisition instead
of duplicating it. Explain the choice, source, working conditions and important
gaps along with the document; do not pretend the user pre-approved that JD.

Select strong professional evidence and relevant differentiators while
preserving true responsibility. Publication titles remain original. Internal
confirmation dates are not resume achievements; preserve real observation
periods without implying a precise current result. Render and show the exact
final artifact with its selection reasons. Record APPROVE/REVISE/REJECT against
that revision. A revision needs fresh checks and review.

## 7. Complete the real application with the user

Open the verified official application page. Registration is manual. If the
user wants centrally prepared credentials, `account prepare` creates an
owner-only local handoff; open it in their editor without reading or copying
its password into chat. The user registers and reports what actually happened.
The CLI does not bypass CAPTCHA, MFA or legal acknowledgments.

Inspect application fields only when requested. Explain all applicable answers
from confirmed facts, including expandable work/education/website sections.
The user fills the form and uploads files. Determine actual cover-letter
requirements and record them; generate a letter only when appropriate. Verify
official culture statements before writing. Keep a separate review translation
local and never upload it accidentally.

The user submits. After their actual report, call `application report-submitted`
once. Preparing a PDF, finishing a preview or clicking Next is not a submission.
Keep final documents and exact evidence; temporary discovery work can be removed.
Before presenting the final upload set, call `application readiness`. If the
official job observation is stale, refresh its evidence/mapping with
`application refresh` on the same application. A timestamp-only refresh preserves
unchanged document approvals. Changed job content or candidate facts requires
affected documents to be refreshed; do not just reapprove an old artifact.
Use `purpose: "review_only"` and `translation_of` for a companion letter so it
cannot replace the submission-language attachment. Submitted preparation
snapshots remain frozen; the reporting command records actual events even when
it must preserve warnings about missing local preparation.

## 8. Optional email and subsequent outcomes

Configure only a dedicated provider-supported app password in
`credentials/mail.json` with owner-only permissions. Many providers restrict
password-based IMAP/SMTP or require OAuth; this implementation is not universal.
If unsupported, use the provider's UI or develop/review another adapter rather
than weakening authentication. See the workflow reference for the exact shape.

On request, read bounded summaries, associate real applications, draft a reply
and show exact recipients/content/attachments locally. A distinct authorization
permits one send. On uncertainty inspect provider state before any new action.
No scheduler or background watcher is installed.

Record rejection/interview/offer observations with sources. Analyze gaps and
possible experiments separately from facts; a low-information outcome can
legitimately yield no specific conclusion. Resume from local records next time.

## 9. Continue without rereading the whole codebase

Run `tools/careerkit status` after a fresh session or interruption. It returns
existing candidate section revisions, seed/batch IDs, application IDs, current
pending reviews and uncertain mail effects, plus suggested next actions. It does
not show contact fields, seed notes, mail bodies or secrets, and does not grant
authorization. `verify` still checks integrity. Mail setup is optional for job
search; document tools are required only when generating the selected format.
