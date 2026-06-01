// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

import { GitRepoInfo } from '@/types/api'

/**
 * Parsed components of a manually entered icode/Gerrit clone URL.
 */
export interface ParsedIcodeUrl {
  git_domain: string
  git_repo: string
  git_url: string
}

/**
 * Parse an icode/Gerrit clone URL into its components.
 *
 * Accepts forms such as:
 *   - http://icode.baidu-int.com/baidu/foo/bar
 *   - https://user@icode.baidu-int.com/a/baidu/foo/bar.git
 *   - ssh://user@icode.baidu.com:8235/baidu/foo/bar
 *   - git@icode.baidu-int.com:baidu/foo/bar.git
 *
 * Returns null if the URL cannot be parsed.
 */
export function parseIcodeUrl(input: string): ParsedIcodeUrl | null {
  const raw = input.trim()
  if (!raw) return null

  let domain = ''
  let path = ''

  // ssh:// scheme form: ssh://[user@]host[:port]/path
  const sshSchemeMatch = raw.match(
    /^ssh:\/\/(?:[^@/]+@)?([^:/\s]+)(?::\d+)?\/(.+)$/i
  )
  if (sshSchemeMatch) {
    domain = sshSchemeMatch[1]
    path = sshSchemeMatch[2]
  } else {
    // scp-like SSH form: user@host:path (no port supported)
    const sshMatch = raw.match(/^[^@\s]+@([^:\s]+):(.+)$/)
    if (sshMatch) {
      domain = sshMatch[1]
      path = sshMatch[2]
    } else {
      // HTTP(S) form (with optional credentials)
      const httpMatch = raw.match(/^https?:\/\/(?:[^@/]+@)?([^/]+)\/(.+)$/i)
      if (!httpMatch) return null
      domain = httpMatch[1]
      path = httpMatch[2]
    }
  }

  // Strip .git suffix
  if (path.endsWith('.git')) path = path.slice(0, -4)
  // Strip Gerrit "/a/" auth prefix
  if (path.startsWith('a/')) path = path.slice(2)
  // Trim leading/trailing slashes
  path = path.replace(/^\/+|\/+$/g, '')

  if (!domain || !path) return null

  return {
    git_domain: domain.toLowerCase(),
    git_repo: path,
    git_url: `https://${domain}/${path}`,
  }
}

/**
 * Build a GitRepoInfo for a manually entered icode repository.
 * Generates a deterministic numeric id based on the domain + repo path so that
 * the same manual entry always produces the same identity.
 */
export function buildIcodeManualRepo(parsed: ParsedIcodeUrl): GitRepoInfo {
  const idSource = `${parsed.git_domain}/${parsed.git_repo}`
  let hash = 0
  for (let i = 0; i < idSource.length; i++) {
    hash = (hash * 31 + idSource.charCodeAt(i)) | 0
  }
  return {
    git_repo_id: Math.abs(hash) || 1,
    name: parsed.git_repo.split('/').pop() || parsed.git_repo,
    git_repo: parsed.git_repo,
    git_url: parsed.git_url,
    git_domain: parsed.git_domain,
    private: true,
    type: 'icode',
  }
}
