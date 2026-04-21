import React, { useState, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BookOpen,
  Upload,
  FileText,
  File,
  CheckCircle,
  XCircle,
  Loader2,
  Tag,
  Clock,
  HardDrive,
} from 'lucide-react';
import apiClient from '../shared/api-client';
import { useApiQuery } from '../shared/hooks';

const fadeUp = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' } },
};

const ACCEPTED_EXTS = ['pdf', 'docx', 'txt', 'md', 'csv'];

function getFileIcon(filename) {
  const ext = (filename || '').split('.').pop()?.toLowerCase();
  if (ext === 'pdf') return <FileText size={16} className="text-[#ef4444]" />;
  if (ext === 'docx') return <FileText size={16} className="text-[#3b82f6]" />;
  if (ext === 'csv') return <HardDrive size={16} className="text-[#22c55e]" />;
  return <File size={16} className="text-[#a3a3a3]" />;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(ts) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return ts; }
}

export default function KnowledgeBase() {
  const [uploads, setUploads] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [customTags, setCustomTags] = useState('');
  const fileInputRef = useRef(null);

  // Fetch existing knowledge base documents
  const { data: kbMemories, loading: kbLoading, refetch: refetchKb } = useApiQuery(async () => {
    try {
      const result = await apiClient.quickSearch('knowledge-base document-summary');
      return (result?.results || result?.memories || []).filter(m =>
        (m.tags || []).includes('document-summary')
      );
    } catch {
      return [];
    }
  }, []);

  const documents = kbMemories || [];

  const handleFiles = useCallback(async (files) => {
    for (const file of files) {
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (!ACCEPTED_EXTS.includes(ext)) {
        setUploads(prev => [...prev, {
          id: Date.now() + Math.random(),
          filename: file.name,
          status: 'error',
          error: `Unsupported file type: .${ext}`,
        }]);
        continue;
      }

      if (file.size > 10 * 1024 * 1024) {
        setUploads(prev => [...prev, {
          id: Date.now() + Math.random(),
          filename: file.name,
          status: 'error',
          error: 'File too large (max 10MB)',
        }]);
        continue;
      }

      const uploadEntry = {
        id: Date.now() + Math.random(),
        filename: file.name,
        size: file.size,
        status: 'uploading',
        chunks: null,
      };

      setUploads(prev => [...prev, uploadEntry]);

      try {
        const result = await apiClient.uploadDocument(file, {
          tags: customTags || undefined,
        });
        setUploads(prev => prev.map(u =>
          u.id === uploadEntry.id
            ? { ...u, status: 'success', chunks: result.chunks, uploadId: result.upload_id }
            : u
        ));
        // Refresh document list after short delay (ingestion is async)
        setTimeout(() => refetchKb(), 3000);
      } catch (err) {
        setUploads(prev => prev.map(u =>
          u.id === uploadEntry.id
            ? { ...u, status: 'error', error: err.response?.data?.error || err.message }
            : u
        ));
      }
    }
  }, [customTags, refetchKb]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files?.length) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  }, [handleFiles]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragActive(false), []);

  return (
    <div className="min-h-full">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
        <div>
          <h1 className="text-[#0a0a0a] text-2xl font-bold font-['Space_Grotesk'] mb-1">Knowledge Base</h1>
          <p className="text-[#525252] text-sm font-['Space_Grotesk']">
            Upload documents to create structured, searchable memories
          </p>
        </div>
        <div className="flex items-center gap-2 text-[#a3a3a3] text-xs font-mono">
          <BookOpen size={14} />
          {documents.length} document{documents.length !== 1 ? 's' : ''}
        </div>
      </motion.div>

      {/* Upload Zone */}
      <motion.div variants={fadeUp} initial="hidden" animate="visible" className="mb-8">
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={`relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
            dragActive
              ? 'border-[#117dff] bg-[#117dff]/5'
              : 'border-[#e3e0db] bg-white hover:border-[#117dff]/40 hover:bg-[#faf9f4]'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.csv"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) handleFiles(Array.from(e.target.files));
              e.target.value = '';
            }}
          />
          <Upload size={32} className={`mx-auto mb-3 ${dragActive ? 'text-[#117dff]' : 'text-[#d4d0ca]'}`} />
          <p className="text-[#0a0a0a] text-sm font-semibold font-['Space_Grotesk'] mb-1">
            Drop files here or click to upload
          </p>
          <p className="text-[#a3a3a3] text-xs font-['Space_Grotesk']">
            PDF, DOCX, TXT, MD, CSV — max 10MB per file
          </p>
          <p className="text-[#a3a3a3] text-[10px] font-mono mt-2">
            Files are chunked into semantic sections and stored as searchable memories
          </p>
        </div>

        {/* Optional tags input */}
        <div className="flex items-center gap-2 mt-3">
          <Tag size={12} className="text-[#a3a3a3]" />
          <input
            type="text"
            value={customTags}
            onChange={(e) => setCustomTags(e.target.value)}
            placeholder="Optional tags (comma-separated): project-docs, research, notes..."
            className="flex-1 text-xs font-mono px-3 py-2 rounded-lg border border-[#e3e0db] bg-white text-[#0a0a0a] placeholder:text-[#d4d0ca] focus:outline-none focus:border-[#117dff]"
          />
        </div>
      </motion.div>

      {/* Upload Progress */}
      <AnimatePresence>
        {uploads.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-8 space-y-2"
          >
            {uploads.map((u) => (
              <div
                key={u.id}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-mono ${
                  u.status === 'success' ? 'bg-[#f0fdf4] border border-[#bbf7d0]' :
                  u.status === 'error' ? 'bg-[#fef2f2] border border-[#fecaca]' :
                  'bg-white border border-[#e3e0db]'
                }`}
              >
                {u.status === 'uploading' && <Loader2 size={14} className="text-[#117dff] animate-spin" />}
                {u.status === 'success' && <CheckCircle size={14} className="text-[#16a34a]" />}
                {u.status === 'error' && <XCircle size={14} className="text-[#dc2626]" />}
                <span className="flex-1 text-[#0a0a0a] truncate">{u.filename}</span>
                {u.size && <span className="text-[#a3a3a3]">{formatBytes(u.size)}</span>}
                {u.chunks && <span className="text-[#16a34a]">{u.chunks} chunks</span>}
                {u.error && <span className="text-[#dc2626]">{u.error}</span>}
                {u.status === 'uploading' && <span className="text-[#117dff]">Processing...</span>}
              </div>
            ))}
            {uploads.some(u => u.status !== 'uploading') && (
              <button
                onClick={() => setUploads([])}
                className="text-[#a3a3a3] text-[10px] font-mono hover:text-[#525252] transition-colors"
              >
                Clear upload history
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Existing Documents */}
      <motion.div variants={fadeUp} initial="hidden" animate="visible" className="bg-white border border-[#e3e0db] rounded-xl p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex items-center gap-2 mb-5">
          <FileText size={16} className="text-[#525252]" />
          <h3 className="text-[#0a0a0a] text-lg font-bold font-['Space_Grotesk']">Documents</h3>
        </div>

        {kbLoading ? (
          <div className="flex items-center justify-center py-10">
            <div className="w-5 h-5 border-2 border-[#117dff] border-t-transparent rounded-full animate-spin" />
          </div>
        ) : documents.length > 0 ? (
          <div className="space-y-3">
            {documents.map((doc) => {
              const meta = doc.metadata || {};
              const srcMeta = doc.source_metadata || {};
              return (
                <div key={doc.id} className="flex items-center gap-4 px-4 py-3 rounded-xl border border-[#eae7e1] hover:bg-[#faf9f4] transition-colors">
                  {getFileIcon(srcMeta.filename || meta.document_title)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[#0a0a0a] text-sm font-semibold font-['Space_Grotesk'] truncate">
                      {meta.document_title || doc.title || 'Untitled'}
                    </p>
                    <div className="flex items-center gap-3 mt-0.5">
                      {meta.total_chunks && (
                        <span className="text-[#a3a3a3] text-[10px] font-mono">{meta.total_chunks} chunks</span>
                      )}
                      {meta.pages && (
                        <span className="text-[#a3a3a3] text-[10px] font-mono">{meta.pages} pages</span>
                      )}
                      {meta.total_chars && (
                        <span className="text-[#a3a3a3] text-[10px] font-mono">{formatBytes(meta.total_chars)}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {(doc.tags || []).filter(t => !['knowledge-base', 'document', 'document-summary'].includes(t)).slice(0, 3).map(tag => (
                      <span key={tag} className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#f3f1ec] text-[#525252] border border-[#e3e0db]">
                        {tag}
                      </span>
                    ))}
                  </div>
                  <span className="text-[#a3a3a3] text-[10px] font-mono shrink-0 flex items-center gap-1">
                    <Clock size={10} />
                    {formatDate(doc.created_at)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-10">
            <BookOpen size={28} className="text-[#d4d0ca] mx-auto mb-3" />
            <p className="text-[#525252] text-sm font-['Space_Grotesk'] mb-1">No documents uploaded yet</p>
            <p className="text-[#a3a3a3] text-xs font-['Space_Grotesk']">
              Upload PDFs, documents, or text files to build your knowledge base
            </p>
          </div>
        )}
      </motion.div>
    </div>
  );
}
