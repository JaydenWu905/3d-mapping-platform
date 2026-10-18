import { lazy, Suspense } from 'react';
import { mergeClasses } from 'minimal-shared/utils';

import { styled } from '@mui/material/styles';

import { chartClasses } from './classes';
import { ChartLoading } from './components';

import type { ChartProps } from './types';

import './styles.css';

// ----------------------------------------------------------------------

const LazyChart = lazy(() =>
  import('react-apexcharts').then((module) => ({ default: module.default }))
);

export function Chart({ type, series, options, slotProps, className, sx, ...other }: ChartProps) {
  return (
    <ChartRoot
      dir="ltr"
      className={mergeClasses([chartClasses.root, className])}
      sx={sx}
      {...other}
    >
      <Suspense fallback={<ChartLoading type={type} sx={slotProps?.loading} />}>
        <LazyChart type={type} series={series} options={options} width="100%" height="100%" />
      </Suspense>
    </ChartRoot>
  );
}

// ----------------------------------------------------------------------

const ChartRoot = styled('div')(() => ({
  width: '100%',
  flexShrink: 0,
  position: 'relative',
  borderRadius: 0,
}));
