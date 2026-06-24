export class ApiError extends Error {
  status: number;
  code: string;
  type: string;
  constructor(status: number, type: string, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.type = type;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: { Accept: "application/json" } });
  let body: unknown;
  try {
    body = await resp.json();
  } catch {
    throw new ApiError(resp.status, "internal_error", "non_json_response",
      `Non-JSON response from ${path} (${resp.status})`);
  }
  if (!resp.ok) {
    const envelope = body as { error?: { type?: string; code?: string; message?: string } };
    const err = envelope.error ?? {};
    throw new ApiError(
      resp.status,
      err.type ?? "internal_error",
      err.code ?? "unknown",
      err.message ?? `Request to ${path} failed (${resp.status})`,
    );
  }
  return body as T;
}
