#!/usr/bin/env python3
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   人脸训练集采集批的 **TMDB 图源变体**（同族共五版）。当初“每人选 3-5 张最高清、优先 TMDB”
#   这条筛选策略的数据来源就是它，改筛选口径前要先读它。
#   为什么没有调用方：采集是一次性动作。
"""
亚洲脸 LoRA 数据采集 — TMDB API 版 (v2)
- 代理支持（绕过 GFW）
- 搜索 API 自动匹配 ID（不再硬编码错误 ID）
- append_to_response=images 获取高清图
"""

import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
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
TARGET_PER_PERSON = 10

TMDB_API_KEY = "8b2b5889a364d2af80526d04dbaaa6f6"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"

PROXY = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}

# (中文名, 英文名/搜索词, 国家)
CELEBRITIES = [
    # Chinese (72 people)
    ("刘诗诗", "Cecilia Liu", "chinese"),
    ("彭小冉", "Peng Xiaoran", "chinese"),
    ("李一桐", "Li Yatong", "chinese"),
    ("甘婷婷", "Gan Tingting", "chinese"),
    ("翁美玲", "Barbara Yung", "chinese"),
    ("胡冰卿", "Hu Bingqing", "chinese"),
    ("黄圣依", "Huang Shengyi", "chinese"),
    ("陈红", "Chen Hong", "chinese"),
    ("舒畅", "Shu Chang", "chinese"),
    ("李若彤", "Carman Lee", "chinese"),
    ("傅艺伟", "Fu Yiwei", "chinese"),
    ("张晓敏", "Zhang Xiaomin", "chinese"),
    ("李建群", "Li Jianqun", "chinese"),
    ("刘亦菲", "Liu Yifei", "chinese"),
    ("赵丽颖", "Zhao Liying", "chinese"),
    ("杨幂", "Yang Mi", "chinese"),
    ("杨紫", "Yang Zi", "chinese"),
    ("迪丽热巴", "Dilraba Dilmurat", "chinese"),
    ("唐嫣", "Tang Yan", "chinese"),
    ("范冰冰", "Fan Bingbing", "chinese"),
    ("鞠婧祎", "Ju Jingyi", "chinese"),
    ("关晓彤", "Guan Xiaotong", "chinese"),
    ("赵露思", "Zhao Lusi", "chinese"),
    ("白鹿", "Bai Lu", "chinese"),
    ("虞书欣", "Esther Yu", "chinese"),
    ("杨超越", "Yang Chaoyue", "chinese"),
    ("李沁", "Li Qin", "chinese"),
    ("佟丽娅", "Tong Liya", "chinese"),
    ("宋祖儿", "Song Zuer", "chinese"),
    ("周也", "Zhou Ye", "chinese"),
    ("张予曦", "Zhang Yuxi", "chinese"),
    ("章若楠", "Zhang Ruonan", "chinese"),
    ("赵今麦", "Zhao Jinmai", "chinese"),
    ("沈月", "Shen Yue", "chinese"),
    ("田曦薇", "Tian Xiwei", "chinese"),
    ("王楚然", "Wang Churan", "chinese"),
    ("张婧仪", "Zhang Jingyi", "chinese"),
    ("卢昱晓", "Lu Yuxiao", "chinese"),
    ("刘心悠", "Liu Xinyou", "chinese"),
    ("刘涛", "Liu Tao", "chinese"),
    ("吴宣仪", "Wu Xuanyi", "chinese"),
    ("周洁琼", "Zhou Jieqiong", "chinese"),
    ("孙怡", "Sun Yi", "chinese"),
    ("孟美岐", "Meng Meiqi", "chinese"),
    ("宁静", "Ning Jing", "chinese"),
    ("宣璐", "Xuan Lu", "chinese"),
    ("巩俐", "Gong Li", "chinese"),
    ("张曼玉", "Maggie Cheung", "chinese"),
    ("张雅钦", "Zhang Yaqin", "chinese"),
    ("彭小", "Peng Xiao", "chinese"),
    ("徐艺洋", "Xu Yiyang", "chinese"),
    ("朱琳", "Zhu Lin", "chinese"),
    ("杨蓉", "Yang Rong", "chinese"),
    ("林青霞", "Brigitte Lin", "chinese"),
    ("王祖贤", "Joey Wong", "chinese"),
    ("祝绪丹", "Zhu Xudan", "chinese"),
    ("程潇", "Cheng Xiao", "chinese"),
    ("许晴", "Xu Qing", "chinese"),
    ("谭松韵", "Tan Songyun", "chinese"),
    ("贾静雯", "Alyssa Chia", "chinese"),
    ("赵雅芝", "Angie Chiu", "chinese"),
    ("邬倩倩", "Wu Qianqian", "chinese"),
    ("陈乔恩", "Joe Chen", "chinese"),
    ("陈好", "Chen Hao", "chinese"),
    ("陈都灵", "Chen Duling", "chinese"),
    ("霍思燕", "Huo Siyan", "chinese"),
    ("高圆圆", "Gao Yuanyuan", "chinese"),
    ("蒋勤勤", "Jiang Qinqin", "chinese"),
    ("董洁", "Dong Jie", "chinese"),
    ("茹萍", "Ru Ping", "chinese"),
    ("何晴", "He Qing", "chinese"),
    ("何赛飞", "He Saifei", "chinese"),
    # Korean (38 people)
    ("全智贤", "Gianna Jun", "korean"),
    ("尹恩惠", "Yoon Eun-hye", "korean"),
    ("文根英", "Moon Geun-young", "korean"),
    ("徐贤", "Seohyun", "korean"),
    ("林允儿", "Im Yoona", "korean"),
    ("申世景", "Shin Se-kyung", "korean"),
    ("裴珠泫", "Irene", "korean"),
    ("郑秀晶", "Krystal Jung", "korean"),
    ("金所炫", "Kim So-hyun", "korean"),
    ("金智秀", "Jisoo", "korean"),
    ("金泰梨", "Kim Tae-ri", "korean"),
    ("高允贞", "Go Yoon-jung", "korean"),
    ("韩素希", "Han So-hee", "korean"),
    ("金裕贞", "Kim Yoo-jung", "korean"),
    ("张元英", "Jang Wonyoung", "korean"),
    ("宋慧乔", "Song Hye-kyo", "korean"),
    ("朴信惠", "Park Shin-hye", "korean"),
    ("朴敏英", "Park Min-young", "korean"),
    ("朴恩斌", "Park Eun-bin", "korean"),
    ("裴秀智", "Bae Suzy", "korean"),
    ("金高银", "Kim Go-eun", "korean"),
    ("金喜善", "Kim Hee-sun", "korean"),
    ("李英爱", "Lee Young-ae", "korean"),
    ("李知恩", "IU", "korean"),
    ("李多海", "Lee Da-hae", "korean"),
    ("李侑菲", "Lee Yoo-bi", "korean"),
    ("李世荣", "Lee Se-young", "korean"),
    ("全汝彬", "Jeon Yeo-been", "korean"),
    ("南志铉", "Nam Ji-hyun", "korean"),
    ("卢正义", "Noh Jeong-ui", "korean"),
    ("崔雪莉", "Sulli", "korean"),
    ("徐睿知", "Seo Ye-ji", "korean"),
    ("成宥利", "Sung Yu-ri", "korean"),
    ("文佳", "Moon Ga-young", "korean"),
    ("权俞利", "Kwon Yu-ri", "korean"),
    ("林智妍", "Lim Ji-yeon", "korean"),
    ("蔡秀彬", "Chae Soo-bin", "korean"),
    ("表艺珍", "Pyo Ye-jin", "korean"),
    ("赵怡贤", "Jo Yi-hyun", "korean"),
    ("韩佳人", "Han Ga-in", "korean"),
    ("高旻示", "Go Min-si", "korean"),
    # Japanese (25 people)
    ("新垣结衣", "Aragaki Yui", "japanese"),
    ("北川景子", "Keiko Kitagawa", "japanese"),
    ("上户彩", "Aya Ueto", "japanese"),
    ("深田恭子", "Kyoko Fukada", "japanese"),
    ("绫濑遥", "Ayase Haruka", "japanese"),
    ("苍井优", "Yu Aoi", "japanese"),
    ("福原遥", "Fukuhara Haruka", "japanese"),
    ("中森明菜", "Akina Nakamori", "japanese"),
    ("菜菜绪", "Nanao", "japanese"),
    ("满岛光", "Hikari Mitsushima", "japanese"),
    ("石原里美", "Ishihara Satomi", "japanese"),
    ("桥本环奈", "Hashimoto Kanna", "japanese"),
    ("广濑铃", "Hirose Suzu", "japanese"),
    ("有村架纯", "Arimura Kasumi", "japanese"),
    ("长泽雅美", "Nagasawa Masami", "japanese"),
    ("户田惠梨香", "Toda Erika", "japanese"),
    ("堀北真希", "Horikita Maki", "japanese"),
    ("小松菜奈", "Komatsu Nana", "japanese"),
    ("永野芽郁", "Nagano Mei", "japanese"),
    ("滨边美波", "Hamabe Minami", "japanese"),
    ("今田美樱", "Imada Mio", "japanese"),
    ("土屋太凤", "Tsuchiya Tao", "japanese"),
    ("三吉彩花", "Miyoshi Ayaka", "japanese"),
    ("上野树里", "Ueno Juri", "japanese"),
    ("山下美月", "Yamashita Mizuki", "japanese"),
    ("斋藤飞鸟", "Saito Asuka", "japanese"),
    ("白石麻衣", "Shiraishi Mai", "japanese"),
    ("西野七濑", "Nishino Nanase", "japanese"),
    ("生田绘梨花", "Ikuta Erika", "japanese"),
    ("樱井玲香", "Sakurai Reika", "japanese"),
    ("与田祐希", "Yoda Yuki", "japanese"),
    ("久保史绪里", "Kubo Shiori", "japanese"),
    ("中山美穗", "Nakayama Miho", "japanese"),
    ("松田圣子", "Matsuda Seiko", "japanese"),
    ("酒井法子", "Sakai Noriko", "japanese"),
    ("柴崎幸", "Shibasaki Ko", "japanese"),
    ("桐谷美玲", "Kiritani Mirei", "japanese"),
    ("宫崎葵", "Miyazaki Aoi", "japanese"),
    ("宫泽理惠", "Miyazawa Rie", "japanese"),
    ("井上真央", "Inoue Mao", "japanese"),
]

CAPTIONS = {
    "chinese": "古风女子，汉服，古典妆容，东方五官，丹凤眼，鹅蛋脸，写真",
    "korean": "韩国女子，精致妆容，亚洲五官，鹅蛋脸，写真",
    "japanese": "日本女子，精致妆容，亚洲五官，写真",
}


def search_person_tmdb(query: str) -> Optional[int]:
    """搜索 TMDB 人物，返回第一个有图的 ID"""
    url = f"{TMDB_BASE_URL}/search/person"
    params = {"api_key": TMDB_API_KEY, "query": query}

    try:
        r = requests.get(url, params=params, proxies=PROXY, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])

        for p in results[:3]:
            pid = p["id"]
            imgs = get_person_image_urls(pid)
            if imgs:
                return pid
            time.sleep(0.2)
    except Exception as e:
        logger.warning(f"搜索 '{query}' 失败: {e}")

    return None


def get_person_image_urls(person_id: int) -> List[str]:
    """用 append_to_response 获取人物图片 URL"""
    url = f"{TMDB_BASE_URL}/person/{person_id}"
    params = {"api_key": TMDB_API_KEY, "append_to_response": "images"}

    try:
        r = requests.get(url, params=params, proxies=PROXY, timeout=15)
        r.raise_for_status()
        data = r.json()

        profiles = data.get("images", {}).get("profiles", [])
        urls = []
        for p in profiles:
            path = p.get("file_path")
            w = p.get("width", 0)
            h = p.get("height", 0)
            if path and w >= MIN_WIDTH and h >= MIN_HEIGHT:
                urls.append(TMDB_IMAGE_BASE + path)
        return urls
    except Exception as e:
        logger.warning(f"获取 person/{person_id} 图片失败: {e}")
        return []


def download_image(url: str, save_path: Path) -> bool:
    """下载图片并验证分辨率"""
    try:
        r = requests.get(url, proxies=PROXY, timeout=20, stream=True)
        r.raise_for_status()

        temp_path = save_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        if not temp_path.exists() or temp_path.stat().st_size < 50000:
            temp_path.unlink(missing_ok=True)
            return False

        temp_path.rename(save_path)

        img_array = np.fromfile(str(save_path), dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            save_path.unlink(missing_ok=True)
            return False

        h, w = img.shape[:2]
        if w < MIN_WIDTH or h < MIN_HEIGHT:
            logger.debug(f"分辨率不足 {w}x{h}: {save_path}")
            save_path.unlink()
            return False

        logger.info(f"  ✓ {w}x{h} {save_path.name}")
        return True

    except Exception as e:
        logger.debug(f"下载失败 {url}: {e}")
        save_path.unlink(missing_ok=True)
        return False


def count_high_res(name: str, country: str) -> int:
    """统计某人已有多少张高分图"""
    d = BASE_DIR / country / name
    if not d.exists():
        return 0
    count = 0
    for f in d.glob("*.jpg"):
        try:
            arr = np.fromfile(str(f), dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                h, w = img.shape[:2]
                if w >= MIN_WIDTH and h >= MIN_HEIGHT:
                    count += 1
        except:
            pass
    return count


def process_celebrity(name: str, en_name: str, country: str):
    """处理单个明星"""
    existing_high = count_high_res(name, country)
    if existing_high >= TARGET_PER_PERSON:
        logger.info(f"跳过 {name}: 已有 {existing_high} 张高分")
        return

    output_dir = BASE_DIR / country / name
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"搜索 {name} ({en_name})...")
    person_id = search_person_tmdb(en_name)
    if person_id is None:
        logger.warning(f"  ✗ {name} 在 TMDB 未找到")
        return

    urls = get_person_image_urls(person_id)
    if not urls:
        logger.warning(f"  ✗ {name} (ID={person_id}) 无高分图")
        return

    logger.info(f"  {name}: {len(urls)} 张高分图可下载")

    downloaded = 0
    for idx, url in enumerate(urls):
        if existing_high + downloaded >= TARGET_PER_PERSON:
            break

        save_path = output_dir / f"{name}_tmdb_{idx:03d}.jpg"
        if save_path.exists():
            downloaded += 1
            continue

        if download_image(url, save_path):
            downloaded += 1
            caption_path = save_path.with_suffix(".txt")
            caption_path.write_text(CAPTIONS[country], encoding="utf-8")

        time.sleep(0.3)

    logger.info(f"  {name}: 新下载 {downloaded} 张")


def main():
    logger.info("=" * 60)
    logger.info("TMDB 高分采集 v2 (代理模式)")
    logger.info(f"最低分辨率: {MIN_WIDTH}x{MIN_HEIGHT}, 目标: {TARGET_PER_PERSON} 张/人")
    logger.info("=" * 60)

    # Test proxy
    try:
        r = requests.get(
            f"{TMDB_BASE_URL}/search/person",
            params={"api_key": TMDB_API_KEY, "query": "test"},
            proxies=PROXY,
            timeout=10,
        )
        r.raise_for_status()
        logger.info("代理连接正常 ✓")
    except Exception as e:
        logger.error(f"代理连接失败: {e}")
        logger.error("请确认 Clash 已开启且监听 127.0.0.1:7890")
        return

    total = len(CELEBRITIES)
    success = 0
    for i, (name, en_name, country) in enumerate(CELEBRITIES, 1):
        logger.info(f"[{i}/{total}] {name}")
        process_celebrity(name, en_name, country)
        success += 1
        time.sleep(0.5)

    logger.info("=" * 60)
    logger.info(f"TMDB 采集完成! 处理 {success}/{total} 个明星")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
