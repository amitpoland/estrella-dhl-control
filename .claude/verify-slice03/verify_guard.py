#!/usr/bin/env python3
"""verify_guard.py - slice-03 MERGED guard. Proof by execution against
self-built CRLF and LF mocks, both BODY shapes, both incoming line-ending forms."""
import json, os, subprocess, sys

HERE  = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.normpath(os.path.join(HERE, "..", "hooks", "implement-guard.py"))
H1 = "// ── Reports Page"
H2 = "// ── Learning / Parser Page"

LINES = ["// ── Wfirma Export Page","function WfirmaExportPage() {",
 "  return React.createElement(Card, null, 'wfirma');","}","",H1,
 "function ReportsPage() {","  const months = ['Jan','Feb'];",
 "  const data = [1,2,3];","  return React.createElement(Card, null, 'r');","}",
 "",H2,"function LearningParserPage() {",
 "  return React.createElement(Card, null, 'learning');","}","",
 "Object.assign(window, {","  DhlClearancePage,","  WfirmaExportPage,",
 "  ReportsPage,","  LearningParserPage,","  AdminSettingsPage,","});",""]

def build_mocks():
    for eol, label in (("\r\n","crlf"), ("\n","lf")):
        d = os.path.join(HERE, "mock_"+label, "service","app","static","v2")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d,"pages.jsx"),"w",encoding="utf-8",newline="") as f:
            f.write(eol.join(LINES))

def disk_lf(label):
    p = os.path.join(HERE,"mock_"+label,"service","app","static","v2","pages.jsx")
    with open(p,"r",encoding="utf-8",newline="") as f:
        return f.read().replace("\r\n","\n")

def crlf(s): return s.replace("\n","\r\n")

def run(payload, env_extra, label):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = os.path.join(HERE, "mock_"+label)
    env.pop("EJ_CENSUS",None); env.pop("EJ_IMPLEMENT",None); env.update(env_extra)
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(payload).encode(),
                       capture_output=True, env=env)
    return p.returncode, p.stderr.decode()

IMPL={"EJ_IMPLEMENT":"1"}; DUAL={"EJ_IMPLEMENT":"1","EJ_CENSUS":"1"}
PJX="C:/PZ-verify/service/app/static/v2/pages.jsx"
PV2="C:/PZ-verify/service/app/static/v2/pages-v2.jsx"
PS="C:/PZ-verify/.claude/memory/PROJECT_STATE.md"
fail=0; total=0
def check(name,payload,env,expect,label):
    global fail,total
    total+=1
    rc,err=run(payload,env,label)
    ok = rc==expect
    if not ok:
        fail+=1
        print("[**FAIL**] exit=%d expect=%d [%s] %s" % (rc,expect,label,name))
        if err.strip(): print("   ", err.strip().splitlines()[-1])
    else:
        print("[PASS] [%s] %s" % (label,name))

def edit(old,new,path=PJX):
    return {"tool_name":"Edit","tool_input":{"file_path":path,"old_string":old,"new_string":new}}

build_mocks()
for label in ("crlf","lf"):
    d = disk_lf(label)
    span_empty = d[d.index(H1):d.index(H2)]            # primary: H1..pre-H2
    span_fb    = d[d.index(H1):d.index(H2)+len(H2)]    # fallback: H1..H2 incl
    for form,fn in (("lf",lambda s:s),("crlf",crlf)):
        check("BODY empty-new (incoming %s)"%form, edit(fn(span_empty),""), IMPL,0,label)
        check("BODY fallback (incoming %s)"%form, edit(fn(span_fb),fn(H2) if form=="crlf" else H2), IMPL,0,label)
    reg_old="  WfirmaExportPage,\n  ReportsPage,\n  LearningParserPage,"
    reg_new="  WfirmaExportPage,\n  LearningParserPage,"
    check("REG (lf)", edit(reg_old,reg_new), IMPL,0,label)
    check("REG (crlf)", edit(crlf(reg_old),crlf(reg_new)), IMPL,0,label)

L="crlf"; d=disk_lf(L)
span_empty=d[d.index(H1):d.index(H2)]; span_fb=d[d.index(H1):d.index(H2)+len(H2)]
check("DECISIONS append", edit("# DECISIONS\n","# DECISIONS\nentry\n",PS), IMPL,0,L)
check("slice-record Write", {"tool_name":"Write","tool_input":{"file_path":"C:/x/reports/implement/t/r.md","content":"r"}}, IMPL,0,L)
check("ro git status", {"tool_name":"Bash","tool_input":{"command":"git status --porcelain -- x"}}, IMPL,0,L)
check("inert when unset", {"tool_name":"Write","tool_input":{"file_path":"C:/any","content":"x"}}, {},0,L)
check("BODY empty-new wrong span", edit(span_empty+"X",""), IMPL,2,L)
check("BODY empty-new with fallback-shaped old (incl H2)", edit(span_fb,""), IMPL,2,L)
check("BODY fallback variant", edit(span_fb+"X",H2), IMPL,2,L)
check("REG removes wrong line", edit("  WfirmaExportPage,\n  ReportsPage,\n  LearningParserPage,","  ReportsPage,\n  LearningParserPage,"), IMPL,2,L)
check("REG new==old", edit("  WfirmaExportPage,\n  ReportsPage,\n  LearningParserPage,","  WfirmaExportPage,\n  ReportsPage,\n  LearningParserPage,"), IMPL,2,L)
check("Edit pages-v2 denied", edit("a","b",PV2), IMPL,2,L)
check("Write pages.jsx denied", {"tool_name":"Write","tool_input":{"file_path":PJX,"content":"x"}}, IMPL,2,L)
check("MultiEdit denied", {"tool_name":"MultiEdit","tool_input":{"file_path":PJX,"edits":[]}}, IMPL,2,L)
check("dual-mode fail-closed", edit(span_empty,""), DUAL,2,L)
check("git commit denied", {"tool_name":"Bash","tool_input":{"command":"git commit -m x"}}, IMPL,2,L)
check("git add denied", {"tool_name":"Bash","tool_input":{"command":"git add -A"}}, IMPL,2,L)
check("shell operator denied", {"tool_name":"Bash","tool_input":{"command":"git status && rm x"}}, IMPL,2,L)
check("non-git shell denied", {"tool_name":"Bash","tool_input":{"command":"robocopy a b"}}, IMPL,2,L)
check("DECISIONS no header", edit("x","xy",PS), IMPL,2,L)
check("DECISIONS not startswith", edit("# DECISIONS\n","z# DECISIONS\n",PS), IMPL,2,L)

print(); print("%d/%d PASS" % (total-fail,total))
sys.exit(1 if fail else 0)
