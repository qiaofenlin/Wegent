// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import * as React from 'react'
import { Check, ChevronLeft, GitBranch as GitBranchIcon } from 'lucide-react'
import { useTranslation } from '@/hooks/useTranslation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export interface ManualBranchEditorProps {
  repoName: string
  branchName?: string | null
  onBack: () => void
  onConfirm: (branchName: string | null) => void
}

export function ManualBranchEditor({
  repoName,
  branchName,
  onBack,
  onConfirm,
}: ManualBranchEditorProps) {
  const { t } = useTranslation()
  const [value, setValue] = React.useState(branchName || '')

  React.useEffect(() => {
    setValue(branchName || '')
  }, [branchName])
  const trimmed = value.trim()

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <button
        type="button"
        className="flex items-center border-b border-border px-3 py-2 cursor-pointer hover:bg-hover w-full text-left group"
        onClick={onBack}
      >
        <ChevronLeft className="w-4 h-4 text-text-muted mr-1 group-hover:text-primary transition-colors flex-shrink-0" />
        <GitBranchIcon className="w-4 h-4 text-text-muted mr-2 flex-shrink-0" />
        <span className="text-sm font-medium text-text-primary flex-shrink-0">
          {t('common:branches.manual_branch_title', '手动设置分支')}
        </span>
        <span className="ml-2 text-xs text-text-muted truncate flex-1 text-right" title={repoName}>
          {repoName}
        </span>
      </button>

      <div className="p-4 space-y-4">
        <div className="space-y-2">
          <label className="block text-sm font-medium text-text-secondary">
            {t('common:branches.branch_name', '分支名')}
          </label>
          <Input
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={t('common:branches.default_branch_placeholder', '留空则使用默认分支')}
            data-testid="manual-branch-input"
          />
          <p className="text-xs text-text-muted">
            {t(
              'common:branches.manual_branch_description',
              '该仓库无法自动获取分支列表。可手动输入目标分支，留空则使用远端默认分支。'
            )}
          </p>
        </div>

        <Button
          variant="primary"
          className="w-full"
          data-testid="manual-branch-confirm-button"
          onClick={() => onConfirm(trimmed || null)}
        >
          <Check className="w-4 h-4 mr-2" />
          {t('common:actions.confirm')}
        </Button>
      </div>
    </div>
  )
}
