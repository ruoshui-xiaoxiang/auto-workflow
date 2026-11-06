# -*- coding: utf-8 -*-
# 核对：那份建议里的具名设定，到底在不在我们的正文/大纲/剧本里。
# 规矩（提示词先验第7条）：凡"原文没有的具名物件"必须单独标成假设，不能当需求。
import os, re, zipfile, glob

D = r'E:/创作/武昭君仪'
TERMS = ['疤', '义体', '义肢', '电路', '剑', '玄色', '丹凤', '金色', '能量核心', '霓虹',
         '赛博', '机械', '高马尾', '深褐', '琉璃', '凤眸', '月白', '深海蓝', '银',
         '白麻布', '长矛', '槊', '枪']

def docx_text(p):
    try:
        with zipfile.ZipFile(p) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    except Exception as e:
        return ''
    xml = re.sub(r'</w:p>', '\n', xml)
    return re.sub(r'<[^>]+>', '', xml)

docs = {}
for p in glob.glob(os.path.join(D, '**', '*.docx'), recursive=True):
    if '~$' in os.path.basename(p): continue
    t = docx_text(p)
    if t: docs[os.path.relpath(p, D)] = t
for p in glob.glob(os.path.join(D, '**', '*.md'), recursive=True):
    io = open(p, encoding='utf-8', errors='ignore')
    docs[os.path.relpath(p, D)] = io.read(); io.close()

print('读到 %d 份文档：' % len(docs))
for k in docs: print('   ', k)
print()
print('%-10s %-6s  命中文档' % ('术语', '次数'))
for t in TERMS:
    hits = []
    n = 0
    for k, v in docs.items():
        c = v.count(t)
        if c:
            hits.append('%s(%d)' % (k, c)); n += c
    print('%-10s %-6d  %s' % (t, n, '; '.join(hits[:4]) if hits else '—— 全部文档 0 次'))
print()
print('=== 「剑」的全部上下文（判它是道具还是别的东西）===')
for k, v in docs.items():
    for m in re.finditer('剑', v):
        s = v[max(0, m.start()-28):m.start()+28].replace('\n', ' ')
        print('  [%s] …%s…' % (k, s))
print()
print('=== 「疤」的全部上下文 ===')
for k, v in docs.items():
    for m in re.finditer('疤', v):
        s = v[max(0, m.start()-30):m.start()+30].replace('\n', ' ')
        print('  [%s] …%s…' % (k, s))
print()
print('=== 「义体/电路/机械」上下文 ===')
for k, v in docs.items():
    for t in ['义体', '电路', '机械']:
        for m in re.finditer(t, v):
            s = v[max(0, m.start()-30):m.start()+30].replace('\n', ' ')
            print('  [%s/%s] …%s…' % (k, t, s))