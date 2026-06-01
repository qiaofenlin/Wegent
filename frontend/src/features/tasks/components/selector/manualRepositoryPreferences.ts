// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { GitRepoInfo, ManualRepositoryPreference } from '@/types/api'
import { getRepositoryIdentity } from './repositoryIdentity'

export function buildManualRepositoryPreference(
  repo: GitRepoInfo,
  defaultBranch?: string | null
): ManualRepositoryPreference {
  return {
    type: repo.type,
    git_domain: repo.git_domain,
    git_repo: repo.git_repo,
    git_url: repo.git_url,
    display_name: repo.name || repo.git_repo.split('/').pop() || repo.git_repo,
    default_branch: defaultBranch || null,
    is_manual: true,
  }
}

export function manualPreferenceToRepo(
  preference: ManualRepositoryPreference
): GitRepoInfo {
  const idSource = `${preference.type}:${preference.git_domain}:${preference.git_repo}`
  let hash = 0
  for (let i = 0; i < idSource.length; i++) {
    hash = (hash * 31 + idSource.charCodeAt(i)) | 0
  }

  return {
    git_repo_id: Math.abs(hash) || 1,
    name:
      preference.display_name ||
      preference.git_repo.split('/').pop() ||
      preference.git_repo,
    git_repo: preference.git_repo,
    git_url: preference.git_url,
    git_domain: preference.git_domain,
    private: true,
    type: preference.type,
    is_manual: true,
    default_branch: preference.default_branch || null,
  }
}

export function mergeRepositoriesWithManualPreferences(
  repos: GitRepoInfo[],
  preferences: ManualRepositoryPreference[] | undefined
): GitRepoInfo[] {
  const manualRepos = (preferences || []).map(manualPreferenceToRepo)
  const merged = [...manualRepos, ...repos]
  const seen = new Set<string>()

  return merged.filter(repo => {
    const key = getRepositoryIdentity(repo)
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

export function upsertManualRepositoryPreference(
  existing: ManualRepositoryPreference[] | undefined,
  next: ManualRepositoryPreference
): ManualRepositoryPreference[] {
  const items = existing || []
  const nextKey = `${next.type}:${next.git_domain}:${next.git_repo}`
  const deduped = items.filter(item => {
    const currentKey = `${item.type}:${item.git_domain}:${item.git_repo}`
    return currentKey !== nextKey
  })

  return [next, ...deduped]
}

export function updateManualRepositoryPreferenceBranch(
  existing: ManualRepositoryPreference[] | undefined,
  repo: Pick<GitRepoInfo, 'type' | 'git_domain' | 'git_repo' | 'git_url' | 'name'>,
  branchName?: string | null
): ManualRepositoryPreference[] {
  return upsertManualRepositoryPreference(
    existing,
    buildManualRepositoryPreference(
      {
        git_repo_id: 0,
        git_repo: repo.git_repo,
        git_url: repo.git_url,
        git_domain: repo.git_domain,
        name: repo.name,
        private: true,
        type: repo.type,
        is_manual: true,
      },
      branchName
    )
  )
}
