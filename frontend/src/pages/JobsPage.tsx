import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import FormControl from '@mui/material/FormControl';
import InputAdornment from '@mui/material/InputAdornment';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';

import AddRoundedIcon from '@mui/icons-material/AddRounded';
import AssignmentRoundedIcon from '@mui/icons-material/AssignmentRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import ErrorRoundedIcon from '@mui/icons-material/ErrorRounded';
import PlayCircleRoundedIcon from '@mui/icons-material/PlayCircleRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';

import { api, messageOf } from '../api/api';
import { Chart, useChart } from '../components/chart';
import { STATUS_LABELS, StatusBadge } from '../components/StatusBadge';
import { useReducedMotion } from '../hooks/useReducedMotion';
import type { JobSummary, StageKey } from '../types';
import {
  JOB_STATUS_FILTERS,
  STAGE_NAMES,
  countJobStatuses,
  filterJobs,
  jobsLastSevenDays,
  statusDistribution,
  visibleStageKeys,
  type JobStatusFilter,
} from '../utils/jobDisplay';

const POLL_INTERVAL_MS = 5000;

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function stageStatusLabel(status: string | undefined): string {
  if (!status) return '—';
  return STATUS_LABELS[status] ?? status;
}

export function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>('all');
  const [pendingDelete, setPendingDelete] = useState<JobSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const data = await api.listJobs();
      setJobs(data);
      setError(null);
    } catch (err: unknown) {
      setError(messageOf(err));
    }
  }, []);

  useEffect(() => {
    void load();

    // 仅页面可见时轮询；隐藏时停止，回到前台立即刷新一次。
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, POLL_INTERVAL_MS);

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [load]);

  const counts = useMemo(
    () => countJobStatuses(jobs ?? []),
    [jobs],
  );
  const distribution = useMemo(() => statusDistribution(jobs ?? []), [jobs]);
  const lastSevenDays = useMemo(() => jobsLastSevenDays(jobs ?? []), [jobs]);
  const filtered = useMemo(
    () => filterJobs(jobs ?? [], query, statusFilter),
    [jobs, query, statusFilter],
  );
  const reducedMotion = useReducedMotion();

  const statusChartOptions = useChart({
    chart: { type: 'bar', animations: { enabled: !reducedMotion, speed: 360 } },
    colors: distribution.map((item) => item.color),
    plotOptions: {
      bar: { horizontal: true, distributed: true, barHeight: '52%', borderRadius: 0 },
    },
    dataLabels: {
      enabled: true,
      style: { fontSize: '16px', fontWeight: 600, colors: ['#ffffff'] },
    },
    stroke: { width: 0 },
    xaxis: {
      categories: distribution.map((item) => item.label),
      labels: { style: { fontSize: '16px' } },
    },
    yaxis: { labels: { style: { fontSize: '16px' } } },
    grid: { xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } } },
    legend: { show: false },
    tooltip: { y: { formatter: (value: number) => `${value} 个任务` } },
    noData: { text: '暂无数据', style: { fontSize: '16px' } },
  });

  const dailyChartOptions = useChart({
    chart: { type: 'bar', animations: { enabled: !reducedMotion, speed: 360 } },
    colors: ['#1877F2'],
    plotOptions: { bar: { columnWidth: '46%', borderRadius: 0 } },
    xaxis: {
      categories: lastSevenDays.labels,
      labels: { style: { fontSize: '16px' } },
    },
    yaxis: {
      labels: { style: { fontSize: '16px' }, formatter: (value: number) => `${Math.round(value)}` },
    },
    legend: { show: false },
    tooltip: { y: { formatter: (value: number) => `${value} 个新建任务` } },
    noData: { text: '暂无数据', style: { fontSize: '16px' } },
  });

  const requestDelete = (job: JobSummary) => {
    setDeleteError(null);
    setPendingDelete(job);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteJob(pendingDelete.job_id);
      setJobs((previous) =>
        previous ? previous.filter((job) => job.job_id !== pendingDelete.job_id) : previous,
      );
      setPendingDelete(null);
    } catch (err: unknown) {
      setDeleteError(messageOf(err));
    } finally {
      setDeleting(false);
    }
  };

  if (!jobs && !error) {
    return (
      <Stack alignItems="center" spacing={2} sx={{ py: 12, color: 'text.secondary' }}>
        <CircularProgress size={28} />
        <Typography sx={{ fontSize: 'var(--font-body)' }}>正在加载任务列表…</Typography>
      </Stack>
    );
  }

  const metrics = [
    { key: 'total', label: '任务总数', value: counts.total, color: '#1877F2', icon: AssignmentRoundedIcon },
    { key: 'running', label: '运行中', value: counts.running, color: '#8E33FF', icon: PlayCircleRoundedIcon },
    { key: 'completed', label: '已完成', value: counts.completed, color: '#22C55E', icon: CheckCircleRoundedIcon },
    { key: 'failed', label: '失败', value: counts.failed, color: '#FF5630', icon: ErrorRoundedIcon },
  ];

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        sx={{ mb: 2.5 }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography component="h1" sx={{ fontSize: 32, fontWeight: 700, lineHeight: 1.2 }}>
            任务总览
          </Typography>
          <Typography sx={{ mt: 0.5, fontSize: 'var(--font-body)', color: 'text.secondary' }}>
            查看三维建图任务状态、阶段进度与最近七日活动。
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddRoundedIcon />}
          onClick={() => navigate('/jobs/new')}
        >
          新建任务
        </Button>
      </Stack>

      {error ? (
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" onClick={() => void load()}>
              重试
            </Button>
          }
          sx={{ mb: 2 }}
        >
          任务列表加载失败：{error}
        </Alert>
      ) : null}

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(4, minmax(0, 1fr))' },
          gap: 1.5,
          mb: 2,
        }}
      >
        {metrics.map(({ key, label, value, color, icon: Icon }) => (
          <Card
            key={key}
            sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}
          >
            <Stack direction="row" alignItems="center" spacing={1}>
              <Box
                sx={{
                  width: 36,
                  height: 36,
                  flex: 'none',
                  display: 'grid',
                  placeItems: 'center',
                  color,
                  bgcolor: `${color}1A`,
                }}
              >
                <Icon fontSize="small" />
              </Box>
              <Typography sx={{ fontSize: 'var(--font-body)', color: 'text.secondary' }}>{label}</Typography>
            </Stack>
            <Typography
              sx={{ mt: 1, fontSize: 42, fontWeight: 700, lineHeight: 1.1, fontFamily: 'var(--mono)' }}
            >
              {value}
            </Typography>
            <Typography sx={{ fontSize: 'var(--font-secondary)', color: 'text.disabled' }}>
              来自真实任务列表
            </Typography>
          </Card>
        ))}
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'repeat(2, minmax(0, 1fr))' },
          gap: 2,
          mb: 2,
        }}
      >
        <Card
          sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}
        >
          <Typography sx={{ mb: 1.5, fontSize: 18, fontWeight: 700 }}>任务状态分布</Typography>
          <Chart
            type="bar"
            series={[{ name: '任务数', data: distribution.map((item) => item.value) }]}
            options={statusChartOptions}
            sx={{ height: 260 }}
          />
        </Card>

        <Card
          sx={{ p: 2, boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}
        >
          <Typography sx={{ mb: 1.5, fontSize: 18, fontWeight: 700 }}>近七日新建任务</Typography>
          <Chart
            type="bar"
            series={[{ name: '新建任务', data: lastSevenDays.values }]}
            options={dailyChartOptions}
            sx={{ height: 260 }}
          />
        </Card>
      </Box>

      <Card sx={{ boxShadow: 'none', border: '1px solid', borderColor: 'divider' }}>
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={1.5}
          alignItems={{ xs: 'stretch', md: 'center' }}
          sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}
        >
          <TextField
            size="small"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索任务 ID 或数据集"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRoundedIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ minWidth: { md: 320 } }}
          />
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <Select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as JobStatusFilter)}
              displayEmpty
            >
              {JOB_STATUS_FILTERS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Box sx={{ flex: 1 }} />
          <Typography sx={{ fontSize: 'var(--font-body)', color: 'text.secondary' }}>
            共 {filtered.length} 个任务
          </Typography>
        </Stack>

        {jobs && jobs.length === 0 ? (
          <Stack alignItems="center" spacing={1.5} sx={{ py: 8, px: 2 }}>
            <Typography sx={{ fontSize: 18, color: 'text.secondary' }}>
              还没有任何任务。
            </Typography>
            <Button variant="outlined" onClick={() => navigate('/jobs/new')}>
              创建第一个三维建图任务
            </Button>
          </Stack>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>任务 ID</TableCell>
                  <TableCell>数据集</TableCell>
                  <TableCell>创建时间</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>阶段</TableCell>
                  <TableCell align="right">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} align="center" sx={{ py: 6, color: 'text.secondary' }}>
                      没有符合条件的任务
                    </TableCell>
                  </TableRow>
                ) : (
                  filtered.map((job) => {
                    const stageKeys: StageKey[] = visibleStageKeys(job);
                    return (
                      <TableRow
                        key={job.job_id}
                        hover
                        onClick={() => navigate(`/jobs/${job.job_id}`)}
                        sx={{ cursor: 'pointer' }}
                      >
                        <TableCell>
                          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                            <Box
                              component="code"
                              sx={{ fontSize: 'var(--font-body)', fontWeight: 600, wordBreak: 'break-all' }}
                            >
                              {job.job_id}
                            </Box>
                            {job.preview_job ? (
                              <Box
                                component="span"
                                sx={{
                                  px: 0.75,
                                  py: 0.1,
                                  fontSize: 'var(--font-secondary)',
                                  color: 'warning.dark',
                                  bgcolor: 'warning.lighter',
                                  border: '1px solid',
                                  borderColor: 'warning.main',
                                }}
                              >
                                演示
                              </Box>
                            ) : null}
                          </Stack>
                        </TableCell>
                        <TableCell sx={{ fontSize: 'var(--font-body)' }}>{job.dataset}</TableCell>
                        <TableCell sx={{ fontSize: 'var(--font-body)', whiteSpace: 'nowrap' }}>
                          {formatDate(job.created_at)}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={job.status} />
                        </TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                            {stageKeys.map((stage) => (
                              <Box
                                key={stage}
                                sx={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 0.5,
                                  px: 0.75,
                                  py: 0.15,
                                  fontSize: 'var(--font-secondary)',
                                  border: '1px solid',
                                  borderColor: 'divider',
                                  color: 'text.secondary',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                <span>{STAGE_NAMES[stage]}</span>
                                <Box
                                  component="span"
                                  sx={{ fontWeight: 600, color: 'text.primary' }}
                                >
                                  {stageStatusLabel(job.stages[stage])}
                                </Box>
                              </Box>
                            ))}
                          </Stack>
                        </TableCell>
                        <TableCell align="right" onClick={(event) => event.stopPropagation()}>
                          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                            <Button size="small" onClick={() => navigate(`/jobs/${job.job_id}`)}>
                              打开
                            </Button>
                            <Button
                              size="small"
                              color="error"
                              startIcon={<DeleteOutlineRoundedIcon fontSize="small" />}
                              onClick={() => requestDelete(job)}
                            >
                              删除
                            </Button>
                          </Stack>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Card>

      <Dialog
        open={pendingDelete !== null}
        onClose={() => {
          if (!deleting) setPendingDelete(null);
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>删除任务</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ fontSize: 'var(--font-body)' }}>
            确认删除任务 <Box component="code">{pendingDelete?.job_id}</Box> ？
            该操作会删除其磁盘上的所有数据，且不可恢复。
          </DialogContentText>
          {deleteError ? (
            <Alert severity="error" sx={{ mt: 2 }}>
              删除失败：{deleteError}
            </Alert>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingDelete(null)} disabled={deleting}>
            取消
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void confirmDelete()}
            disabled={deleting}
          >
            {deleting ? '删除中…' : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
