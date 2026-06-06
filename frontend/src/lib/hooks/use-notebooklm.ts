import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notebooklmApi } from '@/lib/api/notebooklm'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { NotebookLMImportRequest } from '@/lib/types/api'

export function useNotebookLMStatus() {
  return useQuery({
    queryKey: QUERY_KEYS.notebooklmStatus,
    queryFn: () => notebooklmApi.status(),
    staleTime: 30 * 1000,
  })
}

export function useNotebookLMNotebooks(enabled: boolean) {
  return useQuery({
    queryKey: QUERY_KEYS.notebooklmNotebooks,
    queryFn: () => notebooklmApi.listNotebooks(),
    enabled,
  })
}

export function useImportNotebookLM() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: NotebookLMImportRequest) =>
      notebooklmApi.importNotebook(data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      toast({
        title: t('common.success'),
        description: `${t('notebooklm.importSuccess')} (${result.sources_imported} / ${result.notes_imported})`,
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('notebooklm.importError'),
        description: getApiErrorMessage(error, t, 'notebooklm.importError'),
        variant: 'destructive',
      })
    },
  })
}
