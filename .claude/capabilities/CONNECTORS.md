# CONNECTORS.md — Atlas V2 Capability Registry: MCP Servers & Connectors

**Generated:** 2026-06-06 · **Source:** session deferred-tools list + CLAUDE.md connector config
**Canonical tree:** `C:\PZ-verify` · No product code modified.

> MCP connector IDs are session-scoped. The canonical production channel and
> connector are defined in CLAUDE.md: `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`,
> production channel `pz` (ID: `O190928000006027001`).

---

## Summary

| # | Connector | MCP ID prefix | Domain | Production-relevant | Risk level |
|---|---|---|---|---|---|
| 1 | Zoho Cliq (Estrella — primary) | `1760d1e3` | Notifications / PZ results | ✅ YES — production channel `#PZ` | MEDIUM (sends real messages) |
| 2 | Zoho Cliq (instance 2) | `7048b607` | Notifications | possible | MEDIUM |
| 3 | Zoho Cliq (instance 3 — full) | `8dbdc202` | Notifications + reactions | possible | MEDIUM |
| 4 | Zoho WorkDrive | `4f7fda89` | File storage / sharing | ✅ YES — PDF/XLSX upload | MEDIUM (publishes files) |
| 5 | Zoho Mail (admin — full) | `620999a3` | Email / org management | ✅ YES — SMTP path | HIGH (sends real email) |
| 6 | Zoho Mail (personal) | `87b5e553` | Email (personal) | possible | HIGH |
| 7 | Zoho Mail (instance 3) | `91ffe2f1` | Email | possible | HIGH |
| 8 | Zoho CRM | `18d17982` | CRM / customer records | indirect | HIGH (writes CRM records) |
| 9 | Fireflies | `9da61b35` | Meeting transcripts | NO | LOW |
| 10 | Claude Preview MCP | `Claude_Preview` | Dev server browser | ✅ YES — GATE 6 browser smoke | SAFE_READ_ONLY |
| 11 | Claude in Chrome | `Claude_in_Chrome` | Browser automation | QA use only | MEDIUM (DOM writes) |
| 12 | Figma | `b0cacd37` | Design | NO | LOW |
| 13 | Computer Use | `computer-use` | Desktop automation | QA / manual ops | HIGH (full desktop) |
| 14 | CCD Session | `ccd_session` | Session management | governance | LOW |
| 15 | CCD Session Mgmt | `ccd_session_mgmt` | Session archive/search | governance | LOW |
| 16 | CCD Directory | `ccd_directory` | Directory lookup | governance | LOW |
| 17 | Calendar | `d0b77486` | Calendar events | NO | LOW |
| 18 | Drive/Files | `dae2e8f7` | File read/copy | NO | LOW |
| 19 | MCP Registry | `mcp-registry` | Discover MCP servers | NO | LOW |
| 20 | Scheduled Tasks | `scheduled-tasks` | Create/list/update cron | ⚠️ system scheduling | HIGH (system-level) |
| 21 | Postman | `85a817b5` | API collections | development only | MEDIUM |

---

## Per-Connector Detail

---

### CN1. Zoho Cliq — Estrella (PRIMARY, production-bound)

| Field | Value |
|---|---|
| **Name** | Zoho Cliq — Estrella (primary) |
| **MCP Connector ID** | `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce` |
| **CLAUDE.md reference** | §"Available integration" — named connector: `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce`, org `60014108075`, production channel `pz` (ID `O190928000006027001`) |
| **Purpose** | Post final batch results to the `#PZ` production channel. The CLAUDE.md-mandated channel for all PZ batch completions. |
| **Tools available** | `ZohoCliq_Post_message_in_a_channel`, `ZohoCliq_Post_message_in_chat`, `ZohoCliq_Post_message_to_a_bot`, `ZohoCliq_Post_message_to_a_user`, `ZohoCliq_Retrieve_*`, `ZohoCliq_Get_*`, `ZohoCliq_List_*`, `ZohoCliq_Create_and_send_a_thread_message` |
| **R/W level** | WRITE — posts real messages to live channel |
| **Production risk** | MEDIUM — messages are visible to the team |
| **Classification** | WRITE_RISK |
| **Recommended use** | Final batch result posting to `#PZ`. CLAUDE.md: "Always post immediately after PZ completion — WorkDrive state does not block it." |
| **Forbidden use** | Never send local file paths or localhost URLs in Cliq. Never block notification because WorkDrive failed. Never use as the calculation engine — Cliq is a notification layer only. |

---

### CN2. Zoho Cliq (instance 2)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__7048b607-a66c-445b-82a6-f28dbc154915` |
| **Purpose** | Second Zoho Cliq instance. Tool set slightly smaller (no `Add_a_Bot_to_a_Channel`, `Share_files_to_a_channel`, `Add_a_custom_domain`, etc.). |
| **R/W level** | WRITE — posts to Cliq |
| **Production risk** | MEDIUM |
| **Classification** | WRITE_RISK |
| **Recommended use** | If primary connector (CN1) unavailable. Confirm org context before use. |
| **Forbidden use** | Do not use in place of CN1 for production `#PZ` posting without confirming it targets the same org/channel. |

---

### CN3. Zoho Cliq (instance 3 — fullest tool set)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__8dbdc202-2e47-4304-be59-040ecf4de2ee` |
| **Purpose** | Zoho Cliq with the largest tool set — includes reactions, records (database-style), teams, departments, call history. |
| **Tools available** | Post/Retrieve/Share + `Add_a_reaction`, `Add_a_record`, `List_records`, `Retrieve_a_record`, `Update_a_record`, `Get_Team_Members`, `Get_Department_Members`, `Get_Department_Details`, `List_all_Departments`, `Retrieve_Calls_and_Meeting_History`, `Get_Participants_of_a_call_or_meeting`, `Get_Reactions` |
| **R/W level** | WRITE — records, reactions, messages |
| **Production risk** | MEDIUM |
| **Classification** | WRITE_RISK |
| **Recommended use** | Advanced Cliq operations (reactions, record management). Not needed for standard PZ batch posting. |
| **Forbidden use** | Same as CN1/CN2. Do not mix channels between Cliq instances without confirmation. |

---

### CN4. Zoho WorkDrive

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__4f7fda89-6328-4825-b707-0bd598183cb2` |
| **Purpose** | Upload PDFs/XLSXs, create external share links, fetch file lists, manage team folders. Part of the PZ batch completion workflow (WorkDrive REST = primary upload). |
| **Tools available** | `ZohoWorkdrive_Create_External_Share`, `ZohoWorkdrive_Create_New_File`, `ZohoWorkdrive_Upload_File`, `ZohoWorkdrive_Fetch_Files_Folders`, `ZohoWorkdrive_Get_File_List`, `ZohoWorkdrive_Get_Team_Folder_Files`, `ZohoWorkdrive_Download_Server_File`, `ZohoWorkdrive_Search_Records`, `ZohoWorkdrive_Update_Files_Folders`, `ZohoWorkdrive_Get_*`, `ZohoWorkdrive_Create_Team_Folder` |
| **R/W level** | WRITE — uploads files to WorkDrive (publishable) |
| **Production risk** | MEDIUM — published files may be cached/indexed |
| **Classification** | WRITE_RISK |
| **Recommended use** | After `process_batch()` → get `workdrive_pdf_resource_id` + `workdrive_xlsx_resource_id` from the response → create external share links → post to Cliq. |
| **Forbidden use** | Never search WorkDrive for files — resource IDs come from the API response. Never wait for TrueSync (not a cloud upload path). If share link creation fails: report explicitly; never block Cliq notification. |

---

### CN5. Zoho Mail (admin — full tool set)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__620999a3-8e04-40ac-88f9-184d3824e310` |
| **Purpose** | Full admin-level Zoho Mail. Includes org management, domain management, user management, policy management, forwarding rules — and email send. |
| **Tools available** | 100+ tools including send, reply, labels, folders, archive, spam, move, delete, flag, user management, group management, domain management, org settings, forwarding, restrictions, DKIM, SPF, IMAP, POP, vacation reply, tasks |
| **R/W level** | FULL-WRITE — sends real email, manages org-level settings |
| **Production risk** | HIGH — real SMTP, org-level config changes |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Email evidence recovery (read tools only: `listEmails`, `getMessageContent`, `getMessageAttachmentContent`, `searchThreads`, `readMessages`). Admin operations by explicit operator instruction only. |
| **Forbidden use** | Never use `sendEmail` or `sendReplyEmail` without explicit operator approval. Never modify org settings, forwarding rules, or user accounts without explicit authorization. Lesson E (5 email safety properties) applies to ANY automated email sending path. |

---

### CN6. Zoho Mail (personal)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__87b5e553-e695-4b73-9ff9-e5fcf0c70b15` |
| **Purpose** | Personal Zoho Mail account access (read + send). |
| **Tools available** | Subset of CN5: send, reply, read, labels, folders, archive, spam, move, delete, flag, tasks, attachments |
| **R/W level** | WRITE — sends real email from personal account |
| **Production risk** | HIGH |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Email reading only. Send only with explicit operator approval. |
| **Forbidden use** | Autonomous email sending. Lesson E applies. |

---

### CN7. Zoho Mail (instance 3)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__91ffe2f1-cbfe-4d9c-94c1-75e16e37b57f` |
| **Purpose** | Third Zoho Mail instance (personal-tier, similar to CN6). |
| **R/W level** | WRITE — sends real email |
| **Production risk** | HIGH |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Read-only email evidence. Explicit approval for any send. |
| **Forbidden use** | Same as CN6. |

---

### CN8. Zoho CRM

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__18d17982-f361-4765-bfb7-b92df7360cca` |
| **Purpose** | Read/write Zoho CRM records (contacts, leads, accounts, custom modules), execute COQL queries, manage territories, layouts, fields. |
| **Tools available** | `getRecords`, `getRecord`, `createRecords`, `updateRecord`, `updateRecords`, `deleteRecord`, `deleteRecords`, `searchRecords`, `executeCOQLQuery`, `getFields`, `getLayouts`, `getModules`, `getTags`, `createTags`, `convertInventory`, `getRelatedRecords`, `getTimelines`, `getBulkReadJobDetails`, `updateRelatedRecords`, `upsertRecords`, `postAddTags`, `getAllTerritories`, `getAssignmentRules`, `getOrganization`, `getVariables`, `getSingleUser`, `getUsers`, `updateUser`, `updateSingleUser` |
| **R/W level** | FULL-WRITE — creates, updates, deletes CRM records |
| **Production risk** | HIGH — live CRM mutations |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Customer/contractor lookup (read-only via `searchRecords`, `getRecord`). Write operations only with explicit operator approval. |
| **Forbidden use** | Autonomous CRM record creation/update/delete without operator confirmation. |

---

### CN9. Fireflies

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__9da61b35-14a2-4802-932c-f0a289d8f82d` |
| **Purpose** | Access meeting transcripts, summaries, soundbites, analytics. Search across recorded meetings. |
| **Tools available** | `fireflies_get_transcripts`, `fireflies_get_transcript`, `fireflies_get_summary`, `fireflies_fetch`, `fireflies_search`, `fireflies_get_analytics`, `fireflies_get_soundbites`, `fireflies_create_soundbite`, `fireflies_get_active_meetings`, `fireflies_get_user`, `fireflies_get_user_contacts`, `fireflies_get_usergroups`, `fireflies_list_channels`, `fireflies_get_channel`, `fireflies_move_meeting`, `fireflies_share_meeting`, `fireflies_update_meeting_privacy`, `fireflies_update_meeting_title`, `fireflies_revoke_meeting_access`, `fireflies_get_rule_executions` |
| **R/W level** | READ (mostly) + limited write (move/share/title/privacy) |
| **Production risk** | LOW — meeting data, no financial risk |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Meeting transcript analysis. Brand voice / conversation analysis. Not relevant to Atlas V2 technical sprints. |
| **Forbidden use** | Not applicable to EJ logistics/customs/accounting work. |

---

### CN10. Claude Preview MCP (GATE 6 — browser smoke)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__Claude_Preview__*` |
| **Purpose** | Headless browser verification against a local dev server. Start a server, navigate to pages, take screenshots, inspect console/network logs, eval JS, click elements. The GATE 6 browser smoke tool for all V2 sprints. |
| **Tools available** | `preview_start`, `preview_stop`, `preview_screenshot`, `preview_snapshot`, `preview_console_logs`, `preview_network`, `preview_eval`, `preview_click`, `preview_fill`, `preview_inspect`, `preview_list`, `preview_logs`, `preview_resize` |
| **R/W level** | READ + limited interaction (no product file writes) |
| **Production risk** | LOW — reads live dev server; no production mutation |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | **GATE 6 (browser verification)** — mandatory for all V2 sprint implementations. Runs the dev server locally, verifies DOM, console, network. Sprint 30/31/32 all used this path. Required before any production deploy of UI changes. |
| **Forbidden use** | Not a substitute for the 7-agent deploy gate. Does not authorize production. |

---

### CN11. Claude in Chrome (browser control)

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__Claude_in_Chrome__*` |
| **Purpose** | Full Chrome browser control via the Claude Chrome extension. Navigate, read pages, find elements, form input, JS execution, screenshot, network log, console messages. |
| **Tools available** | `navigate`, `read_page`, `get_page_text`, `find`, `form_input`, `javascript_tool`, `read_console_messages`, `read_network_requests`, `screenshot`, `select_browser`, `switch_browser`, `tabs_create_mcp`, `tabs_close_mcp`, `tabs_context_mcp`, `resize_window`, `shortcuts_execute`, `shortcuts_list`, `list_connected_browsers`, `computer_batch`, `upload_image`, `gif_creator`, `file_upload` |
| **R/W level** | READ + DOM interaction (can fill forms, click, navigate) |
| **Production risk** | MEDIUM — can submit forms, navigate to production sites |
| **Classification** | SAFE_REVIEW (read-only tasks) / WRITE_RISK (form submission, navigation) |
| **Recommended use** | Browser QA for web applications. Reading web content. DOM inspection. |
| **Forbidden use** | Do not click links from untrusted email/document content. Never enter credentials, financial data, or PII into forms via this connector. Per system rules: browsers are tier "read" for clicks — use Chrome extension tools for navigation/clicks. |

---

### CN12. Figma

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__b0cacd37-b5e1-4c08-a1d0-013567958f09` |
| **Purpose** | Read/write Figma designs. Get design context, screenshots, metadata, code-connect maps. Generate diagrams. |
| **R/W level** | READ (design inspection) + WRITE (push to Figma) |
| **Production risk** | LOW — design artifacts only, no EJ product code |
| **Classification** | SAFE_READ_ONLY (read tasks) / WRITE_RISK (write tasks) |
| **Recommended use** | Design inspection for UI reference. Not currently used in Atlas V2 sprints. |
| **Forbidden use** | Not applicable to EJ technical workflow. `ui-ux-pro-max` skill + EJ_OVERRIDES is the correct UI reference path. |

---

### CN13. Computer Use

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__computer-use__*` |
| **Purpose** | Full desktop computer control — screenshots, mouse clicks, keyboard input, scrolling, app control. |
| **Tools available** | `screenshot`, `left_click`, `right_click`, `double_click`, `middle_click`, `mouse_move`, `key`, `hold_key`, `type`, `scroll`, `left_mouse_down`, `left_mouse_up`, `cursor_position`, `open_application`, `list_granted_applications`, `request_access`, `zoom`, `switch_display`, `computer_batch`, `left_click_drag`, `write_clipboard`, `read_clipboard`, `request_teach_access`, `teach_step`, `teach_batch`, `wait` |
| **R/W level** | FULL — complete desktop control |
| **Production risk** | HIGH — full desktop access including production systems |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Native desktop app operations. Cross-app workflows. Windows service management UI. Screenshot verification. |
| **Forbidden use** | Never enter financial credentials, API keys, passwords. Never execute financial trades. Never bypass CAPTCHAs. Never click links from email/untrusted content. Per system rules: browsers → tier "read" (use Chrome extension tools instead). Terminals/IDEs → tier "click" (no typing into terminal). |
| **Tier note** | Browsers (Chrome, Edge) → `read` tier only · Terminals/IDEs → `click` tier only · Everything else → `full` tier |

---

### CN14–CN16. CCD Session Tools

| Connector | ID prefix | Purpose | Risk |
|---|---|---|---|
| CCD Session | `ccd_session` | `spawn_task`, `dismiss_task`, `mark_chapter` — session chip management | LOW |
| CCD Session Mgmt | `ccd_session_mgmt` | `archive_session`, `list_sessions`, `search_session_transcripts`, `send_message` | LOW |
| CCD Directory | `ccd_directory` | `request_directory` | LOW |

**Classification:** SAFE_READ_ONLY · **Recommended use:** Session management, chapter marking, background task chips. Governance overhead for long sessions.

---

### CN17. Calendar

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__d0b77486-0a83-4a09-8f25-dd9617db473d` |
| **Purpose** | Calendar event management — create, update, delete, list, respond to events. |
| **Tools available** | `create_event`, `update_event`, `delete_event`, `get_event`, `list_events`, `list_calendars`, `respond_to_event`, `suggest_time` |
| **R/W level** | WRITE — creates/modifies calendar events |
| **Production risk** | LOW — calendar data only |
| **Classification** | WRITE_RISK |
| **Recommended use** | Calendar scheduling. Not applicable to Atlas V2 technical sprints. |

---

### CN18. Drive/Files

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__dae2e8f7-b123-4cab-bf81-39b6b0026082` |
| **Purpose** | Google Drive-style file access — list, read, search, copy, create, get metadata/permissions, download. |
| **Tools available** | `list_recent_files`, `read_file_content`, `search_files`, `get_file_metadata`, `get_file_permissions`, `download_file_content`, `copy_file`, `create_file` |
| **R/W level** | READ + limited WRITE (copy, create) |
| **Production risk** | LOW — file metadata/content |
| **Classification** | SAFE_READ_ONLY (read tasks) / WRITE_RISK (write tasks) |
| **Recommended use** | Reading/searching shared drive files. Not currently used in Atlas V2 sprints. |

---

### CN19. MCP Registry

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__mcp-registry__*` |
| **Purpose** | Discover and search MCP server registry for new connectors. |
| **Tools available** | `list_connectors`, `search_mcp_registry`, `suggest_connectors` |
| **R/W level** | READ-ONLY |
| **Production risk** | NONE |
| **Classification** | SAFE_READ_ONLY |
| **Recommended use** | Discovering new MCP connectors. Meta-capability research. |

---

### CN20. Scheduled Tasks

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__scheduled-tasks__*` |
| **Purpose** | Create, list, and update scheduled tasks (cron jobs / Windows Task Scheduler equivalent). |
| **Tools available** | `create_scheduled_task`, `list_scheduled_tasks`, `update_scheduled_task` |
| **R/W level** | WRITE — creates/modifies system scheduling |
| **Production risk** | HIGH — can create recurring system tasks |
| **Classification** | PRODUCTION_RISK |
| **Recommended use** | Explicit operator-authorized task scheduling only. **Never create a scheduled task that touches email, wFirma, customs, or production data without full Lesson E compliance + operator approval.** |
| **Forbidden use** | Autonomous task creation. Background email automation without all 5 Lesson E safety properties. CLAUDE.md forbids Task Scheduler changes without explicit campaign approval. |

---

### CN21. Postman

| Field | Value |
|---|---|
| **MCP Connector ID** | `mcp__85a817b5-9d21-4844-9a7e-d26ea9e48bb2` |
| **Purpose** | Postman API — manage collections, environments, mocks, specs, workspaces. |
| **R/W level** | READ + WRITE (collections, specs) |
| **Production risk** | MEDIUM — Postman data; no direct EJ production risk |
| **Classification** | SAFE_READ_ONLY (read) / WRITE_RISK (create/update) |
| **Recommended use** | API documentation, collection management. Development aid. |
| **Forbidden use** | Not applicable to Atlas V2 production sprints. |

---

## Production-Critical Connectors (summary)

For EJ Atlas V2 production work, these are the connectors that matter:

| Priority | Connector | Why critical | CLAUDE.md reference |
|---|---|---|---|
| P1 | Zoho Cliq — Estrella (CN1) | Final batch result posting to `#PZ` — mandatory after every PZ batch | §"Available integration" + §"Required workflow" |
| P2 | Claude Preview MCP (CN10) | GATE 6 browser smoke — mandatory for all UI sprints | §"GATE 6" |
| P3 | Zoho WorkDrive (CN4) | PDF/XLSX upload after batch; resource IDs from API response | §"WorkDrive automation flow" |
| P4 | Zoho Mail — admin (CN5) | Email evidence recovery (read-only path) | §email-evidence chain |
| P5 | Computer Use (CN13) | Windows service management, production shell ops | §"Production deployment rule" |

All other connectors are auxiliary or non-applicable to Atlas V2 work.
