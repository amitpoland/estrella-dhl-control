#!/usr/bin/env python3
# Verify implement-guard.py by execution. Run from repo root: python verify_guard.py
import json, subprocess, os, sys
G = os.path.join(".claude", "hooks", "implement-guard.py")
PY = sys.executable
def run(env, payload):
    p = subprocess.run([PY, G], input=json.dumps(payload),
                       capture_output=True, text=True, env={**os.environ, **env})
    return p.returncode
rm1 = r'Remove-Item -LiteralPath "C:\PZ-verify\service\app\static\v2\shipment-detail-page.v1.jsx"'
rm2 = r'Remove-Item -LiteralPath "C:\PZ-verify\service\app\static\v2\shipment-detail-page.v2.jsx"'
IMP = {"EJ_IMPLEMENT":"1","EJ_CENSUS":""}
DUAL= {"EJ_IMPLEMENT":"1","EJ_CENSUS":"1"}
OFF = {"EJ_IMPLEMENT":"","EJ_CENSUS":""}
PS = r"C:\PZ-verify\.claude\memory\PROJECT_STATE.md"
cases = [
 ("dual-mode any -> deny", DUAL, {"tool_name":"Read","tool_input":{"file_path":"x"}}, 2),
 ("inert rm-recurse -> allow", OFF, {"tool_name":"PowerShell","tool_input":{"command":"Remove-Item -Recurse C:\\"}}, 0),
 ("rm literal 1 -> allow", IMP, {"tool_name":"PowerShell","tool_input":{"command":rm1}}, 0),
 ("rm literal 2 -> allow", IMP, {"tool_name":"PowerShell","tool_input":{"command":rm2}}, 0),
 ("rm + -Force -> deny", IMP, {"tool_name":"PowerShell","tool_input":{"command":rm1+" -Force"}}, 2),
 ("rm -Recurse third path -> deny", IMP, {"tool_name":"PowerShell","tool_input":{"command":r'Remove-Item -Recurse -LiteralPath "C:\PZ-verify\service\app\static\v2\master-page.jsx"'}}, 2),
 ("rm wildcard -> deny", IMP, {"tool_name":"PowerShell","tool_input":{"command":r'Remove-Item -LiteralPath "C:\PZ-verify\service\app\static\v2\*.jsx"'}}, 2),
 ("chained delete -> deny", IMP, {"tool_name":"PowerShell","tool_input":{"command":rm1+" ; rm -rf C:\\"}}, 2),
 ("ro git rev-parse -> allow", IMP, {"tool_name":"Bash","tool_input":{"command":"git rev-parse HEAD:service/app/static/v2/shipment-detail-page.v1.jsx"}}, 0),
 ("ro git status -> allow", IMP, {"tool_name":"Bash","tool_input":{"command":"git status --porcelain -- service/app/static/v2/shipment-detail-page.v1.jsx"}}, 0),
 ("git commit -> deny", IMP, {"tool_name":"Bash","tool_input":{"command":"git commit -m x"}}, 2),
 ("git checkout -> deny", IMP, {"tool_name":"Bash","tool_input":{"command":"git checkout HEAD -- foo"}}, 2),
 ("robocopy -> deny", IMP, {"tool_name":"PowerShell","tool_input":{"command":"robocopy a b /L"}}, 2),
 ("Edit PS header+startswith -> allow", IMP, {"tool_name":"Edit","tool_input":{"file_path":PS,"old_string":"# DECISIONS\n","new_string":"# DECISIONS\n### new\n"}}, 0),
 ("Edit PS no header -> deny", IMP, {"tool_name":"Edit","tool_input":{"file_path":PS,"old_string":"foo","new_string":"foobar"}}, 2),
 ("Edit PS not startswith -> deny", IMP, {"tool_name":"Edit","tool_input":{"file_path":PS,"old_string":"# DECISIONS\n","new_string":"REWRITE"}}, 2),
 ("Write PS -> deny", IMP, {"tool_name":"Write","tool_input":{"file_path":PS}}, 2),
 ("Write slice-record -> allow", IMP, {"tool_name":"Write","tool_input":{"file_path":r"C:\PZ-verify\reports\implement\2026\slice-01.md"}}, 0),
 ("Edit app file -> deny", IMP, {"tool_name":"Edit","tool_input":{"file_path":r"C:\PZ-verify\service\app\main.py","old_string":"a","new_string":"ab"}}, 2),
]
bad=0
for name,env,pl,exp in cases:
    got=run(env,pl); ok=(got==exp); bad+= (0 if ok else 1)
    print(f"[{'OK' if ok else 'FAIL'}] {name}: exit {got} (exp {exp})")
print("\nNOTE: 'Edit PS ...' cases assume DECISIONS_HEADER == '# DECISIONS'. If Step 0")
print("pinned a different header, update these 3 cases' old_string to match, then re-run.")
print("RESULT:", "ALL PASS" if bad==0 else f"{bad} FAILED")
sys.exit(1 if bad else 0)
