#!/usr/bin/env python3
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   训练集**精选**步骤：每人 3-5 张最高清、目标 400-500 张、要求分布均衡。
#   为什么没有调用方：它是训练流程里手动执行的一步，不在自动链上。
#   ⚠ 它定的“每人 3-5 张”与清晰度门槛是**数据集构成口径**，重训 LoRA 前要照它复现，别随手换。
"""
从完整数据集筛选精选训练集
策略：每人选 3-5 张最高清的图（优先 TMDB）
目标：400-500 张，均衡分布
"""
import shutil
from pathlib import Path
import cv2
import numpy as np

SRC_DIR = Path(r"E:\LocalAI\dataset\asian_faces")
DST_DIR = Path(r"E:\LocalAI\dataset\asian_faces_curated")
MIN_PER_PERSON = 3
MAX_PER_PERSON = 5
TARGET_TOTAL = 450

def get_image_resolution(img_path: Path) -> int:
    """返回图片的短边像素数"""
    try:
        arr = np.fromfile(str(img_path), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return 0
        h, w = img.shape[:2]
        return min(w, h)
    except Exception:
        return 0

def curate_dataset():
    """筛选精选训练集"""
    if DST_DIR.exists():
        shutil.rmtree(DST_DIR)
    DST_DIR.mkdir(parents=True)
    
    total_selected = 0
    stats = {}
    
    # 遍历三个国家目录
    for country_dir in sorted(SRC_DIR.iterdir()):
        if not country_dir.is_dir() or country_dir.name not in ['chinese', 'korean', 'japanese']:
            continue
        
        country_name = country_dir.name
        country_dst = DST_DIR / country_name
        country_dst.mkdir(parents=True)
        
        country_stats = {'people': 0, 'images': 0}
        
        # 遍历每个人物目录
        for person_dir in sorted(country_dir.iterdir()):
            if not person_dir.is_dir():
                continue
            
            person_name = person_dir.name
            country_stats['people'] += 1
            
            # 收集所有图片及其分辨率
            images_with_res = []
            for img_path in person_dir.glob('*.jpg'):
                res = get_image_resolution(img_path)
                if res > 0:
                    # TMDB 图片加权（优先选择）
                    is_tmdb = '_tmdb_' in img_path.name
                    images_with_res.append((img_path, res, is_tmdb))
            
            if not images_with_res:
                continue
            
            # 排序：先按是否 TMDB（TMDB 优先），再按分辨率降序
            images_with_res.sort(key=lambda x: (x[2], x[1]), reverse=True)
            
            # 选择 MIN_PER_PERSON 到 MAX_PER_PERSON 张
            num_to_select = min(MAX_PER_PERSON, len(images_with_res))
            num_to_select = max(MIN_PER_PERSON, min(num_to_select, len(images_with_res)))
            
            selected = images_with_res[:num_to_select]
            
            # 复制到目标目录
            person_dst = country_dst / person_name
            person_dst.mkdir(parents=True)
            
            for img_path, res, is_tmdb in selected:
                dst_path = person_dst / img_path.name
                shutil.copy2(img_path, dst_path)
                
                # 同时复制对应的 txt 标注文件
                txt_path = img_path.with_suffix('.txt')
                if txt_path.exists():
                    shutil.copy2(txt_path, dst_path.with_suffix('.txt'))
                
                country_stats['images'] += 1
                total_selected += 1
        
        stats[country_name] = country_stats
        print(f"{country_name}: {country_stats['people']} 人, {country_stats['images']} 张")
    
    print(f"\n总计: {total_selected} 张")
    print(f"目标: {TARGET_TOTAL} 张")
    print(f"输出目录: {DST_DIR}")
    
    return total_selected

if __name__ == "__main__":
    print("=" * 60)
    print("亚洲脸 LoRA 精选训练集生成")
    print(f"策略: 每人 {MIN_PER_PERSON}-{MAX_PER_PERSON} 张，优先 TMDB 高清图")
    print("=" * 60)
    
    total = curate_dataset()
    
    print("\n" + "=" * 60)
    print("筛选完成！")
    print("=" * 60)
