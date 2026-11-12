import { api, setCsrf } from "./client"
import type {
  Capabilities,
  Decision,
  MeResponse,
  ResultList,
  RunView,
  Statistics,
  Task,
  TaskFile,
} from "./types"

export async function login(username: string, password: string): Promise<MeResponse> {
  const { data } = await api.post<MeResponse>("/api/v1/auth/login", {
    username,
    password,
  })
  setCsrf(data.csrf_token)
  return data
}

export async function me(): Promise<MeResponse> {
  const { data } = await api.get<MeResponse>("/api/v1/auth/me")
  setCsrf(data.csrf_token)
  return data
}

export async function logout(): Promise<void> {
  await api.post("/api/v1/auth/logout")
  setCsrf(null)
}

export async function getCapabilities(): Promise<Capabilities> {
  const { data } = await api.get<Capabilities>("/api/v1/capabilities")
  return data
}

export async function listTasks(): Promise<Task[]> {
  const { data } = await api.get<Task[]>("/api/v1/tasks")
  return data
}

export async function getTask(taskId: string): Promise<Task> {
  const { data } = await api.get<Task>(`/api/v1/tasks/${taskId}`)
  return data
}

export async function deleteTask(taskId: string): Promise<void> {
  await api.delete(`/api/v1/tasks/${taskId}`)
}

export async function createTask(customerRole: string): Promise<Task> {
  const { data } = await api.post<Task>("/api/v1/tasks", {
    customer_role: customerRole,
  })
  return data
}

export async function listFiles(taskId: string): Promise<TaskFile[]> {
  const { data } = await api.get<TaskFile[]>(`/api/v1/tasks/${taskId}/files`)
  return data
}

export async function uploadFile(taskId: string, file: File): Promise<TaskFile> {
  const form = new FormData()
  form.append("file", file)
  const { data } = await api.post<TaskFile>(`/api/v1/tasks/${taskId}/files`, form)
  return data
}

export async function deleteFile(taskId: string, fileId: string): Promise<void> {
  await api.delete(`/api/v1/tasks/${taskId}/files/${fileId}`)
}

export async function setFileClassification(
  taskId: string,
  fileId: string,
  materialType: string | null,
): Promise<TaskFile> {
  const { data } = await api.patch<TaskFile>(
    `/api/v1/tasks/${taskId}/files/${fileId}/classification`,
    { material_type: materialType },
  )
  return data
}

export function assetUrl(taskId: string, assetId: string): string {
  return `/api/v1/tasks/${taskId}/assets/${assetId}`
}

export async function createRun(taskId: string): Promise<RunView> {
  const { data } = await api.post<RunView>(`/api/v1/tasks/${taskId}/runs`, {})
  return data
}

export async function getRun(taskId: string, runId: string): Promise<RunView> {
  const { data } = await api.get<RunView>(`/api/v1/tasks/${taskId}/runs/${runId}`)
  return data
}

export async function listResults(taskId: string): Promise<ResultList> {
  const { data } = await api.get<ResultList>(`/api/v1/tasks/${taskId}/results`)
  return data
}

export async function updateDecision(
  taskId: string,
  resultId: string,
  body: { run_id: string; decision: string; reject_reason: string | null },
): Promise<{ decision: Decision; statistics: { overall: Statistics } }> {
  const { data } = await api.patch(
    `/api/v1/tasks/${taskId}/results/${resultId}/decision`,
    body,
  )
  return data
}

export async function completeTask(
  taskId: string,
  runId: string,
  inputRevision: number,
): Promise<{ state: string }> {
  const { data } = await api.post(`/api/v1/tasks/${taskId}/complete`, {
    run_id: runId,
    input_revision: inputRevision,
  })
  return data
}
