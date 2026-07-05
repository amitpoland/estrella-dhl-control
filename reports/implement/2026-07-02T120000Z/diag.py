import sys
with open(r'C:\PZ-verify\service\app\static\v2\pages.jsx','r',encoding='utf-8',newline='') as f:
    c = f.read()
c2 = c.replace('\r\n', '\n')
h1 = '// ── Reports Page'
h2 = '// ── Learning / Parser Page'
print('H1 found:', h1 in c2)
print('H2 found:', h2 in c2)
s = c2.index(h1)
e = c2.index(h2)
span = c2[s:e]
print('span length (chars):', len(span))
print('first 30:', repr(span[:30]))
print('last 30:', repr(span[-30:]))
with open(r'C:\PZ-verify\reports\implement\2026-07-02T120000Z\span_debug.txt','w',encoding='utf-8') as out:
    out.write(span)
