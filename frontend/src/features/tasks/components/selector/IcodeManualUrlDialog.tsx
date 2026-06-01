// SPDX-FileCopyrightText: 2025 Weibo, Inc.
//
// SPDX-License-Identifier: Apache-2.0

'use client'

import * as React from 'react'
import { useTranslation } from '@/hooks/useTranslation'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { GitBranch, GitRepoInfo } from '@/types/api'
import { buildIcodeManualRepo, parseIcodeUrl } from './icodeRepoUtils'

export interface IcodeManualUrlDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (repo: GitRepoInfo, branch: GitBranch) => void
}

const DEFAULT_BRANCH = 'master'

/**
 * Dialog for manually entering an icode/Gerrit clone URL and branch name.
 *
 * icode does not expose a REST API to HTTP-password clients, so repository
 * lists and branch lists cannot be fetched. This dialog lets the user
 * provide the clone URL and target branch directly.
 */
export function IcodeManualUrlDialog({
  open,
  onOpenChange,
  onSubmit,
}: IcodeManualUrlDialogProps) {
  const { t } = useTranslation()
  const [url, setUrl] = React.useState('')
  const [branch, setBranch] = React.useState(DEFAULT_BRANCH)
  const [error, setError] = React.useState<string | null>(null)

  // Reset state when dialog closes
  React.useEffect(() => {
    if (!open) {
      setUrl('')
      setBranch(DEFAULT_BRANCH)
      setError(null)
    }
  }, [open])

  const handleConfirm = () => {
    setError(null)
    const parsed = parseIcodeUrl(url)
    if (!parsed) {
      setError(t('common:repos.icode_manual.invalid_url'))
      return
    }
    const trimmedBranch = branch.trim() || DEFAULT_BRANCH
    const repo = buildIcodeManualRepo(parsed)
    const branchObj: GitBranch = {
      name: trimmedBranch,
      protected: false,
      default: true,
    }
    onSubmit(repo, branchObj)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{t('common:repos.icode_manual.title')}</DialogTitle>
          <DialogDescription>
            {t('common:repos.icode_manual.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="icode-clone-url">
              {t('common:repos.icode_manual.url_label')}
            </Label>
            <Input
              id="icode-clone-url"
              data-testid="icode-manual-url-input"
              placeholder={t('common:repos.icode_manual.url_placeholder')}
              value={url}
              onChange={e => setUrl(e.target.value)}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="icode-branch">
              {t('common:repos.icode_manual.branch_label')}
            </Label>
            <Input
              id="icode-branch"
              data-testid="icode-manual-branch-input"
              placeholder={DEFAULT_BRANCH}
              value={branch}
              onChange={e => setBranch(e.target.value)}
            />
          </div>

          {error && <p className="text-sm text-error">{error}</p>}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="icode-manual-cancel-button"
          >
            {t('common:actions.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={handleConfirm}
            data-testid="icode-manual-confirm-button"
          >
            {t('common:actions.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
