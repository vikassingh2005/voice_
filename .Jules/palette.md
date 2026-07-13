## 2024-05-24 - Missing Aria-labels on Icon-only Buttons
**Learning:** The application extensively uses SVG icons inside buttons without textual content or accessible names (e.g. chat controls, voice mic, theme settings), rendering them opaque to screen readers. Focus styles were also entirely disabled globally.
**Action:** When adding new interactive components, I will ensure they have `aria-label` or `title` attributes and preserve standard `focus-visible` outlines.
