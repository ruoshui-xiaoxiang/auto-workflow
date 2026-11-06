# -*- coding: utf-8 -*-
r"""图文对齐 ＋ 美学打分（clip_score.py）·给图片"逐条断言落地没有"的读数。

## 为什么建这个
今天一整轮 A/B 都缺同一把尺：提示词里写了六个元素，进画几个只能我肉眼数；
"大气散射""冷暖分离"这类装置落没落地，也只有人眼看。这个脚本把它变成可复算的数：
**Chinese-CLIP 文本塔 × 图像塔余弦**，一条断言一条分。

## 三条口径（写死在这里，免得三个月后没人记得）
1. **对齐分是相对量不是绝对量**：CLIP 余弦的绝对值没有物理意义，只有"同一张图上
   A 断言比 B 断言高多少""同一断言在图 1 比图 2 高多少"可比。**跨模型跨版本不可比。**
2. **必须先回测方向再拿去排序**（`--backtest`）：拿已知正例（画面里真有）与负例（真没有）跑，
   要求 正例 > 负例；分不开或反号，这把尺当场作废，不许出结论。
   —— 今天已经翻车四次（暖色红块掩膜、重复像素、连通域计数、肤内高频），规矩定了就不许绕。
3. **美学分是 LAION 口味不是我们的口味**：它的训练标注是大众打分，
   和"用户实圈可用率"不是一回事。所以它进不了任何判据，只当旁证列，
   并且要拿 S6 那批"9 坏 / 27 好"的已知标注回测它到底分不分得开（那批 13 根尺子最大分离度只有 0.62）。

## 用法
  py -3 clip_score.py align    --imgs <目录或文件> --claims claims.txt [--out 表.csv]
  py -3 clip_score.py aesthetic --imgs <目录或文件>
  py -3 clip_score.py backtest  --pos 正例图 --neg 负例图 --claims 单条断言.txt
"""
import argparse
import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", r"D:\AIWorkflow\models\hf")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

CC = "OFA-Sys/chinese-clip-vit-large-patch14"
OA = "openai/clip-vit-large-patch14"
AES_REPO = "camenduru/improved-aesthetic-predictor"      # 镜像上 christophschuhmann/shunk031 两个都 401
AES_FILE = "sac+logos+ava1-l14-linearMSE.pth"             # v1 头，输入 768 维＝OpenAI CLIP ViT-L/14
CH = 768


def rd(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def wr_png(p, im):
    ok, buf = cv2.imencode(".png", im)
    buf.tofile(p)


def imgs_of(arg):
    out = []
    for a in arg:
        if os.path.isdir(a):
            out += [os.path.join(a, f) for f in sorted(os.listdir(a))
                    if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        elif os.path.isfile(a):
            out.append(a)
    return out


def device():
    if not torch.cuda.is_available():
        return "cpu"
    free, tot = torch.cuda.mem_get_info()
    return "cuda" if free > 3_200_000_000 else "cpu"   # ComfyUI 常占 12 GB，剩太少就走 CPU


class Align:
    """Chinese-CLIP：中文断言 ↔ 图像 余弦。"""

    def __init__(self, dev=None):
        from transformers import ChineseCLIPModel, ChineseCLIPProcessor
        self.dev = dev or device()
        self.m = ChineseCLIPModel.from_pretrained(CC).to(self.dev).eval()
        if self.dev == "cuda":
            self.m = self.m.half()
        self.p = ChineseCLIPProcessor.from_pretrained(CC)
        print("对齐模型 = Chinese-CLIP ViT-L/14，设备 %s" % self.dev, file=sys.stderr)

    @torch.no_grad()
    def embed_img(self, paths, bs=4):
        feats = []
        for i in range(0, len(paths), bs):
            ims = []
            for p in paths[i:i + bs]:
                im = rd(p)
                ims.append(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
            x = self.p(images=ims, return_tensors="pt").to(self.dev)
            if self.dev == "cuda":
                x["pixel_values"] = x["pixel_values"].half()
            feats.append(self.m.get_image_features(**x).float().cpu().numpy())
        f = np.concatenate(feats)
        return f / np.linalg.norm(f, axis=1, keepdims=True)

    @torch.no_grad()
    def embed_txt(self, texts, bs=16):
        out = []
        for i in range(0, len(texts), bs):
            b = texts[i:i + bs]
            x = self.p(text=b, return_tensors="pt", padding=True, truncation=True).to(self.dev)
            out.append(self.m.get_text_features(**x).float().cpu().numpy())
        f = np.concatenate(out)
        return f / np.linalg.norm(f, axis=1, keepdims=True)


class Aes:
    """OpenAI CLIP ViT-L/14 图像特征 ＋ LAION improved-aesthetic-predictor 头。"""

    def __init__(self, dev=None):
        from transformers import CLIPModel, CLIPProcessor
        import torch.nn as nn
        self.dev = dev or device()
        self.m = CLIPModel.from_pretrained(OA).to(self.dev).eval()
        if self.dev == "cuda":
            self.m = self.m.half()
        self.p = CLIPProcessor.from_pretrained(OA)
        from huggingface_hub import hf_hub_download
        w = [hf_hub_download(repo_id=AES_REPO, filename=AES_FILE)]
        # 这份 .pth 的键是 layers.0/2/4/6/7（无 dropout，最后两层之间不过 ReLU），
        # 与官方 README 里那版带 Dropout 的结构不同——照权重形状建，别照记忆建。
        class Head(nn.Module):
            def __init__(self):
                super().__init__()
                self.layers = nn.Sequential(
                    nn.Linear(CH, 1024), nn.ReLU(),
                    nn.Linear(1024, 128), nn.ReLU(),
                    nn.Linear(128, 64), nn.ReLU(),
                    nn.Linear(64, 16), nn.Linear(16, 1))

            def forward(self, x):
                return self.layers(x)
        sd = torch.load(w[0], map_location="cpu", weights_only=True)
        self.head = Head()
        self.head.load_state_dict(sd)
        self.head = self.head.to(self.dev).eval()
        self.pth = w[0]
        print("美学头 = %s，设备 %s" % (os.path.basename(w[0]), self.dev), file=sys.stderr)

    @torch.no_grad()
    def __call__(self, paths, bs=4):
        out = []
        for i in range(0, len(paths), bs):
            ims = [cv2.cvtColor(rd(p), cv2.COLOR_BGR2RGB) for p in paths[i:i + bs]]
            x = self.p(images=ims, return_tensors="pt").to(self.dev)
            if self.dev == "cuda":
                x["pixel_values"] = x["pixel_values"].half()
            f = self.m.get_image_features(**x).float()
            # ⚠️ 不要 L2 归一化。官方 README 那段是归一化的，但这份 .pth 不是那么训的：
            #    归一化后六张极端样本（纯黑/噪声/中灰/两张生成图/一张参考图）极差只有 0.462，
            #    不归一化是 8.041 且排序合理（噪声 2.28 < 中灰 3.68 < 纯黑 4.12 < 实拍 5.5~10.3）。
            #    归一化＝把输入缩到单位球，头里那几层大权重直接进饱和区，输出变成常数。
            out += [float(v) for v in self.head(f).flatten()]
        return out


def load_claims(path):
    lines = [l.strip() for l in open(path, encoding="utf-8").read().split("\n")]
    return [l for l in lines if l and not l.startswith("#")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["align", "aesthetic", "backtest"])
    ap.add_argument("--imgs", nargs="+", required=True)
    ap.add_argument("--claims")
    ap.add_argument("--pos", nargs="+")
    ap.add_argument("--neg", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()
    dev = "cpu" if a.cpu else None
    files = imgs_of(a.imgs)
    if not files:
        raise SystemExit("没有可读的图")

    if a.mode == "aesthetic":
        s = Aes(dev)
        print("# 美学分（LAION 口味，非判据）头=%s" % os.path.basename(s.pth))
        for p, v in zip(files, s(files)):
            print("  %-9.3f  %s" % (v, os.path.basename(p)))
        return 0

    al = Align(dev)
    claims = load_claims(a.claims) if a.claims else []
    if a.mode == "align":
        if not claims:
            raise SystemExit("align 需要 --claims")
        ti = al.embed_txt(claims)
        ii = al.embed_img(files)
        S = ii @ ti.T
        print("  %-42s %s" % ("图", "  ".join("%-8s" % ("C%d" % i) for i in range(len(claims)))))
        for j, p in enumerate(files):
            print("  %-42s %s" % (os.path.basename(p)[:42], "  ".join("%-8.3f" % v for v in S[j])))
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write("file," + ",".join('"%s"' % c for c in claims) + "\n")
                for j, p in enumerate(files):
                    f.write('"%s",%s\n' % (p, ",".join("%.4f" % v for v in S[j])))
            print("表 -> %s" % a.out)
        return 0

    # backtest：同一条断言在正例上必须高于负例
    pos, neg = imgs_of(a.pos), imgs_of(a.neg)
    if not claims or not pos or not neg:
        raise SystemExit("backtest 需要 --claims(单条) --pos --neg")
    ti = al.embed_txt(claims)
    vp = (al.embed_img(pos) @ ti.T).mean(axis=1) if len(ti) == 1 else None
    if len(ti) > 1:
        print("多条断言：逐条在正/负例上的均值差")
        P = (al.embed_img(pos) @ ti.T).mean(axis=0)
        N = (al.embed_img(neg) @ ti.T).mean(axis=0)
        good = 0
        for k, c in enumerate(claims):
            d = P[k] - N[k]
            okf = d > 0
            good += okf
            print("   %-46s 正%.3f 负%.3f 差%+.3f %s" % (c[:46], P[k], N[k], d, "✓" if okf else "🔴反号"))
        print("⇒ %d/%d 方向正确" % (good, len(claims)))
    else:
        P = (al.embed_img(pos) @ ti.T).flatten()
        N = (al.embed_img(neg) @ ti.T).flatten()
        print("断言：%s" % claims[0])
        print("  正例 n=%d 均值 %.3f（最低 %.3f）" % (len(P), P.mean(), P.min()))
        print("  负例 n=%d 均值 %.3f（最高 %.3f）" % (len(N), N.mean(), N.max()))
        sep = P.min() - N.max()
        print("⇒ %s（正例最低 − 负例最高 = %+.3f）" % ("分得开，尺可用" if sep > 0 else "分不开，这把尺作废", sep))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
