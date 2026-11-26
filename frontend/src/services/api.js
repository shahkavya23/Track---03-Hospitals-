// Purpose: Client API service for interacting with the RAKSHA backend.

export async function fetchStatus() {
  const res = await fetch('/api/status');
  if (!res.ok) throw new Error('Failed to fetch status');
  return await res.json();
}

export async function fetchFiles() {
  const res = await fetch('/api/files');
  if (!res.ok) throw new Error('Failed to fetch files');
  return await res.json();
}

export async function fetchReport() {
  const res = await fetch('/api/report');
  if (!res.ok) throw new Error('Failed to fetch report');
  return await res.json();
}

export async function loadPreset(presetKey) {
  const res = await fetch('/api/load-preset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preset: presetKey }),
  });
  if (!res.ok) throw new Error('Failed to load preset');
  return await res.json();
}

export async function uploadFile(file) {
  const filename = file.name || 'uploaded_file.txt';
  const res = await fetch(`/api/upload?filename=${encodeURIComponent(filename)}`, {
    method: 'POST',
    body: file,
  });
  if (!res.ok) throw new Error(`Failed to upload ${filename}`);
  return await res.json();
}

export async function runPipeline() {
  const res = await fetch('/api/run', { method: 'POST' });
  if (!res.ok) throw new Error('Pipeline execution failed');
  return await res.json();
}

export async function fetchDiff(filename) {
  const res = await fetch(`/api/diff?file=${encodeURIComponent(filename)}`);
  if (!res.ok) throw new Error('Failed to fetch diff');
  return await res.json();
}

export async function resetWorkspace() {
  const res = await fetch('/api/reset', { method: 'POST' });
  if (!res.ok) throw new Error('Failed to reset workspace');
  return await res.json();
}

export async function deleteFile(filename) {
  const res = await fetch('/api/delete-file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  if (!res.ok) throw new Error('Failed to delete file');
  return await res.json();
}
