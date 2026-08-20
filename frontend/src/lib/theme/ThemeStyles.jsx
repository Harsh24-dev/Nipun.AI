// Global CSS that responds to data attributes for theming
// This component injects a <style> tag with theme-responsive utility classes
export default function ThemeStyles() {
  return (
    <style>{`
      /* Base theme variables applied from JS — these are defaults */
      :root {
        --background: #FAF9F6;
        --surface: #FFFFFF;
        --surface-raised: #FFFFFF;
        --surface-sunken: #F3F1EC;
        --text: #2B2620;
        --text-secondary: #5C554A;
        --text-muted: #6B6459;
        --border: #E7E2D8;
        --border-subtle: #F0ECE4;
        --accent: #C5A059;
        --accent-subtle: #F5EDD8;
        --accent-text: #FFFFFF;
        --destructive: #DC2626;
        --success: #16A34A;
        --warning: #D97706;
        --radius: 0.5rem;
      }

      body {
        background-color: var(--background);
        color: var(--text);
        transition: background-color 0.2s ease, color 0.2s ease;
      }

      /* Motion levels */
      [data-motion="reduced"] * {
        animation-duration: 0.01ms !important;
        transition-duration: 0.05s !important;
      }
      [data-motion="minimal"] * {
        animation-duration: 0.1s !important;
        transition-duration: 0.15s !important;
      }

      /* Density */
      [data-density="spacious"] {
        --spacing-unit: 1.25;
      }
      [data-density="normal"] {
        --spacing-unit: 1;
      }
      [data-density="compact"] {
        --spacing-unit: 0.8;
      }

      /* Focus ring */
      :focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
      }

      /* Motif pattern backgrounds (low opacity) */
      [data-motif="rangoli"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.04;
        background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 5 L55 30 L30 55 L5 30 Z' fill='none' stroke='currentColor' stroke-width='0.5'/%3E%3Ccircle cx='30' cy='30' r='12' fill='none' stroke='currentColor' stroke-width='0.5'/%3E%3C/svg%3E");
        background-size: 60px 60px;
        pointer-events: none;
      }

      [data-motif="paisley"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.03;
        background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 10 Q50 15 45 35 Q40 55 20 45 Q5 35 15 20 Q20 10 30 10Z' fill='none' stroke='currentColor' stroke-width='0.5'/%3E%3C/svg%3E");
        background-size: 60px 60px;
        pointer-events: none;
      }

      [data-motif="jaali"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.04;
        background-image: url("data:image/svg+xml,%3Csvg width='40' height='40' xmlns='http://www.w3.org/2000/svg'%3E%3Crect x='5' y='5' width='30' height='30' rx='15' fill='none' stroke='currentColor' stroke-width='0.4'/%3E%3Crect x='10' y='10' width='20' height='20' rx='10' fill='none' stroke='currentColor' stroke-width='0.3'/%3E%3C/svg%3E");
        background-size: 40px 40px;
        pointer-events: none;
      }

      [data-motif="blockprint"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.03;
        background-image: url("data:image/svg+xml,%3Csvg width='40' height='40' xmlns='http://www.w3.org/2000/svg'%3E%3Crect x='2' y='2' width='16' height='16' fill='currentColor' opacity='0.3'/%3E%3Crect x='22' y='22' width='16' height='16' fill='currentColor' opacity='0.3'/%3E%3C/svg%3E");
        background-size: 40px 40px;
        pointer-events: none;
      }

      [data-motif="warli"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.03;
        background-image: url("data:image/svg+xml,%3Csvg width='50' height='50' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='25' cy='15' r='5' fill='none' stroke='currentColor' stroke-width='0.5'/%3E%3Cline x1='25' y1='20' x2='25' y2='35' stroke='currentColor' stroke-width='0.5'/%3E%3Cline x1='25' y1='28' x2='15' y2='22' stroke='currentColor' stroke-width='0.5'/%3E%3Cline x1='25' y1='28' x2='35' y2='22' stroke='currentColor' stroke-width='0.5'/%3E%3Cline x1='25' y1='35' x2='18' y2='45' stroke='currentColor' stroke-width='0.5'/%3E%3Cline x1='25' y1='35' x2='32' y2='45' stroke='currentColor' stroke-width='0.5'/%3E%3C/svg%3E");
        background-size: 50px 50px;
        pointer-events: none;
      }

      [data-motif="temple"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.04;
        background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 5 L35 20 L50 20 L38 30 L42 45 L30 36 L18 45 L22 30 L10 20 L25 20Z' fill='none' stroke='currentColor' stroke-width='0.4'/%3E%3C/svg%3E");
        background-size: 60px 60px;
        pointer-events: none;
      }

      [data-motif="himalaya"] .motif-bg::before {
        content: '';
        position: absolute;
        inset: 0;
        opacity: 0.03;
        background-image: url("data:image/svg+xml,%3Csvg width='80' height='40' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M0 40 L20 15 L35 28 L50 8 L65 25 L80 12 L80 40Z' fill='none' stroke='currentColor' stroke-width='0.4'/%3E%3C/svg%3E");
        background-size: 80px 40px;
        pointer-events: none;
      }

      /* Scrollbar styling */
      ::-webkit-scrollbar { width: 6px; height: 6px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
      ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

      /* Selection */
      ::selection { background: var(--accent-subtle); color: var(--text); }
    `}</style>
  );
}