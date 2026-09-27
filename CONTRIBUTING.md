# Contributing safely

Contribute generic source, tests and documentation only. User templates, custom
document-generation scripts, career data, job history, account data, logs,
screenshots and final PDFs remain private. Do not copy another repository's Git
history or operational configuration. Public examples must be fictional, using
reserved example domains; do not anonymize a real career by changing only a name.

1. Run `./tools/bootstrap` and `./tools/test`. Tests create isolated synthetic
   workspaces under runtime and remove their documents on success/failure.
2. Inspect each changed source file, dependency and example. Verify that no
   private path, publication title, project narrative, employer/customer detail,
   identifier or template was carried over. Unknown files require classification.
3. Stage exact files. Run `./tools/audit-public`. It inspects working sources,
   staged blobs, all reachable commit trees and commit/tag metadata. A historical
   leak is a failure even if HEAD is clean. Symlinks, gitlinks and unclassified
   binary assets are not silently skipped.
4. Commit with `type(scope): subject`, using a suitable public contributor
   identity. A public GitHub noreply identity is allowed as public attribution;
   private contact addresses are not. Do not bypass pre-commit/commit-msg hooks.
5. After the commit, perform and attest the semantic privacy review of the
   exact publication set:

   ```sh
   ./tools/audit-public --attest-semantic-review
   ```

6. Push normally. The pre-push hook scans the actual pushed object IDs too,
   including a detached object not otherwise reachable by a branch. Its entire
   report must match the reviewed attestation. Changes to files, index, history,
   refs or private fingerprint rules invalidate the attestation. Reinspect and
   attest again; do not bypass the hook.

For a migration from a private workspace, have a local-only script collect
appropriate high-signal fingerprints **outside this public program**. Never make
Career Kit automatically traverse its parent. Store the result privately:

```json
{"literals": ["synthetic-private-canary"], "metadata_literals": []}
```

```sh
./tools/audit-public --private-rules runtime.nosync/work/private-rules.json
```

Rules are cached privately so hooks use the same fingerprint set. Match values
are never printed. A maintainer must still inspect context, encoded payloads,
file names and accidentally retained personal design choices. Automated coverage
of every publishable object is achievable; a mathematical guarantee that no
unknown prose identifies anyone is not.

If the user explicitly confirms an existing public contributor identity, local
rules may include `public_attributions`: a map from an exact commit object ID
to `headers_sha256` and the confirmation `reason`. The hash covers the original
`author` and `committer` header lines joined by a newline. Only those exact
identity headers are excluded from private-literal matching. Secret, email and
path checks still inspect them; commit messages, files, tags and other commits
remain fully checked. This is not a global name allowlist, and no real identity
or deployment-specific approval belongs in the public source.

Do not upload the private rules or audit workspace as CI artifacts. Investigate
any finding locally. If private information entered remote history, changing
HEAD alone is insufficient: stop publishing and plan the appropriate history
and hosting-provider remediation before continuing.
