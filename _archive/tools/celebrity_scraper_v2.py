#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   人脸训练集采集批的第二版（同族共五版）。
#   为什么没有调用方：被后续按数据源拆分的变体接替；保留作实验记录。
"""
补爬缺失明星 + 扩大范围
重点：年轻时期照片，加大请求间隔防限流
"""

import os
import re
import json
import time
import random
import requests
from PIL import Image
from urllib.parse import urlencode
from pathlib import Path
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('celebrity_scraper_v2.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("D:/AIWorkflow/training/datasets/asian_faces")
IMAGES_PER_CELEBRITY = 5
MIN_WIDTH = 200
MIN_HEIGHT = 200
MIN_FILE_SIZE_KB = 20
DOWNLOAD_TIMEOUT = 15

# 补爬名单：缺失的 + 新扩的
CELEBRITIES = {
    # === 上次缺失的中国明星 ===
    "刘诗诗": "chinese",
    "白鹿": "chinese",
    "关晓彤": "chinese",
    "陈都灵": "chinese",
    "黄圣依": "chinese",
    "李若彤": "chinese",
    "翁美玲": "chinese",
    "舒畅": "chinese",
    "董洁": "chinese",
    "胡冰卿": "chinese",
    "甘婷婷": "chinese",
    "李一桐": "chinese",
    "彭小冉": "chinese",

    # === 上次缺失的韩国明星 ===
    "林允儿": "korean",
    "金泰梨": "korean",
    "高允贞": "korean",
    "裴珠泫": "korean",
    "金智秀": "korean",
    "孙娜恩": "korean",
    "郑秀晶": "korean",
    "金所炫": "korean",
    "全智贤": "korean",
    "徐贤": "korean",
    "南志铉": "korean",
    "申世景": "korean",

    # === 上次缺失的日本明星 ===
    "长的雅美": "japanese",
    "堀北真希": "japanese",
    "新垣结衣": "japanese",
    "北川景子": "japanese",
    "深田恭子": "japanese",
    "上户彩": "japanese",
    "柴崎幸": "japanese",
    "满岛光": "japanese",
    "中森明菜": "japanese",
    "宫泽理惠": "japanese",
    "松田圣子": "japanese",
    "酒井法子": "japanese",
    "三吉彩花": "japanese",
    "福原遥": "japanese",
    "西野七濑": "japanese",
    "白石麻衣": "japanese",
    "樱井玲香": "japanese",
    "生田绘梨花": "japanese",

    # === 新扩：中国经典美人 ===
    "陈红": "chinese",
    "何晴": "chinese",
    "茹萍": "chinese",
    "李建群": "chinese",
    "邬倩倩": "chinese",
    "张晓敏": "chinese",
    "傅艺伟": "chinese",
    "许晴": "chinese",

    # === 新扩：韩国 ===
    "尹恩惠": "korean",
    "文根英": "korean",
    "成宥利": "korean",
    "李侑菲": "korean",
    "林智妍": "korean",
    "金高银": "korean",
    "朴恩斌": "korean",
    "李世荣": "korean",

    # === 新扩：日本 ===
    "的濑遥": "japanese",
    "宫崎葵": "japanese",
    "崛北真希": "japanese",
    "井上真央": "japanese",
    "上野树里": "japanese",
    "长的masami": "japanese",
    "的木希": "japanese",
    "新木优子": "japanese",
    "门胁麦": "japanese",
    "二阶堂富美": "japanese",
}


def get_headers():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "DNT": "1",
        "Pragma": "no-cache",
        "Referer": "https://image.baidu.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


def search_baidu_images(keyword, num_images=20):
    urls = []
    page_num = 0
    session = requests.Session()
    session.headers.update(get_headers())

    try:
        session.get("https://image.baidu.com/", timeout=5)
    except Exception:
        pass

    while len(urls) < num_images:
        params = {
            "tn": "resultjson_com",
            "logid": str(random.randint(1000000000, 9999999999)),
            "ipn": "rj",
            "ct": 201326592,
            "is": "",
            "fp": "result",
            "fr": "",
            "word": keyword,
            "queryWord": keyword,
            "cl": 2,
            "lm": -1,
            "ie": "utf-8",
            "oe": "utf-8",
            "adpicid": "",
            "st": -1,
            "z": "",
            "ic": "",
            "hd": "",
            "latest": "",
            "copyright": "",
            "se": "",
            "tab": "",
            "width": "",
            "height": "",
            "face": 0,
            "istype": 2,
            "qc": "",
            "nc": 1,
            "expermode": "",
            "nojc": "",
            "isAsync": "",
            "pn": page_num,
            "rn": 30,
            "gsm": hex(page_num)[2:],
        }

        url = "https://image.baidu.com/search/acjson?" + urlencode(params)

        try:
            response = session.get(url, timeout=10)
            response.raise_for_status()

            text = response.text
            json_match = re.search(r'\((.*)\)', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = json.loads(text)

            images = data.get("data", [])
            if not images:
                break

            for img in images:
                if len(urls) >= num_images:
                    break
                img_url = (
                    img.get("thumbURL") or
                    img.get("ThumbURL") or
                    img.get("objURL") or
                    img.get("ObjURL")
                )
                if img_url:
                    img_url = img_url.replace("\\/", "/")
                    urls.append(img_url)

            page_num += 30
            time.sleep(random.uniform(2, 4))

        except Exception as e:
            logger.warning(f"搜索 {keyword} 第 {page_num} 页失败：{e}")
            break

    return urls[:num_images]


def download_image(url, save_path, timeout=15):
    try:
        headers = get_headers()
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return False

        save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = save_path.with_suffix(".tmp")

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        if not temp_path.exists() or temp_path.stat().st_size == 0:
            temp_path.unlink(missing_ok=True)
            return False

        try:
            with Image.open(temp_path) as img:
                if img.format == "WEBP" or temp_path.suffix == ".webp":
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(save_path, "JPEG", quality=95)
                    temp_path.unlink()
                else:
                    temp_path.rename(save_path)
        except Exception:
            temp_path.rename(save_path)

        if not save_path.exists() or save_path.stat().st_size == 0:
            save_path.unlink(missing_ok=True)
            return False

        return True

    except Exception as e:
        logger.debug(f"下载失败 {url}: {e}")
        return False


def validate_image(image_path):
    try:
        file_size_kb = image_path.stat().st_size / 1024
        if file_size_kb < MIN_FILE_SIZE_KB:
            return False

        with Image.open(image_path) as img:
            width, height = img.size
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return False
            img.convert("RGB")
        return True
    except Exception:
        return False


def generate_caption(name, region):
    if region == "chinese":
        return f"古风女子，汉服，古典妆容，东方五官，丹凤眼，鹅蛋脸，写真"
    elif region == "korean":
        return f"韩国女子，精致妆容，亚洲五官，鹅蛋脸，写真"
    else:
        return f"日本女子，精致妆容，亚洲五官，写真"


def process_celebrity(name, region, output_dir):
    result = {"name": name, "region": region, "downloaded": 0, "valid": 0}

    celeb_dir = output_dir / region / name
    celeb_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否已有图片
    existing = list(celeb_dir.glob("*.jpg"))
    if len(existing) >= IMAGES_PER_CELEBRITY:
        logger.info(f"{name}: 已有 {len(existing)} 张，跳过")
        return result

    # 搜索关键词：加"年轻"以获取年轻时期照片
    if region == "chinese":
        keywords = [f"{name} 年轻 古装", f"{name} 年轻 写真"]
    elif region == "korean":
        keywords = [f"{name} young portrait", f"{name} portrait"]
    else:
        keywords = [f"{name} 年轻 ポートレート", f"{name} portrait"]

    urls = []
    for kw in keywords:
        urls.extend(search_baidu_images(kw, num_images=IMAGES_PER_CELEBRITY * 2))
        if len(urls) >= IMAGES_PER_CELEBRITY:
            break
        time.sleep(random.uniform(3, 5))

    if not urls:
        logger.warning(f"{name}: 未搜索到图片")
        return result

    # 去重 URL
    seen_urls = set()
    unique_urls = []
    for u in urls:
        if u not in seen_urls:
            seen_urls.add(u)
            unique_urls.append(u)

    downloaded = []
    for i, url in enumerate(unique_urls):
        if len(downloaded) >= IMAGES_PER_CELEBRITY:
            break

        save_path = celeb_dir / f"{name}_{len(downloaded):03d}.jpg"
        if download_image(url, save_path):
            downloaded.append(save_path)
            result["downloaded"] += 1

        time.sleep(random.uniform(2, 4))

    valid_images = []
    for img_path in downloaded:
        if validate_image(img_path):
            valid_images.append(img_path)
            result["valid"] += 1
        else:
            img_path.unlink(missing_ok=True)

    # 生成 caption
    caption = generate_caption(name, region)
    for img_path in valid_images:
        txt_path = img_path.with_suffix(".txt")
        txt_path.write_text(caption, encoding="utf-8")

    logger.info(f"{name}: 下载 {result['downloaded']}, 有效 {result['valid']}")
    return result


def main():
    logger.info("=" * 60)
    logger.info("补爬开始")
    logger.info(f"目标明星数：{len(CELEBRITIES)}")
    logger.info("=" * 60)

    results = []
    for i, (name, region) in enumerate(CELEBRITIES.items()):
        logger.info(f"[{i+1}/{len(CELEBRITIES)}] 处理：{name} ({region})")
        result = process_celebrity(name, region, OUTPUT_DIR)
        results.append(result)

        # 每人之间等久一点，防限流
        time.sleep(random.uniform(4, 7))

    total_downloaded = sum(r["downloaded"] for r in results)
    total_valid = sum(r["valid"] for r in results)

    logger.info("=" * 60)
    logger.info("补爬完成")
    logger.info(f"总下载：{total_downloaded}")
    logger.info(f"总有效：{total_valid}")
    logger.info("=" * 60)

    # 保存结果
    results_path = OUTPUT_DIR / "scraping_results_v2.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"结果保存到：{results_path}")


if __name__ == "__main__":
    main()
