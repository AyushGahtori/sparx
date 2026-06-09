# SPARX Control Center Enterprise UI Redesign

## Scope

This redesign is frontend-only. Backend APIs, routes, payloads, response formats, authentication flow, data models, and integrations remain unchanged.

Protected frontend contracts:

- `frontend/js/config.js`
- `frontend/js/router.js`
- `frontend/js/services/api.js`

## UI Architecture

- App shell: persistent left navigation, sticky top navigation, responsive main content.
- Design system: shared CSS tokens in `frontend/css/global.css`.
- Page styling: shell and page-specific enterprise surfaces in `frontend/css/dashboard.css`.
- Forms: shared field, filter, focus, and action styles in `frontend/css/forms.css`.
- Data grids: shared table, row, and detail styles in `frontend/css/tables.css`.
- Components: sidebar, navbar, modal, loading, table, and notification utilities.

## Global Components

- Sidebar: primary navigation for Dashboard, Manual Calls, Campaigns, Callbacks, Meetings, Call History, AI Summaries, and Settings.
- Topbar: page title, global command search, system status, environment badge, API docs link, dark mode toggle, notifications, and operator profile.
- Command palette: `Ctrl+K` global navigation for all major workflows.
- Theme toggle: persisted light/dark mode via `localStorage`.
- Status pills: connected, warning, offline, running, completed, failed, priority, and lead-intent states.
- Panels/cards: glass-style enterprise cards with soft borders and shadows.

## Page Wireframes

Home:
- Hero control center
- Quick workflow actions
- System health
- Module coverage
- Recent processed calls

Dashboard:
- KPI cards: Total Calls, Active Campaigns, Callback Queue, Meetings Scheduled, AI Success Rate, Conversion Rate
- Analytics strip: calls, meetings, campaigns, callback completion
- Recent calls data grid
- Campaign status widget
- Callback queue widget
- Quick actions

Manual AI Calling:
- Guided workflow: Contact, Agent, Configure, Live Status, Results
- Contact and call configuration form
- Real-time call status panel

Campaign Management:
- Campaign creation workspace
- Lead file preview
- Campaign dashboard with search, filters, progress bars, status, contacts, success rate, last activity, and actions
- Campaign data rollup

Callback Queue:
- Callback creation form
- Queue snapshot
- Task-management grid with priority, due date, source, status, retry count, and quick actions

Meeting Details:
- CRM-style page header
- Tabs: Summary, Transcript, Follow-Ups, Activity Timeline, AI Insights
- Meeting sync and metrics
- Meeting data grid

Call History:
- Advanced search and filters
- Modern data grid with contact, campaign, outcome, duration, timestamp, lead type, and actions

AI Summaries:
- AI signal cards for sentiment, meeting potential, next best action, and confidence
- Summary dashboard with filters, export, status indicators, and detail actions

Settings & Diagnostics:
- Runtime health
- Google OAuth
- Operator links
- Configuration map for general settings, integrations, API status, and logs

## Design Tokens

Primary:
- `#4F46E5`
- `#6366F1`

Success:
- `#10B981`

Warning:
- `#F59E0B`

Danger:
- `#EF4444`

Neutral:
- Slate palette via CSS variables

Radius:
- Cards and panels: 14-16px
- Inputs and buttons: 10-12px

Interaction:
- Smooth hover/focus transitions
- Accessible focus outlines
- Reduced-motion support
- Responsive desktop, laptop, tablet, and mobile layouts
