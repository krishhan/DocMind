"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { useParams, useRouter } from "next/navigation";
import { 
  ArrowLeft, Send, MessageSquare, Loader2, BookOpen, AlertCircle, 
  ChevronDown, ChevronUp, Bot, User, RefreshCw, FileText,
  Pencil, Trash2, Check, X, Copy
} from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  source_chunks?: { page_number: number; text: string; document_name?: string }[];
  created_at: string;
}

interface Conversation {
  id: number;
  title: string;
  created_at: string;
}

interface DocumentDetail {
  id: number;
  filename: string;
  status: string;
  upload_date: string;
  file: string;
  error_message?: string;
}

// Custom Markdown Code Block with Copy Actions
const CodeBlock = ({ language, value }: { language: string; value: string }) => {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="relative border border-zinc-800 rounded-xl overflow-hidden my-4 bg-zinc-950 font-mono text-xs select-text">
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800 text-zinc-400">
        <span className="text-[10px] uppercase font-bold tracking-wider">{language || "code"}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-white transition-colors cursor-pointer text-[10px] font-bold"
        >
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <pre className="p-4 overflow-x-auto text-zinc-100 leading-relaxed font-mono">
        <code>{value}</code>
      </pre>
    </div>
  );
};

export default function DocumentChatPage() {
  const { user, loading: authLoading, apiFetch, backendUrl } = useAuth();
  const router = useRouter();
  const params = useParams();
  const docId = params.id as string;

  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvoId, setActiveConvoId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingDoc, setLoadingDoc] = useState(true);
  
  // States for multi-document selection checklist
  const [allDocs, setAllDocs] = useState<DocumentDetail[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([parseInt(docId)]);

  const [inputText, setInputText] = useState("");
  const [editingConvoId, setEditingConvoId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [showPDF, setShowPDF] = useState(true);
  const [pdfPage, setPdfPage] = useState<number>(1);
  const [asking, setAsking] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});
  const [copiedMsgId, setCopiedMsgId] = useState<number | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Authenticate user
  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, router]);

  // Fetch document details
  const fetchDocDetails = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/documents/${docId}/`);
      if (res.ok) {
        const data = await res.json();
        setDocument(data);
      } else {
        router.push("/dashboard");
      }
    } catch (err) {
      console.error("Failed to fetch document", err);
    } finally {
      setLoadingDoc(false);
    }
  }, [docId, apiFetch, router]);

  // Fetch all ready documents for multi-document select
  const fetchAllDocuments = useCallback(async () => {
    try {
      const res = await apiFetch("/api/documents/");
      if (res.ok) {
        const data = await res.json();
        const docList = Array.isArray(data) ? data : (data.results || []);
        setAllDocs(docList.filter((d: any) => d.status === "ready"));
      }
    } catch (err) {
      console.error("Failed to fetch library documents", err);
    }
  }, [apiFetch]);

  // Fetch conversations list
  const fetchConversations = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/documents/${docId}/conversations/`);
      if (res.ok) {
        const data = await res.json();
        setConversations(data);
      }
    } catch (err) {
      console.error("Failed to fetch conversations", err);
    }
  }, [docId, apiFetch]);

  // Fetch specific conversation details (messages)
  const fetchConversationMessages = useCallback(async (convoId: number) => {
    try {
      const res = await apiFetch(`/api/chat/conversations/${convoId}/`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages || []);
      }
    } catch (err) {
      console.error("Failed to fetch messages", err);
    }
  }, [apiFetch]);

  // Init loads
  useEffect(() => {
    if (user && docId) {
      fetchDocDetails();
      fetchConversations();
      fetchAllDocuments();
    }
  }, [user, docId, fetchDocDetails, fetchConversations, fetchAllDocuments]);

  // Scroll to bottom on messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, asking]);

  const selectConversation = (convoId: number) => {
    setActiveConvoId(convoId);
    setErrorMsg("");
    fetchConversationMessages(convoId);
  };

  const startNewConversation = () => {
    setActiveConvoId(null);
    setMessages([]);
    setErrorMsg("");
  };

  const getFileUrl = () => {
    if (!document?.file) return "";
    
    let relativePath = document.file;
    if (document.file.startsWith("http")) {
      try {
        relativePath = new URL(document.file).pathname;
      } catch (e) {
        const mediaIndex = document.file.indexOf("/media/");
        if (mediaIndex !== -1) {
          relativePath = document.file.substring(mediaIndex);
        }
      }
    }
    
    if (backendUrl) {
      return `${backendUrl}${relativePath}`;
    }
    
    if (typeof window !== "undefined") {
      const hostname = window.location.hostname;
      const port = window.location.port;
      if (port === "3000") {
        return `http://${hostname}:8000${relativePath}`;
      }
      const portSuffix = port ? `:${port}` : "";
      return `http://${hostname}${portSuffix}${relativePath}`;
    }
    return relativePath;
  };

  const handleDeleteConversation = async (e: React.MouseEvent, convoId: number) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this conversation?")) return;

    try {
      const res = await apiFetch(`/api/chat/conversations/${convoId}/`, {
        method: "DELETE",
      });
      if (res.ok) {
        setConversations(prev => prev.filter(c => c.id !== convoId));
        if (activeConvoId === convoId) {
          startNewConversation();
        }
      } else {
        const data = await res.json().catch(() => ({}));
        setErrorMsg(data.error || "Failed to delete conversation");
      }
    } catch (err) {
      console.error("Delete conversation failed", err);
      setErrorMsg("Network error. Failed to delete conversation.");
    }
  };

  const handleStartRename = (e: React.MouseEvent, convo: Conversation) => {
    e.stopPropagation();
    setEditingConvoId(convo.id);
    setEditTitle(convo.title);
  };

  const handleCancelRename = (e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setEditingConvoId(null);
    setEditTitle("");
  };

  const handleRenameConversation = async (e: React.FormEvent | React.MouseEvent, convoId: number) => {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    if (!editTitle.trim()) return;

    try {
      const res = await apiFetch(`/api/chat/conversations/${convoId}/`, {
        method: "PATCH",
        body: JSON.stringify({ title: editTitle.trim() }),
      });
      if (res.ok) {
        setConversations(prev => prev.map(c => c.id === convoId ? { ...c, title: editTitle.trim() } : c));
        setEditingConvoId(null);
        setEditTitle("");
      } else {
        const data = await res.json().catch(() => ({}));
        setErrorMsg(data.error || "Failed to rename conversation");
      }
    } catch (err) {
      console.error("Rename conversation failed", err);
      setErrorMsg("Network error. Failed to rename conversation.");
    }
  };

  const handleCopyMessage = (text: string, msgId: number) => {
    navigator.clipboard.writeText(text);
    setCopiedMsgId(msgId);
    setTimeout(() => setCopiedMsgId(null), 2000);
  };

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || asking) return;

    const userQuestion = inputText.trim();
    setInputText("");
    setErrorMsg("");
    setAsking(true);

    // Optimistically append user message to feed
    const tempUserMsg: Message = {
      id: Date.now(),
      role: "user",
      content: userQuestion,
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, tempUserMsg]);

    try {
      const res = await apiFetch(`/api/documents/${docId}/ask/`, {
        method: "POST",
        body: JSON.stringify({
          question: userQuestion,
          conversation_id: activeConvoId,
          document_ids: selectedDocIds
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        setErrorMsg(errData.error || "Failed to get response");
        setAsking(false);
        return;
      }

      // Read JSON-encoded SSE stream
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error("No reader available");

      let assistantAnswer = "";
      let retrievedSources: any[] = [];
      let tempAssistantMsgId = Date.now() + 1;

      // Optimistically append empty assistant bubble
      setMessages(prev => [
        ...prev,
        {
          id: tempAssistantMsgId,
          role: "assistant",
          content: "",
          created_at: new Date().toISOString()
        }
      ]);

      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        const parts = buffer.split("\n\n");
        // Keep the last partial event in the buffer
        buffer = parts.pop() || "";

        for (const part of parts) {
          if (!part.trim()) continue;
          
          const lines = part.split("\n");
          let eventName = "";
          let dataText = "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventName = line.substring(7).trim();
            } else if (line.startsWith("data: ")) {
              dataText = line.substring(6);
            }
          }

          if (eventName === "sources") {
            const metadata = JSON.parse(dataText);
            retrievedSources = metadata.sources || [];
            setActiveConvoId(metadata.conversation_id);
            setMessages(prev => 
              prev.map(m => m.id === tempAssistantMsgId ? { ...m, source_chunks: retrievedSources } : m)
            );
          } else if (eventName === "message") {
            try {
              const payload = JSON.parse(dataText);
              assistantAnswer += payload.text;
            } catch (e) {
              // Backward compatibility fallback for raw text streaming
              assistantAnswer += dataText;
            }
            setMessages(prev => 
              prev.map(m => m.id === tempAssistantMsgId ? { ...m, content: assistantAnswer } : m)
            );
          } else if (eventName === "done") {
            // Streaming finalized
            console.log("Response stream finalized.");
          } else if (eventName === "error") {
            try {
              const payload = JSON.parse(dataText);
              setErrorMsg(payload.error || "Failed to stream answer");
            } catch (e) {
              setErrorMsg(dataText);
            }
            // Remove optimistic assistant bubble on error
            setMessages(prev => prev.filter(m => m.id !== tempAssistantMsgId));
          }
        }
      }

      // Refresh conversations list to update title
      fetchConversations();

    } catch (err) {
      setErrorMsg("Network error. Failed to read response stream.");
    } finally {
      setAsking(false);
    }
  };

  const toggleSource = (msgId: number) => {
    setExpandedSources(prev => ({
      ...prev,
      [msgId]: !prev[msgId]
    }));
  };

  // Premium Page Skeleton Loader
  if (authLoading || !user) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-zinc-950">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (loadingDoc) {
    return (
      <div className="h-screen w-screen bg-zinc-950 text-zinc-100 flex overflow-hidden">
        {/* Sidebar Skeleton */}
        <aside className="w-80 shrink-0 bg-zinc-900 border-r border-zinc-800 flex flex-col justify-between hidden md:flex p-4 space-y-6">
          <div className="space-y-4 animate-pulse">
            <div className="h-8 bg-zinc-800 rounded-xl w-3/4" />
            <div className="h-16 bg-zinc-800 rounded-xl w-full" />
            <div className="h-10 bg-zinc-800 rounded-xl w-full" />
            <div className="space-y-2 pt-4">
              <div className="h-4 bg-zinc-800 rounded w-1/2" />
              <div className="h-10 bg-zinc-800 rounded-xl w-full" />
              <div className="h-10 bg-zinc-800 rounded-xl w-full" />
              <div className="h-10 bg-zinc-800 rounded-xl w-full" />
            </div>
          </div>
          <div className="h-6 bg-zinc-800 rounded w-1/3 self-center" />
        </aside>

        {/* Main Content Skeleton */}
        <section className="flex-1 flex flex-col min-w-0 bg-zinc-950 p-6 space-y-6 animate-pulse">
          <div className="h-14 bg-zinc-900 border border-zinc-800 rounded-2xl w-full" />
          <div className="flex-1 flex gap-6">
            <div className="hidden lg:block w-1/2 bg-zinc-900 border border-zinc-800 rounded-3xl" />
            <div className="flex-1 bg-zinc-900/40 border border-zinc-800/50 rounded-3xl p-6 flex flex-col justify-between">
              <div className="space-y-4">
                <div className="flex gap-4">
                  <div className="h-8 w-8 bg-zinc-800 rounded-lg shrink-0" />
                  <div className="space-y-2 flex-1">
                    <div className="h-4 bg-zinc-800 rounded w-1/3" />
                    <div className="h-16 bg-zinc-800 rounded-2xl w-3/4" />
                  </div>
                </div>
                <div className="flex gap-4 justify-end">
                  <div className="space-y-2 flex-1 items-end flex flex-col">
                    <div className="h-4 bg-zinc-800 rounded w-1/4" />
                    <div className="h-12 bg-zinc-800 rounded-2xl w-2/3" />
                  </div>
                  <div className="h-8 w-8 bg-zinc-800 rounded-lg shrink-0" />
                </div>
              </div>
              <div className="h-12 bg-zinc-950 border border-zinc-800 rounded-xl w-full" />
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="h-screen w-screen bg-zinc-950 text-zinc-100 flex overflow-hidden">
      {/* SIDEBAR */}
      <aside className="w-80 shrink-0 bg-zinc-900 border-r border-zinc-800 flex flex-col justify-between hidden md:flex">
        <div className="flex flex-col flex-1 min-h-0">
          {/* Header */}
          <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
            <button
              onClick={() => router.push("/dashboard")}
              className="flex items-center gap-2 text-zinc-400 hover:text-white text-sm font-semibold transition-colors duration-200 cursor-pointer"
            >
              <ArrowLeft className="h-4 w-4" />
              <span>Back to Library</span>
            </button>
          </div>

          {/* Doc metadata */}
          <div className="p-4 bg-zinc-950/30 border-b border-zinc-800">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 shrink-0 flex items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
                <FileText className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Document</h2>
                <p className="text-sm font-bold text-white line-clamp-1 mt-0.5" title={document?.filename}>
                  {document?.filename}
                </p>
              </div>
            </div>
          </div>

          {/* Multi-Document Selector checklist */}
          <div className="p-4 border-b border-zinc-800/80 max-h-60 overflow-y-auto flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Select Documents</h3>
              <span className="text-[10px] bg-indigo-500/20 text-indigo-400 font-bold px-2 py-0.5 rounded-full">
                {selectedDocIds.length} active
              </span>
            </div>
            
            <div className="space-y-1.5 mt-2 select-none">
              {allDocs.map((docItem) => (
                <label 
                  key={docItem.id} 
                  className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer hover:bg-zinc-800/40 transition-colors text-xs border ${
                    selectedDocIds.includes(docItem.id)
                      ? "border-indigo-500/20 bg-indigo-500/5 text-white" 
                      : "border-transparent text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedDocIds.includes(docItem.id)}
                    onChange={() => {
                      setSelectedDocIds(prev => {
                        if (docItem.id === parseInt(docId)) {
                          if (prev.length === 1) return prev;
                        }
                        if (prev.includes(docItem.id)) {
                          return prev.filter(id => id !== docItem.id);
                        } else {
                          return [...prev, docItem.id];
                        }
                      });
                    }}
                    className="mt-0.5 rounded border-zinc-700 bg-zinc-800 text-indigo-600 focus:ring-indigo-500 focus:ring-offset-zinc-900"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold truncate leading-tight" title={docItem.filename}>
                      {docItem.filename}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* New Chat Button */}
          <div className="p-4">
            <button
              onClick={startNewConversation}
              className={`w-full py-2.5 px-4 rounded-xl border font-semibold text-sm transition-all duration-200 flex items-center justify-center gap-2 cursor-pointer ${
                activeConvoId === null
                  ? "bg-indigo-600 border-transparent text-white shadow-lg shadow-indigo-500/15 cursor-default"
                  : "bg-zinc-800/40 border-zinc-800 hover:border-zinc-700 text-zinc-300 hover:bg-zinc-800/80"
              }`}
            >
              <MessageSquare className="h-4 w-4" />
              <span>New Conversation</span>
            </button>
          </div>

          {/* History conversations list */}
          <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
            <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider px-2 mb-2">Past Chats</h3>
            {conversations.length === 0 ? (
              <p className="text-xs text-zinc-600 px-2 italic">No past conversations</p>
            ) : (
              conversations.map((convo) => {
                const isEditing = editingConvoId === convo.id;
                return (
                  <div
                    key={convo.id}
                    className={`w-full p-2.5 rounded-xl border text-sm font-medium transition-all flex items-center justify-between gap-2 group ${
                      activeConvoId === convo.id
                        ? "bg-zinc-800/80 border-indigo-500/30 text-white"
                        : "bg-zinc-900 border-zinc-800/50 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/20 hover:border-zinc-800"
                    }`}
                  >
                    {isEditing ? (
                      <form
                        onSubmit={(e) => handleRenameConversation(e, convo.id)}
                        className="flex items-center gap-2 w-full"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="text"
                          required
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="flex-1 bg-zinc-950 border border-zinc-800 focus:border-indigo-500 rounded px-2 py-1 text-xs text-white focus:outline-none"
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === "Escape") handleCancelRename();
                          }}
                        />
                        <button
                          type="submit"
                          className="p-1 text-emerald-400 hover:bg-zinc-800 rounded transition-colors"
                          title="Save"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCancelRename()}
                          className="p-1 text-red-400 hover:bg-zinc-800 rounded transition-colors"
                          title="Cancel"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </form>
                    ) : (
                      <div
                        onClick={() => selectConversation(convo.id)}
                        className="flex items-center gap-2.5 flex-1 min-w-0 cursor-pointer h-full py-0.5"
                      >
                        <MessageSquare className="h-4 w-4 shrink-0 text-indigo-400/70" />
                        <span className="truncate flex-1">{convo.title}</span>
                      </div>
                    )}
                    
                    {!isEditing && (
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150 shrink-0">
                        <button
                          onClick={(e) => handleStartRename(e, convo)}
                          className="p-1 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded transition-all cursor-pointer"
                          title="Rename conversation"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={(e) => handleDeleteConversation(e, convo.id)}
                          className="p-1 text-zinc-400 hover:text-red-400 hover:bg-zinc-800 rounded transition-all cursor-pointer"
                          title="Delete conversation"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="p-4 border-t border-zinc-800 text-center">
          <span className="text-xs text-zinc-600">DocMind RAG Engine v2.0</span>
        </div>
      </aside>

      {/* PDF VIEWER PANEL */}
      {showPDF && document?.file && (
        <div className="hidden lg:flex w-[48%] h-full border-r border-zinc-800 bg-zinc-950 flex-col relative shrink-0">
          <iframe
            src={`${getFileUrl()}#page=${pdfPage}`}
            className="w-full h-full border-none"
            title="PDF Document"
            key={`${document.id}-${pdfPage}`}
          />
        </div>
      )}

      {/* CHAT INTERFACE */}
      <section className="flex-1 flex flex-col min-w-0 bg-zinc-950 relative">
        {/* Background blobs */}
        <div className="absolute top-[10%] left-[20%] w-[50%] h-[50%] rounded-full bg-indigo-500/5 blur-[120px] pointer-events-none" />

        {/* Unified Chat Header (Desktop and Mobile) */}
        <header className="border-b border-zinc-800/80 bg-zinc-900/40 backdrop-blur-md px-6 py-4 flex items-center justify-between shrink-0 z-10">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/dashboard")}
              className="text-zinc-400 hover:text-white md:hidden"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-indigo-400 hidden md:block" />
              <span className="font-bold text-white text-sm line-clamp-1 max-w-[200px] sm:max-w-md">
                {document?.filename} {selectedDocIds.length > 1 && `(+${selectedDocIds.length - 1} docs)`}
              </span>
            </div>
          </div>
          
          {document?.file && (
            <button
              onClick={() => setShowPDF(!showPDF)}
              className="flex items-center gap-2 bg-zinc-850 hover:bg-zinc-800 text-zinc-300 hover:text-white text-xs font-semibold px-3 py-1.5 rounded-xl border border-zinc-700/50 transition-all duration-200 cursor-pointer"
            >
              <BookOpen className="h-3.5 w-3.5 text-indigo-400" />
              <span>{showPDF ? "Hide Document" : "Show Document"}</span>
            </button>
          )}
        </header>

        {/* MESSAGES FEED */}
        <div className="flex-1 overflow-y-auto p-6 md:p-8 space-y-6">
          {messages.length === 0 && !asking ? (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto">
              <div className="h-16 w-16 items-center justify-center flex rounded-2xl bg-indigo-500/10 text-indigo-400 mb-6 border border-indigo-500/10 shadow-lg">
                <BookOpen className="h-8 w-8" />
              </div>
              <h2 className="text-2xl font-extrabold text-white tracking-tight">Ask your Library</h2>
              <p className="text-zinc-400 text-sm mt-2 leading-relaxed font-medium">
                Enter a question below. DocMind will retrieve context across all {selectedDocIds.length} selected documents and answer with AI.
              </p>
              
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full mt-8">
                <button 
                  onClick={() => setInputText("What is the main topic or summary of the active documents?")}
                  className="p-3 bg-zinc-900/40 border border-zinc-800 hover:border-zinc-700 rounded-xl text-xs text-left text-zinc-300 hover:bg-zinc-800/30 transition-all font-semibold cursor-pointer"
                >
                  "Summarize active documents"
                </button>
                <button 
                  onClick={() => setInputText("Are there any key dates or deadlines mentioned across the documents?")}
                  className="p-3 bg-zinc-900/40 border border-zinc-800 hover:border-zinc-700 rounded-xl text-xs text-left text-zinc-300 hover:bg-zinc-800/30 transition-all font-semibold cursor-pointer"
                >
                  "Identify key dates/deadlines"
                </button>
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((msg) => {
                const isUser = msg.role === "user";
                return (
                  <div key={msg.id} className={`flex gap-4 ${isUser ? "justify-end" : "justify-start"}`}>
                    {/* Bot Icon */}
                    {!isUser && (
                      <div className="h-8 w-8 shrink-0 rounded-lg bg-indigo-600/10 text-indigo-400 flex items-center justify-center border border-indigo-500/15">
                        <Bot className="h-4 w-4" />
                      </div>
                    )}

                    <div className="max-w-[85%] space-y-2">
                      <div
                        className={`rounded-2xl px-4 py-3 text-sm leading-relaxed border shadow-sm ${
                          isUser
                            ? "bg-indigo-600 border-transparent text-white font-medium rounded-tr-none"
                            : "bg-zinc-900/70 border-zinc-800/60 text-zinc-100 rounded-tl-none backdrop-blur-sm"
                        }`}
                      >
                        {isUser ? (
                          <p className="whitespace-pre-wrap">{msg.content}</p>
                        ) : (
                          <div className="markdown-content select-text">
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm, remarkMath]}
                              rehypePlugins={[rehypeKatex]}
                              components={{
                                code({ node, inline, className, children, ...props }: any) {
                                  const match = /language-(\w+)/.exec(className || '');
                                  const codeString = String(children).replace(/\n$/, '');
                                  return !inline && match ? (
                                    <CodeBlock language={match[1]} value={codeString} />
                                  ) : (
                                    <code className="bg-zinc-800 text-indigo-300 px-1.5 py-0.5 rounded font-mono text-xs font-semibold" {...props}>
                                      {children}
                                    </code>
                                  );
                                },
                                table({ children }) {
                                  return (
                                    <div className="overflow-x-auto my-4 rounded-xl border border-zinc-800 shadow-sm">
                                      <table className="min-w-full divide-y divide-zinc-800 text-sm text-left">{children}</table>
                                    </div>
                                  );
                                },
                                thead({ children }) {
                                  return <thead className="bg-zinc-900/60 font-bold text-zinc-200">{children}</thead>;
                                },
                                th({ children }) {
                                  return <th className="px-4 py-2.5 text-left font-extrabold text-zinc-300 border-b border-zinc-800 uppercase text-[10px] tracking-wider">{children}</th>;
                                },
                                tr({ children }) {
                                  return <tr className="hover:bg-zinc-900/20 transition-colors odd:bg-zinc-900/5 even:bg-transparent">{children}</tr>;
                                },
                                td({ children }) {
                                  return <td className="px-4 py-2.5 text-zinc-400 border-b border-zinc-800/40 text-xs leading-normal">{children}</td>;
                                }
                              }}
                            >
                              {msg.content}
                            </ReactMarkdown>
                          </div>
                        )}
                      </div>

                      {/* Source Chunks Collapsible Section & Message Actions */}
                      {!isUser && (
                        <div className="pl-2 flex flex-col gap-2 items-start">
                          {/* Message Copy and Source Actions */}
                          <div className="flex items-center gap-3 text-[10px] font-bold text-zinc-500 select-none">
                            {msg.source_chunks && msg.source_chunks.length > 0 && (
                              <button
                                onClick={() => toggleSource(msg.id)}
                                className="flex items-center gap-1 text-indigo-400 hover:text-indigo-300 transition-colors cursor-pointer"
                              >
                                <BookOpen className="h-3 w-3" />
                                <span>Sources ({msg.source_chunks.length})</span>
                                {expandedSources[msg.id] ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                              </button>
                            )}
                            <button
                              onClick={() => handleCopyMessage(msg.content, msg.id)}
                              className="flex items-center gap-1 hover:text-zinc-300 transition-colors cursor-pointer"
                            >
                              {copiedMsgId === msg.id ? (
                                <>
                                  <Check className="h-3 w-3 text-emerald-400" />
                                  <span className="text-emerald-400">Copied!</span>
                                </>
                              ) : (
                                <>
                                  <Copy className="h-3 w-3" />
                                  <span>Copy Response</span>
                                </>
                              )}
                            </button>
                          </div>

                          {/* Expanded Sources Section (Grouped by Document) */}
                          {expandedSources[msg.id] && msg.source_chunks && (
                            <div className="mt-1 space-y-2 border-l border-zinc-800 pl-3 w-full">
                              {msg.source_chunks.map((source, sIdx) => (
                                <div 
                                  key={sIdx} 
                                  onClick={() => {
                                    setShowPDF(true);
                                    setPdfPage(source.page_number);
                                  }}
                                  className="bg-zinc-950/40 border border-zinc-800/60 p-2.5 rounded-xl text-xs space-y-1 cursor-pointer hover:border-indigo-500/40 transition-colors group/source text-left w-full"
                                >
                                  <div className="font-bold text-zinc-500 flex items-center gap-1.5 justify-between">
                                    <div className="flex items-center gap-1.5 min-w-0">
                                      <span className="h-1.5 w-1.5 bg-indigo-500 rounded-full shrink-0" />
                                      <span className="truncate text-zinc-400" title={source.document_name}>
                                        {source.document_name || "Document"}
                                      </span>
                                      <span className="text-[10px] bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-500 shrink-0">
                                        Page {source.page_number}
                                      </span>
                                    </div>
                                    <span className="text-[10px] text-indigo-400 font-semibold group-hover/source:underline shrink-0">View PDF</span>
                                  </div>
                                  <p className="text-zinc-400 leading-relaxed italic">"...{source.text.trim()}..."</p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* User Icon */}
                    {isUser && (
                      <div className="h-8 w-8 shrink-0 rounded-lg bg-zinc-800 text-zinc-400 flex items-center justify-center border border-zinc-700">
                        <User className="h-4 w-4" />
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Bot thinking indicator (Skeleton) */}
              {asking && (
                <div className="flex gap-4 justify-start animate-pulse">
                  <div className="h-8 w-8 shrink-0 rounded-lg bg-indigo-600/10 text-indigo-400 flex items-center justify-center border border-indigo-500/15">
                    <Bot className="h-4 w-4" />
                  </div>
                  <div className="bg-zinc-900/50 border border-zinc-800/60 rounded-2xl rounded-tl-none px-5 py-4 text-sm text-zinc-400 flex-1 max-w-md space-y-2">
                    <div className="h-3.5 bg-zinc-800 rounded w-1/4" />
                    <div className="h-3.5 bg-zinc-800 rounded w-3/4 animate-pulse" />
                    <div className="h-3.5 bg-zinc-800 rounded w-1/2" />
                  </div>
                </div>
              )}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* INPUT FORM PANEL */}
        <div className="p-6 border-t border-zinc-800/60 bg-zinc-900/20 backdrop-blur-md shrink-0">
          <div className="max-w-3xl mx-auto">
            {errorMsg && (
              <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-500/10 border border-red-500/20 p-4 text-sm text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            <form onSubmit={handleAsk} className="flex gap-3 relative">
              <input
                type="text"
                required
                disabled={asking}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                className="flex-1 bg-zinc-950 border border-zinc-800/80 hover:border-zinc-700 focus:border-indigo-500 rounded-xl px-4 py-3.5 pr-14 text-sm text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 transition-all disabled:opacity-50 font-medium"
                placeholder="Ask DocMind a question about the active documents..."
              />
              <button
                type="submit"
                disabled={asking || !inputText.trim()}
                className="absolute right-2 top-2 h-10 w-10 shrink-0 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg flex items-center justify-center shadow-lg transition-colors disabled:opacity-40 disabled:hover:bg-indigo-600 cursor-pointer"
              >
                <Send className="h-4 w-4" />
              </button>
            </form>
            
            <p className="text-[10px] text-zinc-600 mt-2.5 text-center font-semibold">
              Grounded on selected document context. Daily user rate limit: 20 queries.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
