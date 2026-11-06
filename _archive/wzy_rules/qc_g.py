# -*- coding: utf-8 -*-
import numpy as np, cv2, os
from insightface.app import FaceAnalysis
REF=r"D:/AIWorkflow/tmp/wzy/ref/junyi_ref1.jpg"
D=r"D:/AIWorkflow/tmp/wzy/dz0g"
app=FaceAnalysis(name="buffalo_l", allowed_modules=["detection","recognition"])
app.prepare(ctx_id=-1, det_size=(640,640))
def get(p):
    im=cv2.imdecode(np.fromfile(p,dtype=np.uint8),cv2.IMREAD_COLOR)
    fs=app.get(im); return (im,fs)
rim,rfs=get(REF)
re_=rfs[0].normed_embedding
print("ref face_px=%dx%d"%(rfs[0].bbox[2]-rfs[0].bbox[0], rfs[0].bbox[3]-rfs[0].bbox[1]))
for k in ("R1","R2","R3","C1","C2"):
    im,fs=get(os.path.join(D,k+".png"))
    if not fs:
        print("%-3s 检出 0 张脸 -> 身份不可机判"%k); continue
    x=fs[0]; b=x.bbox.astype(int)
    sim=float(np.dot(re_, x.normed_embedding))
    print("%-3s det=%.2f face=%dx%d  sim(ref)=%.3f %s"%(
        k,x.det_score,b[2]-b[0],b[3]-b[1],sim,"同人" if sim>=0.5 else "不像"))
