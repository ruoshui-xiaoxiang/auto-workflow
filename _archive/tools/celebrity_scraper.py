#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   人脸 LoRA 训练集采集批的**初版**（通用抓取）。同族还有四个按数据源/策略分叉的变体，
#   五版并存是当时的实验记录，不是漏清理：每版的取舍都影响过最终数据集。
#   为什么没有调用方：采集是一次性动作，跑完就停；重跑由人手动决定。
#   ⚠ 要重采先看这一族哪个版本对应你要的数据源，别默认拿初版。
"""
明星人脸数据采集爬虫
从百度图片搜索下载指定明星的照片，用于训练亚洲人脸 LoRA
"""

import os
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlencode
from PIL import Image
import cv2
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('celebrity_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 配置 ====================

# 输出目录
OUTPUT_DIR = Path("D:/AIWorkflow/training/datasets/asian_faces")

# 每个明星下载的图片数
IMAGES_PER_CELEBRITY = 5

# 图片最小尺寸（过滤小图）
MIN_WIDTH = 200
MIN_HEIGHT = 200

# 图片最小文件大小（过滤缩略图，单位：KB）
MIN_FILE_SIZE_KB = 20

# 下载超时（秒）
DOWNLOAD_TIMEOUT = 15

# 请求间隔（秒），避免被封
REQUEST_DELAY = (1, 3)

# 是否启用人脸检测（需要 OpenCV）
ENABLE_FACE_DETECTION = True

# 人脸检测后裁剪边距（像素）
FACE_CROP_MARGIN = 50

# ==================== 明星名单 ====================

CELEBRITIES = {
    # 中国 - 新生代
    "刘亦菲": "chinese",
    "杨幂": "chinese",
    "赵丽颖": "chinese",
    "迪丽热巴": "chinese",
    "杨紫": "chinese",
    "刘诗诗": "chinese",
    "鞠婧祎": "chinese",
    "白鹿": "chinese",
    "周也": "chinese",
    "张婧仪": "chinese",
    "赵露思": "chinese",
    "虞书欣": "chinese",
    "李沁": "chinese",
    "宋祖儿": "chinese",
    "关晓彤": "chinese",
    "谭松韵": "chinese",
    "陈都灵": "chinese",
    "王楚然": "chinese",
    "卢昱晓": "chinese",
    "田曦薇": "chinese",
    "张雅钦": "chinese",
    "沈月": "chinese",
    "章若楠": "chinese",
    "周洁琼": "chinese",
    "程潇": "chinese",
    "吴宣仪": "chinese",
    "孟美岐": "chinese",
    "杨超越": "chinese",
    "徐艺洋": "chinese",
    "赵今麦": "chinese",
    # 中国 - 中生代
    "陈好": "chinese",
    "李小冉": "chinese",
    "佟丽娅": "chinese",
    "宋轶": "chinese",
    "宣璐": "chinese",
    "李一桐": "chinese",
    "张予曦": "chinese",
    "彭小": "chinese",
    "祝绪丹": "chinese",
    "杨蓉": "chinese",
    "甘婷婷": "chinese",
    "刘涛": "chinese",
    "胡冰卿": "chinese",
    "孙怡": "chinese",
    "董洁": "chinese",
    "舒畅": "chinese",
    "贾静雯": "chinese",
    "范冰冰": "chinese",
    "黄圣依": "chinese",
    "陈乔恩": "chinese",
    "高圆圆": "chinese",
    "刘心悠": "chinese",
    "唐嫣": "chinese",
    "霍思燕": "chinese",
    # 中国 - 经典
    "林青霞": "chinese",
    "张曼玉": "chinese",
    "王祖贤": "chinese",
    "邱淑贞": "chinese",
    "陈红": "chinese",
    "何赛飞": "chinese",
    "蒋勤勤": "chinese",
    "巩俐": "chinese",
    "宁静": "chinese",
    "朱琳": "chinese",
    "何晴": "chinese",
    "刘晓庆": "chinese",
    "李若彤": "chinese",
    "赵雅芝": "chinese",
    "翁美玲": "chinese",
    # 韩国 - 新生代
    "李知恩": "korean",
    "裴秀智": "korean",
    "林允儿": "korean",
    "朴敏英": "korean",
    "韩素希": "korean",
    "金泰梨": "korean",
    "高允贞": "korean",
    "文佳": "korean",
    "张元英": "korean",
    "裴珠泫": "korean",
    "金智秀": "korean",
    "孙娜恩": "korean",
    "郑秀晶": "korean",
    "金所炫": "korean",
    "卢正义": "korean",
    "赵怡贤": "korean",
    "高旻示": "korean",
    "全汝彬": "korean",
    "徐贤": "korean",
    # 韩国 - 中生代/经典
    "朴信惠": "korean",
    "南志铉": "korean",
    "申世景": "korean",
    "蔡秀彬": "korean",
    "金裕贞": "korean",
    "徐睿知": "korean",
    "表艺珍": "korean",
    "李世荣": "korean",
    "权俞利": "korean",
    "崔雪莉": "korean",
    "韩佳人": "korean",
    "李多海": "korean",
    "成宥利": "korean",
    "李英爱": "korean",
    "金喜善": "korean",
    "全智贤": "korean",
    "宋慧乔": "korean",
    # 日本 - 新生代
    "桥本环奈": "japanese",
    "滨边美波": "japanese",
    "今田美樱": "japanese",
    "永野芽郁": "japanese",
    "石原里美": "japanese",
    "菜菜绪": "japanese",
    "三吉彩花": "japanese",
    "小松菜奈": "japanese",
    "有村架纯": "japanese",
    "广濑铃": "japanese",
    "土屋太凤": "japanese",
    "福原遥": "japanese",
    "西野七濑": "japanese",
    "斋藤飞鸟": "japanese",
    "白石麻衣": "japanese",
    "山下美月": "japanese",
    "与田祐希": "japanese",
    "久保史绪里": "japanese",
    "樱井玲香": "japanese",
    "生田绘梨花": "japanese",
    # 日本 - 中生代/经典
    "绫濑遥": "japanese",
    "长泽雅美": "japanese",
    "堀北真希": "japanese",
    "新垣结衣": "japanese",
    "北川景子": "japanese",
    "深田恭子": "japanese",
    "上户彩": "japanese",
    "柴崎幸": "japanese",
    "满岛光": "japanese",
    "苍井优": "japanese",
    "户田惠梨香": "japanese",
    "桐谷美玲": "japanese",
    "中森明菜": "japanese",
    "宫泽理惠": "japanese",
    "松田圣子": "japanese",
    "中山美穗": "japanese",
    "酒井法子": "japanese",
}

# ==================== 工具函数 ====================

def get_headers() -> Dict[str, str]:
    """完整浏览器指纹"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
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


def search_baidu_images(keyword: str, num_images: int = 20) -> List[str]:
    """
    从百度图片搜索获取图片 URL 列表
    """
    urls = []
    page_num = 0

    # 使用 session 保持 cookie
    session = requests.Session()
    headers = get_headers()
    session.headers.update(headers)

    # 先访问主页获取 cookie
    try:
        session.get("https://image.baidu.com/", timeout=5)
    except Exception:
        pass

    while len(urls) < num_images:
        # 百度图片搜索 API（翻页）
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

            # 百度可能返回 JSONP 或纯 JSON
            text = response.text

            # 尝试提取 JSONP 格式
            json_match = re.search(r'\((.*)\)', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                # 直接解析 JSON
                data = json.loads(text)

            images = data.get("data", [])

            if not images:
                break

            for img in images:
                if len(urls) >= num_images:
                    break
                # 优先使用 thumbURL（objURL 是百度加密的，不可用）
                img_url = (
                    img.get("thumbURL") or
                    img.get("ThumbURL") or
                    img.get("objURL") or
                    img.get("ObjURL")
                )
                if img_url:
                    # 百度图片 URL 有时是编码的，需要解码
                    img_url = img_url.replace("\\/", "/")
                    urls.append(img_url)

            page_num += 30
            time.sleep(random.uniform(1, 2))

        except Exception as e:
            logger.warning(f"搜索 {keyword} 第 {page_num} 页失败：{e}")
            break

    return urls[:num_images]


def download_image(url: str, save_path: Path, timeout: int = 15) -> bool:
    """
    下载单张图片，自动转换 webp 为 jpg
    """
    try:
        headers = get_headers()
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        # 检查内容类型
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return False

        # 写入临时文件
        save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = save_path.with_suffix(".tmp")

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # 验证文件
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            temp_path.unlink(missing_ok=True)
            return False

        # 如果是 webp，转换为 jpg
        try:
            with Image.open(temp_path) as img:
                if img.format == "WEBP" or temp_path.suffix == ".webp":
                    # 转换为 RGB（webp 可能是 RGBA）
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(save_path, "JPEG", quality=95)
                    temp_path.unlink()
                else:
                    # 直接重命名
                    temp_path.rename(save_path)
        except Exception:
            # PIL 打不开，直接重命名
            temp_path.rename(save_path)

        if not save_path.exists() or save_path.stat().st_size == 0:
            save_path.unlink(missing_ok=True)
            return False

        return True

    except Exception as e:
        logger.debug(f"下载失败 {url}: {e}")
        return False


def validate_image(image_path: Path) -> bool:
    """
    验证图片：尺寸、文件大小、能否打开
    """
    try:
        # 文件大小检查
        file_size_kb = image_path.stat().st_size / 1024
        if file_size_kb < MIN_FILE_SIZE_KB:
            return False

        # 打开图片检查
        with Image.open(image_path) as img:
            width, height = img.size

            # 尺寸检查
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return False

            # 转换为 RGB（如果需要）
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
                img.save(image_path)

        return True

    except Exception:
        return False


def detect_and_crop_face(image_path: Path, output_path: Path) -> bool:
    """
    检测人脸并裁剪
    """
    try:
        # 读取图片
        img = cv2.imread(str(image_path))
        if img is None:
            return False

        # 转为灰度图
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 使用 Haar Cascade 检测人脸
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(100, 100),
        )

        if len(faces) == 0:
            return False

        # 取最大的人脸
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = largest_face

        # 计算裁剪区域（加边距）
        h_img, w_img = img.shape[:2]
        x1 = max(0, x - FACE_CROP_MARGIN)
        y1 = max(0, y - FACE_CROP_MARGIN)
        x2 = min(w_img, x + w + FACE_CROP_MARGIN)
        y2 = min(h_img, y + h + FACE_CROP_MARGIN)

        # 裁剪
        cropped = img[y1:y2, x1:x2]

        # 保存
        cv2.imwrite(str(output_path), cropped)
        return True

    except Exception as e:
        logger.debug(f"人脸检测失败 {image_path}: {e}")
        return False


def file_hash(file_path: Path) -> str:
    """计算文件哈希（用于去重）"""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# ==================== 主流程 ====================

def process_celebrity(name: str, region: str, output_dir: Path) -> Dict:
    """
    处理单个明星：搜索、下载、验证、人脸裁剪
    """
    result = {
        "name": name,
        "region": region,
        "downloaded": 0,
        "valid": 0,
        "with_face": 0,
        "errors": [],
    }

    logger.info(f"开始处理：{name} ({region})")

    # 创建输出目录
    celeb_dir = output_dir / region / name
    celeb_dir.mkdir(parents=True, exist_ok=True)

    # 搜索图片 URL
    search_keyword = f"{name} 古装 写真" if region == "chinese" else f"{name} portrait"
    urls = search_baidu_images(search_keyword, num_images=IMAGES_PER_CELEBRITY * 3)

    if not urls:
        result["errors"].append("未搜索到图片")
        logger.warning(f"{name}: 未搜索到图片")
        return result

    # 下载图片
    downloaded = []
    for i, url in enumerate(urls):
        if len(downloaded) >= IMAGES_PER_CELEBRITY:
            break

        # 生成文件名
        ext = ".jpg"
        save_path = celeb_dir / f"{name}_{i:03d}{ext}"

        # 下载
        if download_image(url, save_path):
            downloaded.append(save_path)
            result["downloaded"] += 1

        # 随机延迟
        time.sleep(random.uniform(*REQUEST_DELAY))

    # 验证图片
    valid_images = []
    for img_path in downloaded:
        if validate_image(img_path):
            valid_images.append(img_path)
            result["valid"] += 1
        else:
            img_path.unlink(missing_ok=True)

    # 人脸检测 + 裁剪
    if ENABLE_FACE_DETECTION:
        face_images = []
        for img_path in valid_images:
            # 先保存到临时位置
            temp_path = img_path.with_suffix(".temp.jpg")
            img_path.rename(temp_path)

            if detect_and_crop_face(temp_path, img_path):
                face_images.append(img_path)
                result["with_face"] += 1
                temp_path.unlink(missing_ok=True)
            else:
                # 没有检测到人脸，保留原图
                temp_path.rename(img_path)
                face_images.append(img_path)
    else:
        face_images = valid_images

    logger.info(
        f"{name}: 下载 {result['downloaded']}, "
        f"有效 {result['valid']}, "
        f"有人脸 {result['with_face']}"
    )

    return result


def deduplicate_dataset(output_dir: Path):
    """
    数据集去重（基于文件哈希）
    """
    logger.info("开始去重...")

    seen_hashes = set()
    removed = 0

    for img_path in output_dir.rglob("*.jpg"):
        file_hash_val = file_hash(img_path)

        if file_hash_val in seen_hashes:
            img_path.unlink()
            removed += 1
        else:
            seen_hashes.add(file_hash_val)

    logger.info(f"去重完成，删除 {removed} 个重复文件")


def generate_captions(output_dir: Path):
    """
    为每张图片生成 caption 文件
    """
    logger.info("生成 caption 文件...")

    caption_template = {
        "chinese": "古风女子，汉服，古典妆容，东方五官，丹凤眼，鹅蛋脸，写真",
        "korean": "韩国女子，优雅，东方五官，写真",
        "japanese": "日本女子，清新，东方五官，写真",
    }

    for img_path in output_dir.rglob("*.jpg"):
        # 从路径获取区域信息
        parts = img_path.parts
        region = "chinese"
        for part in parts:
            if part in ("chinese", "korean", "japanese"):
                region = part
                break

        caption = caption_template.get(region, caption_template["chinese"])

        # 写入 caption 文件
        caption_path = img_path.with_suffix(".txt")
        with open(caption_path, "w", encoding="utf-8") as f:
            f.write(caption)

    logger.info("Caption 生成完成")


def main():
    """
    主函数
    """
    logger.info("=" * 60)
    logger.info("明星人脸数据采集开始")
    logger.info(f"输出目录：{OUTPUT_DIR}")
    logger.info(f"明星数量：{len(CELEBRITIES)}")
    logger.info(f"每人图片数：{IMAGES_PER_CELEBRITY}")
    logger.info("=" * 60)

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 处理所有明星
    results = []

    # 使用线程池并发下载（但每个明星内部是串行的）
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(process_celebrity, name, region, OUTPUT_DIR): name
            for name, region in CELEBRITIES.items()
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"{name} 处理失败：{e}")
                results.append({
                    "name": name,
                    "region": CELEBRITIES[name],
                    "downloaded": 0,
                    "valid": 0,
                    "with_face": 0,
                    "errors": [str(e)],
                })

    # 统计
    total_downloaded = sum(r["downloaded"] for r in results)
    total_valid = sum(r["valid"] for r in results)
    total_with_face = sum(r["with_face"] for r in results)

    logger.info("=" * 60)
    logger.info("采集完成统计")
    logger.info(f"总下载：{total_downloaded}")
    logger.info(f"总有效：{total_valid}")
    logger.info(f"有人脸：{total_with_face}")
    logger.info("=" * 60)

    # 去重
    deduplicate_dataset(OUTPUT_DIR)

    # 生成 caption
    generate_captions(OUTPUT_DIR)

    # 保存结果
    result_file = OUTPUT_DIR / "scraping_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"结果已保存到：{result_file}")
    logger.info("全部完成！")


if __name__ == "__main__":
    main()
