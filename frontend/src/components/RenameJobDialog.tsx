import { useEffect, useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField } from '@mui/material';
import { api, messageOf } from '../api/api';
import { jobNameError, normalizedJobName } from '../utils/jobName';

export function RenameJobDialog({ open, jobId, name, onClose, onSaved }: {
  open: boolean; jobId: string; name: string; onClose: () => void; onSaved: () => Promise<void>;
}) {
  const [value, setValue] = useState(name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setValue(name); setError(null); } }, [open, name]);
  const validation = jobNameError(value);
  async function save() {
    if (validation || saving) return;
    setSaving(true); setError(null);
    try { await api.renameJob(jobId, normalizedJobName(value)); await onSaved(); onClose(); }
    catch (e) { setError(messageOf(e)); }
    finally { setSaving(false); }
  }
  return <Dialog open={open} onClose={() => { if (!saving) onClose(); }} fullWidth maxWidth="sm">
    <DialogTitle>修改任务名称</DialogTitle>
    <DialogContent>
      <TextField autoFocus fullWidth label="任务名称" value={value} disabled={saving} sx={{ mt: 1 }}
        onChange={e => setValue(e.target.value)} error={!!validation} helperText={validation || '最多 80 个字符，可以与其他任务同名。'}
        onKeyDown={e => { if (e.key === 'Enter') void save(); }} />
      {error ? <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert> : null}
    </DialogContent>
    <DialogActions><Button onClick={onClose} disabled={saving}>取消</Button><Button onClick={() => void save()} disabled={!!validation || saving} variant="contained">{saving ? '保存中…' : '保存名称'}</Button></DialogActions>
  </Dialog>;
}
