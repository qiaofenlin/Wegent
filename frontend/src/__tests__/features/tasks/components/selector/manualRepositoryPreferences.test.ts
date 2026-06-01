// SPDX-FileCopyrightText: 2026 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import {
  buildManualRepositoryPreference,
  manualPreferenceToRepo,
  mergeRepositoriesWithManualPreferences,
  upsertManualRepositoryPreference,
} from '@/features/tasks/components/selector/manualRepositoryPreferences'
import type { GitRepoInfo, ManualRepositoryPreference } from '@/types/api'

describe('manualRepositoryPreferences', () => {
  const manualPreference: ManualRepositoryPreference = {
    type: 'icode',
    git_domain: 'icode.baidu.com',
    git_repo: 'baidu/hi/openclaw_infoflow',
    git_url: 'https://icode.baidu.com/baidu/hi/openclaw_infoflow',
    display_name: 'openclaw_infoflow',
    default_branch: 'master',
    is_manual: true,
  }

  it('converts a manual preference to a repo item', () => {
    const repo = manualPreferenceToRepo(manualPreference)

    expect(repo.git_repo).toBe('baidu/hi/openclaw_infoflow')
    expect(repo.git_domain).toBe('icode.baidu.com')
    expect(repo.is_manual).toBe(true)
    expect(repo.default_branch).toBe('master')
  })

  it('builds a manual preference from a selected repo', () => {
    const repo: GitRepoInfo = {
      git_repo_id: 1,
      name: 'openclaw_infoflow',
      git_repo: 'baidu/hi/openclaw_infoflow',
      git_url: 'https://icode.baidu.com/baidu/hi/openclaw_infoflow',
      git_domain: 'icode.baidu.com',
      private: true,
      type: 'icode',
      is_manual: true,
      default_branch: 'master',
    }

    expect(buildManualRepositoryPreference(repo, 'release')).toEqual({
      ...manualPreference,
      default_branch: 'release',
    })
  })

  it('merges provider repos with manual repos and deduplicates by identity', () => {
    const providerRepo: GitRepoInfo = {
      git_repo_id: 2,
      name: 'another-repo',
      git_repo: 'owner/another-repo',
      git_url: 'https://github.com/owner/another-repo',
      git_domain: 'github.com',
      private: false,
      type: 'github',
    }

    const duplicateManualRepo = manualPreferenceToRepo(manualPreference)
    const merged = mergeRepositoriesWithManualPreferences(
      [duplicateManualRepo, providerRepo],
      [manualPreference]
    )

    expect(merged).toHaveLength(2)
    expect(merged[0].git_repo).toBe('baidu/hi/openclaw_infoflow')
    expect(merged[1].git_repo).toBe('owner/another-repo')
  })

  it('upserts manual repositories by type/domain/repo key', () => {
    const updated = upsertManualRepositoryPreference([manualPreference], {
      ...manualPreference,
      default_branch: 'release',
    })

    expect(updated).toHaveLength(1)
    expect(updated[0].default_branch).toBe('release')
  })

  it('supports manual repositories without an explicit default branch', () => {
    const updated = upsertManualRepositoryPreference([manualPreference], {
      ...manualPreference,
      default_branch: null,
    })

    expect(updated[0].default_branch).toBeNull()
    expect(manualPreferenceToRepo(updated[0]).default_branch).toBeNull()
  })
})
