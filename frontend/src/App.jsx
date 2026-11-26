// Purpose: Main React container coordinating state, modular components, and API interactions.
import React, { useState, useEffect } from 'react';
import { Sparkles } from 'lucide-react';
import Header from './components/Header';
import StatsBar from './components/StatsBar';
import Navigation from './components/Navigation';
import IngestTab from './components/tabs/IngestTab';
import PipelineTab from './components/tabs/PipelineTab';
import DiffTab from './components/tabs/DiffTab';
import LinkageTab from './components/tabs/LinkageTab';
import ClinicalTab from './components/tabs/ClinicalTab';
import QuarantineTab from './components/tabs/QuarantineTab';
import ReportTab from './components/tabs/ReportTab';
import * as api from './services/api';
import './App.css';

export default function App() {
  const [activeTab, setActiveTab] = useState('files');
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
  const [clinicalEntities, setClinicalEntities] = useState([]);

  const showToast = (msg) => {
    setToast(msg);
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

  const handleLoadPreset = async (presetKey) => {
    try {
      const data = await api.loadPreset(presetKey);
      if (data.success) {
        showToast(`Loaded Scenario: ${data.title}`);
        await loadStatusAndFiles();
        setMetrics(null);
        setReport(null);
        setClusters({});
        setDiffData(null);
        if (data.loaded_files && data.loaded_files.length > 0) {
          setSelectedDiffFile(data.loaded_files[0]);
        }
      }
    } catch (error) {
      showToast(error.message || 'Error loading preset scenario');
    }
  };

  const handleFileUpload = async (event) => {
    const uploadedFiles = event.target?.files;
    if (!uploadedFiles || uploadedFiles.length === 0) return;

    const selectedFiles = Array.from(uploadedFiles);
    const tooLargeFile = selectedFiles.find((file) => file.size > 200 * 1024 * 1024);
    if (tooLargeFile) {
      showToast(`${tooLargeFile.name} exceeds the 200 MB upload limit.`);
      if (event.target && 'value' in event.target) event.target.value = '';
      return;
    }

    setRunning(true);
    showToast(`Resetting workspace and ingesting ${selectedFiles.length} file(s)...`);
    try {
      // Reset workspace first so old files don't contaminate the new run
      await api.resetWorkspace();
      setFiles([]);
      setMetrics(null);
      setReport(null);
      setClusters({});
      setDiffData(null);
      setClinicalEntities([]);

      // Upload all selected files
      for (const file of selectedFiles) {
        const uploadRes = await api.uploadFile(file);
        if (uploadRes.is_valid === false) {
          showToast(`Warning: ${file.name} quarantined (${uploadRes.quarantine_reason || 'unsupported format'})`);
        }
      }
      await loadStatusAndFiles();
      if (selectedFiles.length > 0) {
        setSelectedDiffFile(selectedFiles[0].name);
      }
      showToast(`Running Privacy Firewall Pipeline on ${selectedFiles.length} file(s)...`);
      await handleRunPipeline(selectedFiles[0]?.name);
    } catch (error) {
      showToast(error.message || 'File upload failed');
      setRunning(false);
    } finally {
      if (event.target && 'value' in event.target) {
        event.target.value = '';
      }
    }
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
    } catch (e) {
      showToast(`Failed to remove ${filename}`);
    }
  };

  const handleRunPipeline = async (targetFile) => {
    setRunning(true);
    setActiveTab('pipeline');
    try {
      const data = await api.runPipeline();
      if (data.success) {
        setMetrics(data.metrics);
        setReport(data.report);
        setClusters(data.clusters || {});
        if (data.clinical_entities) {
          setClinicalEntities(data.clinical_entities);
        }
        await loadStatusAndFiles();
        const fileToView = targetFile || selectedDiffFile || (data.sanitized_files && data.sanitized_files[0]) || '';
        if (fileToView) {
          setSelectedDiffFile(fileToView);
          await loadDiffForFile(fileToView);
        }
        showToast('Pipeline Completed! Viewing Sanitized Output');
        setActiveTab('diff');
      } else {
        showToast(data.error || 'Pipeline execution failed');
      }
    } catch (error) {
      showToast(error.message || 'Pipeline communication error');
    } finally {
      setRunning(false);
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
      setClinicalEntities([]);
      await loadStatusAndFiles();
      showToast('Workspace reset.');
    } catch (e) {
      showToast('Failed to reset workspace');
    }
  };

  const hasOutput = Boolean(metrics || report);

  return (
    <div className={`raksha-shell page-${activeTab} min-h-screen bg-[#0B1120] text-slate-100 flex flex-col font-sans selection:bg-teal-500/30 selection:text-teal-200`}>
      {/* Toast Notification */}
      {toast && (
        <div className="fixed top-5 right-5 z-50 bg-[#111C2E] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-teal-500/40 animate-fade-in">
          <Sparkles className="w-4 h-4 text-teal-400" />
          <span className="font-semibold text-xs text-slate-200">{toast}</span>
        </div>
      )}

      {/* Top Header */}
      <Header
        status={status}
        onReset={handleResetWorkspace}
      />

      {/* KPI Stats Bar */}
      <StatsBar
        filesCount={files.length}
        metrics={metrics}
        report={report}
        clustersCount={Object.keys(clusters).length || (metrics ? metrics.records_linked : 0)}
      />

      {/* Navigation Tabs */}
      <Navigation
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        filesCount={files.length}
        hasOutput={hasOutput}
      />

      {/* Active Tab View */}
      <main className="raksha-main flex-1 max-w-7xl w-full mx-auto p-6 md:p-8">
        {activeTab === 'files' && (
          <IngestTab
            files={files}
            onLoadPreset={handleLoadPreset}
            onFileUpload={handleFileUpload}
            uploadProgress={uploadProgress}
            onDeleteFile={handleDeleteFile}
            onClearQueue={handleResetWorkspace}
            onRun={handleRunPipeline}
            running={running}
          />
        )}

        {activeTab === 'pipeline' && (
          <PipelineTab
            filesCount={files.length}
            metrics={metrics}
            running={running}
            onRun={handleRunPipeline}
          />
        )}

        {activeTab === 'diff' && (
          <DiffTab
            files={files}
            selectedFile={selectedDiffFile}
            onSelectFile={setSelectedDiffFile}
            diffData={diffData}
          />
        )}

        {activeTab === 'linkage' && (
          <LinkageTab
            clusters={clusters}
          />
        )}

        {activeTab === 'clinical' && (
          <ClinicalTab clinicalEntities={clinicalEntities} />
        )}

        {activeTab === 'quarantine' && (
          <QuarantineTab
            report={report}
          />
        )}

        {activeTab === 'report' && (
          <ReportTab
            report={report}
          />
        )}
      </main>
    </div>
  );
}
