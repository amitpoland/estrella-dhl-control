# Engineering OS — Version History

Canonical active version: **EJ Engineering OS v1.3** (ratified 2026-07-10).
This file is the evidence-backed delta ledger required by the amendment rule
(`00 §6`): every version step is justified by observed practice in real
packages, never by speculation.

| Version | Name | Date | Status | Evidence (repository) |
|---|---|---|---|---|
| **v1.0** | Foundation | 2026-07-08 | superseded (historical baseline preserved) | `.engineering-os/*` as created 2026-07-08: one canonical authority chain (`00 §2`), capability manifests (`05`, 7 manifests), skill/agent boundaries (`03`/`04` + the two registries), protected-domain gates (`01 §4.6`), 7-agent deploy gate reference (`08`), token economy (`09`), subordination to CLAUDE.md (`00 §4`) |
| **v1.1** | Campaign Execution | ratified 2026-07-10 | folded into v1.3 | Operator ran every 2026-07-10 package under the header "ENGINEERING OS v1.1"; Campaign-Run doctrine (memory `feedback-campaign-run-doctrine`, standing post-MASTER-EXEC-1); delta-verification continuity rule (MASTER-EXEC-1 Campaign Run 7 instruction: "Reuse the completed G1 inspection … perform only a delta verification"); isolated per-package worktrees (`C:\PZ-verify-cr6/-cr7/-cr8/-s2/-s4/-ext1` …); one-implementation-owner + VERIFY/GATE-only second session (PFW Slice 3 concurrency ruling, 2026-07-10); operator gates + evidence-based completion (see v1.2) |
| **v1.2** | Release Certification | ratified 2026-07-10 | folded into v1.3 | Phase-8 Release Certification doctrine (memory `feedback-phase8-release-certification`, operator-mandated 2026-07-10, 14-section evidence-only certification; first applied to PFW Slices 3+4); deploy-source discipline (memory `feedback-deploy-source-discipline`, 3 mandatory steps after the 2026-07-10 double deploy incident); seven-plus false completion claims contradicted by fetch/PR-state/PID evidence on 2026-07-10 → never-seal-from-claims |
| **v1.3** | Operational Excellence & Knowledge Capture | ratified 2026-07-10 | **ACTIVE** | First Phase-9 record set: `docs/governance/campaign-closure-proforma-wireframe-2026-07-10.md` (self-described "Engineering OS v1.3 Phase 9 record": closure record, tech-debt register with dispositions, dependency audit, performance baseline, production health check, knowledge transfer), `docs/decisions/ADR-proforma-wireframe-rebuild.md`, `service/docs/ops/proforma-detail-wireframe-runbook.md`, `docs/campaigns/master-exec-1-closure.md`; Open-PR Disposition Audit (2026-07-10: #877 merged, #878 superseded #808, #799 closed as superseded); continuation-campaign rule (PR #879 rechartered PFW-EXT-1 — "Do not call it Slice 5"); POST-RELEASE STABILIZATION-1 monitoring (caught DEFECT-1 in production) |

## Delta summary (what each step added)

- **v1.0 → v1.1:** the *Campaign Run* became the execution unit — continue from
  the latest stable state, never restart solved work, delta verification over
  rediscovery, isolated worktrees, exactly one implementation owner (a second
  session is VERIFY/GATE only), explicit operator gates, evidence-based
  completion, and the standard campaign output format. Canonical text: `00 §7`.
- **v1.1 → v1.2:** *release certification* — verify Git → deployed disk →
  process → logs → endpoint → business behavior; deployed-file hash matching;
  record main / production / rollback SHAs; never seal from chat claims (false
  claims HALT); deploy-source discipline (source at target SHA before copy,
  `/XD storage`, no destructive mirror, wait-for-STOPPED, RUNNING = done).
  Canonical text: `00 §8` + `08 §6.1`.
- **v1.2 → v1.3:** *operational excellence* — the Phase-9 knowledge-capture
  set (closure record, ADR, runbook, tech-debt register with GATE-4
  dispositions, dependency audit, production health observation, performance
  baseline where relevant), open-PR disposition audits, residue
  classification, the continuation-campaign rule (closed campaigns cannot
  silently gain slices), and post-release stabilization monitoring.
  Canonical text: `00 §9`.

## Evidence ordering note (anti-circularity)

The Phase-9 artifacts cited as v1.3 evidence were produced **by campaign practice, before
this ratification package was chartered**: the PFW closure record, ADR, and runbook were
authored at the PFW campaign's close (2026-07-10, before EOS-UPGRADE-1 existed), and the
MASTER-EXEC-1 closure record likewise at that program's close. Practice preceded canon; this
package codifies observed practice — it did not author its own evidence. One reconciliation
was made in this package: the PFW runbook's deployment step said `/MIR`, contradicting the
non-mirror rule established at the #875/#879 deploy gates — the runbook was corrected to the
canonical `/E` form here (see `08 §6.1`).

## Amendment rule (unchanged in substance from v1.0 §6)

Future changes go into **v1.4+** only with recorded evidence — an observed
failure or friction captured in a real package's record (PROJECT_STATE, a
scorecard, a lesson, a closure record). No recorded evidence = no change.
The v1.0 text is preserved in git history; this ledger is append-only.
