// Purpose: Client API service for interacting with the RAKSHA backend.

async function getErrorMessage(response, fallback) {
  try {
    const payload = await response.json();
    return payload.error || payload.message || fallback;
  } catch {
    return fallback;
  }
}

export async function fetchStatus() {
  const res = await fetch('/api/status');
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch status'));
  return await res.json();
}

export async function fetchFiles() {
  const res = await fetch('/api/files');
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch files'));
  return await res.json();
}

export async function fetchReport() {
  const res = await fetch('/api/report');
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch report'));
  return await res.json();
}

export async function loadPreset(presetKey) {
  const res = await fetch('/api/load-preset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preset: presetKey }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to load preset'));
  return await res.json();
}

export function uploadFile(filename, content, isBase64 = false, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/api/upload');
    request.setRequestHeader('Content-Type', 'application/json');
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onload = () => {
      try {
        const payload = JSON.parse(request.responseText);
        if (request.status < 200 || request.status >= 300) {
          reject(new Error(payload.error || 'Failed to upload file'));
          return;
        }
        resolve(payload);
      } catch {
        reject(new Error(request.status < 200 || request.status >= 300 ? 'Upload request failed' : 'Invalid upload response'));
      }
    };
    request.onerror = () => reject(new Error('Upload connection failed'));
    request.onabort = () => reject(new Error('Upload was cancelled'));
    request.send(JSON.stringify({ filename, content, is_base64: isBase64 }));
  });
}

export async function runPipeline() {
  const res = await fetch('/api/run', { method: 'POST' });
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Pipeline execution failed'));
  return await res.json();
}

export async function fetchDiff(filename) {
  const res = await fetch(`/api/diff?file=${encodeURIComponent(filename)}`);
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch diff'));
  return await res.json();
}

export async function resetWorkspace() {
  const res = await fetch('/api/reset', { method: 'POST' });
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to reset workspace'));
  return await res.json();
}

export async function deleteFile(filename) {
  const res = await fetch('/api/delete-file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to delete file'));
  return await res.json();
}
