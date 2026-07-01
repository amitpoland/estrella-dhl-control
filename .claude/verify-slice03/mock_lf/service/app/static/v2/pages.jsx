// ── Wfirma Export Page
function WfirmaExportPage() {
  return React.createElement(Card, null, 'wfirma');
}

// ── Reports Page
function ReportsPage() {
  const months = ['Jan','Feb'];
  const data = [1,2,3];
  return React.createElement(Card, null, 'r');
}

// ── Learning / Parser Page
function LearningParserPage() {
  return React.createElement(Card, null, 'learning');
}

Object.assign(window, {
  DhlClearancePage,
  WfirmaExportPage,
  ReportsPage,
  LearningParserPage,
  AdminSettingsPage,
});
