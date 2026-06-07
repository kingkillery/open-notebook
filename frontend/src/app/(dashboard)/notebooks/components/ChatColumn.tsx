'use client'

import { useMemo } from 'react'
import { Sparkles, AlertCircle } from 'lucide-react'
import { useNotebookChat } from '@/lib/hooks/useNotebookChat'
import { useNotes } from '@/lib/hooks/use-notes'
import {
  useExecuteNotebookTransformation,
  useTransformations
} from '@/lib/hooks/use-transformations'
import { ChatPanel } from '@/components/source/ChatPanel'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ContextSelections } from '../[id]/page'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceListResponse } from '@/lib/types/api'
interface ChatColumnProps {
  notebookId: string
  contextSelections: ContextSelections
  sources: SourceListResponse[]
  sourcesLoading: boolean
}

export function ChatColumn({ notebookId, contextSelections, sources, sourcesLoading }: ChatColumnProps) {
  const { t } = useTranslation()

  // Fetch notes for this notebook
  const { data: notes = [], isLoading: notesLoading } = useNotes(notebookId)

  // Initialize notebook chat hook
  const chat = useNotebookChat({
    notebookId,
    sources,
    notes,
    contextSelections
  })

  // Calculate context stats for indicator
  const contextStats = useMemo(() => {
    let sourcesInsights = 0
    let sourcesFull = 0
    let notesCount = 0

    // Count sources by mode
    sources.forEach(source => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') {
        sourcesInsights++
      } else if (mode === 'full') {
        sourcesFull++
      }
    })

    // Count notes that are included (not 'off')
    notes.forEach(note => {
      const mode = contextSelections.notes[note.id]
      if (mode === 'full') {
        notesCount++
      }
    })

    return {
      sourcesInsights,
      sourcesFull,
      notesCount,
      tokenCount: chat.tokenCount,
      charCount: chat.charCount
    }
  }, [sources, notes, contextSelections, chat.tokenCount, chat.charCount])

  const transformations = useTransformations()
  const executeNotebookTransformation = useExecuteNotebookTransformation(notebookId)

  const contextConfig = useMemo(() => {
    const sourcesConfig: Record<string, string> = {}
    sources.forEach((source) => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') {
        sourcesConfig[source.id] = 'insights'
      } else if (mode === 'full') {
        sourcesConfig[source.id] = 'full content'
      } else {
        sourcesConfig[source.id] = 'not in'
      }
    })

    const notesConfig: Record<string, string> = {}
    notes.forEach((note) => {
      const mode = contextSelections.notes[note.id]
      notesConfig[note.id] = mode === 'full' ? 'full content' : 'not in'
    })

    return { sources: sourcesConfig, notes: notesConfig }
  }, [sources, notes, contextSelections])

  const handleRunTransformation = (transformationId: string, title: string) => {
    executeNotebookTransformation.mutate({
      transformationId,
      data: {
        context_config: contextConfig,
        save_as_note: true,
        note_title: title,
      },
    })
  }

  // Show loading state while sources/notes are being fetched
  if (sourcesLoading || notesLoading) {
    return (
      <Card className="h-full flex flex-col">
        <CardContent className="flex-1 flex items-center justify-center">
          <LoadingSpinner size="lg" />
        </CardContent>
      </Card>
    )
  }

  // Show error state if data fetch failed (unlikely but good to handle)
  if (!sources && !notes) {
    return (
      <Card className="h-full flex flex-col">
        <CardContent className="flex-1 flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-sm">{t('chat.unableToLoadChat')}</p>
            <p className="text-xs mt-2">{t('common.refreshPage') || 'Please try refreshing the page'}</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0 gap-3">
      <Card className="flex-shrink-0">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="space-y-0.5">
            <div className="text-sm font-medium">{t('transformations.notebookOptions')}</div>
            <div className="text-xs text-muted-foreground">
              {t('transformations.notebookOptionsDesc')}
            </div>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  transformations.isLoading ||
                  executeNotebookTransformation.isPending ||
                  (transformations.data?.length ?? 0) === 0
                }
              >
                <Sparkles className="h-4 w-4" />
                {executeNotebookTransformation.isPending
                  ? t('transformations.running')
                  : t('transformations.runTransformation')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {transformations.data?.map((transformation) => (
                <DropdownMenuItem
                  key={transformation.id}
                  className="flex flex-col items-start gap-1"
                  onClick={() => handleRunTransformation(transformation.id, transformation.title)}
                >
                  <span className="font-medium">{transformation.title}</span>
                  {transformation.description && (
                    <span className="line-clamp-2 text-xs text-muted-foreground">
                      {transformation.description}
                    </span>
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </CardContent>
      </Card>
      <ChatPanel
        title={t('chat.chatWithNotebook')}
        contextType="notebook"
        messages={chat.messages}
        isStreaming={chat.isSending}
        contextIndicators={null}
        onSendMessage={(message, modelOverride) => chat.sendMessage(message, modelOverride)}
        modelOverride={chat.currentSession?.model_override ?? chat.pendingModelOverride ?? undefined}
        onModelChange={(model) => chat.setModelOverride(model ?? null)}
        sessions={chat.sessions}
        currentSessionId={chat.currentSessionId}
        onCreateSession={(title) => chat.createSession(title)}
        onSelectSession={chat.switchSession}
        onUpdateSession={(sessionId, title) => chat.updateSession(sessionId, { title })}
        onDeleteSession={chat.deleteSession}
        loadingSessions={chat.loadingSessions}
        notebookContextStats={contextStats}
        notebookId={notebookId}
      />
    </div>
  )
}
