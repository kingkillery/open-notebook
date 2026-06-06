import apiClient from './client'
import {
  NotebookLMAccount,
  NotebookLMStatus,
  NotebookLMRemoteNotebook,
  NotebookLMImportRequest,
  NotebookLMImportResponse,
  NotebookLMStudioGenerateRequest,
  NotebookLMStudioGenerateResponse,
} from '@/lib/types/api'

export const notebooklmApi = {
  status: async () => {
    const response = await apiClient.get<NotebookLMStatus>('/notebooklm/status')
    return response.data
  },

  accounts: async () => {
    const response = await apiClient.get<NotebookLMAccount[]>(
      '/notebooklm/accounts'
    )
    return response.data
  },

  listNotebooks: async (profile?: string) => {
    const response = await apiClient.get<NotebookLMRemoteNotebook[]>(
      '/notebooklm/notebooks',
      { params: profile ? { profile } : undefined }
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

  generateStudio: async (data: NotebookLMStudioGenerateRequest) => {
    const response = await apiClient.post<NotebookLMStudioGenerateResponse>(
      '/notebooklm/studio/generate',
      data
    )
    return response.data
  },
}
