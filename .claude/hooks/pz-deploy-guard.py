#!/usr/bin/env python
"""
PZ deploy / merge / push-to-main PreToolUse guard.

Purpose: BLOCK (permissionDecision="deny") operator-only actions that must never
be executed by Claude Code:
  1. copy/write INTO the production tree (C:\\PZ) via shell
  2. execution of the canonical deployment script or a runtime-config writer
  3. control of the production service (PZService)
  4. gh pr merge
  5. git push to main / origin main
  6. Edit/Write a file under C:\\PZ (closes the direct file-write path)

These are reserved for the human operator. The deploy-guard is a hard DENY
authority — not an "ask".

CLASSIFY THE ACTION, NOT THE TEXT (2026-08-20)
----------------------------------------------
The guard used to deny any command whose text merely CONTAINED "deploy-pz.ps1".
That made `sed -n ... Deploy-PZ.ps1`, `git diff -- ...Deploy-PZ.ps1`,
`Get-FileHash ...Deploy-PZ.ps1` and even `echo "Deploy-PZ.ps1"` unrunnable:
15 of 16 measured read-only inspections were denied. A protected filename in
command text is NOT evidence of execution — it is usually evidence of reading.

The guard now splits the command into shell segments and asks, per segment,
whether the protected token is DATA being read or CODE being executed. A segment
whose head command is a known read-only verb, with no in-place/write flag, no
output redirection and no command substitution, is classified ALLOW_READ. Every
other shape containing a protected token stays denied. The default is unchanged:
anything not provably read-only fails closed.

Wiring: registered as a PreToolUse hook in .claude/settings.json under TWO
matchers:
  - "Bash|PowerShell" — guards shell commands (rules 1-5)
  - "Edit|Write"      — guards file_path writes into C:\\PZ (rule 6)

Behaviour:
  - Guarded shell command         -> permissionDecision="deny", exit 0.
  - Guarded Edit|Write file_path  -> permissionDecision="deny", exit 0.
  - Unparseable payload           -> permissionDecision="ask",  exit 0 (FAIL CLOSED).
  - Otherwise                     -> exit 0 with NO output (must never block
                                     ordinary commands or edits).

KNOWN RESIDUAL (accepted, documented): a heredoc whose BODY contains a
production path plus a write verb is denied, because `bash <<EOF` executes its
body and the two cases are indistinguishable in text. Create such files with the
Write tool, not with shell heredocs.

Output is written as raw UTF-8 bytes so non-ASCII reason text cannot trip
a cp1252 Windows console (Lesson L).
"""
import sys
import os
import json
import re


# ---- Protected tokens ------------------------------------------------------

# 'C:\PZ' as a path token: exact, or followed by \ or /. Case-insensitive.
# Negative lookahead excludes C:\PZ-verify (followed by '-') and C:\PZAPP
# (followed by alphanumeric). Also covers C:/PZ variants.
# The SAME directory has three spellings on this host: the Windows form
# (C:\\PZ), the forward-slash form (C:/PZ), and the MSYS/Git Bash mount form
# (/c/PZ) -- which is what the Bash tool produces natively, so it is the form
# an agent reaches for first. Recognising only the drive-letter spellings left
# `cp -r service/app/. /c/PZ/app/` unguarded: a whole-tree production overwrite
# the classifier called read-only. A guard that can be evaded by spelling is
# not a guard. `(?![\w\-])` still keeps C:\\PZ-verify and /c/PZ-main out.
PROD_PZ_RX = re.compile(
    r"(?:(?<![\w\-])/cygdrive/c/|(?<![\w\-])/c/|c:[\\/])pz(?![\w\-])",
    re.IGNORECASE,
)

# The canonical deployment script. Matched by NAME because the script is
# configuration-driven: its command line carries no production path token, so the
# path-based rule cannot see it. Covers Deploy-PZ.ps1 however it is invoked
# (relative, absolute, via &, via powershell -File). Name-matching alone is NOT
# the decision — see _segment_is_read_only: the name only matters in a segment
# that actually executes something.
DEPLOY_SCRIPT_RX = re.compile(r"deploy-pz\.ps1", re.IGNORECASE)

# Scripts that write production RUNTIME CONFIGURATION (C:\PZ\.env) rather than code.
# They are matched by NAME for the same reason as the deploy script: their command
# lines carry no C:\PZ token, so the path rule cannot see them. .env controls live
# service behaviour (API keys, write-gate flags), so running one is an operator action.
RUNTIME_CONFIG_SCRIPT_RX = re.compile(
    r"env_config_manager\.ps1|activate_pz_lifecycle\.py", re.IGNORECASE
)

# Control of the production Windows service. A control VERB plus the PZService
# TARGET, tested independently so pipeline order cannot evade the match
# (`Get-Service PZService | Stop-Service` reads target-before-verb).
# CLAUDE.md core rule 3: never stop or modify PZService.
SERVICE_VERB_RX = re.compile(
    r"\b(?:sc(?:\.exe)?|nssm(?:\.exe)?|net)\s+(?:stop|start|restart|config|delete|failure)\b"
    r"|\b(?:stop|start|restart|set|remove|new)-service\b",
    re.IGNORECASE,
)
SERVICE_TARGET_RX = re.compile(r"pzservice", re.IGNORECASE)

# Piping a read into an interpreter turns the read into an execution:
#   git show HEAD:...Deploy-PZ.ps1 | powershell -
# Each segment looks innocent alone (segment 1 is a genuine read, segment 2
# names nothing protected), so this is caught on the whole command instead.
PIPE_TO_INTERPRETER_RX = re.compile(
    r"\|\s*&?\s*(?:powershell|pwsh|cmd|bash|sh|zsh|python\d?|node|perl|ruby"
    r"|iex|invoke-expression)\b",
    re.IGNORECASE,
)

# An encoded PowerShell command cannot be classified from its text at all.
ENCODED_COMMAND_RX = re.compile(
    r"-e(?:c|nc|ncoded|ncodedcommand)?\s+[A-Za-z0-9+/=]{16,}", re.IGNORECASE
)

# Verbs that place bytes somewhere. Used together with a production path.
WRITE_VERB_RX = re.compile(
    r"\brobocopy\b|\bxcopy\b|copy-item\b|move-item\b|set-content\b|add-content\b"
    r"|out-file\b|new-item\b|remove-item\b|\bcp\b|\bmv\b|\btee\b",
    re.IGNORECASE,
)


# ---- Read-only vocabulary --------------------------------------------------
# A conservative allowlist. Anything absent is NOT read-only, so growth of the
# shell vocabulary cannot silently weaken the guard.

READ_ONLY_HEADS = frozenset(
    # POSIX / Git Bash
    "cat head tail sed awk grep egrep fgrep rg ack less more nl wc file stat ls "
    "dir find diff cmp md5sum sha1sum sha256sum echo printf cut sort uniq tr jq "
    "xxd od basename dirname realpath readlink true pwd date which type comm tee0"
    .split()
    +
    # PowerShell (lower-cased; aliases included)
    "get-content gc type select-string sls get-item gi get-childitem gci "
    "get-filehash get-acl get-itemproperty compare-object measure-object "
    "out-string out-host write-host write-output format-list format-table "
    "resolve-path test-path convertfrom-json convertto-json select-object "
    "where-object sort-object group-object".split()
)

# `git` is read-only only for these subcommands. `git push` / `git commit` etc.
# fall through to the normal rules.
GIT_READ_ONLY_SUBCOMMANDS = frozenset(
    "show diff log ls-files ls-tree cat-file grep blame status rev-parse "
    "describe show-ref merge-base shortlog name-rev rev-list whatchanged "
    # hash-object is how a deploy is byte-verified against the repo, and
    # ls-remote/for-each-ref are pure queries. Their absence made the
    # verification step of a deploy look like an unclassifiable write.
    "diff-tree config hash-object ls-remote for-each-ref".split()
)

# git subcommands that write only inside the LOCAL REPOSITORY. They take file
# paths and prose as arguments and can neither execute what they name nor reach
# C:\PZ, so a protected filename in `git commit -m "fix Deploy-PZ.ps1 guard"` is
# prose, not an invocation. `push` is deliberately absent -- it is rule
# 'git-push-main'.
GIT_LOCAL_WRITE_SUBCOMMANDS = frozenset("commit add tag stash notes".split())

# `gh` subcommands that carry PROSE about the repository -- a PR title, body or
# comment describing deployment work. They cannot execute a named script and
# cannot reach C:\PZ. `gh pr merge` is deliberately absent: it keeps its own
# Council-authorized gate, which runs on the whole command.
GH_PROSE_RX = re.compile(
    r"^\s*gh\s+(?:pr|issue)\s+(?:create|edit|comment|view|list|status|diff|checks)\b",
    re.IGNORECASE,
)

# Splits a command into independently-classified segments.
SEGMENT_SPLIT_RX = re.compile(r"&&|\|\||[;|\n]")

# Command substitution / expansion — the segment's real content is not visible.
SUBSTITUTION_RX = re.compile(r"\$\(|\$\{|`|@\(")

# Output redirection. `2>/dev/null` and `2>&1` are diagnostic noise suppression,
# not writes, and are the only forms tolerated inside a read-only segment.
BENIGN_REDIRECT_RX = re.compile(r"\d?>\s*(?:&\d|/dev/null|\$null|nul)\b", re.IGNORECASE)
ANY_REDIRECT_RX = re.compile(r">")

# In-place / write flags for otherwise-read-only stream editors.
INPLACE_RX = re.compile(r"(?:^|\s)-{1,2}[a-z]*i(?:[a-z]*)?(?:\s|$|\.)|in-?place", re.IGNORECASE)
STREAM_EDITORS = frozenset(["sed", "awk", "perl", "ruby"])


# Shell escape / quote characters that split a protected token without changing
# what the shell executes: PowerShell backtick, cmd caret, and quote characters
# (`.\Dep"loy-PZ.ps1`, ``.\Deploy-PZ.ps`1``). Token detection runs on a
# normalised copy so escaping cannot hide the name. Detection only -- the raw
# segment is what the read-only test inspects.
ESCAPE_NOISE_RX = re.compile(r"[`^\"']")


def _normalise(text):
    """Lower-cased text with shell escape/quote noise removed, for token matching."""
    return ESCAPE_NOISE_RX.sub("", text).lower()


def _is_prod_pz_path(text):
    """Return True if `text` contains a 'C:\\PZ' path token (case-insensitive,
    backslash or forward-slash separator). Matches C:\\PZ exactly or C:\\PZ\\...,
    C:\\PZ/.... Does NOT match C:\\PZ-verify\\..., C:\\Users\\Super Fashion\\PZ APP."""
    if not text:
        return False
    return PROD_PZ_RX.search(text) is not None


REDIRECT_TARGET_RX = re.compile(r"\d?>>?\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>]+)")


def _redirects_into_protected(command):
    """True only when a redirect's TARGET is inside the production tree.

    The previous rule asked whether the command mentioned a production path
    *anywhere* and contained a redirect *anywhere*, then treated two
    independent facts as one. `cat >> notes.md <<'EOF'` whose body quotes the
    production marker path satisfied both and was refused, though it writes to
    notes.md. A protected path in a heredoc body, a grep pattern or an echo
    string is prose; only the destination of a redirect is an operation.
    """
    stripped = BENIGN_REDIRECT_RX.sub("", command)
    for target in REDIRECT_TARGET_RX.findall(stripped):
        target = target.strip("\"'")
        if (_is_prod_pz_path(target)
                or DEPLOY_SCRIPT_RX.search(target)
                or RUNTIME_CONFIG_SCRIPT_RX.search(target)):
            return True
    return False


HEREDOC_RX = re.compile(r"<<-?\s*(['\"]?)(\w+)\1\n.*?^\2$", re.S | re.M)
INTERPRETER_HEADS = frozenset(
    "python python3 py powershell pwsh bash sh zsh node perl ruby cmd".split()
)


def _strip_heredoc_prose(command):
    """Drop heredoc BODIES, which are data rather than operands.

    `cat >> notes.md <<'MD' ... MD` whose body quotes a production path was read
    as several nonsense segments ('marker at C:\\PZ\\version.txt'), none of them
    provably read-only, and the fail-closed rule refused the whole command --
    while it only ever writes notes.md.

    The body is data ONLY when nothing executes it. If any segment head is an
    interpreter the body is code, so it is left in place and classified in full.
    """
    heads = {
        _segment_head(seg).split(" ", 1)[0]
        for seg in SEGMENT_SPLIT_RX.split(command)
        if seg.strip()
    }
    if heads & INTERPRETER_HEADS:
        return command
    return HEREDOC_RX.sub(lambda m: "<<" + m.group(2), command)


def _segment_head(segment):
    """The executable word of a segment, lower-cased. '' when there is none.

    `git <sub>` collapses to 'git <sub>' so read-only git subcommands can be
    allowed without allowing `git push`.
    """
    tokens = segment.strip().split()
    if not tokens:
        return ""
    head = tokens[0].strip("'\"").lower()
    if head == "git" and len(tokens) > 1:
        return "git " + tokens[1].strip("'\"").lower()
    return head


def _segment_is_read_only(segment):
    """True when this segment provably only READS.

    Read-only requires ALL of:
      - head command is in the read-only vocabulary (git: read-only subcommand),
      - no command substitution (content would be invisible to us),
      - no output redirection other than stderr suppression,
      - no in-place flag on a stream editor.
    Everything else is not provably read-only and therefore is not read-only.
    """
    head = _segment_head(segment)
    if not head:
        return False

    if head.startswith("git "):
        if head.split(" ", 1)[1] not in GIT_READ_ONLY_SUBCOMMANDS:
            return False
    elif head not in READ_ONLY_HEADS:
        return False

    if SUBSTITUTION_RX.search(segment):
        return False

    # A redirect matters here only when it writes somewhere PROTECTED. Refusing
    # every redirect made `grep ... > report.txt` and `echo ... > /tmp/note`
    # unclassifiable the moment the text happened to mention a production path.
    if _redirects_into_protected(segment):
        return False

    base = head.split(" ", 1)[0]
    if base in STREAM_EDITORS and INPLACE_RX.search(segment):
        return False

    return True


# ---- Payload extraction ----------------------------------------------------
def _extract_command(data):
    """Pull the shell command from a PreToolUse payload, tolerating simplified
    test payloads that put 'command' at the top level."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    if isinstance(data.get("command"), str):
        return data["command"]
    return ""


def _extract_file_path(data):
    """Pull file_path from a PreToolUse payload, tolerating simplified test
    payloads that put 'file_path' at the top level."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str):
        return tool_input["file_path"]
    if isinstance(data.get("file_path"), str):
        return data["file_path"]
    return ""


# ---- Classification --------------------------------------------------------
# Structured verdicts. `classify_command` returns None (allow) or a dict.
BLOCK_DEPLOY_OPERATOR_ONLY = "BLOCK_DEPLOY_OPERATOR_ONLY"
BLOCK_PRODUCTION_WRITE = "BLOCK_PRODUCTION_WRITE"
BLOCK_UNKNOWN = "BLOCK_UNKNOWN"


def _blocked(result, rule, operation, reason, authority="operator"):
    return {
        "result": result,
        "matched_rule": rule,
        "operation": operation,
        "reason": reason,
        "authority_required": authority,
    }


def _segment_is_inert(segment):
    """True when a segment can neither execute what it names nor write outside
    the local repository: a read-only command, or a local-repository git write."""
    if _segment_is_read_only(segment):
        return True
    if SUBSTITUTION_RX.search(segment):
        return False
    if GH_PROSE_RX.search(segment):
        return True
    head = _segment_head(segment)
    return (
        head.startswith("git ")
        and head.split(" ", 1)[1] in GIT_LOCAL_WRITE_SUBCOMMANDS
    )


def _command_is_inert(command):
    """True when EVERY segment is inert.

    Such a command carries no execution and no write outside the repository, so
    protected names inside it are prose, pathspecs or search patterns -- a commit
    message describing PZService control, a grep for a robocopy line. Checked
    before the whole-command rules, which otherwise match their own description.
    """
    segments = [s for s in SEGMENT_SPLIT_RX.split(command) if s.strip()]
    return bool(segments) and all(_segment_is_inert(s) for s in segments)


def classify_command(command):
    """Return None when the command may proceed, else a structured block dict.

    Order: inert commands short-circuit, then whole-command production-mutation
    rules (they hold however the command is shaped), then per-segment
    protected-token rules.
    """
    if _command_is_inert(command):
        return None

    low = _normalise(command)

    # --- whole-command production mutation ---------------------------------
    if SERVICE_VERB_RX.search(low) and SERVICE_TARGET_RX.search(low):
        return _blocked(
            BLOCK_PRODUCTION_WRITE, "service-control", "PRODUCTION_MUTATION",
            "controlling the production service (PZService) is operator-only",
        )

    if ENCODED_COMMAND_RX.search(low):
        return _blocked(
            BLOCK_UNKNOWN, "encoded-command", "UNKNOWN",
            "an encoded command cannot be classified; unclassifiable execution fails closed",
        )

    names_protected = (
        DEPLOY_SCRIPT_RX.search(low) is not None
        or RUNTIME_CONFIG_SCRIPT_RX.search(low) is not None
        or _is_prod_pz_path(low)
    )
    if names_protected and PIPE_TO_INTERPRETER_RX.search(low):
        return _blocked(
            BLOCK_DEPLOY_OPERATOR_ONLY, "pipe-to-interpreter", "DEPLOY_EXECUTION",
            "piping protected deployment content into an interpreter executes it; "
            "read it without the pipe instead",
        )

    if _redirects_into_protected(command):
        return _blocked(
            BLOCK_PRODUCTION_WRITE, "redirect-into-prod", "PRODUCTION_MUTATION",
            "redirecting output into C:\\PZ is a production write and is operator-only",
        )

    # --- per-segment classification ----------------------------------------
    for segment in SEGMENT_SPLIT_RX.split(_strip_heredoc_prose(command)):
        if not segment.strip():
            continue
        seg_low = _normalise(segment)

        touches_prod = _is_prod_pz_path(seg_low)
        names_deploy = DEPLOY_SCRIPT_RX.search(seg_low) is not None
        names_config = RUNTIME_CONFIG_SCRIPT_RX.search(seg_low) is not None

        if not (touches_prod or names_deploy or names_config):
            continue  # nothing protected in this segment

        # An inert segment names the protected token as data, a pathspec or
        # prose: reading a protected file (production files included), a local
        # git write, a PR description. One definition, shared with the
        # whole-command short-circuit above.
        if _segment_is_inert(segment):
            continue

        # 1. copy/write into the production tree (C:\PZ)
        if touches_prod and WRITE_VERB_RX.search(seg_low):
            return _blocked(
                BLOCK_PRODUCTION_WRITE, "deploy-to-prod-PZ", "PRODUCTION_MUTATION",
                "copy/write into C:\\PZ is operator-only",
            )

        # 2. Execution of the canonical deployment script.
        #    Deploy-PZ.ps1 reads every production path from windows_prod_v2.json, so
        #    the command text an agent would run ('.\\Deploy-PZ.ps1') contains NO
        #    C:\\PZ token and the path rule above would not fire. Rollback is equally
        #    production-mutating and is denied by the same rule. Reading the script
        #    was already permitted above.
        if names_deploy:
            return _blocked(
                BLOCK_DEPLOY_OPERATOR_ONLY, "deploy-script-invocation", "DEPLOY_EXECUTION",
                "requested execution of the canonical production deploy script "
                "Deploy-PZ.ps1 (-WhatIf is also denied to the agent: use the operator "
                "shell). Reading, diffing and hashing the script are permitted",
            )

        # 3. Runtime-configuration writers. Same name-matching rationale as 2.
        if names_config:
            return _blocked(
                BLOCK_DEPLOY_OPERATOR_ONLY, "runtime-config-write", "PRODUCTION_MUTATION",
                "this script writes production runtime configuration (C:\\PZ\\.env) "
                "and is operator-only. Reading it is permitted",
            )

        # 4. A production path in a segment that is not provably read-only and
        #    carries no recognised write verb: unclassifiable. Fail closed.
        if touches_prod:
            return _blocked(
                BLOCK_UNKNOWN, "unclassified-prod-touch", "UNKNOWN",
                "this command reaches into C:\\PZ in a way the guard cannot classify "
                "as read-only; ambiguous production access fails closed",
            )

    # --- merge / push authority (whole command) ----------------------------
    # gh pr merge — Council-authorized merge gate
    # (ADR-council-authorized-merge-gate). Default-OFF + FAIL-CLOSED: a narrowly
    # scoped, machine-verifiable authorization check. With no flag / no trusted
    # signing key / no signed authorization artifact (the current repository state
    # — no CI signer), evaluate_merge ALWAYS returns "deny", so the merge denial is
    # NOT weakened. Protected files / guard self-modification / non-squash / stale
    # head / expired / consumed / unsigned all deny. Validator error also denies.
    if "gh pr merge" in low:
        try:
            _hook_dir = os.path.dirname(os.path.abspath(__file__))
            if _hook_dir not in sys.path:
                sys.path.insert(0, _hook_dir)
            from merge_authorization import evaluate_merge as _evaluate_merge
            decision, reason = _evaluate_merge(command)
        except Exception as _exc:  # fail closed on ANY error
            decision, reason = ("deny", "merge-authorization validator error: "
                                + type(_exc).__name__)
        if decision != "allow":
            return _blocked(
                BLOCK_DEPLOY_OPERATOR_ONLY, "gh-pr-merge", "PRODUCTION_MUTATION",
                "gh pr merge is operator-only unless Council-authorized — " + reason,
            )

    # git push to main / origin main
    if "git push" in low and re.search(r"git\s+push\b[^\n]*\bmain\b", low):
        return _blocked(
            BLOCK_DEPLOY_OPERATOR_ONLY, "git-push-main", "PRODUCTION_MUTATION",
            "git push to main is operator-only",
        )

    return None


# ---- Output ----------------------------------------------------------------
def _emit(decision, reason):
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    try:
        sys.stdout.buffer.write(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        sys.stdout.buffer.flush()
    except Exception:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")))


# ---- BOM-transparent stdin (Lesson L) --------------------------------------
def _read_stdin_json():
    """Return parsed JSON payload, or None on read/parse failure (fail-closed
    sentinel — caller emits 'ask')."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            raw = sys.stdin.read()
        except Exception:
            return None
    raw = raw.lstrip("\ufeff").lstrip("ï»¿").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return None


def main():
    data = _read_stdin_json()
    if data is None:
        # Fail CLOSED — surface to operator rather than silently allowing.
        _emit("ask", "PZ deploy-guard: ERROR — could not parse PreToolUse payload; confirm before running.")
        return 0

    # Shell-command path (Bash|PowerShell matcher) ---------------------------
    command = _extract_command(data)
    if command.strip():
        verdict = classify_command(command)
        if verdict is not None:
            _emit(
                "deny",
                "PZ deploy-guard: {result} (rule '{matched_rule}', operation "
                "{operation}) — {reason}. Authority required: {authority_required}.".format(
                    **verdict
                ),
            )
            return 0

    # File-path write path (Edit|Write matcher) ------------------------------
    file_path = _extract_file_path(data)
    if file_path.strip() and _is_prod_pz_path(file_path):
        _emit(
            "deny",
            f"PZ deploy-guard: {BLOCK_PRODUCTION_WRITE} (rule 'prod-tree-edit') — "
            f"Edit/Write into prod tree '{file_path}'. C:\\PZ is operator-only; "
            f"never edit production files directly.",
        )
        return 0

    # ordinary command/edit — silent, never blocks
    return 0


if __name__ == "__main__":
    sys.exit(main())
