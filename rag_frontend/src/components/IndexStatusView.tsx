import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Loader2, PlayCircle, RefreshCcw, CheckCircle2, XCircle, Clock3 } from 'lucide-react';

type JobStatus = 'queued' | 'running' | 'completed' | 'failed';

interface IndexJob {
  job_id: string;
  status: JobStatus;
  markdown_dir: string;
  created_at: string;
  updated_at: string;
  result?: {
    indexed_documents?: number;
    skipped_documents?: number;
    indexed_chunks?: number;
    errors?: Array<{ file: string; error: string }>;
  } | null;
  error?: string | null;
}

const defaultIndexDir = '../output_TQB2858_8.4_refined/mineru_markdowns';

function statusBadge(status: JobStatus) {
  if (status === 'completed') {
    return <span className="badge" style={{ color: '#34d399', borderColor: 'rgba(52,211,153,0.3)' }}>completed</span>;
  }
  if (status === 'failed') {
    return <span className="badge" style={{ color: '#f87171', borderColor: 'rgba(248,113,113,0.3)' }}>failed</span>;
  }
  if (status === 'running') {
    return <span className="badge" style={{ color: '#60a5fa', borderColor: 'rgba(96,165,250,0.3)' }}>running</span>;
  }
  return <span className="badge">queued</span>;
}

const IndexStatusView = () => {
  const [markdownDir, setMarkdownDir] = useState(defaultIndexDir);
  const [currentJobId, setCurrentJobId] = useState('');
  const [job, setJob] = useState<IndexJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const active = useMemo(() => job?.status === 'queued' || job?.status === 'running', [job?.status]);

  const fetchJob = async (jobId: string) => {
    if (!jobId.trim()) return;
    setIsPolling(true);
    setErrorMessage('');
    try {
      const response = await axios.get<IndexJob>(`/api/index/${jobId.trim()}`);
      setJob(response.data);
    } catch (error: any) {
      setErrorMessage(error?.response?.data?.detail || '获取任务状态失败，请检查任务 ID。');
    } finally {
      setIsPolling(false);
    }
  };

  const createJob = async () => {
    if (!markdownDir.trim() || isSubmitting) return;
    setIsSubmitting(true);
    setErrorMessage('');
    try {
      const response = await axios.post<IndexJob>('/api/index', {
        markdown_dir: markdownDir.trim(),
      });
      setJob(response.data);
      setCurrentJobId(response.data.job_id);
    } catch (error: any) {
      setErrorMessage(error?.response?.data?.detail || '提交索引任务失败。');
    } finally {
      setIsSubmitting(false);
    }
  };

  useEffect(() => {
    if (!currentJobId || !active) return;
    const timer = window.setInterval(() => {
      fetchJob(currentJobId);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [currentJobId, active]);

  return (
    <div className="qa-view-container fade-in">
      <div className="chat-history" style={{ gap: '20px' }}>
        <section className="glass" style={{ borderRadius: 16, padding: 20 }}>
          <h2 style={{ fontSize: 18, marginBottom: 10 }}>索引任务控制台</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 16 }}>
            提交 `Markdown` 目录后，系统会在后台执行统一索引任务并持续更新状态。
          </p>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <input
              className="qa-input"
              value={markdownDir}
              onChange={(event) => setMarkdownDir(event.target.value)}
              placeholder="输入 markdown 目录路径"
              style={{ background: 'var(--bg-secondary)', borderRadius: 10, border: '1px solid var(--border-color)' }}
            />
            <button className="qa-send-btn" onClick={createJob} disabled={isSubmitting}>
              {isSubmitting ? <Loader2 size={18} className="animate-spin" /> : <PlayCircle size={18} />}
            </button>
          </div>
        </section>

        <section className="glass" style={{ borderRadius: 16, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h3 style={{ fontSize: 16 }}>任务状态查询</h3>
            <button
              className="source-item"
              onClick={() => fetchJob(currentJobId)}
              style={{ border: '1px solid var(--border-color)', cursor: 'pointer' }}
            >
              <RefreshCcw size={12} /> 刷新
            </button>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
            <input
              className="qa-input"
              value={currentJobId}
              onChange={(event) => setCurrentJobId(event.target.value)}
              placeholder="粘贴 job_id"
              style={{ background: 'var(--bg-secondary)', borderRadius: 10, border: '1px solid var(--border-color)' }}
            />
            <button className="qa-send-btn" onClick={() => fetchJob(currentJobId)} disabled={isPolling}>
              {isPolling ? <Loader2 size={18} className="animate-spin" /> : <Clock3 size={18} />}
            </button>
          </div>

          {errorMessage && (
            <div style={{ color: '#fca5a5', background: 'rgba(252,165,165,0.08)', borderRadius: 10, padding: 10, fontSize: 12 }}>
              {errorMessage}
            </div>
          )}

          {job && (
            <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Job ID</div>
                  <div style={{ fontSize: 13 }}>{job.job_id}</div>
                </div>
                <div>{statusBadge(job.status)}</div>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>目录：{job.markdown_dir}</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>创建时间：{job.created_at}</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>更新时间：{job.updated_at}</div>

              {job.status === 'completed' && (
                <div style={{ background: 'rgba(16,185,129,0.08)', borderRadius: 10, padding: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, color: '#34d399' }}>
                    <CheckCircle2 size={14} /> 索引完成
                  </div>
                  <div style={{ fontSize: 13 }}>文档：{job.result?.indexed_documents ?? 0}</div>
                  <div style={{ fontSize: 13 }}>跳过：{job.result?.skipped_documents ?? 0}</div>
                  <div style={{ fontSize: 13 }}>分块：{job.result?.indexed_chunks ?? 0}</div>
                  {(job.result?.errors?.length ?? 0) > 0 && (
                    <div style={{ marginTop: 8, fontSize: 12, color: '#fca5a5' }}>
                      错误条目：{job.result?.errors?.length}
                    </div>
                  )}
                </div>
              )}

              {job.status === 'failed' && (
                <div style={{ background: 'rgba(248,113,113,0.1)', borderRadius: 10, padding: 12, color: '#fecaca' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <XCircle size={14} /> 索引失败
                  </div>
                  <div style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{job.error || '无详细错误信息'}</div>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default IndexStatusView;
