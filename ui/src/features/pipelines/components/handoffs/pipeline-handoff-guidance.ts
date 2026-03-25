import type { PipelineGitHandoff } from '@/features/pipelines/types'

type GuidanceContext = {
  reason: string
  normalizedReason: string
  strategy: string
  sourceBranch: string
  targetBranch: string
  stashRef: string
  commitSha: string
}

type GuidanceRule = {
  key: string
  title: string
  summary: string
  matches: (context: GuidanceContext) => boolean
  steps: (context: GuidanceContext) => string[]
}

export type PipelineHandoffGuidanceReference = {
  label: string
  value: string
}

export type PipelineHandoffGuidance = {
  key: string
  title: string
  summary: string
  steps: string[]
  references: PipelineHandoffGuidanceReference[]
}

const normalizeText = (value: unknown) => String(value || '').trim()

const normalizeReason = (value: unknown) => normalizeText(value).toLowerCase()

const matchAny = (value: string, patterns: RegExp[]) => patterns.some((pattern) => pattern.test(value))

const branchHint = (context: GuidanceContext) => {
  if (!context.targetBranch) {
    return 'Re-run the branch-switch command after your workspace is clean.'
  }

  return `Switch to the target branch (${context.targetBranch}) again after cleanup.`
}

const guidanceRules: GuidanceRule[] = [
  {
    key: 'checkout-overwrite',
    title: 'Local Changes Block Branch Switch',
    summary: 'Git refused checkout because local files would be overwritten.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /would be overwritten by checkout/,
        /please commit your changes or stash them/,
        /local changes to the following files/,
        /overwritten by merge/,
      ]),
    steps: (context) => [
      'Open the task workspace and run `git status` to inspect local modifications.',
      'Commit or stash the local changes you want to keep.',
      branchHint(context),
      'Click `Re-enable Task` after checkout succeeds.',
    ],
  },
  {
    key: 'merge-conflict',
    title: 'Merge Conflict Requires Manual Resolution',
    summary: 'Git detected file-level conflicts that must be resolved manually.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /merge conflict/,
        /automatic merge failed/,
        /conflict \(content\)/,
        /fix conflicts and then commit/,
      ]),
    steps: () => [
      'Resolve each conflicted file in your editor and remove conflict markers.',
      'Stage resolved files with `git add <file>`.',
      'Complete the merge (`git commit`) and verify `git status` is clean.',
      'Click `Re-enable Task` once the merge is complete.',
    ],
  },
  {
    key: 'rebase-conflict',
    title: 'Rebase Conflict Requires Continuation',
    summary: 'Rebase paused because one or more commits could not be applied cleanly.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /rebase in progress/,
        /could not apply/,
        /resolve all conflicts manually/,
        /run git rebase --continue/,
      ]),
    steps: () => [
      'Resolve conflicts in the listed files.',
      'Stage resolved files with `git add <file>`.',
      'Run `git rebase --continue` until rebase completes.',
      'Click `Re-enable Task` after `git status` returns clean.',
    ],
  },
  {
    key: 'branch-missing',
    title: 'Target Branch Not Found',
    summary: 'The branch requested by the pipeline is missing locally or remotely.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /pathspec .* did not match any file/,
        /couldn't find remote ref/,
        /unknown revision or path/,
        /not a valid object name/,
      ]),
    steps: (context) => [
      'Fetch latest refs with `git fetch --all --prune`.',
      context.targetBranch
        ? `Create or track the branch: \`git checkout -b ${context.targetBranch} origin/${context.targetBranch}\` (adjust remote if needed).`
        : 'Create or track the expected branch before retrying.',
      'Confirm branch availability with `git branch -a`.',
      'Click `Re-enable Task` after the branch exists.',
    ],
  },
  {
    key: 'branch-exists',
    title: 'Branch Already Exists',
    summary: 'The pipeline tried to create a branch name that is already present.',
    matches: (context) => matchAny(context.normalizedReason, [/a branch named .* already exists/, /branch .* already exists/]),
    steps: (context) => [
      context.sourceBranch
        ? `Check out the existing branch with \`git checkout ${context.sourceBranch}\`.`
        : 'Check out the existing branch or rename it if it is stale.',
      'Ensure this branch is the correct workspace for the task.',
      'Delete or rename stale branches if needed (`git branch -m` / `git branch -D`).',
      'Click `Re-enable Task` when branch state is correct.',
    ],
  },
  {
    key: 'auth-permission',
    title: 'Repository Authentication Or Permission Failed',
    summary: 'Git could not authenticate to the remote repository.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /authentication failed/,
        /permission denied/,
        /repository not found/,
        /could not read username/,
        /fatal: .*403/,
        /fatal: .*401/,
        /publickey/,
        /access denied/,
      ]),
    steps: () => [
      'Verify remote URL and account permissions for this repository.',
      'Refresh credentials (SSH key, token, or credential helper).',
      'Test access with `git ls-remote <remote>`.',
      'Click `Re-enable Task` after authentication succeeds.',
    ],
  },
  {
    key: 'network-connectivity',
    title: 'Network Connectivity Interrupted Git Operation',
    summary: 'Git could not reach the remote due to DNS, timeout, or connection issues.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /unable to access/,
        /could not resolve host/,
        /failed to connect/,
        /operation timed out/,
        /network is unreachable/,
        /connection reset/,
        /tls handshake timeout/,
      ]),
    steps: () => [
      'Check VPN, proxy, and internet connectivity.',
      'Retry with `git fetch` or the failed command in the same workspace.',
      'If intermittent, retry after a short delay.',
      'Click `Re-enable Task` once remote access works.',
    ],
  },
  {
    key: 'git-lock',
    title: 'Git Lock File Prevented Operation',
    summary: 'Another Git process or stale lock file blocked repository writes.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /index\.lock/,
        /another git process seems to be running/,
        /cannot lock ref/,
        /could not lock/,
      ]),
    steps: () => [
      'Ensure no other Git process is running in the repository.',
      'If a stale lock remains, remove the lock file carefully (`.git/index.lock` or listed lock).',
      'Retry the failed Git command.',
      'Click `Re-enable Task` when Git operations succeed.',
    ],
  },
  {
    key: 'non-fast-forward',
    title: 'Push Was Rejected (Non Fast-Forward)',
    summary: 'Remote branch contains commits not present locally.',
    matches: (context) =>
      matchAny(context.normalizedReason, [
        /non-fast-forward/,
        /failed to push some refs/,
        /updates were rejected/,
      ]),
    steps: () => [
      'Pull or rebase from remote to include latest commits.',
      'Resolve any conflicts and complete the rebase or merge.',
      'Push again and confirm no rejection remains.',
      'Click `Re-enable Task` after push succeeds.',
    ],
  },
  {
    key: 'detached-head',
    title: 'Detached HEAD Requires Branch Checkout',
    summary: 'Repository is not currently on a branch, so branch-based operations failed.',
    matches: (context) => matchAny(context.normalizedReason, [/detached head/, /not currently on a branch/]),
    steps: (context) => [
      context.sourceBranch
        ? `Return to a branch with \`git checkout ${context.sourceBranch}\` (or the intended working branch).`
        : 'Check out the intended working branch.',
      'If needed, create a new branch before continuing.',
      'Confirm `git status` reports a branch name (not detached HEAD).',
      'Click `Re-enable Task` after branch context is restored.',
    ],
  },
  {
    key: 'submodule',
    title: 'Submodule State Needs Manual Sync',
    summary: 'A submodule reference prevented the Git command from completing.',
    matches: (context) => matchAny(context.normalizedReason, [/submodule/, /no submodule mapping found/]),
    steps: () => [
      'Sync submodule configuration with `git submodule sync --recursive`.',
      'Update submodules using `git submodule update --init --recursive`.',
      'Commit submodule pointer changes if required.',
      'Click `Re-enable Task` after submodule state is valid.',
    ],
  },
  {
    key: 'subtask-commit-push',
    title: 'Subtask Commit and Push Review',
    summary: 'A commit and push operation across subtasks requires manual verification.',
    matches: (context) =>
      matchAny(context.strategy, [
        /subtask-primary:commit/,
        /subtask-secondary:push/,
      ]),
    steps: () => [
      'Run `git log --oneline -5` in each subtask workspace to confirm expected commits are present.',
      'Verify the push completed successfully with `git status` and check the remote.',
      'If the push is missing, run the push command manually from the correct branch.',
      'Click `Re-enable Task` once both commit and push are verified, or `Keep Blocked` to defer.',
    ],
  },
]

const fallbackRule: GuidanceRule = {
  key: 'manual-review',
  title: 'Manual Git Review Required',
  summary: 'The handoff did not match a known pattern, so manual diagnosis is needed.',
  matches: () => true,
  steps: () => [
    'Open the task workspace and run `git status`.',
    'Review the error message and run the failed Git command manually.',
    'Fix the repository state so the command completes without errors.',
    'Click `Re-enable Task` once the repository is healthy, or choose `Keep Blocked` to defer.',
  ],
}

const buildReferences = (context: GuidanceContext): PipelineHandoffGuidanceReference[] => {
  const references: PipelineHandoffGuidanceReference[] = []

  if (context.targetBranch) {
    references.push({ label: 'Target branch', value: context.targetBranch })
  }

  if (context.sourceBranch) {
    references.push({ label: 'Source branch', value: context.sourceBranch })
  }

  if (context.stashRef) {
    references.push({ label: 'Stash ref', value: context.stashRef })
  }

  if (context.commitSha) {
    references.push({ label: 'Commit', value: context.commitSha.slice(0, 12) })
  }

  if (context.strategy) {
    references.push({ label: 'Strategy', value: context.strategy })
  }

  return references
}

/**
 * Resolves contextual Git handoff guidance for known and unknown failure scenarios.
 */
export const resolvePipelineHandoffGuidance = (handoff: PipelineGitHandoff): PipelineHandoffGuidance => {
  const context: GuidanceContext = {
    reason: normalizeText(handoff.reason),
    normalizedReason: normalizeReason(handoff.reason),
    strategy: normalizeText(handoff.strategy),
    sourceBranch: normalizeText(handoff.source_branch),
    targetBranch: normalizeText(handoff.target_branch),
    stashRef: normalizeText(handoff.stash_ref),
    commitSha: normalizeText(handoff.commit_sha),
  }

  const matchedRule = guidanceRules.find((rule) => rule.matches(context)) || fallbackRule

  return {
    key: matchedRule.key,
    title: matchedRule.title,
    summary: matchedRule.summary,
    steps: matchedRule.steps(context),
    references: buildReferences(context),
  }
}
