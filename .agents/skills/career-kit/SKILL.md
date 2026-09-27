---
name: career-kit
description: Guide onboarding, evidence-based job matching, user-configured resume and cover-letter generation, private mail and human-operated application workflows in a Career Kit checkout. Use only within the independent root marked by .career-kit.json.
---

# Career Kit

Read `AGENTS.md` from the same root. Never resolve missing files against an
ancestor workspace or import another user's setup. This skill is an operational
router, not authorization to send email, create accounts or submit applications.

1. Run `tools/bootstrap` and `tools/careerkit doctor`; inspect actual local
   state and verify its integrity. Do not repeat onboarding for an existing user.
2. For initial setup and project interviews, read
   `document/getting-started.md`. Ask detailed questions based on the actual
   project, group one topic's questions, retain stable source/question IDs and
   distinguish confirmed, unknown, corrected and non-disclosable answers.
3. For job, review, application, mail or outcome work, read
   `document/workflows.md` and use the tracked CLI. Semantic decisions remain
   with the main conversational agent; exact revisions and I/O remain with code.
4. For document work, additionally read `document/document-backends.md`. Ask
   the user for their own templates and tool preferences. A missing renderer is
   setup work, not permission to copy another deployment's implementation.
5. For recovery, secrets or storage, read `document/data-and-security.md`.
   Stop at uncertain side effects; do not manufacture successful results.

Keep applicant identity and long-lived secrets out of model prompts. Use
purpose-bound candidate bundles. Present the exact final document for review;
record the user's actual response, not a predicted approval. Accounts and
application Submit are human-operated. Each email Send is separately authorized.

For public code changes, follow `CONTRIBUTING.md`, including independent tests,
all-history privacy scanning and semantic review before push. Do not delegate
ordinary coding or candidate work to subagents by default.
