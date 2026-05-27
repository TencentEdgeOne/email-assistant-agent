/**
 * Design tokens — Minimal premium style.
 *
 * Inspired by Linear / Vercel / Raycast: neutral surfaces, disciplined
 * spacing, near-zero decoration, and a single muted teal accent that
 * surfaces only where it earns attention. No gradients on surfaces,
 * no heavy shadows; hierarchy comes from typography weight + spacing,
 * not from color volume.
 */

export const tokens = {
  color: {
    // Surfaces — layered neutral grays (zero hue tint)
    bg: '#ffffff',
    surface: '#fafafa',
    surfaceHover: '#f5f5f5',
    surfaceMuted: '#f0f0f0',
    surfaceElevated: '#ffffff',
    gradientBrand: 'linear-gradient(135deg, #f5f5f5 0%, #fafafa 100%)',
    gradientBrandStrong: 'linear-gradient(135deg, #115e59 0%, #0d9488 100%)',

    // Borders — barely there
    border: '#e8e8e8',
    borderStrong: '#d4d4d4',
    borderSubtle: '#f0f0f0',

    // Text — high contrast hierarchy (no mid-tone confusion)
    text: '#0a0a0a',
    textMuted: '#525252',
    textSubtle: '#737373',
    textDisabled: '#a3a3a3',
    textInverted: '#ffffff',

    // Brand — muted teal (used sparingly: active states, primary CTA, links)
    brand: '#0d9488',
    brandHover: '#0f766e',
    brandSoft: '#f0fdfa',
    brandSofter: '#f7fffe',
    brandBorder: '#5eead4',

    // Status — desaturated, understated
    success: '#15803d',
    successSoft: '#f0fdf4',
    warning: '#a16207',
    warningSoft: '#fefce8',
    danger: '#b91c1c',
    dangerSoft: '#fef2f2',
    info: '#0284c7',
    infoSoft: '#f0f9ff',

    // Email category palette — more muted / fewer bright primaries
    categoryUrgent: '#b91c1c',
    categoryMeeting: '#0284c7',
    categoryInternal: '#0d9488',
    categoryMarketing: '#a16207',
    categoryNotification: '#6b7280',
    categoryFollowup: '#15803d',
    categorySpam: '#9ca3af',
    categoryBilling: '#7c3aed',
    categoryOther: '#6b7280',
  },

  font: {
    sans: "'Inter', 'Plus Jakarta Sans', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    mono: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace",
  },

  fontSize: {
    xs: 11,
    sm: 12,
    base: 13,
    md: 14,
    lg: 15,
    xl: 18,
    '2xl': 20,
    '3xl': 26,
  },

  fontWeight: {
    regular: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },

  lineHeight: {
    tight: 1.3,
    snug: 1.5,
    normal: 1.6,
    relaxed: 1.75,
  },

  space: {
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    5: 20,
    6: 28,
    7: 36,
    8: 48,
  } as Record<number, number>,

  radius: {
    sm: 4,
    md: 6,
    lg: 8,
    xl: 12,
    '2xl': 16,
    pill: 999,
  },

  shadow: {
    sm: '0 1px 2px rgba(0, 0, 0, 0.03)',
    md: '0 2px 6px rgba(0, 0, 0, 0.04)',
    pop: '0 8px 24px rgba(0, 0, 0, 0.06), 0 2px 4px rgba(0, 0, 0, 0.02)',
    focus: '0 0 0 2px rgba(13, 148, 136, 0.12)',
    inset: 'inset 0 0 0 1px rgba(0, 0, 0, 0.04)',
  },

  motion: {
    fast: '100ms ease',
    base: '150ms ease',
    slow: '220ms cubic-bezier(0.2, 0, 0, 1)',
    spring: '280ms cubic-bezier(0.34, 1.56, 0.64, 1)',
  },
} as const;
