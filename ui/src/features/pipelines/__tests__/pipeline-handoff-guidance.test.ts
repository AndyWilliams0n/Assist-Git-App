import { describe, it, expect } from 'vitest'

import { resolvePipelineHandoffGuidance } from '@/features/pipelines/components/handoffs/pipeline-handoff-guidance'
import type { PipelineGitHandoff } from '@/features/pipelines/types'

const makeHandoff = (overrides: Partial<PipelineGitHandoff> = {}): PipelineGitHandoff => ({
  id: 'handoff-1',
  task_id: 'task-1',
  run_id: 'run-1',
  jira_key: 'TEST-1',
  strategy: '',
  stash_ref: '',
  commit_sha: '',
  source_branch: '',
  target_branch: '',
  file_summary_json: '',
  reason: '',
  resolved: 0,
  resolved_at: '',
  resolved_by: '',
  resolution_note: '',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  ...overrides,
})

describe('resolvePipelineHandoffGuidance', () => {
  describe('checkout-overwrite rule', () => {
    it('matches "would be overwritten by checkout" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'error: Your local changes to the following files would be overwritten by checkout' })
      )

      expect(guidance.key).toBe('checkout-overwrite')
      expect(guidance.title).toBe('Local Changes Block Branch Switch')
    })

    it('matches "please commit your changes or stash them" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'Please commit your changes or stash them before you switch branches.' })
      )

      expect(guidance.key).toBe('checkout-overwrite')
    })

    it('includes target branch hint in steps when target branch is set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({
          reason: 'would be overwritten by checkout',
          target_branch: 'feature/my-branch',
        })
      )

      expect(guidance.steps.some((s) => s.includes('feature/my-branch'))).toBe(true)
    })

    it('includes generic branch hint in steps when target branch is empty', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'would be overwritten by checkout', target_branch: '' })
      )

      expect(guidance.steps.some((s) => s.includes('Re-run the branch-switch command'))).toBe(true)
    })
  })

  describe('merge-conflict rule', () => {
    it('matches "merge conflict" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'CONFLICT: merge conflict in src/index.ts' })
      )

      expect(guidance.key).toBe('merge-conflict')
      expect(guidance.title).toBe('Merge Conflict Requires Manual Resolution')
    })

    it('matches "automatic merge failed" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'Automatic merge failed; fix conflicts and then commit the result.' })
      )

      expect(guidance.key).toBe('merge-conflict')
    })

    it('matches "fix conflicts and then commit" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'fix conflicts and then commit' })
      )

      expect(guidance.key).toBe('merge-conflict')
    })
  })

  describe('rebase-conflict rule', () => {
    it('matches "rebase in progress" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'error: rebase in progress; first finish the current rebase.' })
      )

      expect(guidance.key).toBe('rebase-conflict')
      expect(guidance.title).toBe('Rebase Conflict Requires Continuation')
    })

    it('matches "run git rebase --continue" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'After resolving conflicts, run git rebase --continue' })
      )

      expect(guidance.key).toBe('rebase-conflict')
    })
  })

  describe('branch-missing rule', () => {
    it('matches "pathspec did not match any file" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: "error: pathspec 'feature/xyz' did not match any file(s) known to git" })
      )

      expect(guidance.key).toBe('branch-missing')
      expect(guidance.title).toBe('Target Branch Not Found')
    })

    it('matches "couldn\'t find remote ref" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: "fatal: couldn't find remote ref feature/missing" })
      )

      expect(guidance.key).toBe('branch-missing')
    })

    it('includes branch-specific create command when target_branch is set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({
          reason: "pathspec 'x' did not match any file",
          target_branch: 'feature/new-feature',
        })
      )

      expect(guidance.steps.some((s) => s.includes('feature/new-feature'))).toBe(true)
    })
  })

  describe('branch-exists rule', () => {
    it('matches "a branch named already exists" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: "fatal: A branch named 'feature/existing' already exists." })
      )

      expect(guidance.key).toBe('branch-exists')
      expect(guidance.title).toBe('Branch Already Exists')
    })

    it('includes checkout command with source branch when source_branch is set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({
          reason: 'a branch named feature/existing already exists',
          source_branch: 'feature/existing',
        })
      )

      expect(guidance.steps[0]).toContain('feature/existing')
    })
  })

  describe('auth-permission rule', () => {
    it('matches "authentication failed" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'fatal: Authentication failed for https://github.com/org/repo' })
      )

      expect(guidance.key).toBe('auth-permission')
      expect(guidance.title).toBe('Repository Authentication Or Permission Failed')
    })

    it('matches "permission denied" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'ERROR: Permission denied (publickey).' })
      )

      expect(guidance.key).toBe('auth-permission')
    })

    it('matches "publickey" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'git@github.com: Permission denied (publickey).' })
      )

      expect(guidance.key).toBe('auth-permission')
    })
  })

  describe('network-connectivity rule', () => {
    it('matches "unable to access" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: "fatal: unable to access 'https://github.com/org/repo': Could not resolve host" })
      )

      expect(guidance.key).toBe('network-connectivity')
      expect(guidance.title).toBe('Network Connectivity Interrupted Git Operation')
    })

    it('matches "operation timed out" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'error: RPC failed; curl 28 Operation timed out after 120000 ms' })
      )

      expect(guidance.key).toBe('network-connectivity')
    })
  })

  describe('git-lock rule', () => {
    it('matches "index.lock" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'fatal: Unable to create .git/index.lock: File exists.' })
      )

      expect(guidance.key).toBe('git-lock')
      expect(guidance.title).toBe('Git Lock File Prevented Operation')
    })

    it('matches "another git process seems to be running" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'Another git process seems to be running in this repository' })
      )

      expect(guidance.key).toBe('git-lock')
    })
  })

  describe('non-fast-forward rule', () => {
    it('matches "non-fast-forward" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'error: failed to push some refs; rejection reason: non-fast-forward' })
      )

      expect(guidance.key).toBe('non-fast-forward')
      expect(guidance.title).toBe('Push Was Rejected (Non Fast-Forward)')
    })

    it('matches "updates were rejected" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: '! [rejected]  main -> main (updates were rejected)' })
      )

      expect(guidance.key).toBe('non-fast-forward')
    })
  })

  describe('detached-head rule', () => {
    it('matches "detached head" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'HEAD is in detached HEAD state at abc1234' })
      )

      expect(guidance.key).toBe('detached-head')
      expect(guidance.title).toBe('Detached HEAD Requires Branch Checkout')
    })

    it('matches "not currently on a branch" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'error: HEAD is not currently on a branch' })
      )

      expect(guidance.key).toBe('detached-head')
    })

    it('includes source branch in checkout command when source_branch is set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({
          reason: 'detached head',
          source_branch: 'main',
        })
      )

      expect(guidance.steps[0]).toContain('main')
    })
  })

  describe('submodule rule', () => {
    it('matches "submodule" reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'error: no submodule mapping found in .gitmodules for path libs/shared' })
      )

      expect(guidance.key).toBe('submodule')
      expect(guidance.title).toBe('Submodule State Needs Manual Sync')
    })
  })

  describe('subtask-commit-push rule', () => {
    it('matches "subtask-primary:commit" strategy', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ strategy: 'subtask-primary:commit', reason: '' })
      )

      expect(guidance.key).toBe('subtask-commit-push')
      expect(guidance.title).toBe('Subtask Commit and Push Review')
    })

    it('matches "subtask-secondary:push" strategy', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ strategy: 'subtask-secondary:push', reason: '' })
      )

      expect(guidance.key).toBe('subtask-commit-push')
    })
  })

  describe('manual-review fallback rule', () => {
    it('returns fallback guidance for unknown reason', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'some completely unknown git error XYZ-999' })
      )

      expect(guidance.key).toBe('manual-review')
      expect(guidance.title).toBe('Manual Git Review Required')
    })
  })

  describe('references', () => {
    it('includes target_branch reference when set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'merge conflict', target_branch: 'main' })
      )

      const ref = guidance.references.find((r) => r.label === 'Target branch')
      expect(ref?.value).toBe('main')
    })

    it('includes source_branch reference when set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'merge conflict', source_branch: 'feature/abc' })
      )

      const ref = guidance.references.find((r) => r.label === 'Source branch')
      expect(ref?.value).toBe('feature/abc')
    })

    it('includes stash_ref reference when set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'merge conflict', stash_ref: 'stash@{0}' })
      )

      const ref = guidance.references.find((r) => r.label === 'Stash ref')
      expect(ref?.value).toBe('stash@{0}')
    })

    it('truncates commit_sha to 12 characters', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'merge conflict', commit_sha: 'abc1234567890full' })
      )

      const ref = guidance.references.find((r) => r.label === 'Commit')
      expect(ref?.value).toBe('abc123456789')
    })

    it('includes strategy reference when set', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'merge conflict', strategy: 'merge' })
      )

      const ref = guidance.references.find((r) => r.label === 'Strategy')
      expect(ref?.value).toBe('merge')
    })

    it('returns empty references when all fields are empty', () => {
      const guidance = resolvePipelineHandoffGuidance(makeHandoff({ reason: 'merge conflict' }))

      expect(guidance.references).toHaveLength(0)
    })
  })

  describe('case insensitivity', () => {
    it('matches reason patterns case-insensitively', () => {
      const guidance = resolvePipelineHandoffGuidance(
        makeHandoff({ reason: 'MERGE CONFLICT detected in src/app.ts' })
      )

      expect(guidance.key).toBe('merge-conflict')
    })
  })
})
