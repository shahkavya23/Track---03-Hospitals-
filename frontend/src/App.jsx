import React, { useState, useEffect } from 'react';
import { CheckCircle2, AlertCircle } from 'lucide-react';
import Header from './components/Header';
import SanitizeWorkspace from './components/tabs/IngestTab';
import LinkageTab from './components/tabs/LinkageTab';
import AuditTab from './components/tabs/ReportTab';
import * as api from './services/api';
import './App.css';

export default function App() {
  const [activeTab, setActiveTab] = useState('sanitize');
  const [status, setStatus] = useState(null);
  const [files, setFiles] = useState([]);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [report, setReport] = useState(null);
  const [clusters, setClusters] = useState({});
  const [selectedDiffFile, setSelectedDiffFile] = useState('');
  const [diffData, setDiffData] = useState(null);
  const [toast, setToast] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);

  const showToast = (msg, tone = 'success') => {
    setToast({ msg, tone });
    setTimeout(() => setToast(null), 3500);
  };

  const loadStatusAndFiles = async () => {
    try {
      const statusData = await api.fetchStatus();
      setStatus(statusData);
    } catch {
      // Backend starting up
    }
    try {
      const filesData = await api.fetchFiles();
      const currentFiles = filesData.files || [];
      setFiles(currentFiles);
      if (currentFiles.length > 0 && (!selectedDiffFile || !currentFiles.some(f => f.name === selectedDiffFile))) {
        setSelectedDiffFile(currentFiles[0].name);
      }
    } catch {
      // Staged files empty
    }
    try {
      const reportData = await api.fetchReport();
      setReport(reportData.report);
    } catch {
      // Report not ready
    }
  };

  useEffect(() => {
    loadStatusAndFiles();
  }, []);

  const loadDiffForFile = async (filename) => {
    if (!filename) return;
    try {
      const data = await api.fetchDiff(filename);
      setDiffData(data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (selectedDiffFile) {
      loadDiffForFile(selectedDiffFile);
    }
  }, [selectedDiffFile]);

  const handleRunPipeline = async (fileToInspect = selectedDiffFile) => {
    setRunning(true);
    try {
      const data = await api.runPipeline();
      if (data.success) {
        setMetrics(data.metrics);
        setReport(data.report);
        setClusters(data.clusters || {});
        await loadStatusAndFiles();
        if (fileToInspect) {
          setSelectedDiffFile(fileToInspect);
          await loadDiffForFile(fileToInspect);
        }
        showToast('Sanitization complete');
      } else {
        showToast(data.error || 'Pipeline execution failed', 'error');
      }
    } catch (error) {
      showToast(error.message || 'Pipeline communication error', 'error');
    } finally {
      setRunning(false);
    }
  };

  const handleLoadPreset = async (presetKey) => {
    try {
      const data = await api.loadPreset(presetKey);
      if (data.success) {
        await loadStatusAndFiles();
        const firstFile = data.loaded_files?.[0] || '';
        if (firstFile) {
          setSelectedDiffFile(firstFile);
        }
        await handleRunPipeline(firstFile);
      }
    } catch (error) {
      showToast(error.message || 'Error loading scenario', 'error');
    }
  };

  const handleFileUpload = async (event) => {
    const uploadedFiles = event.target.files;
    if (!uploadedFiles || uploadedFiles.length === 0) return;

    const selectedFiles = Array.from(uploadedFiles);
    const tooLargeFile = selectedFiles.find((file) => file.size > 200 * 1024 * 1024);
    if (tooLargeFile) {
      showToast(`${tooLargeFile.name} exceeds the 200 MB limit`, 'error');
      event.target.value = '';
      return;
    }
    setUploadProgress({ total: selectedFiles.length, completed: 0, currentFile: selectedFiles[0].name, percent: 0 });
    let completed = 0;
    try {
      for (const file of selectedFiles) {
        setUploadProgress({ total: selectedFiles.length, completed, currentFile: file.name, percent: 0 });
        const content = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onprogress = (progressEvent) => {
            if (progressEvent.lengthComputable) {
              setUploadProgress({ total: selectedFiles.length, completed, currentFile: file.name, percent: Math.round((progressEvent.loaded / progressEvent.total) * 15) });
            }
          };
          reader.onload = () => {
            const dataUrl = String(reader.result);
            resolve(dataUrl.slice(dataUrl.indexOf(',') + 1));
          };
          reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
          reader.readAsDataURL(file);
        });
        await api.uploadFile(file.name, content, true, (percent) => {
          setUploadProgress({ total: selectedFiles.length, completed, currentFile: file.name, percent: 15 + Math.round(percent * 0.85) });
        });
        completed += 1;
        setUploadProgress({ total: selectedFiles.length, completed, currentFile: file.name, percent: 100 });
      }
      await loadStatusAndFiles();
      const primaryFile = selectedFiles[0].name;
      setSelectedDiffFile(primaryFile);
      setUploadProgress({ total: selectedFiles.length, completed: selectedFiles.length, currentFile: primaryFile, percent: 100, processing: true });
      await handleRunPipeline(primaryFile);
    } catch (error) {
      showToast(error.message || 'File upload failed', 'error');
    } finally {
      setUploadProgress(null);
    }
    event.target.value = '';
  };

  const handleDeleteFile = async (filename) => {
    try {
      await api.deleteFile(filename);
      showToast(`Removed ${filename}`);
      await loadStatusAndFiles();
      if (selectedDiffFile === filename) {
        setSelectedDiffFile('');
        setDiffData(null);
      }
    } catch {
      showToast(`Failed to remove ${filename}`, 'error');
    }
  };

  const handleResetWorkspace = async () => {
    try {
      await api.resetWorkspace();
      setFiles([]);
      setMetrics(null);
      setReport(null);
      setClusters({});
      setDiffData(null);
      setSelectedDiffFile('');
      await loadStatusAndFiles();
      showToast('Workspace cleared');
    } catch {
      showToast('Failed to reset workspace', 'error');
    }
  };

  const hasOutput = Boolean(metrics || report);
  const quarantinedCount = metrics?.files_quarantined ?? report?.counts?.files_quarantined ?? 0;
  const clustersCount = Object.keys(clusters).length || metrics?.records_linked || report?.counts?.records_linked || 0;

  return (
    <div className="min-h-screen bg-[#111214] text-[#F4F4F5] flex flex-col font-sans">
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-4 py-3 rounded-lg flex items-center gap-2 border text-xs font-medium animate-enter ${
            toast.tone === 'error'
              ? 'bg-[#1B1316] border-rose-500/30 text-rose-200'
              : 'bg-[#17181C] border-white/[0.12] text-zinc-100'
          }`}
        >
          {toast.tone === 'error' ? (
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" strokeWidth={1.5} />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" strokeWidth={1.5} />
          )}
          <span>{toast.msg}</span>
        </div>
      )}

      <Header
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        status={status}
        hasOutput={hasOutput}
        filesCount={files.length}
        quarantinedCount={quarantinedCount}
        clustersCount={clustersCount}
        running={running}
        onRun={() => handleRunPipeline()}
        onReset={handleResetWorkspace}
      />

      <main className="flex-1 w-full max-w-6xl mx-auto px-6 py-8">
        <div className="animate-enter" key={activeTab}>
          {activeTab === 'sanitize' && (
            <SanitizeWorkspace
              files={files}
              metrics={metrics}
              report={report}
              running={running}
              uploadProgress={uploadProgress}
              selectedFile={selectedDiffFile}
              diffData={diffData}
              onSelectFile={setSelectedDiffFile}
              onLoadPreset={handleLoadPreset}
              onFileUpload={handleFileUpload}
              onDeleteFile={handleDeleteFile}
              onClearQueue={handleResetWorkspace}
              onRun={() => handleRunPipeline()}
              onOpenAudit={() => setActiveTab('audit')}
            />
          )}

          {activeTab === 'linkage' && (
            <LinkageTab
              clusters={clusters}
              onGoSanitize={() => setActiveTab('sanitize')}
            />
          )}

          {activeTab === 'audit' && (
            <AuditTab report={report} />
          )}
        </div>
      </main>
    </div>
  );
}
