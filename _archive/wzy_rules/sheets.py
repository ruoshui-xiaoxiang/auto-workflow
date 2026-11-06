# -*- coding: utf-8 -*-
"""把资产包剩余锚点拼成 3 张联络表，供逐张目视写定妆词。"""
import os, numpy as np, cv2
D = r'E:\创作\武昭君仪\武昭君仪资产包'
def get(tag):
    for f in os.listdir(D):
        if f.startswith(tag): return os.path.join(D, f)
    return None
def sheet(tags, cell, name, cols):
    ims = []
    for t in tags:
        p = get(t)
        im = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) if p else None
        if im is None: continue
        r = cell / max(im.shape[:2])
        im = cv2.resize(im, None, fx=r, fy=r, interpolation=cv2.INTER_AREA)
        h, w = im.shape[:2]
        c = np.full((h + 34, w, 3), 250, np.uint8)
        c[:h] = im
        cv2.putText(c, t, (8, h + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        ims.append(c)
    rows = [ims[i:i+cols] for i in range(0, len(ims), cols)]
    out = []
    for rw in rows:
        H = max(x.shape[0] for x in rw)
        rw = [np.pad(x, ((0, H-x.shape[0]), (0,0), (0,0)), constant_values=255) for x in rw]
        out.append(np.hstack(rw))
    W = max(x.shape[1] for x in out)
    out = [np.pad(x, ((0,0),(0,W-x.shape[1]),(0,0)), constant_values=255) for x in out]
    g = np.vstack(out)
    cv2.imencode('.jpg', g, [cv2.IMWRITE_JPEG_QUALITY, 86])[1].tofile('prev/' + name)
    print(name, g.shape[::-1])
sheet(['A03','A06','A07','A08','A09','A10'], 620, 'sheet_chars.jpg', 3)
sheet(['P02','P03','P04','P05'], 620, 'sheet_props.jpg', 2)
sheet(['SC01','SC02','SC04','SC05','SC06','SC07','SC08','ST01'], 520, 'sheet_scenes.jpg', 4)
