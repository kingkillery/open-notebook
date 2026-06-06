'use client'

import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ExternalLink, RefreshCw, Download } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
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

export default function NotebookLMPage() {
  const { t } = useTranslation()
  const status = useNotebookLMStatus()
  const connected = !!status.data?.authenticated
  const notebooks = useNotebookLMNotebooks(connected)
  const importMutation = useImportNotebookLM()

  // Import options (shared across rows for simplicity).
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
      },
      { onSettled: () => setPendingId(null) }
    )
  }

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
    if (!s.authenticated) {
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

          {connected && (
            <>
              <div className="flex flex-wrap items-center gap-6 rounded-md border p-4">
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
                  <Card key={nb.id} className="flex flex-col">
                    <CardHeader>
                      <CardTitle className="text-base line-clamp-2">
                        {nb.title}
                      </CardTitle>
                      <CardDescription>
                        <Badge variant="secondary">
                          {nb.source_count} {t('notebooklm.sources')}
                        </Badge>
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
