import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { BookCopy, Bot, FileSearch, GitBranch, Loader2, Send, User } from 'lucide-react';
import { Link } from 'react-router-dom';

interface Citation {
  evidence_id: string;
  document_id?: string;
  source_md?: string;
  source_location?: string;
  chunk_id?: string;
  quote?: string;
  score?: number;
  evidence_type?: 'text' | 'graph' | string;
}

interface GraphPath {
  summary: string;
  evidence_id: string;
  source_md?: string;
  source_location?: string;
}

interface Message {
  role: 'user' | 'ai';
  content: string;
  citations?: Citation[];
  graph_paths?: GraphPath[];
}

const QAView = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'ai',
      content:
        '您好！我是 IND 智慧助手。您可以向我提问关于药学注册资料的任何问题，我会基于文本证据和知识图谱关系返回带引用的回答。',
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) {
      return;
    }

    const userMessage = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await axios.post('/api/chat', {
        query: userMessage,
        top_k: 5,
        retrieval_options: {
          include_debug: false,
        },
      });

      setMessages((prev) => [
        ...prev,
        {
          role: 'ai',
          content: response.data.answer,
          citations: response.data.citations,
          graph_paths: response.data.graph_paths,
        },
      ]);
    } catch (error) {
      console.error('Q&A Error:', error);
      setMessages((prev) => [
        ...prev,
        {
          role: 'ai',
          content: '抱歉，系统处理您的提问时出现了错误，请稍后再试。',
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="qa-view-container fade-in">
      <div className="chat-history">
        {messages.map((msg, index) => (
          <div key={index} className={`message-wrapper ${msg.role}`}>
            <div className="flex items-center gap-2 mb-1 px-2">
              {msg.role === 'user' ? (
                <>
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">User</span>
                  <User size={12} className="text-slate-500" />
                </>
              ) : (
                <>
                  <Bot size={12} className="text-indigo-400" />
                  <span className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">
                    IND AI Assistant
                  </span>
                </>
              )}
            </div>

            <div className="message-bubble whitespace-pre-wrap">{msg.content}</div>

            {msg.citations && msg.citations.length > 0 && (
              <div className="sources-panel">
                <div className="flex items-center gap-2 text-[10px] text-slate-500 mb-2 uppercase tracking-tighter">
                  <BookCopy size={10} /> 证据引用
                </div>
                <div className="flex flex-col gap-2">
                  {msg.citations.map((citation) => (
                    <div
                      key={citation.evidence_id}
                      className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-3 text-[11px]">
                        <span className="text-indigo-300">
                          {citation.source_md || '未知文档'} / {citation.source_location || '未知位置'}
                        </span>
                        <span className="text-slate-500">
                          {citation.evidence_type || 'text'} · {(citation.score || 0).toFixed(2)}
                        </span>
                      </div>
                      {citation.quote && (
                        <div className="mt-2 text-xs text-slate-300 leading-relaxed">{citation.quote}</div>
                      )}
                      {citation.source_md && (
                        <Link
                          to={`/file/${encodeURIComponent(citation.source_md)}`}
                          className="mt-2 inline-flex items-center gap-1 text-[11px] text-cyan-300 hover:text-cyan-200"
                        >
                          <FileSearch size={12} />
                          查看文档详情
                        </Link>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {msg.graph_paths && msg.graph_paths.length > 0 && (
              <div className="sources-panel">
                <div className="flex items-center gap-2 text-[10px] text-slate-500 mb-2 uppercase tracking-tighter">
                  <GitBranch size={10} /> 图谱路径
                </div>
                <div className="flex flex-col gap-2">
                  {msg.graph_paths.map((path) => (
                    <div
                      key={`${path.evidence_id}-${path.summary}`}
                      className="rounded-xl border border-indigo-500/10 bg-indigo-500/5 px-3 py-2 text-xs text-slate-300"
                    >
                      <div>{path.summary}</div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        {path.source_md || '未知文档'} / {path.source_location || '未知位置'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className="message-wrapper ai">
            <div className="message-bubble flex items-center gap-3">
              <Loader2 size={16} className="animate-spin text-indigo-400" />
              <span className="text-slate-400">正在执行混合检索、图谱扩展并组装证据...</span>
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      <div className="chat-input-area">
        <div className="input-box-wrapper">
          <input
            type="text"
            className="qa-input"
            placeholder="输入您的问题，如：TQB2858 的主要安全性信号有哪些？"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && handleSend()}
          />
          <button className="qa-send-btn" onClick={handleSend} disabled={!input.trim() || isLoading}>
            <Send size={20} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default QAView;
