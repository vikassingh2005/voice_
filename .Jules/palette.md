## 2024-05-18 - [Missing ARIA labels on icon buttons and inputs]
**Learning:** Relied on `title` attributes for tooltips but missed `aria-label`s for screen readers on icon-only buttons (like chat clear, zoom) and important inputs (like chat and terminal). Screen readers need explicit labels when text content is absent.
**Action:** Always ensure icon-only buttons and form inputs have descriptive `aria-label`s, even if a visual `title` tooltip or placeholder is present.
