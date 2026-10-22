# Review approval administration

Automatic code review and GitHub approval are separate integrations. The review
service produces receipts; this repository's `Review auto approval` workflow
submits an `APPROVE` through an independent GitHub App after validating a clean
receipt for the current PR head.

## Configuration

- Install the organization's dedicated review App on `QVerisAI/QVerisFlow`.
- Set Actions variable `REVIEW_APP_ID` to its App ID.
- Set Actions secret `REVIEW_APP_PRIVATE_KEY` from the App's existing secure key
  storage. Never put private keys in PRs, comments, logs, or ordinary variables.
- The App needs Pull requests write permission to submit reviews. For this
  repository\'s required-review rule to count its approvals, the installation also
  needs Contents write permission; PR-only approvals are recorded but leave
  `REVIEW_REQUIRED`. Approve this permission separately and keep installation
  access restricted to explicitly authorized repositories.
- The workflow still requests a token scoped to this repository with only Pull
  requests write permission, then revokes it at the end of the job. It uses the
  default token only for read operations and does not request content writes.
- A private App owned by another organization cannot be installed here. Use an
  organization-owned review App, or obtain explicit authorization to make the
  existing App installable outside its owner before installing it here.

Missing configuration fails explicitly. There is no personal-token fallback,
default-token approval permission expansion, or branch-protection bypass.

## Rules and recovery

Only receipts from the known review service's numeric bot and App identities are
trusted. The receipt must name the current head, report a clean review, and be
newer than suggestions reviews on that head. Incomplete review state, unresolved
automated findings, and active change requests prevent approval. Only approvals
owned by the configured review App are withdrawn when the facts change.

Automatic reviews that only update the trusted structured summary also qualify
when that summary reports completion with no findings on the exact current head.
This fallback never overrides a suggestions review on the same head; a new clean
receipt is required to supersede such a review.

The privileged workflow checks out logic from the default branch and never runs
code from the PR branch. Changes to the approval policy therefore take effect
after merge, following an independent review.

Review submissions, edits, and dismissals (including human approvals that clear
earlier change requests) first run a secret-free notification workflow. Its
completion invokes the default-branch approval workflow, which can access App
credentials even for fork PRs. The notification carries only a numeric PR target;
the receiver re-reads all approval evidence instead of trusting a verdict, code,
or artifact from the notification. Edited clean comments and PR head changes are
also reconciled directly from trusted events.

After configuration changes or missed notifications, reconcile an existing PR:

Set `PR_NUMBER` to the existing PR number, then run:

```bash
gh workflow run review-auto-approve.yml --repo QVerisAI/QVerisFlow --ref main -f pull_number="$PR_NUMBER"
```

Inspect the workflow job summary and the PR's review list. Success means an
`APPROVED` review by the configured App on the current head, rather than merely a
clean review comment. Also confirm that the repository reports an approved review
decision; a recorded review alone can be insufficient under required-review
rules. Repeating reconciliation on the same head is idempotent.

Run policy regression tests without network calls or credentials:

```bash
node --test scripts/auto-approve-review.test.mjs
```

## Thread state changes and full reconciliation

GitHub Actions does not directly support the review-thread resolution webhook.
An hourly default-branch sweep re-reads all open PRs, including thread state, and
withdraws or restores this App's approvals using the same policy. Scheduled runs
can be delayed by GitHub. For immediate verification after resolving or reopening
a thread, dispatch the workflow without a PR number:

```bash
gh workflow run review-auto-approve.yml --repo QVerisAI/QVerisFlow --ref main
```

Each sweep PR shares its concurrency group with normal event reconciliation.
The paginated sweep uses independent matrix jobs with fail-fast disabled, so one
PR verification failure does not skip the remaining PRs.
Normal review receipts still reconcile immediately through their event handlers.
