import type { CSSObject, TypographyVariantsOptions } from '@mui/material/styles';

import { pxToRem } from 'minimal-shared/utils';

import { themeConfig } from '../theme-config';

// ----------------------------------------------------------------------

/**
 * Local type scale:
 * - body / button: 16px; secondary: 14px
 * - page headings: 28–32px
 * - key numbers: applied via `.metric-value` (36–44px)
 * - chart axes / legends: configured at >= 16px in useChart
 */

export type FontStyleExtend = {
  fontWeightSemiBold: CSSObject['fontWeight'];
  fontSecondaryFamily: CSSObject['fontFamily'];
};

const primaryFont = themeConfig.fontFamily.primary;
const secondaryFont = themeConfig.fontFamily.secondary;

export const typography: TypographyVariantsOptions = {
  fontFamily: primaryFont,
  fontSecondaryFamily: secondaryFont,
  fontWeightLight: '300',
  fontWeightRegular: '400',
  fontWeightMedium: '500',
  fontWeightSemiBold: '600',
  fontWeightBold: '700',
  h1: {
    fontFamily: secondaryFont,
    fontWeight: 700,
    lineHeight: 40 / 32,
    fontSize: pxToRem(32),
  },
  h2: {
    fontFamily: secondaryFont,
    fontWeight: 700,
    lineHeight: 36 / 28,
    fontSize: pxToRem(28),
  },
  h3: {
    fontFamily: secondaryFont,
    fontWeight: 700,
    lineHeight: 1.4,
    fontSize: pxToRem(24),
  },
  h4: {
    fontWeight: 700,
    lineHeight: 1.4,
    fontSize: pxToRem(20),
  },
  h5: {
    fontWeight: 700,
    lineHeight: 1.4,
    fontSize: pxToRem(18),
  },
  h6: {
    fontWeight: 600,
    lineHeight: 24 / 17,
    fontSize: pxToRem(17),
  },
  subtitle1: {
    fontWeight: 600,
    lineHeight: 1.5,
    fontSize: pxToRem(18),
  },
  subtitle2: {
    fontWeight: 600,
    lineHeight: 24 / 16,
    fontSize: pxToRem(16),
  },
  body1: {
    lineHeight: 1.65,
    fontSize: pxToRem(16),
  },
  body2: {
    lineHeight: 1.6,
    fontSize: pxToRem(14),
  },
  caption: {
    lineHeight: 1.6,
    fontSize: pxToRem(14),
  },
  overline: {
    fontWeight: 700,
    lineHeight: 1.5,
    fontSize: pxToRem(16),
    textTransform: 'uppercase',
  },
  button: {
    fontWeight: 600,
    lineHeight: 1.5,
    fontSize: pxToRem(16),
    textTransform: 'unset',
  },
};
