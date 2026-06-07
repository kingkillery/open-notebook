export interface Transformation {
  id: string
  name: string
  title: string
  description: string
  prompt: string
  apply_default: boolean
  created: string
  updated: string
}

export interface CreateTransformationRequest {
  name: string
  title: string
  description: string
  prompt: string
  apply_default?: boolean
}

export interface UpdateTransformationRequest {
  name?: string
  title?: string
  description?: string
  prompt?: string
  apply_default?: boolean
}

export interface ExecuteTransformationRequest {
  transformation_id: string
  input_text: string
  model_id: string
}

export interface ExecuteTransformationResponse {
  output: string
  transformation_id: string
  model_id: string
}

export interface NotebookTransformationExecuteRequest {
  context_config?: {
    sources?: Record<string, string>
    notes?: Record<string, string>
  }
  save_as_note?: boolean
  note_title?: string
}

export interface NotebookTransformationExecuteResponse {
  output: string
  transformation_id: string
  model_id: string
  notebook_id: string
  note?: {
    id: string
    title: string | null
    content: string | null
    note_type: string | null
    created: string
    updated: string
    command_id?: string | null
  } | null
}

export interface DefaultPrompt {
  transformation_instructions: string
}