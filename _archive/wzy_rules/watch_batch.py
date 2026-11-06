# -*- coding: utf-8 -*-
"""批次看门狗（独立进程，不依赖 run_batch 活着）。

为什么单独一个文件：今晚人不在。run_batch 自己挂了（内存挤爆→连续瞬时失败→停批）
就没人接手，GPU 会空转到早上。看门狗只干三件事：
  1) 驱动进程还在不在；不在了，先看是不是还有镜没跑完；
  2) 空闲物理内存低于阈值时先把 ComfyUI 重启（锁页缓冲分配失败的唯一解，03:41 实测 1.9→21.8GB）；
  3) 从「未完成的第一镜」重新拉起驱动，并把每一轮动作写进 watch.log。
判定纪律不变：看门狗只负责"让它继续跑"，不负责判片子好坏。
"""
import os, sys, json, time, subprocess

WZY = r'D:\AIWorkflow\tmp\wzy'
H3 = os.path.join(WZY, 'h3')
PY = r'D:\AIWorkflow\ComfyUI_H3\python_embeded\python.exe'
DRIVER = os.path.join(WZY, 'run_batch.py')
COMFY_DIR = r'D:\AIWorkflow\ComfyUI_H3'
COMFY_LOG = r'D:\AIWorkflow\logs\comfyui_h3.log'
WATCH_LOG = os.path.join(H3, 'watch.log')
COMFY_CMD = [PY, '-s', 'ComfyUI/main.py', '--windows-standalone-build', '--use-sage-attention',
             '--port', '8189', '--output-directory', r'D:\AIWorkflow\ComfyUI_H3\output']
LOW_MEM_GB = 3.0
DONE = ('completed', '待判')          # 待判＝产物在、等人眼，不重跑


def log(*a):
    line = '[%s] %s' % (time.strftime('%m-%d %H:%M:%S'), ' '.join(str(x) for x in a))
    with open(WATCH_LOG, 'a', encoding='utf8') as f:
        f.write(line + '\n')
    print(line, flush=True)


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf8', errors='replace', timeout=90)
    return (r.stdout or '').strip()


def free_gb():
    out = ps("$o=Get-CimInstance Win32_OperatingSystem; '{0:N1}' -f ($o.FreePhysicalMemory/1MB)")
    try:
        return float(out.splitlines()[-1])
    except Exception:
        return 99.0


def pids(match, name='python.exe'):
    """必须按进程名过滤：查询用的 powershell 自己命令行里就含这个串，
    不过滤会自匹配（driver_alive 恒真＝看门狗形同虚设）。"""
    out = ps("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq '%s' -and "
             "$_.CommandLine -like '*%s*' } | ForEach-Object { $_.ProcessId }" % (name, match))
    return [int(x) for x in out.split() if x.strip().isdigit() and int(x) != os.getpid()]


def driver_alive():
    return bool(pids('run_batch.py'))


def comfy_alive():
    import urllib.request
    try:
        with urllib.request.urlopen('http://127.0.0.1:8189/queue', timeout=5) as r:
            json.loads(r.read().decode('utf8'))
        return True
    except Exception:
        return False


def restart_comfy():
    log('重启 ComfyUI 释放锁页内存（空闲 %.1fGB < %.1fGB）' % (free_gb(), LOW_MEM_GB))
    for p in pids('ComfyUI/main.py'):
        subprocess.run(['taskkill', '/PID', str(p), '/F'], capture_output=True)
    time.sleep(8)
    with open(COMFY_LOG, 'ab') as lf:
        subprocess.Popen(COMFY_CMD, cwd=COMFY_DIR, stdout=lf, stderr=lf, shell=False)
    for k in range(30):
        time.sleep(5)
        if comfy_alive():
            log('  ComfyUI 已就绪（%ds），空闲 %.1fGB' % ((k + 1) * 5, free_gb()))
            return True
    log('  !! ComfyUI 30 次探测没起来，交给下一轮')
    return False


def pending_ids():
    led = json.load(open(os.path.join(H3, 'ledger.json'), encoding='utf8')) \
        if os.path.isfile(os.path.join(H3, 'ledger.json')) else {}
    jobs = json.load(open(os.path.join(H3, 'jobs.json'), encoding='utf8'))
    return [j['id'] for j in jobs if led.get(j['id'], {}).get('verdict') not in DONE], led


def engine_pids():
    return pids('h3_i2va_batch')


def queue_busy():
    try:
        q = subprocess.run(['curl', '-s', '--max-time', '6', 'http://127.0.0.1:8189/queue'],
                           capture_output=True, text=True, timeout=20).stdout
        d = json.loads(q or '{}')
        return bool(d.get('queue_running')) or bool(d.get('queue_pending'))
    except Exception:
        return False


def ledger_age_min():
    try:
        return (time.time() - os.path.getmtime(os.path.join(H3, 'ledger.json'))) / 60.0
    except OSError:
        return 999.0


def kill_hung():
    """08:07 踩过：ComfyUI 在渲染中 `Windows fatal exception: access violation` 整个崩了，
    引擎子进程永远等不到回包，驱动卡在 subprocess.run 里——**看门狗看"驱动进程还在"就以为一切正常，
    GPU 白空转 2 小时 14 分**。"驱动活着"不等于"在推进"，必须另看有没有新账本落盘。"""
    for pid in [x for x in pids('h3_i2va_batch')] + [x for x in pids('run_batch.py')]:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
        log('  杀掉卡住的进程', pid)
    time.sleep(5)


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 400      # 400×90s ≈ 10h
    relaunch = {}
    log('看门狗启动，%d 轮 × 90s（含"驱动活着但没推进"检测）' % rounds)
    for _ in range(rounds):
        try:
            pend, _led = pending_ids()
            if not pend:
                log('全部镜已有产物记录（completed/待判），看门狗收工')
                break
            if driver_alive():
                # 卡死检测：驱动在、但服务端队列空（或 ComfyUI 没了）且 20 分钟没有新账本
                if ledger_age_min() > 20 and (not comfy_alive() or not queue_busy()):
                    log('驱动活着但已 %d 分钟无产出且队列空＝卡死（多半是 ComfyUI 崩了），接手'
                        % int(ledger_age_min()))
                    kill_hung()
                    restart_comfy()
                    log('  交回驱动：下一轮自动重拉')
                continue
            if comfy_alive():
                busy = queue_busy()
            else:
                busy = False
            if busy:
                log('驱动没了但 ComfyUI 还在渲染，等它落盘（当前未完成：%s）' % ','.join(pend[:4]))
            else:
                # 同一镜连续拉 3 次还不落盘，多半是它的首帧/资产缺（驱动会"停链"），
                # 再重启只是死循环烧 GPU——停下来留话给人。
                relaunch[pend[0]] = relaunch.get(pend[0], 0) + 1
                if relaunch[pend[0]] > 3:
                    log('!! %s 已拉起 3 次仍无产物，停手等人（多半缺首帧或资产，别再烧卡）' % pend[0])
                    break
                if free_gb() < LOW_MEM_GB or not comfy_alive():
                    restart_comfy()
                log('驱动不在且队列空 → 从 %s 重新拉起（第 %d 次；未完成 %d 镜：%s）'
                    % (pend[0], relaunch[pend[0]], len(pend), ','.join(pend)))
                blog = open(os.path.join(H3, 'batch.log'), 'ab')
                subprocess.Popen([PY, DRIVER, '--from', pend[0]], cwd=WZY,
                                 stdout=blog, stderr=blog)
        except Exception as e:
            log('看门狗自身异常（继续）：%r' % e)
        time.sleep(90)




if __name__ == '__main__':
    main()
