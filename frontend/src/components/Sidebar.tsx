import { Link as RouterLink, useLocation } from 'react-router-dom';

import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import AddCircleOutlineRoundedIcon from '@mui/icons-material/AddCircleOutlineRounded';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';

// ----------------------------------------------------------------------

export const SIDEBAR_WIDTH = 200;

const NAV_ITEMS = [
  {
    to: '/',
    label: '任务总览',
    caption: '状态统计与任务列表',
    icon: <DashboardOutlinedIcon />,
    match: (pathname: string) => pathname === '/' || (/^\/jobs\/(?!new$)/.test(pathname)),
  },
  {
    to: '/jobs/new',
    label: '新建任务',
    caption: '上传数据并配置算法',
    icon: <AddCircleOutlineRoundedIcon />,
    match: (pathname: string) => pathname === '/jobs/new',
  },
];

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();

  return (
    <Box
      sx={{
        width: SIDEBAR_WIDTH,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.paper',
        borderRight: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Stack direction="row" spacing={1.25} sx={{ alignItems: 'center', px: 2, py: 2 }}>
        <Box
          sx={{
            width: 38,
            height: 38,
            flex: 'none',
            display: 'grid',
            placeItems: 'center',
            bgcolor: 'primary.main',
            color: 'primary.contrastText',
          }}
        >
          <MapOutlinedIcon fontSize="small" />
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1.2 }} noWrap>
            三维建图平台
          </Typography>
          <Typography sx={{ fontSize: 'var(--font-secondary)', color: 'text.secondary', mt: 0.25 }} noWrap>
            三维重建工作台
          </Typography>
        </Box>
      </Stack>

      <Divider />

      <List sx={{ px: 1, py: 1.25 }}>
        {NAV_ITEMS.map((item) => {
          const active = item.match(pathname);

          return (
            <ListItemButton
              key={item.to}
              component={RouterLink}
              to={item.to}
              onClick={onNavigate}
              selected={active}
              sx={{
                mb: 0.5,
                px: 1.25,
                py: 0.85,
                color: active ? 'primary.main' : 'text.secondary',
                borderLeft: '3px solid',
                borderLeftColor: active ? 'primary.main' : 'transparent',
                bgcolor: active ? 'primary.lighter' : 'transparent',
                '&.Mui-selected': {
                  bgcolor: 'primary.lighter',
                  color: 'primary.dark',
                  '&:hover': { bgcolor: 'primary.lighter' },
                },
              }}
            >
              <ListItemIcon
                sx={{ minWidth: 30, color: 'inherit', '& svg': { fontSize: 20 } }}
              >
                {item.icon}
              </ListItemIcon>
              <ListItemText
                primary={item.label}
                secondary={item.caption}
                primaryTypographyProps={{ fontSize: 'var(--font-body)', fontWeight: 700, lineHeight: 1.35 }}
                secondaryTypographyProps={{
                  fontSize: 11.5,
                  color: active ? 'primary.dark' : 'text.secondary',
                  noWrap: true,
                }}
              />
            </ListItemButton>
          );
        })}
      </List>

      <Box sx={{ mt: 'auto', px: 2, py: 2, borderTop: '1px solid', borderColor: 'divider' }}>
        <Typography sx={{ fontSize: 'var(--font-secondary)', color: 'text.secondary', mb: 0.75 }}>
          处理流程
        </Typography>
        <Stack spacing={0.5}>
          {['位姿估计', '表面重建', '距离场'].map((label, index) => (
            <Stack key={label} direction="row" spacing={0.75} sx={{ alignItems: 'center' }}>
              <Box
                sx={{
                  width: 16,
                  height: 16,
                  flex: 'none',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 'var(--font-secondary)',
                  fontWeight: 800,
                  color: 'primary.contrastText',
                  bgcolor: ['primary.main', 'secondary.main', 'info.main'][index],
                }}
              >
                {index + 1}
              </Box>
              <Typography sx={{ fontSize: 'var(--font-secondary)', color: 'text.primary' }}>{label}</Typography>
            </Stack>
          ))}
        </Stack>
      </Box>
    </Box>
  );
}

type SidebarProps = {
  mobileOpen: boolean;
  onMobileClose: () => void;
};

export function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  return (
    <>
      <Box
        component="aside"
        className="app-sidebar"
        sx={{
          width: SIDEBAR_WIDTH,
          flex: 'none',
          display: { xs: 'none', md: 'block' },
          position: 'sticky',
          top: 0,
          alignSelf: 'flex-start',
          height: '100vh',
          zIndex: 1100,
        }}
      >
        <SidebarContent />
      </Box>

      <Drawer
        open={mobileOpen}
        onClose={onMobileClose}
        ModalProps={{ keepMounted: true }}
        sx={{ display: { xs: 'block', md: 'none' } }}
        slotProps={{ paper: { sx: { width: SIDEBAR_WIDTH, borderRadius: 0 } } }}
      >
        <SidebarContent onNavigate={onMobileClose} />
      </Drawer>
    </>
  );
}
