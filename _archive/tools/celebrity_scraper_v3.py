#!/usr/bin/env python3
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   人脸训练集采集批的第三版（同族共五版）。
#   为什么没有调用方：同上。⚠ 别按“版本号最大就是现役”理解——现役取决于当初哪版跑出了数据集。
"""
亚洲脸 LoRA 数据采集 v3 — 高分辨率版
目标：采集 800x800 以上的高质量图片
"""

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode

import cv2
import requests
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(r"E:\LocalAI\dataset\asian_faces")
MIN_WIDTH = 800
MIN_HEIGHT = 800
MIN_FILE_SIZE = 100_000  # 100KB
TARGET_PER_PERSON = 5

# 重点补充日韩低分辨率重灾区
HIGH_RES_CELEBRITIES = {
    "chinese": [
        "刘诗诗", "彭小冉", "李一桐", "甘婷婷", "翁美玲",
        "胡冰卿", "黄圣依", "茹萍", "李建群", "许晴",
        "傅艺伟", "张晓敏", "陈红", "舒畅", "李若彤",
    ],
    "korean": [
        "全智贤", "尹恩惠", "文根英", "徐贤", "林允儿",
        "申世景", "裴珠泫", "郑秀晶", "金所炫", "金智秀",
        "金泰梨", "高允贞", "韩素希", "金裕贞", "张元英",
    ],
    "japanese": [
        "新垣结衣", "北川景子", "上户彩", "深田恭子", "绫濑遥",
        "苍井优", "福原遥", "中森明菜", "菜菜绪", "满岛光",
    ],
}


def get_headers() -> Dict[str, str]:
    """完整浏览器指纹"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
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


def search_baidu_images(query: str, num_images: int = 20) -> List[str]:
    """搜索百度图片，优先高清"""
    headers = get_headers()
    session = requests.Session()
    session.headers.update(headers)

    try:
        session.get("https://image.baidu.com/", timeout=5)
    except Exception:
        pass

    urls = []
    seen_urls = set()

    for page_num in range(3):
        if len(urls) >= num_images:
            break

        params = {
            "tn": "resultjson",
            "word": query + " 高清 大图",
            "ie": "utf-8",
            "pn": page_num * 30,
            "rn": 30,
            "gsm": hex(page_num * 30)[2:],
            "width": 800,
            "height": 800,
            "ic": 0,
            "ipn": "result",
            "s": "",
            "face": 0,
            "istype": 2,
            "nc": 1,
            "expermode": "",
            "nojc": "",
            "isAsync": "",
            "queryWord": query + " 高清 大图",
            "cl": 2,
            "lm": -1,
            "nc": 1,
            "oe": "utf-8",
            "oe": "utf-8",
            "st": -1,
            "z": 0,
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

                if img_url and img_url not in seen_urls:
                    seen_urls.add(img_url)
                    urls.append(img_url)

            time.sleep(random.uniform(2, 4))

        except Exception as e:
            logger.warning(f"搜索 {query} 第 {page_num} 页失败：{e}")
            time.sleep(random.uniform(3, 5))

    return urls


def download_image(url: str, save_path: Path, timeout: int = 15) -> bool:
    """下载图片并验证分辨率"""
    headers = get_headers()

    try:
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "image" not in content_type and not url.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return False

        temp_path = save_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        if not temp_path.exists() or temp_path.stat().st_size < MIN_FILE_SIZE:
            temp_path.unlink(missing_ok=True)
            return False

        final_path = save_path
        if temp_path.suffix == ".webp" or save_path.suffix == ".webp":
            try:
                with Image.open(temp_path) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(final_path, "JPEG", quality=95)
                    temp_path.unlink()
            except Exception:
                temp_path.unlink(missing_ok=True)
                return False
        else:
            temp_path.rename(final_path)

        img = cv2.imread(str(final_path))
        if img is None:
            final_path.unlink(missing_ok=True)
            return False

        h, w = img.shape[:2]
        if w < MIN_WIDTH or h < MIN_HEIGHT:
            logger.debug(f"分辨率不足 {w}x{h}: {final_path}")
            final_path.unlink()
            return False

        logger.info(f"✓ 高分 {w}x{h}: {final_path.name}")
        return True

    except Exception as e:
        logger.debug(f"下载失败 {url}: {e}")
        save_path.unlink(missing_ok=True)
        Path(str(save_path) + ".tmp").unlink(missing_ok=True)
        return False


def process_celebrity(name: str, country: str, caption_template: str):
    """处理单个明星"""
    output_dir = BASE_DIR / country / name
    output_dir.mkdir(parents=True, exist_ok=True)

    existing = list(output_dir.glob("*.jpg"))
    if len(existing) >= TARGET_PER_PERSON:
        logger.info(f"跳过 {name}：已有 {len(existing)} 张")
        return

    logger.info(f"处理：{name} ({country})")

    queries = [
        f"{name} 高清 写真",
        f"{name} 高清 大图",
        f"{name} portrait HD",
    ]

    all_urls = []
    for query in queries:
        urls = search_baidu_images(query, num_images=15)
        all_urls.extend(urls)
        time.sleep(random.uniform(2, 3))

    seen_urls = set()
    unique_urls = []
    for url in all_urls:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_urls.append(url)

    downloaded = 0
    for idx, url in enumerate(unique_urls):
        if downloaded >= TARGET_PER_PERSON:
            break

        save_path = output_dir / f"{name}_{idx:03d}.jpg"
        if save_path.exists():
            downloaded += 1
            continue

        if download_image(url, save_path):
            downloaded += 1
            caption_path = save_path.with_suffix(".txt")
            caption_path.write_text(caption_template, encoding="utf-8")

        time.sleep(random.uniform(1, 2))

    logger.info(f"{name}: 下载 {downloaded}, 目标 {TARGET_PER_PERSON}")


def main():
    logger.info("=" * 60)
    logger.info("亚洲脸 LoRA 数据采集 v3 — 高分辨率版")
    logger.info(f"最低分辨率：{MIN_WIDTH}x{MIN_HEIGHT}")
    logger.info(f"最低文件大小：{MIN_FILE_SIZE // 1000}KB")
    logger.info("=" * 60)

    captions = {
        "chinese": "古风女子，汉服，古典妆容，东方五官，丹凤眼，鹅蛋脸，写真",
        "korean": "韩国女子，精致妆容，亚洲五官，鹅蛋脸，写真",
        "japanese": "日本女子，精致妆容，亚洲五官，写真",
    }

    total = sum(len(v) for v in HIGH_RES_CELEBRITIES.values())
    current = 0

    for country, names in HIGH_RES_CELEBRITIES.items():
        for name in names:
            current += 1
            logger.info(f"[{current}/{total}] 处理：{name} ({country})")
            process_celebrity(name, country, captions[country])
            time.sleep(random.uniform(4, 7))

    logger.info("=" * 60)
    logger.info("采集完成！")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
