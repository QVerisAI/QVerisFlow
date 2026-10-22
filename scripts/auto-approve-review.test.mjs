import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import policy from './auto-approve-review.cjs';

const sha = '697f879ff94b3dc5fbf01fa1d28946e94d2b36e5';
const oldSha = '23d6b4b919cef467da5877b63b7fd4d166deffe6';
const reviewer = { id: 199175422, login: 'chatgpt-codex-connector[bot]', type: 'Bot' };
const clean = (overrides = {}) => ({
  id: 10,
  user: reviewer,
  performed_via_github_app: { id: 1144995 },
  created_at: '2026-10-22T06:27:27Z',
  body: `<!-- codex-review-receipt:v1 -->\n\nCodex Review: Didn't find any major issues. Swish!\n\n**Reviewed commit:** \`${sha.slice(0, 10)}\``,
  ...overrides,
});

function fixture({
  comments = [clean()],
  reviews = [],
  threads = [],
  pages,
  pr: changes = {},
  liveHeads = [],
  threadError,
  failRead,
} = {}) {
  const writes = [];
  const pr = {
    number: 440,
    state: 'open',
    draft: false,
    base: { ref: 'main' },
    head: { sha },
    user: { login: 'linfangw' },
    ...changes,
  };
  let reads = 0,
    threadPage = 0;
  const listReviews = () => {},
    listComments = () => {};
  const github = {
    rest: {
      pulls: {
        listReviews,
        get: async () => {
          if (reads === failRead) throw new Error('API unavailable');
          return { data: { ...pr, head: { sha: liveHeads[reads++] || pr.head.sha } } };
        },
      },
      issues: { listComments },
    },
    paginate: async (method) => (method === listReviews ? reviews : comments),
    graphql: async () => {
      if (threadError) throw new Error('GraphQL unavailable');
      return {
        repository: {
          pullRequest: {
            reviewThreads: pages?.[threadPage++] || {
              nodes: threads,
              pageInfo: { hasNextPage: false },
            },
          },
        },
      };
    },
  };
  const appGithub = {
    rest: {
      pulls: {
        createReview: async (request) => {
          writes.push({ type: 'approve', ...request });
          return {
            data: {
              id: 900,
              html_url: 'https://github.com/QVerisAI/qveris-agent-toolkit/pull/440#pullrequestreview-900',
            },
          };
        },
        dismissReview: async (request) => {
          writes.push({ type: 'dismiss', ...request });
        },
      },
    },
  };
  const context = {
    repo: { owner: 'QVerisAI', repo: 'qveris-agent-toolkit' },
    payload: { repository: { default_branch: 'main' }, inputs: { pull_number: '440' } },
  };
  return {
    writes,
    context,
    run: () => policy.reconcileApproval({ github, appGithub, context, appSlug: 'qveris-review-bot' }),
  };
}

test('approves a trusted clean receipt for the current head using a separate App', async () => {
  const f = fixture();
  assert.equal((await f.run()).result, 'approved');
  assert.equal(f.writes.length, 1);
  assert.equal(f.writes[0].event, 'APPROVE');
  assert.equal(f.writes[0].commit_id, sha);
});

test('rejects spoofed identities, wrong Apps, quoted clean text, and ambiguous or stale hashes', async () => {
  for (const comment of [
    clean({ user: { ...reviewer, id: 999 } }),
    clean({ user: { ...reviewer, type: 'User' } }),
    clean({ performed_via_github_app: { id: 999 } }),
    clean({ body: clean().body.replace('Codex Review:', '> Codex Review:') }),
    clean({ body: clean().body.replace(sha.slice(0, 10), oldSha.slice(0, 10)) }),
    clean({ body: clean().body + `\n**Reviewed commit:** \`${sha}\`` }),
  ]) {
    const f = fixture({ comments: [comment] });
    assert.equal((await f.run()).result, 'withheld');
    assert.deepEqual(f.writes, []);
  }
});

test('a later suggestions review supersedes an earlier clean receipt', async () => {
  const f = fixture({
    reviews: [{ id: 20, user: reviewer, state: 'COMMENTED', commit_id: sha, submitted_at: '2026-10-22T06:28:00Z' }],
  });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(f.writes, []);
});

test('a fresh clean receipt can supersede an older suggestions review', async () => {
  const f = fixture({
    reviews: [{ id: 20, user: reviewer, state: 'COMMENTED', commit_id: sha, submitted_at: '2026-10-22T06:26:00Z' }],
  });
  assert.equal((await f.run()).result, 'approved');
});

test('an incomplete current-head summary prevents approval', async () => {
  const state = { code_review: { commit_sha: sha, status: 'running', has_unresolved_findings: null } };
  const summary = clean({
    body: `<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 ${JSON.stringify(state)} -->`,
  });
  const f = fixture({ comments: [summary, clean()] });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(f.writes, []);
});

test('a completed trusted clean summary supports automatic reviews without a separate receipt', async () => {
  const state = {
    code_review: { commit_sha: sha, status: 'completed', has_any_findings: false, has_unresolved_findings: false },
  };
  const summary = clean({
    body: `<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 ${JSON.stringify(state)} -->`,
  });
  const f = fixture({ comments: [summary] });
  assert.equal((await f.run()).result, 'approved');
});

test('an unrelated summary edit cannot override a suggestions review on the same head', async () => {
  const state = {
    code_review: { commit_sha: sha, status: 'completed', has_any_findings: false, has_unresolved_findings: false },
  };
  const summary = clean({
    updated_at: '2026-10-22T06:30:00Z',
    body: `<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 ${JSON.stringify(state)} -->`,
  });
  const f = fixture({
    comments: [summary],
    reviews: [{ id: 20, user: reviewer, state: 'COMMENTED', commit_id: sha, submitted_at: '2026-10-22T06:28:00Z' }],
  });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(f.writes, []);
});

test('unresolved findings on later thread pages prevent approval', async () => {
  const f = fixture({
    pages: [
      { nodes: [], pageInfo: { hasNextPage: true, endCursor: 'next' } },
      {
        nodes: [{ isResolved: false, comments: { nodes: [{ author: { __typename: 'Bot', databaseId: reviewer.id, login: 'chatgpt-codex-connector' } }] } }],
        pageInfo: { hasNextPage: false },
      },
    ],
  });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(f.writes, []);
});

test('human change requests are honored; a later comment does not clear them', async () => {
  const user = { login: 'maintainer' };
  const f = fixture({
    reviews: [
      { id: 30, user, state: 'CHANGES_REQUESTED' },
      { id: 31, user, state: 'COMMENTED' },
    ],
  });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(f.writes, []);
});

test('a later human approval clears that reviewer’s change request', async () => {
  const user = { login: 'maintainer' };
  const f = fixture({
    reviews: [
      { id: 30, user, state: 'CHANGES_REQUESTED' },
      { id: 31, user, state: 'APPROVED' },
    ],
  });
  assert.equal((await f.run()).result, 'approved');
});

const appApproval = (commit_id = sha) => ({
  id: 40,
  user: { login: 'qveris-review-bot[bot]' },
  state: 'APPROVED',
  commit_id,
});

test('retrying the same head does not create a duplicate approval', async () => {
  const f = fixture({ reviews: [appApproval()] });
  assert.equal((await f.run()).result, 'already-approved');
  assert.deepEqual(f.writes, []);
});

test('withdraws only this App’s stale approval when clean evidence disappears', async () => {
  const f = fixture({
    comments: [],
    reviews: [appApproval(oldSha), { ...appApproval(), id: 50, user: { login: 'maintainer' } }],
  });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(
    f.writes.map((x) => [x.type, x.review_id]),
    [['dismiss', 40]],
  );
});

test('replaces its older-head approval with a current-head approval', async () => {
  const f = fixture({ reviews: [appApproval(oldSha)] });
  assert.equal((await f.run()).result, 'approved');
  assert.deepEqual(
    f.writes.map((x) => x.type),
    ['dismiss', 'approve'],
  );
});

test('retargeting an approved PR away from the default branch withdraws its approval', async () => {
  const f = fixture({ pr: { base: { ref: 'release' } }, reviews: [appApproval()] });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(
    f.writes.map((x) => x.type),
    ['dismiss'],
  );
});

test('withholds approval if head moves before submission', async () => {
  const f = fixture({ liveHeads: [sha, oldSha] });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(f.writes, []);
});

test('withdraws the approval if head moves during submission', async () => {
  const f = fixture({ liveHeads: [sha, sha, oldSha] });
  assert.equal((await f.run()).result, 'withheld');
  assert.deepEqual(
    f.writes.map((x) => x.type),
    ['approve', 'dismiss'],
  );
});

test('withdraws its existing approval when review verification fails', async () => {
  const f = fixture({ reviews: [appApproval()], threadError: true });
  await assert.rejects(f.run, /could not be verified/);
  assert.deepEqual(
    f.writes.map((x) => x.type),
    ['dismiss'],
  );
});

test('withdraws a newly submitted approval if final verification is unavailable', async () => {
  const f = fixture({ failRead: 2 });
  await assert.rejects(f.run, /API unavailable/);
  assert.deepEqual(
    f.writes.map((x) => x.type),
    ['approve', 'dismiss'],
  );
});

test('does not approve closed, draft, other-base, or App-authored PRs', async () => {
  for (const pr of [
    { state: 'closed' },
    { draft: true },
    { base: { ref: 'release' } },
    { user: { login: 'qveris-review-bot[bot]' } },
  ]) {
    const f = fixture({ pr });
    assert.equal((await f.run()).result, 'withheld');
    assert.deepEqual(f.writes, []);
  }
});

const notification = (overrides = {}) => ({
  event: 'pull_request_review',
  conclusion: 'success',
  path: '.github/workflows/review-approval-receipt.yml',
  display_title: 'Review approval for PR #440',
  pull_requests: [],
  ...overrides,
});

test('a secret-free fork notification reconciles using current facts on the trusted workflow', async () => {
  const f = fixture();
  f.context.eventName = 'workflow_run';
  delete f.context.payload.inputs;
  f.context.payload.workflow_run = notification();
  assert.equal((await f.run()).result, 'approved');
  assert.equal(f.writes[0].pull_number, 440);
});

test('notification PR metadata must agree with its constrained run title', () => {
  assert.equal(
    policy.pullNumberFromContext({
      eventName: 'workflow_run',
      payload: {
        workflow_run: notification({ pull_requests: [{ number: 440 }] }),
      },
    }),
    440,
  );
  assert.throws(
    () =>
      policy.pullNumberFromContext({
        eventName: 'workflow_run',
        payload: {
          workflow_run: notification({ pull_requests: [{ number: 437 }] }),
        },
      }),
    /metadata does not match/,
  );
});

test('wrong workflow sources and unconstrained notification targets are rejected', () => {
  for (const overrides of [
    { event: 'push' },
    { conclusion: 'failure' },
    { path: '.github/workflows/untrusted.yml' },
    { display_title: 'PR #440; run commands' },
  ]) {
    assert.throws(() =>
      policy.pullNumberFromContext({
        eventName: 'workflow_run',
        payload: {
          workflow_run: notification(overrides),
        },
      }),
    );
  }
});

test('all human review transitions notify a secret-capable receiver without checking out fork code', () => {
  const receipt = readFileSync(new URL('../.github/workflows/review-approval-receipt.yml', import.meta.url), 'utf8');
  const receiver = readFileSync(new URL('../.github/workflows/review-auto-approve.yml', import.meta.url), 'utf8');
  assert.match(receipt, /pull_request_review:\s*\n\s*types: \[submitted, edited, dismissed\]/);
  assert.match(receipt, /permissions: \{\}/);
  assert.doesNotMatch(receipt, /\$\{\{\s*secrets\.|checkout@|create-github-app-token|\bif:/);
  assert.match(receiver, /workflow_run:\s*\n\s*workflows: \[Review approval receipt\]/);
  assert.doesNotMatch(receiver, /^  pull_request_review:/m);
  assert.match(receiver, /ref: \$\{\{ github.event.repository.default_branch \}\}/);
  assert.match(receiver, /pull_request_target:\s*\n\s*types: \[[^\]]*\bedited\b/);
});


test('sweep contexts retain prototype-backed repository identity and share event concurrency', () => {
  const context = Object.assign(Object.create({
    get repo() { return {owner: 'QVerisAI', repo: 'qveris-agent-toolkit'}; },
  }), {payload: fixture().context.payload});
  const target = policy.contextForPullRequest(context, 7);
  assert.deepEqual(target.repo, {owner: 'QVerisAI', repo: 'qveris-agent-toolkit'});
  assert.equal(target.payload.inputs.pull_number, '7');
  assert.equal(target.payload.repository.default_branch, 'main');
  const workflow = readFileSync(new URL('../.github/workflows/review-auto-approve.yml', import.meta.url), 'utf8');
  const groups = workflow.split('\n').filter(line => line.includes('review-approval-${{ github.repository }}'));
  assert.equal(groups.length, 2);
  for (const group of groups) assert.ok(group.includes("format('Review approval for PR #{0}',"));
  assert.match(groups[0], /workflow_run.display_title/);
  assert.match(groups[1], /matrix.pull_number/);
  assert.match(workflow, /fail-fast: false/);
  assert.match(workflow, /contextForPullRequest\(context, process.env.PULL_NUMBER\)/);
  assert.match(workflow, /schedule:\s*\n\s*- cron:/);
});

// Captured GraphQL identity shape differs from the REST review identity.
test('unresolved GraphQL bot findings withdraw approval by stable numeric identity', async () => {
  for (const login of ['chatgpt-codex-connector', reviewer.login]) {
    const f = fixture({ reviews: [appApproval()], threads: [{isResolved: false,
      comments: {nodes: [{author: {__typename: 'Bot', databaseId: reviewer.id, login}}]},
    }] });
    assert.equal((await f.run()).result, 'withheld');
    assert.deepEqual(f.writes.map(x => x.type), ['dismiss']);
  }
});

test('shared-head workflow metadata can contain additional related PRs', () => {
  for (const numbers of [[440, 437], [437, 440]]) {
    const context = {eventName: 'workflow_run', payload: {workflow_run:
      notification({pull_requests: numbers.map(number => ({number}))})}};
    assert.equal(policy.pullNumberFromContext(context), 440);
  }
  assert.throws(() => policy.pullNumberFromContext({eventName: 'workflow_run',
    payload: {workflow_run: notification({pull_requests: [{number: 437}, {number: 441}]})}}),
    /metadata does not match/);
});
