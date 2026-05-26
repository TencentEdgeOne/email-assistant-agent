/**
 * Inline SVG icon set — Lucide-style, 1.5px stroke, ``currentColor`` so
 * callers control the tint via CSS. We bundle these instead of pulling in
 * ``lucide-react`` to keep the template's ``npm install`` lean (the goal
 * is "git clone → 30s install"; an icon library would double the dep tree).
 *
 * All icons share the same API:
 *   <Icon name="mail" size={16} />
 *
 * Adding a new icon: copy the path data from https://lucide.dev/icons,
 * keep the 24x24 viewBox + 1.5px stroke, drop it into ``ICONS`` below.
 */
import { CSSProperties } from 'react';

interface IconProps {
  name: IconName;
  size?: number | string;
  strokeWidth?: number;
  style?: CSSProperties;
  className?: string;
  'aria-hidden'?: boolean | 'true' | 'false';
  'aria-label'?: string;
}

export type IconName =
  | 'mail'
  | 'inbox'
  | 'sparkles'
  | 'send'
  | 'check'
  | 'check-circle'
  | 'x'
  | 'x-circle'
  | 'refresh-cw'
  | 'corner-down-left'
  | 'pause'
  | 'play'
  | 'loader'
  | 'alert-circle'
  | 'info'
  | 'lightbulb'
  | 'calendar'
  | 'briefcase'
  | 'megaphone'
  | 'bell'
  | 'rotate-ccw'
  | 'trash-2'
  | 'receipt'
  | 'folder'
  | 'arrow-right'
  | 'arrow-up-right'
  | 'circle'
  | 'circle-dot'
  | 'edit-3'
  | 'skip-forward'
  | 'siren'
  | 'archive'
  | 'zap'
  | 'clipboard'
  | 'search'
  | 'eye'
  | 'filter'
  | 'chevron-down';

// 24x24 viewBox path data, Lucide style. Use single quotes for clarity.
const ICONS: Record<IconName, string> = {
  mail: '<path d="M22 8a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2Z"/><path d="m2 8 8.6 5.7a2 2 0 0 0 2.8 0L22 8"/>',
  inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>',
  sparkles:
    '<path d="m12 3-1.9 5.8L4 10l6.1 1.9L12 18l1.9-6.1L20 10l-6.1-1.2Z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  'check-circle':
    '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  x: '<line x1="18" x2="6" y1="6" y2="18"/><line x1="6" x2="18" y1="6" y2="18"/>',
  'x-circle':
    '<circle cx="12" cy="12" r="10"/><line x1="15" x2="9" y1="9" y2="15"/><line x1="9" x2="15" y1="9" y2="15"/>',
  'refresh-cw':
    '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/><path d="M20.49 15A9 9 0 0 1 5.64 18.36L1 14"/>',
  'corner-down-left':
    '<polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
  pause: '<rect width="4" height="16" x="6" y="4" rx="1"/><rect width="4" height="16" x="14" y="4" rx="1"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  loader:
    '<line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/>',
  'alert-circle':
    '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  lightbulb:
    '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
  calendar:
    '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/>',
  briefcase:
    '<rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  megaphone:
    '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  'rotate-ccw':
    '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
  'trash-2':
    '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
  receipt:
    '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  'arrow-right': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  'arrow-up-right': '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
  circle: '<circle cx="12" cy="12" r="10"/>',
  'circle-dot':
    '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/>',
  'edit-3':
    '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  'skip-forward': '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/>',
  siren:
    '<path d="M7 12a5 5 0 0 1 10 0"/><path d="M5 20.5h14a1 1 0 0 0 1-1V18a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v1.5a1 1 0 0 0 1 1Z"/><path d="M12 7V2"/><path d="M9.07 9.07 5.5 5.5"/><path d="M14.93 9.07l3.57-3.57"/>',
  archive:
    '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  clipboard:
    '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
  search:
    '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/>',
  eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  filter:
    '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  'chevron-down': '<polyline points="6 9 12 15 18 9"/>',
};

export function Icon({
  name,
  size = 16,
  strokeWidth = 1.75,
  style,
  className,
  'aria-hidden': ariaHidden,
  'aria-label': ariaLabel,
}: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={{ flexShrink: 0, ...style }}
      role={ariaLabel ? 'img' : undefined}
      aria-hidden={ariaLabel ? undefined : ariaHidden ?? true}
      aria-label={ariaLabel}
      // dangerouslySetInnerHTML is fine for static, audited icon paths.
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  );
}

// Convenience: spinning loader variant for "in progress" states.
export function IconSpinner({ size = 16, style }: Omit<IconProps, 'name'>) {
  return (
    <Icon
      name="loader"
      size={size}
      style={{
        animation: 'spin 1s linear infinite',
        ...style,
      }}
    />
  );
}
