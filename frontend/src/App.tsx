import { useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';

import MenuRoundedIcon from '@mui/icons-material/MenuRounded';

import { Sidebar } from './components/Sidebar';
import { JobDetailPage } from './pages/JobDetailPage';
import { JobsPage } from './pages/JobsPage';
import { NewJobPage } from './pages/NewJobPage';

function pageTitle(pathname: string) {
  if (pathname === '/jobs/new') return '新建任务';
  if (/^\/jobs\/[^/]+$/.test(pathname)) return '任务详情';
  return '任务总览';
}

function Shell() {
  const { pathname } = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      <Sidebar mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />

      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <AppBar
          className="app-topbar"
          position="sticky"
          color="inherit"
          elevation={0}
          sx={{
            height: 56,
            justifyContent: 'center',
            bgcolor: 'background.paper',
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Toolbar
            disableGutters
            sx={{ minHeight: '56px !important', px: { xs: 1.5, sm: 3 }, gap: 1.5 }}
          >
            <IconButton
              aria-label="打开导航菜单"
              onClick={() => setMobileOpen(true)}
              sx={{ display: { md: 'none' } }}
            >
              <MenuRoundedIcon />
            </IconButton>
            <Typography sx={{ fontSize: 14, color: 'text.secondary', display: { xs: 'none', sm: 'block' } }}>
              三维建图平台
            </Typography>
            <Typography sx={{ fontSize: 14, color: 'text.disabled', display: { xs: 'none', sm: 'block' } }}>
              /
            </Typography>
            <Typography sx={{ fontSize: 18, fontWeight: 700 }}>{pageTitle(pathname)}</Typography>
            <Box sx={{ flex: 1 }} />
            <Typography
              sx={{
                fontSize: 12,
                color: 'text.secondary',
                border: '1px solid',
                borderColor: 'divider',
                px: 1,
                py: 0.4,
                display: { xs: 'none', lg: 'block' },
              }}
            >
              位姿估计 · 表面重建 · 距离场
            </Typography>
          </Toolbar>
        </AppBar>

        <Box component="main" className="app-main" sx={{ flex: 1, minWidth: 0 }}>
          <Routes>
            <Route path="/demo/waiting-preview" element={<Navigate to="/jobs/new" replace />} />
            <Route path="/" element={<JobsPage />} />
            <Route path="/jobs/new" element={<NewJobPage />} />
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
            <Route path="*" element={<JobsPage />} />
          </Routes>
        </Box>
      </Box>
    </Box>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}
