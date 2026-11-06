def range_chain_check():
    """★摆幅链自证（10-04 立的，起因就是范例第一版报表把解码链的展幅当成了片子的削顶）。
    分两段，各管各的：
    ① **纯函数**（不碰任何解码器，永远跑）：limited 下 16→0／235→100，且 16–235 之外要给出
       负 IRE 与 >100 IRE（超白、亚黑量得到＝旗只换算了一次）；full 下 0→0／255→100；
       色度归一只改饱和距离、不改色度角。
    ② **真片子**（要 ffmpeg）：tv 旗条纹片走码值域读回来码值**一个没动**；同一张片走 cv2 兜底
       必须被展成 0–255 —— 这条是"为什么不能走它"的活证据，哪天 OpenCV 改了行为这里先响。
    ⚠ 为什么"超范围码值"这段不做成真片子：实测 ffmpeg 在 rawvideo 输入与带旗的输出之间自己动手
    换算（`tv` 夹到 16–235、`pc` 又从 16–235 展到 0–255，写 16 存成 0）——**造不出这种片子**，
    拿编码器当尺子只会量到编码器。所以那条走 ① 的纯函数断言。"""
    import tempfile
    bad = []
    # —— ① 纯函数段：不依赖任何外部工具 ——
    codes = [6, 16, 64, 160, 235, 250]
    plane = np.array([codes], dtype=np.uint8)
    lim = ire_from_y(plane, "limited")
    for j, v in enumerate(codes):
        exp = (v - 16.0) / 219.0 * 100.0
        if abs(float(lim[0, j]) - exp) > 0.02:
            bad.append(u"码值 %d 按 limited 应 %.2f IRE，实得 %.2f" % (v, exp, float(lim[0, j])))
    if not (float(lim[0, 0]) < 0.0 and float(lim[0, -1]) > 100.0):
        bad.append(u"亚黑没给出负 IRE／超白没给出 >100 IRE ⇒ 旗被换算了不止一次")
    full = ire_from_y(plane, "full")
    if abs(float(full[0, 0])) > 0.02 or abs(float(full[0, -1]) - 250.0 / 255.0 * 100.0) > 0.02:
        bad.append(u"full 摆幅下 6→%.2f／250→%.2f，应 2.35／98.04" % (float(full[0, 0]), float(full[0, -1])))
    cb, cr = np.array([[128.0, 150.0]]), np.array([[128.0, 140.0]])
    a0, r0 = angle_and_R(*chroma_to_full(cb, cr, "full"))
    a1, r1 = angle_and_R(*chroma_to_full(cb, cr, "limited"))
    if abs(float(a0[1]) - float(a1[1])) > 1e-4:
        bad.append(u"色度归一把色度角也改了（%.2f°→%.2f°）⇒ 归一系数不能这么用" % (a0[1], a1[1]))
    if not float(r1[1]) > float(r0[1]):
        bad.append(u"limited 归一后饱和距离没变大（%.2f→%.2f）⇒ 255/219 那条缩放反了"
                   % (float(r0[1]), float(r1[1])))
    # —— ② 真片子段：要 ffmpeg ——
    if not find_ffmpeg():
        print(u"   · 摆幅链自证：① 纯函数段已跑｜② 真片子段本机没有 ffmpeg ⇒ **跳过**（没跑过 ≠ 过了）")
        return bad
    tmp = os.path.join(tempfile.gettempdir(), "light_scopes")
    if not os.path.isdir(tmp):
        os.makedirs(tmp)
    vals = [16, 64, 160, 235]
    tvp = os.path.join(tmp, "selftest_tv.mp4")
    ok_tv, band = _encode_bands(vals, "tv", tvp)
    if not ok_tv:
        print(u"   · 摆幅链自证：② 造不出条纹片（%s）⇒ **跳过**" % band)
        return bad
    got, note = coded_frames_from_video(tvp, [0], tmp)
    if not got:
        bad.append(u"码值域读帧失败：%s" % note)
    else:
        _, yy, cb0, cr0 = got[0]
        for i, v in enumerate(vals):
            m = int(np.median(yy[i * band:(i + 1) * band, :]))
            if abs(m - v) > 1:
                bad.append(u"码值 %d 读回来是 %d ⇒ 我的读帧链动了摆幅（%s）" % (v, m, note))
        ire, _, _ = frame_planes(yy, cb0, cr0, "limited")
        for i, v in enumerate(vals):
            exp = (v - 16.0) / 219.0 * 100.0
            m = float(np.median(ire[i * band:(i + 1) * band, :]))
            if abs(m - exp) > 0.5:
                bad.append(u"片上码值 %d 按 limited 应 %.1f IRE，实得 %.1f" % (v, exp, m))
    cap = cv2.VideoCapture(tvp)
    okf, fr = cap.read()
    cap.release()
    if okf:
        g = fr[:, :, 1]
        lo, hi = float(np.median(g[:band, :])), float(np.median(g[-band:, :]))
        if not (lo <= 1.0 and hi >= 254.0):
            bad.append(u"cv2 那条链的展幅行为变了（写 16→读 %.0f，写 235→读 %.0f）"
                       u" ⇒ 重看兜底口径与『只能按 full 算』那条注" % (lo, hi))
    if os.path.isfile(tvp):
        os.remove(tvp)
    print(u"   · 摆幅链自证：① 旗只换算一次（超白 >100／亚黑 <0 量得到）② 码值域直读不展幅"
          u"＋cv2 兜底展幅已验")
    return bad


