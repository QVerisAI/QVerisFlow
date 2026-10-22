const REVIEWER_ID = 199175422;
const REVIEW_APP_ID = 1144995;
const REVIEWER_LOGIN = 'chatgpt-codex-connector[bot]';

function isTrustedReceipt(item) {
  return (
    item.user?.id === REVIEWER_ID &&
    item.user?.type === 'Bot' &&
    item.performed_via_github_app?.id === REVIEW_APP_ID &&
    item.body?.startsWith('<!-- codex-review-receipt:v1 -->')
  );
}

function receiptForHead(item, sha) {
  if (!isTrustedReceipt(item)) return null;
  const matches = [...item.body.matchAll(/\*\*Reviewed commit:\*\*\s*`([a-f0-9]{10,40})`/gi)];
  if (matches.length !== 1 || !sha.startsWith(matches[0][1].toLowerCase())) return null;
  const text = item.body.slice('<!-- codex-review-receipt:v1 -->'.length).trimStart();
  return {
    clean:
      /^Codex Review:\s*(?:Didn't find any (?:major )?issues|Did not find any (?:major )?issues|No (?:major )?issues found)\./i.test(
        text,
      ),
    timestamp: Date.parse(item.submitted_at || item.created_at),
    id: item.id,
  };
}

async function hasUnresolvedFindings(github, repo, number) {
  let cursor = null;
  do {
    const data = await github.graphql(
      `query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $number) {
          reviewThreads(first: 100, after: $cursor) {
            nodes { isResolved comments(first: 1) { nodes { author { login } } } }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }`,
      { ...repo, number, cursor },
    );
    const threads = data.repository?.pullRequest?.reviewThreads;
    if (!threads) throw new Error('Unable to read review threads; approval withheld.');
    if (
      threads.nodes.some((thread) => !thread.isResolved && thread.comments.nodes[0]?.author?.login === REVIEWER_LOGIN)
    )
      return true;
    cursor = threads.pageInfo.hasNextPage ? threads.pageInfo.endCursor : null;
    if (threads.pageInfo.hasNextPage && !cursor) throw new Error('Review thread pagination failed.');
  } while (cursor);
  return false;
}

function pullNumberFromContext(context) {
  let value;
  if (context.eventName === 'workflow_run') {
    const run = context.payload.workflow_run;
    if (
      run?.event !== 'pull_request_review' ||
      run.conclusion !== 'success' ||
      run.path !== '.github/workflows/review-approval-receipt.yml'
    ) {
      throw new Error('Unexpected review notification workflow.');
    }
    // GitHub can omit pull_requests for fork workflow runs. The notification's
    // constrained run title carries only a target number, never an approval verdict.
    const match = run.display_title?.match(/^Review approval for PR #([1-9][0-9]*)$/);
    if (!match) throw new Error('Review notification has no valid PR number.');
    value = match[1];
    if ((run.pull_requests || []).some((pr) => pr.number !== Number(value))) {
      throw new Error('Review notification PR metadata does not match.');
    }
  } else {
    value =
      context.payload.pull_request?.number || context.payload.issue?.number || context.payload.inputs?.pull_number;
  }
  value = Number(value);
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error('A valid pull request number is required.');
  return value;
}

async function reconcileApproval({ github, appGithub, context, appSlug }) {
  if (!/^[a-z0-9-]+$/i.test(appSlug || '')) throw new Error('Missing review App identity.');
  const number = pullNumberFromContext(context);
  if (!Number.isSafeInteger(number) || number <= 0) throw new Error('A valid pull request number is required.');
  const repo = context.repo;
  const params = { ...repo, pull_number: number };
  const appLogin = `${appSlug}[bot]`;
  const getPr = async () => (await github.rest.pulls.get(params)).data;
  const pr = await getPr();
  const sha = pr.head.sha;
  const reviews = await github.paginate(github.rest.pulls.listReviews, { ...params, per_page: 100 });
  const approvals = reviews.filter((review) => review.user?.login === appLogin && review.state === 'APPROVED');
  let reason, validationError;
  try {
    if (pr.state !== 'open' || pr.draft || pr.base.ref !== context.payload.repository.default_branch) {
      reason = 'PR is closed, draft, or targets another branch';
    } else if (pr.user.login === appLogin) {
      reason = 'Review App cannot approve its own PR';
    } else {
      const comments = await github.paginate(github.rest.issues.listComments, {
        ...repo,
        issue_number: number,
        per_page: 100,
      });
      const receipts = comments.map((item) => receiptForHead(item, sha)).filter(Boolean);
      // A later suggestions review supersedes an earlier clean comment, including
      // when the REST review object omits performed_via_github_app metadata.
      for (const review of reviews) {
        if (review.user?.id === REVIEWER_ID && review.commit_id === sha && review.state !== 'DISMISSED') {
          receipts.push({ clean: false, timestamp: Date.parse(review.submitted_at), id: review.id });
        }
      }
      const effectiveReviews = new Map();
      for (const review of reviews) {
        if (['APPROVED', 'CHANGES_REQUESTED'].includes(review.state)) {
          effectiveReviews.set(review.user?.login, review.state);
        }
      }
      const summary = comments.findLast(
        (comment) =>
          comment.user?.id === REVIEWER_ID &&
          comment.performed_via_github_app?.id === REVIEW_APP_ID &&
          comment.body?.startsWith('<!-- codex-pull-request-review-summary -->'),
      );
      const stateJson = summary?.body.match(/<!-- codex-review-state:v1 (.*?) -->/)?.[1];
      const state = stateJson ? JSON.parse(stateJson).code_review : null;
      // Automatic clean reviews can update only the structured summary, without
      // posting a separate receipt. A summary must never supersede a suggestions
      // review on this same head: unrelated summary edits can have a newer date.
      const hasSuggestionsReview = reviews.some(
        (review) => review.user?.id === REVIEWER_ID && review.commit_id === sha && review.state !== 'DISMISSED',
      );
      if (
        !hasSuggestionsReview &&
        state?.commit_sha === sha &&
        state.status === 'completed' &&
        state.has_any_findings === false &&
        state.has_unresolved_findings === false
      ) {
        receipts.push({ clean: true, timestamp: Date.parse(summary.updated_at || summary.created_at), id: summary.id });
      }
      receipts.sort((a, b) => b.timestamp - a.timestamp || Number(a.clean) - Number(b.clean) || b.id - a.id);
      if (!receipts.length || !receipts[0].clean) reason = 'No latest trusted clean review for the current head';
      else if (state?.commit_sha === sha && (state.status !== 'completed' || state.has_unresolved_findings !== false)) {
        reason = 'Current-head review is incomplete or has unresolved findings';
      } else if ([...effectiveReviews.values()].includes('CHANGES_REQUESTED')) reason = 'Changes are still requested';
      else if (await hasUnresolvedFindings(github, repo, number)) reason = 'Unresolved automated review findings';
    }
  } catch (error) {
    validationError = error;
    reason = 'Review facts could not be verified; retry required';
  }

  const dismiss = async (review, message) =>
    appGithub.rest.pulls.dismissReview({
      ...params,
      review_id: review.id,
      message,
    });
  for (const review of approvals) {
    if (reason || review.commit_id !== sha)
      await dismiss(review, reason || 'Approval belongs to an older head commit.');
  }
  if (validationError) throw new Error(reason, { cause: validationError });
  if (reason) return { number, sha, result: 'withheld', reason };
  if (approvals.some((review) => review.commit_id === sha)) return { number, sha, result: 'already-approved' };

  const live = await getPr();
  if (live.head.sha !== sha || live.state !== 'open' || live.draft) {
    return { number, sha, result: 'withheld', reason: 'PR changed during review reconciliation' };
  }
  const { data: approval } = await appGithub.rest.pulls.createReview({
    ...params,
    commit_id: sha,
    event: 'APPROVE',
    body: `Automated review completed without findings for ${sha}. No unresolved automated review findings or change requests remain.`,
  });
  let after;
  try {
    after = await getPr();
  } catch (error) {
    await dismiss(approval, 'Unable to verify PR state after approval submission.');
    throw error;
  }
  if (after.head.sha !== sha || after.state !== 'open' || after.draft) {
    await dismiss(approval, 'PR changed while approval was being submitted.');
    return { number, sha, result: 'withheld', reason: 'PR changed while approval was being submitted' };
  }
  return { number, sha, result: 'approved', url: approval.html_url };
}

module.exports = { isTrustedReceipt, receiptForHead, pullNumberFromContext, reconcileApproval };
