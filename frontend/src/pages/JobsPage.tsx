import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, messageOf } from '../api/api';
import type { JobSummary } from '../types';
import { StatusBadge } from '../components/StatusBadge';

export function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api
      .listJobs()
      .then(setJobs)
      .catch((e: unknown) => setError(messageOf(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async (jobId: string) => {
    if (!window.confirm(`确认删除任务 ${jobId} ？该操作会删除其磁盘上的所有数据。`)) return;
    try {
      await api.deleteJob(jobId);
      load();
    } catch (e: unknown) {
      window.alert(messageOf(e));
    }
  };

  const fmtDate = (iso: string) => new Date(iso).toLocaleString('zh-CN', { hour12: false });

  return (
    <div className="page">
      <div className="page-head">
        <h2>任务列表</h2>
        <Link to="/jobs/new" className="btn btn-primary">
          ＋ 新建任务
        </Link>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {!jobs ? (
        <div className="panel-empty">加载中…</div>
      ) : jobs.length === 0 ? (
        <div className="panel-empty-box">
          <div>还没有任何任务。</div>
          <Link to="/jobs/new" className="btn btn-ghost">
            创建第一个三维建图任务
          </Link>
        </div>
      ) : (
        <div className="job-table-wrap">
          <table className="job-table">
            <thead>
              <tr>
                <th>任务 ID</th>
                <th>数据集</th>
                <th>创建时间</th>
                <th>状态</th>
                <th>Pose / Surface / Distance</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} onClick={() => navigate(`/jobs/${j.job_id}`)}>
                  <td>
                    <code>{j.job_id}</code>
                    {j.preview_job ? <span className="tag tag-demo">演示</span> : null}
                  </td>
                  <td>{j.dataset}</td>
                  <td>{fmtDate(j.created_at)}</td>
                  <td>
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="stage-chips">
                    {(['pose', 'surface', 'distance'] as const).map((s) => (
                      <span key={s} className={`chip chip-${j.stages[s] ?? 'waiting'}`}>
                        {s}: {j.stages[s] ?? '—'}
                      </span>
                    ))}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/jobs/${j.job_id}`);
                        }}
                      >
                        打开
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          void remove(j.job_id);
                        }}
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}