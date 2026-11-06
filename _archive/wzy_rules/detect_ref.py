# -*- coding: utf-8 -*-
import numpy as np, cv2, os
from insightface.app import FaceAnalysis
D=r"D:/AIWorkflow/tmp/wzy/ref"
app=FaceAnalysis(name="buffalo_l", allowed_modules=["detection","recognition"])
app.prepare(ctx_id=-1, det_size=(640,640))
for f in ("junyi_ref1.jpg","junyi_ref2.jpg"):
    im=cv2.imdecode(np.fromfile(os.path.join(D,f),dtype=np.uint8),cv2.IMREAD_COLOR)
    h,w=im.shape[:2]
    fs=app.get(im)
    print("==",f,"img",w,"x",h,"faces",len(fs))
    for x in fs:
        b=x.bbox.astype(int); print("   det=%.3f bbox=%s face_px=%dx%d"%(x.det_score,tuple(b),b[2]-b[0],b[3]-b[1]))
        e=x.normed_embedding
        print("   emb_norm=%.3f  first3=%s"%(np.linalg.norm(e), np.round(e[:3],3)))
if len(os.listdir(D))>=2:
    a=app.get(cv2.imdecode(np.fromfile(os.path.join(D,"junyi_ref1.jpg"),dtype=np.uint8),cv2.IMREAD_COLOR))
    b=app.get(cv2.imdecode(np.fromfile(os.path.join(D,"junyi_ref2.jpg"),dtype=np.uint8),cv2.IMREAD_COLOR))
    if a and b:
        print("sim(ref1,ref2)=%.3f"%float(np.dot(a[0].normed_embedding,b[0].normed_embedding)))
