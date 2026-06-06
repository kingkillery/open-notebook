import apiClient from './client'
import {
  NotebookLMStatus,
  NotebookLMRemoteNotebook,
  NotebookLMImportRequest,
  NotebookLMImportResponse,
} from '@/lib/types/api'

export const notebooklmApi = {
  status: async () => {
    const response = await apiClient.get<NotebookLMStatus>('/notebooklm/status')
    return response.data
  },

  listNotebooks: async () => {
    const response = await apiClient.get<NotebookLMRemoteNotebook[]>(
      '/notebooklm/notebooks'
    )
    return response.data
  },

  importNotebook: async (data: NotebookLMImportRequest) => {
    const response = await apiClient.post<NotebookLMImportResponse>(
      '/notebooklm/import',
      data
    )
    return response.data
  },
}
