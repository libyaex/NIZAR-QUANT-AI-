import type { ReactNode } from 'react';
const I = ({ children }: { children: ReactNode }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);
export const Icons = {
  home: <I><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></I>,
  scan: <I><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></I>,
  chart: <I><path d="M4 20V4" /><path d="M4 20h16" /><path d="M8 15l4-5 3 3 5-7" /></I>,
  bolt: <I><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></I>,
  list: <I><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" /></I>,
  clock: <I><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></I>,
  stats: <I><path d="M5 20V10M12 20V4M19 20v-7" /></I>,
  target: <I><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></I>,
  link: <I><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 00-5.7 0l-3 3A4 4 0 0011 18.7l1-1" /></I>,
  gear: <I><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 00-.1-1.3l2-1.5-2-3.4-2.3.9a7 7 0 00-2.2-1.3L14 3h-4l-.4 2.4a7 7 0 00-2.2 1.3l-2.3-.9-2 3.4 2 1.5a7 7 0 000 2.6l-2 1.5 2 3.4 2.3-.9a7 7 0 002.2 1.3L10 21h4l.4-2.4a7 7 0 002.2-1.3l2.3.9 2-3.4-2-1.5c.1-.4.1-.9.1-1.3z" /></I>,
  more: <I><circle cx="5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="19" cy="12" r="1.2" /></I>,
  logout: <I><path d="M9 21H5V3h4M16 17l5-5-5-5M21 12H9" /></I>,
};
