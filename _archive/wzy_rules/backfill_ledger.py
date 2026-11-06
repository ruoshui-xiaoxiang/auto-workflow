# -*- coding: utf-8 -*-
"""把 09-26 凌晨那轮的四条缺陷记录回填进 h3/ledger.json（他 09-27 拍：回填）。

为什么单独写一个脚本而不是手改 JSON：每条都要带回**当时渲的提示词哈希**（引擎 manifest 里有），
这样账本、成片、提示词三者对得上，下一个工具不会再被"completed 无缺陷"骗一次。
H01–H04 不碰；H05 保留下午那轮的 completed（那版基调已修好，中帧我看过），只补缺陷史。
"""
import glob
import hashlib
import json
import os
import shutil
import time

H3 = r'D:/AIWorkflow/tmp/wzy/h3'
POOL = r'E:/图像影音资源池/武昭君仪/批次'
LED = os.path.join(H3, 'ledger.json')

RENDER = {                      # 镜 → (成片批次目录, 当时渲的提示词文件, 判定, 缺陷, 成因/处置)
 'H05': ('20260926_022703', 'H05_video.txt', '待判',
         '古代镜基调一句里并列两个场景 → 0 帧雾林、181 帧起变挂灯笼的青砖镇街，正文"顺着树倒坐下去"落成坐石板',
         '成因＝ANCIENT_CN 里那个"或"字（名词自带先验，禁令压不住）。处置＝基调按镜拆开（ANCIENT_CN 纯洛阳夜行／新增 ANCIENT_F_CN 纯黄昏雾林）。'
         '09-26 18:41 已按修好的基调重渲过一张＝账本现存这张，中帧复查无霓虹渗入 ⇒ 保留 completed，本条只留缺陷史。'),
 'H07': ('20260926_044034', 'H07_video.txt', '待判',
         '① 第一拍把缠白麻布的长杆渲成一颗子弹（黄铜弹壳＋黑弹头）；② 第二拍携行布带画成从杆拖到地的白长条；'
         '③ 第三拍右上角全息牌长出可读汉字「恋」（未解）',
         '①成因三处：道具锁只锁"形态数量"没锁尺度＋SLING_CN 漏套去枪替换＋全局基调原句自带"白麻布裹枪"（按逐字纪律贴进 23 镜每一镜）。'
         '处置＝SPEAR_LOCK 加尺度（身高相当／粗细如手腕／完全封口）、SLING 加"不超过一拃"、基调也过去枪替换、并立永久硬闸（视觉区出现"枪"字即拒绝出表）。'
         '③未解：这是赛博街景的结构性问题，已改成整批跑完出"烧字位置清单"交他定遮/补/重拍。'),
 'H08': ('20260926_050202', 'H08_video.txt', '待判',
         '同框"一个肩扛长条包裹的女人"被渲成第二个武君仪（同脸同衣）',
         '成因＝正文只给了一句没给任何可视区分特征，而模型手上只有一张脸。处置＝新增 ANTI_CLONE（每人彼此可辨、同一人不得出现两次）'
         '＋CAST_LOCK 逐镜点名形貌。08:23 他要求撤回这条重做 ⇒ 保留成片供目检，缺陷与成因留此。'),
 'H13': ('20260926_052955', 'H13_video.txt', '判废',
         '道具露出裸杆头、与"通体白麻布缠严"不符',
         '成因＝这张用的是 02:03 的旧首帧，**绕过了整条提示词管线**（三道闸从没看过那张图）。'
         '处置＝新增 pipeline_gate（手塞首帧必须有本管线生成的提示词，否则拒绝出表）＋CAST_ANCHOR 给瘦高个挂 A08 脸锚；'
         '新首帧 kf_out/H13b_s0.png 已在册（09-26 17:08，1344×768）⇒ 待按现行词重渲。'),
}


def rendered_sha(batch_dir, prompt_file):
    mf = glob.glob(os.path.join(POOL, batch_dir, '*.manifest.json'))
    if not mf:
        return None, None
    m = json.load(open(mf[0], encoding='utf8'))
    im = (m.get('images') or [{}])[0]
    return im.get('prompt_sha256'), (m.get('args') or {}).get('prompt_file')


def main():
    led = json.load(open(LED, encoding='utf8'))
    shutil.copyfile(LED, LED + '.bak-回填缺陷前')
    now = time.strftime('%F %T')
    for sid, (bd, pf, verdict, bad, cause) in RENDER.items():
        mp4 = os.path.join(POOL, bd, 'video', os.listdir(os.path.join(POOL, bd, 'video'))[0]) \
            if os.path.isdir(os.path.join(POOL, bd, 'video')) else None
        cur = os.path.join(H3, pf)
        cur_sha = hashlib.sha256(open(cur, 'rb').read()).hexdigest() if os.path.isfile(cur) else None
        rsha, rpf = rendered_sha(bd, pf)
        hist = {'回填时间': now, '成片批次': bd, '成片': mp4, '判定': verdict,
                '缺陷': bad, '成因与处置': cause,
                '当时渲的提示词sha': (rsha or '')[:12] or 'manifest 未存', '现行提示词sha': (cur_sha or '')[:12],
                '版本对应': '一致' if rsha and rsha == cur_sha else ('不一致（差异见 prompt_provenance.py）' if rsha else '无法比对')}
        e = led.setdefault(sid, {})
        e.setdefault('defect_history', [])
        if not any(h.get('成片批次') == bd for h in e['defect_history']):
            e['defect_history'].append(hist)
        if sid != 'H05':
            e.update(verdict=verdict, mp4=mp4, bad=[bad[:60]], cause=cause[:80],
                     note='09-27 按用户决定回填；此判定来自 09-26 凌晨那轮，非下午那轮', ts=now)
        else:
            e['note'] = 'completed 指 09-26 18:41 那版（基调已修）；凌晨那版的缺陷史在 defect_history'
    json.dump(led, open(LED, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('已回填 %d 镜；备份 %s' % (len(RENDER), LED + '.bak-回填缺陷前'))
    for sid, e in led.items():
        print('  %-4s %-8s 缺陷史 %d 条  mp4=%s' % (sid, e.get('verdict'), len(e.get('defect_history', [])),
                                                    (e.get('mp4') or '')[-28:]))


if __name__ == '__main__':
    main()
