#!/usr/bin/env python3
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   人脸训练集采集批的 **Bing 图源变体**（同族共五版，各按数据源/策略分叉）。
#   为什么没有调用方：采集是一次性动作；保留是为“当初为什么选/不选这个源”留有据可查。
"""
亚洲脸 LoRA 数据采集 — Bing 图片版
Bing 图片搜索爬取，分辨率通常比百度高
"""

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote, urlencode

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
DEBUG_DIR = Path(r"E:\LocalAI\tools\debug_images")
DEBUG_DIR.mkdir(exist_ok=True)
MIN_WIDTH = 400
MIN_HEIGHT = 400
MIN_FILE_SIZE = 100_000
TARGET_PER_PERSON = 5
DEBUG_MODE = True

CELEBRITIES = {
    "chinese": [
        "陈红", "舒畅", "李若彤", "邬倩倩",
    ],
    "korean": [
        "全智贤", "尹恩惠", "文根英", "徐贤", "林允儿",
        "申世景", "裴珠泫", "郑秀晶", "金所炫", "金智秀",
        "金泰梨",
    ],
    "japanese": [
        "新垣结衣", "北川景子", "上户彩", "堀北真希",
        "宫泽理惠", "松田圣子", "柴崎幸", "满岛光",
        "生田绘梨花", "白石麻衣", "西野七濑", "酒井法子",
        "三吉彩花", "樱井玲香", "长的雅美",
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
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


def search_bing_images(query: str, num_images: int = 30) -> List[str]:
    """搜索 Bing 图片"""
    headers = get_headers()
    session = requests.Session()
    session.headers.update(headers)

    urls = []
    seen_urls = set()

    for first in range(0, num_images, 35):
        if len(urls) >= num_images:
            break

        params = {
            "q": query,
            "first": first,
            "count": 35,
            "qft": "+filterui:imagesize-large",
        }

        url = "https://www.bing.com/images/search?" + urlencode(params)

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            html = response.text

            img_urls = re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', html)

            for img_url in img_urls:
                if len(urls) >= num_images:
                    break
                if img_url not in seen_urls:
                    seen_urls.add(img_url)
                    urls.append(img_url)

            time.sleep(random.uniform(2, 4))

        except Exception as e:
            logger.warning(f"搜索 {query} 第 {first} 条失败：{e}")
            time.sleep(random.uniform(3, 5))

    return urls


def download_image(url: str, save_path: Path, timeout: int = 15) -> bool:
    """下载图片并验证分辨率"""
    headers = get_headers()

    try:
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "image" not in content_type and not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return False

        temp_path = save_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        if not temp_path.exists() or temp_path.stat().st_size < MIN_FILE_SIZE:
            temp_path.unlink(missing_ok=True)
            return False

        final_path = save_path

        try:
            with Image.open(temp_path) as img:
                actual_format = img.format
                if actual_format == "WEBP" or temp_path.suffix.lower() == ".webp":
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(final_path, "JPEG", quality=95)
                    temp_path.unlink()
                else:
                    temp_path.rename(final_path)
        except Exception as e:
            logger.debug(f"PIL 转换失败 {temp_path}: {e}")
            temp_path.unlink(missing_ok=True)
            return False

        import numpy as np
        img_array = np.fromfile(final_path, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            if DEBUG_MODE:
                import shutil
                debug_path = DEBUG_DIR / f"failed_{final_path.name}"
                shutil.copy2(final_path, debug_path)
                logger.debug(f"保存失败文件到 debug: {debug_path}")
            final_path.unlink(missing_ok=True)
            return False

        h, w = img.shape[:2]
        if w < MIN_WIDTH or h < MIN_HEIGHT:
            logger.debug(f"分辨率不足 {w}x{h}: {final_path}")
            final_path.unlink()
            return False

        logger.info(f"✓ Bing 高分 {w}x{h}: {final_path.name}")
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
    high_res_count = 0
    for img_path in existing:
        try:
            img = cv2.imread(str(img_path))
            if img is not None:
                h, w = img.shape[:2]
                if w >= MIN_WIDTH and h >= MIN_HEIGHT:
                    high_res_count += 1
        except:
            pass

    if high_res_count >= TARGET_PER_PERSON:
        logger.info(f"跳过 {name}：已有 {high_res_count} 张高分")
        return

    logger.info(f"处理：{name} ({country})")

    queries = [
        f"{name} portrait HD",
        f"{name} 高清 写真",
        f"{name} photoshoot",
    ]

    all_urls = []
    for query in queries:
        urls = search_bing_images(query, num_images=20)
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

        save_path = output_dir / f"{name}_bing_{idx:03d}.jpg"
        if save_path.exists():
            downloaded += 1
            continue

        if download_image(url, save_path):
            downloaded += 1
            caption_path = save_path.with_suffix(".txt")
            caption_path.write_text(caption_template, encoding="utf-8")

        time.sleep(random.uniform(1, 2))

    logger.info(f"{name}: 下载 {downloaded} 张高分")


def main():
    logger.info("=" * 60)
    logger.info("亚洲脸 LoRA 数据采集 — Bing 图片版")
    logger.info(f"最低分辨率：{MIN_WIDTH}x{MIN_HEIGHT}")
    logger.info(f"最低文件大小：{MIN_FILE_SIZE // 1000}KB")
    logger.info("=" * 60)

    captions = {
        "chinese": "古风女子，汉服，古典妆容，东方五官，丹凤眼，鹅蛋脸，写真",
        "korean": "韩国女子，精致妆容，亚洲五官，鹅蛋脸，写真",
        "japanese": "日本女子，精致妆容，亚洲五官，写真",
    }

    total = sum(len(v) for v in CELEBRITIES.values())
    current = 0

    for country, names in CELEBRITIES.items():
        for name in names:
            current += 1
            logger.info(f"[{current}/{total}] 处理：{name} ({country})")
            process_celebrity(name, country, captions[country])
            time.sleep(random.uniform(4, 7))

    logger.info("=" * 60)
    logger.info("Bing 采集完成！")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
