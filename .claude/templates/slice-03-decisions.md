<!-- DECISIONS entry (append under "# DECISIONS"). Fill <SHA> and <DATE>. -->

<DATE-UTC> — slice-03: ReportsPage canonical authority = pages-v2.jsx.
pages-v2.jsx loads second in v2/index.html; its window.ReportsPage wins by last-write
(author comment "// overrides the old one"). The pages.jsx copy never executed and is
excised: the Reports function block AND its Object.assign(window,{…}) registration line.
pages.jsx pre-excision HEAD blob SHA: <SHA>.
Reversible: git checkout <SHA> -- service/app/static/v2/pages.jsx
No commit or deploy performed by the slice.
