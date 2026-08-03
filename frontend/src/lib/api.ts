const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1";

function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }
  return headers;
}

function getAuthHeadersWithoutContentType(): HeadersInit {
  const headers: HeadersInit = {};
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }
  return headers;
}

function clearSessionAndRedirectToLogin(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    window.location.href = "/login";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) {
      clearSessionAndRedirectToLogin();
    }
    const errorData = await response.json().catch(() => null);
    const message =
      errorData?.detail || errorData?.message || `Lỗi HTTP: ${response.status}`;
    throw new Error(message);
  }
  // Handle 204 No Content
  if (response.status === 204) {
    return null as T;
  }
  return response.json();
}

export async function apiGet<T>(endpoint: string, params?: Record<string, string>): Promise<T> {
  let url = `${BASE_URL}${endpoint}`;
  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }
  const response = await fetch(url, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  return handleResponse<T>(response);
}

export async function apiPost<T>(endpoint: string, data?: unknown): Promise<T> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: data ? JSON.stringify(data) : undefined,
  });
  return handleResponse<T>(response);
}

export async function apiPatch<T>(endpoint: string, data?: unknown): Promise<T> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: "PATCH",
    headers: getAuthHeaders(),
    body: data ? JSON.stringify(data) : undefined,
  });
  return handleResponse<T>(response);
}

export async function apiDelete<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  return handleResponse<T>(response);
}

export async function apiUpload<T>(
  endpoint: string,
  formData: FormData
): Promise<T> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: "POST",
    headers: getAuthHeadersWithoutContentType(),
    body: formData,
  });
  return handleResponse<T>(response);
}

export async function apiDownload(endpoint: string): Promise<Blob> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: "GET",
    headers: getAuthHeadersWithoutContentType(),
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearSessionAndRedirectToLogin();
    }
    throw new Error(`Lỗi tải file: ${response.status}`);
  }
  return response.blob();
}
