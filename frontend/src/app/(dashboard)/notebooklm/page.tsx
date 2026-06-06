'use client'

import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ExternalLink, RefreshCw, Download, Users } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  useNotebookLMStatus,
  useNotebookLMNotebooks,
  useImportNotebookLM,
} from '@/lib/hooks/use-notebooklm'
import type { NotebookLMRemoteNotebook } from '@/lib/types/api'

const ALL = '__all__'

export default function NotebookLMPage() {
  const { t } = useTranslation()
  const status = useNotebookLMStatus()
  const accounts = status.data?.accounts ?? []
  const connected = !!status.data?.authenticated

  // Account filter: ALL aggregates across every connected account.
  const [selected, setSelected] = useState<string>(ALL)
  const profileFilter = selected === ALL ? undefined : selected
  const notebooks = useNotebookLMNotebooks(connected, profileFilter)
  const importMutation = useImportNotebookLM()

  const [importSources, setImportSources] = useState(true)
  const [importNotes, setImportNotes] = useState(true)
  const [embed, setEmbed] = useState(false)
  const [pendingId, setPendingId] = useState<string | null>(null)

  const handleImport = (nb: NotebookLMRemoteNotebook) => {
    setPendingId(nb.id)
    importMutation.mutate(
      {
        remote_notebook_id: nb.id,
        import_sources: importSources,
        import_notes: importNotes,
        embed,
        profile: nb.profile,
      },
      { onSettled: () => setPendingId(null) }
    )
  }

  const expiredAccounts = accounts.filter((a) => !a.authenticated)
  const multipleAccounts = accounts.length > 1

  const renderStatus = () => {
    if (status.isLoading) return null
    const s = status.data
    if (!s) return null

    if (!s.available) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t('notebooklm.title')}</AlertTitle>
          <AlertDescription>{t('notebooklm.statusNotInstalled')}</AlertDescription>
        </Alert>
      )
    }
    if (!connected) {
      return (
        <Alert className="bg-amber-50 text-amber-900 border-amber-200">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t('notebooklm.title')}</AlertTitle>
          <AlertDescription>
            {s.message || t('notebooklm.statusExpired')}
          </AlertDescription>
        </Alert>
      )
    }
    return (
      <Alert className="bg-emerald-50 text-emerald-900 border-emerald-200">
        <CheckCircle2 className="h-4 w-4" />
        <AlertTitle>{t('notebooklm.statusConnected')}</AlertTitle>
        <AlertDescription>{s.message}</AlertDescription>
      </Alert>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-6 space-y-6">
          <header className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold tracking-tight">
                {t('notebooklm.title')}
              </h1>
              <p className="text-muted-foreground">{t('notebooklm.subtitle')}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                status.refetch()
                if (connected) notebooks.refetch()
              }}
              disabled={status.isFetching || notebooks.isFetching}
            >
              <RefreshCw
                className={`h-4 w-4 ${status.isFetching ? 'animate-spin' : ''}`}
              />
              {t('notebooklm.refresh')}
            </Button>
          </header>

          {renderStatus()}

          {/* Per-account expired-session warnings */}
          {expiredAccounts.map((a) => (
            <Alert
              key={a.profile}
              className="bg-amber-50 text-amber-900 border-amber-200"
            >
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>{a.email || a.profile}</AlertTitle>
              <AlertDescription>
                {t('notebooklm.accountExpired')}{' '}
                <code>nlm login --profile {a.profile}</code>
              </AlertDescription>
            </Alert>
          ))}

          {/* Hint for connecting more accounts */}
          {connected && (
            <p className="text-xs text-muted-foreground">
              {t('notebooklm.addAccountHint')}{' '}
              <code>nlm login --profile &lt;name&gt;</code>
            </p>
          )}

          {connected && (
            <>
              <div className="flex flex-wrap items-center gap-6 rounded-md border p-4">
                {/* Account picker (only meaningful with 2+ accounts) */}
                {multipleAccounts && (
                  <div className="flex items-center gap-2">
                    <Users className="h-4 w-4 text-muted-foreground" />
                    <Select value={selected} onValueChange={setSelected}>
                      <SelectTrigger className="w-[240px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={ALL}>
                          {t('notebooklm.allAccounts')}
                        </SelectItem>
                        {accounts.map((a) => (
                          <SelectItem
                            key={a.profile}
                            value={a.profile}
                            disabled={!a.authenticated}
                          >
                            {a.email || a.profile}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={importSources}
                    onCheckedChange={(v) => setImportSources(!!v)}
                  />
                  {t('notebooklm.importSources')}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={importNotes}
                    onCheckedChange={(v) => setImportNotes(!!v)}
                  />
                  {t('notebooklm.importNotes')}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={embed}
                    onCheckedChange={(v) => setEmbed(!!v)}
                  />
                  {t('notebooklm.embed')}
                </label>
              </div>

              {notebooks.isError && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>{t('notebooklm.loadError')}</AlertDescription>
                </Alert>
              )}

              {notebooks.data && notebooks.data.length === 0 && (
                <p className="text-muted-foreground">{t('notebooklm.empty')}</p>
              )}

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {notebooks.data?.map((nb) => (
                  <Card key={`${nb.profile}:${nb.id}`} className="flex flex-col">
                    <CardHeader>
                      <CardTitle className="text-base line-clamp-2">
                        {nb.title}
                      </CardTitle>
                      <CardDescription className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">
                          {nb.source_count} {t('notebooklm.sources')}
                        </Badge>
                        {multipleAccounts && nb.account && (
                          <Badge variant="outline">{nb.account}</Badge>
                        )}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="mt-auto flex items-center gap-2">
                      <Button
                        size="sm"
                        onClick={() => handleImport(nb)}
                        disabled={importMutation.isPending}
                      >
                        <Download className="h-4 w-4" />
                        {pendingId === nb.id
                          ? t('notebooklm.importing')
                          : t('notebooklm.import')}
                      </Button>
                      {nb.url && (
                        <Button asChild size="sm" variant="ghost">
                          <a href={nb.url} target="_blank" rel="noreferrer">
                            <ExternalLink className="h-4 w-4" />
                            {t('notebooklm.open')}
                          </a>
                        </Button>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  )
}
