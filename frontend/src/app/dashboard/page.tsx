"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import { 
  FileText, Upload, Trash2, MessageSquare, AlertCircle, CheckCircle2, 
  Loader2, LogOut, Clock, RefreshCw, User
} from "lucide-react";

interface Document {
  id: number;
  filename: string;
  upload_date: string;
  status: "processing" | "ready" | "failed";
  file: string;
  error_message?: string;
  processing_progress: number;
}

export default function DashboardPage() {
  const { user, loading: authLoading, logout, apiFetch, backendUrl } = useAuth();
  const router = useRouter();

  const [documents, setDocuments] = useState<Document[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, router]);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await apiFetch("/api/documents/");
      if (res.ok) {
        const data = await res.json();
        // Handle paginated endpoint results key or raw array
        const docList = Array.isArray(data) ? data : (data.results || []);
        setDocuments(docList);
      }
    } catch (err) {
      console.error("Failed to fetch documents", err);
    } finally {
      setLoadingDocs(false);
    }
  }, [apiFetch]);

  // Initial fetch
  useEffect(() => {
    if (user) {
      fetchDocuments();
    }
  }, [user, fetchDocuments]);

  // Smart polling: poll backend status updates if there are any 'processing' documents
  useEffect(() => {
    const hasProcessing = documents.some(doc => doc.status === "processing");
    if (!hasProcessing) return;

    const interval = setInterval(() => {
      fetchDocuments();
    }, 2500);

    return () => clearInterval(interval);
  }, [documents, fetchDocuments]);

  // Upload PDF with real progress feedback using XMLHttpRequest
  const handleFileUpload = async (file: File) => {
    if (!file) return;

    if (file.type !== "application/pdf") {
      setUploadError("Only PDF files are supported.");
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setUploadError("File size exceeds 10MB limit.");
      return;
    }

    setUploading(true);
    setUploadError("");
    setUploadProgress(0);

    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    const access = localStorage.getItem("access_token");
    
    // Resolve upload URL
    const targetUrl = `${backendUrl}/api/documents/`;

    xhr.open("POST", targetUrl, true);
    if (access) {
      xhr.setRequestHeader("Authorization", `Bearer ${access}`);
    }

    // Monitor upload progress (0-95%)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(Math.min(95, percent));
      }
    };

    xhr.onload = () => {
      setUploading(false);
      setUploadProgress(100);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const newDoc = JSON.parse(xhr.responseText);
          setDocuments(prev => [newDoc, ...prev]);
        } catch (e) {
          fetchDocuments();
        }
      } else {
        try {
          const errData = JSON.parse(xhr.responseText);
          setUploadError(errData.error || "Failed to upload file");
        } catch (e) {
          setUploadError("Failed to upload file. Invalid server response.");
        }
      }
    };

    xhr.onerror = () => {
      setUploading(false);
      setUploadProgress(0);
      setUploadError("Network connection error. Failed to upload.");
    };

    xhr.send(formData);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleDelete = async (e: React.MouseEvent, docId: number) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this document? This will remove all associated vectors and chats.")) return;

    try {
      const res = await apiFetch(`/api/documents/${docId}/`, {
        method: "DELETE",
      });

      if (res.ok) {
        setDocuments(prev => prev.filter(doc => doc.id !== docId));
      }
    } catch (err) {
      console.error("Delete failed", err);
    }
  };

  const formatDate = (dateString: string) => {
    const options: Intl.DateTimeFormatOptions = { 
      year: 'numeric', 
      month: 'short', 
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    };
    return new Date(dateString).toLocaleDateString(undefined, options);
  };

  if (authLoading || !user) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-zinc-950">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col relative overflow-hidden">
      {/* Background gradients */}
      <div className="absolute top-0 right-0 w-[40%] h-[40%] rounded-full bg-indigo-500/5 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-[40%] h-[40%] rounded-full bg-purple-500/5 blur-[120px] pointer-events-none" />

      {/* Header bar */}
      <header className="border-b border-zinc-800 bg-zinc-900/40 backdrop-blur-md sticky top-0 z-50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-600 to-purple-600 shadow-md text-white font-bold">
            DM
          </div>
          <span className="text-xl font-bold tracking-tight text-white select-none">DocMind</span>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-zinc-300 text-sm bg-zinc-800/40 px-3 py-1.5 rounded-full border border-zinc-800 select-none">
            <User className="h-4 w-4 text-indigo-400" />
            <span>{user.username}</span>
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-2 text-zinc-400 hover:text-red-400 text-sm font-semibold transition-colors duration-200 cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            <span>Sign Out</span>
          </button>
        </div>
      </header>

      {/* Main container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 md:p-8 space-y-8 z-10">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white bg-clip-text">
              My Documents
            </h1>
            <p className="text-sm text-zinc-400 mt-1 select-none">
              Upload PDF files to index them and start chatting
            </p>
          </div>

          <button 
            onClick={fetchDocuments}
            disabled={loadingDocs}
            className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 hover:bg-zinc-800/80 px-4 py-2 rounded-xl text-sm font-semibold text-zinc-300 transition-all self-start md:self-auto cursor-pointer"
          >
            <RefreshCw className={`h-4 w-4 ${loadingDocs ? "animate-spin text-indigo-500" : ""}`} />
            <span>Sync</span>
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Uploader Column */}
          <div className="space-y-4">
            <h2 className="text-lg font-bold text-zinc-300 select-none">Upload New File</h2>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-2xl p-8 flex flex-col items-center justify-center text-center cursor-pointer transition-all duration-200 min-h-[260px] bg-zinc-900/20 backdrop-blur-sm select-none ${
                dragOver 
                  ? "border-indigo-500 bg-indigo-500/5 shadow-inner" 
                  : "border-zinc-800 hover:border-zinc-700 hover:bg-zinc-900/30"
              }`}
              onClick={() => document.getElementById("file-input")?.click()}
            >
              <input
                id="file-input"
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(e) => {
                  const files = e.target.files;
                  if (files && files.length > 0) handleFileUpload(files[0]);
                }}
              />
              
              {uploading ? (
                <div className="flex flex-col items-center gap-3 w-full max-w-[200px]">
                  <div className="relative flex h-14 w-14 items-center justify-center rounded-full bg-indigo-500/10 text-indigo-400">
                    <Loader2 className="h-7 w-7 animate-spin" />
                  </div>
                  <p className="text-sm font-semibold text-zinc-200">Uploading file...</p>
                  
                  {/* Real-time upload progress bar */}
                  <div className="w-full bg-zinc-800 h-1.5 rounded-full overflow-hidden mt-1.5">
                    <div className="bg-indigo-500 h-full transition-all duration-150" style={{ width: `${uploadProgress}%` }} />
                  </div>
                  <span className="text-[10px] text-zinc-400 font-bold">{uploadProgress}%</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <div className="relative flex h-14 w-14 items-center justify-center rounded-full bg-zinc-800 text-zinc-400">
                    <Upload className="h-7 w-7" />
                  </div>
                  <p className="text-sm font-semibold text-zinc-300">
                    Drag & drop PDF here, or <span className="text-indigo-400 font-bold">browse</span>
                  </p>
                  <p className="text-xs text-zinc-500">Only PDF files up to 10MB supported</p>
                </div>
              )}
            </div>

            {uploadError && (
              <div className="flex items-center gap-2 rounded-xl bg-red-500/10 border border-red-500/20 p-4 text-sm text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{uploadError}</span>
              </div>
            )}
          </div>

          {/* Files List Column */}
          <div className="lg:col-span-2 space-y-4">
            <h2 className="text-lg font-bold text-zinc-300 select-none">Indexed Files ({documents.length})</h2>

            {loadingDocs ? (
              /* Premium Card skeleton loaders */
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="border border-zinc-800 rounded-2xl p-5 bg-zinc-900/20 flex flex-col justify-between min-h-[160px] animate-pulse">
                    <div>
                      <div className="flex items-start justify-between">
                        <div className="h-10 w-10 bg-zinc-800 rounded-lg animate-pulse" />
                        <div className="h-8 w-8 bg-zinc-800 rounded-lg animate-pulse" />
                      </div>
                      <div className="h-4 bg-zinc-800 rounded w-2/3 mt-4 animate-pulse" />
                      <div className="h-3 bg-zinc-850 rounded w-1/3 mt-2 animate-pulse" />
                    </div>
                    <div className="mt-4 pt-4 border-t border-zinc-800/60 flex items-center justify-between">
                      <div className="h-4 bg-zinc-850 rounded w-1/4 animate-pulse" />
                      <div className="h-6 bg-zinc-850 rounded-full w-12 animate-pulse" />
                    </div>
                  </div>
                ))}
              </div>
            ) : documents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 bg-zinc-900/20 border border-zinc-800 border-dashed rounded-2xl text-center px-4 select-none">
                <FileText className="h-10 w-10 text-zinc-600 mb-3" />
                <p className="text-zinc-400 font-semibold">No documents uploaded yet</p>
                <p className="text-zinc-500 text-xs mt-1">Upload a PDF file using the panel to get started.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    onClick={() => {
                      if (doc.status === "ready") {
                        router.push(`/documents/${doc.id}`);
                      }
                    }}
                    className={`border border-zinc-800 rounded-2xl p-5 bg-zinc-900/40 hover:bg-zinc-900/80 transition-all duration-200 flex flex-col justify-between min-h-[160px] group relative select-none ${
                      doc.status === "ready" ? "cursor-pointer hover:border-indigo-500/30" : "cursor-default"
                    }`}
                  >
                    <div>
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-800 text-zinc-300">
                          <FileText className="h-5 w-5" />
                        </div>
                        
                        <div className="flex gap-2">
                          {/* Delete button */}
                          <button
                            onClick={(e) => handleDelete(e, doc.id)}
                            className="text-zinc-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-zinc-800 transition-colors duration-200 shrink-0 cursor-pointer"
                            title="Delete document"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>

                      <h3 className="mt-3 text-sm font-bold text-white line-clamp-1 group-hover:text-indigo-400 transition-colors">
                        {doc.filename}
                      </h3>
                      
                      <div className="flex items-center gap-1.5 text-zinc-500 text-xs mt-1.5">
                        <Clock className="h-3 w-3" />
                        <span>{formatDate(doc.upload_date)}</span>
                      </div>
                    </div>

                    <div className="mt-4 pt-4 border-t border-zinc-800/60 flex items-center justify-between">
                      {/* Status Badges */}
                      {doc.status === "ready" && (
                        <>
                          <div className="flex items-center gap-1 text-emerald-400 text-xs font-semibold">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            <span>Ready to Chat</span>
                          </div>
                          <span className="flex items-center gap-1 text-indigo-400 text-xs font-bold bg-indigo-500/10 border border-indigo-500/10 px-2 py-0.5 rounded-full group-hover:bg-indigo-500 group-hover:text-white transition-colors duration-200">
                            Chat <MessageSquare className="h-3 w-3 ml-0.5" />
                          </span>
                        </>
                      )}
                      
                      {doc.status === "processing" && (
                        /* Premium processing embedding progress bar */
                        <div className="flex flex-col gap-1 w-full">
                          <div className="flex items-center justify-between text-amber-400 text-xs font-semibold">
                            <div className="flex items-center gap-1.5">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              <span>Embedding...</span>
                            </div>
                            <span>{doc.processing_progress || 0}%</span>
                          </div>
                          <div className="w-full bg-zinc-800 h-1 rounded-full overflow-hidden mt-1">
                            <div className="bg-amber-400 h-full transition-all duration-300" style={{ width: `${doc.processing_progress || 0}%` }} />
                          </div>
                        </div>
                      )}

                      {doc.status === "failed" && (
                        <div className="flex flex-col gap-1 w-full">
                          <div className="flex items-center gap-1 text-red-400 text-xs font-semibold" title={doc.error_message}>
                            <AlertCircle className="h-3.5 w-3.5" />
                            <span>Processing Failed</span>
                          </div>
                          {doc.error_message && (
                            <span className="text-[10px] text-zinc-500 line-clamp-1">
                              {doc.error_message}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
