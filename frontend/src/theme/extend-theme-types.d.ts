import type {} from '@mui/material/themeCssVarsAugmentation';

import type { FontStyleExtend } from './core/typography';
import type { CustomShadows } from './core/custom-shadows';
import type {
  GreyExtend,
  TypeTextExtend,
  CommonColorsExtend,
  PaletteColorExtend,
  TypeBackgroundExtend,
} from './core/palette';

// ----------------------------------------------------------------------

declare module '@mui/material/styles' {
  // grey
  interface Color extends GreyExtend {}
  // text
  interface TypeText extends TypeTextExtend {}
  // black & white
  interface CommonColors extends CommonColorsExtend {}
  // background
  interface TypeBackground extends TypeBackgroundExtend {}
  // primary, secondary, info, success, warning, error
  interface PaletteColor extends PaletteColorExtend {}
  interface SimplePaletteColorOptions extends Partial<PaletteColorExtend> {}
}

declare module '@mui/material/styles' {
  interface TypographyVariants extends FontStyleExtend {}
  interface TypographyVariantsOptions extends Partial<FontStyleExtend> {}
}

declare module '@mui/material/styles' {
  interface Theme {
    customShadows: CustomShadows;
  }
  interface ThemeOptions {
    customShadows?: CustomShadows;
  }
  interface ThemeVars {
    customShadows: CustomShadows;
    typography: Theme['typography'];
    transitions: Theme['transitions'];
  }
}
