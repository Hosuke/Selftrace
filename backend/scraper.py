"""
碑帖单字采集工具
从书法字典网站采集隶书碑帖单字图片

支持数据源：
1. sfds.cn (书法大师) - URL结构规律，按Unicode查字
2. shufazidian.com (书法字典) - POST接口查字

用法：
    python scraper.py --source sfds --chars "永和九年" --style lishu --output ../data/characters/lishu
"""
import argparse
import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"
CHAR_DIR = DATA_DIR / "characters" / "lishu"
INDEX_FILE = DATA_DIR / "lishu_index.json"


def scrape_sfds(char: str, output_dir: Path) -> list[dict]:
    """
    从 sfds.cn 采集单字书法图片
    URL格式: https://www.sfds.cn/{hex_code}/
    其中 hex_code 是字的 Unicode 十六进制编码（大写）
    """
    hex_code = format(ord(char), 'X')
    url = f"https://www.sfds.cn/{hex_code}/"

    results = []
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # 解析页面中的隶书图片链接
        # sfds.cn 页面中图片通常在 img 标签中，按书体分类
        import re
        # 查找隶书区域的图片
        img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', re.I)
        imgs = img_pattern.findall(html)

        # 查找包含碑帖信息的内容
        stele_pattern = re.compile(r'(曹全碑|礼器碑|乙瑛碑|张迁碑|史晨碑|石门颂|西狭颂|鲜于璜碑|衡方碑|华山庙碑)', re.I)

        for i, img_url in enumerate(imgs):
            if not img_url.startswith('http'):
                img_url = f"https://www.sfds.cn{img_url}" if img_url.startswith('/') else f"https://www.sfds.cn/{img_url}"

            # 只下载书法图片（通常包含特定路径模式）
            if any(kw in img_url.lower() for kw in ['lishu', '隶', 'ls', '/l/']):
                filename = f"{char}_{i:03d}.png"
                filepath = output_dir / filename
                try:
                    urllib.request.urlretrieve(img_url, filepath)
                    results.append({
                        "char": char,
                        "source": "sfds.cn",
                        "style": "lishu",
                        "image": filename,
                        "url": img_url,
                    })
                    print(f"  下载: {char} -> {filename}")
                except Exception as e:
                    print(f"  下载失败: {img_url} - {e}")

    except Exception as e:
        print(f"  采集失败 [{char}]: {e}")

    return results


def scrape_shufazidian(char: str, output_dir: Path) -> list[dict]:
    """
    从 shufazidian.com 采集单字
    使用 POST 接口，type=6 表示隶书
    """
    url = "http://www.shufazidian.com/"
    results = []

    try:
        data = urllib.parse.urlencode({
            'wd': char,
            'sort': '6',  # 6 = 隶书
        }).encode('utf-8')

        req = urllib.request.Request(url, data=data, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Content-Type': 'application/x-www-form-urlencoded',
        })

        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        import re
        img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', re.I)
        imgs = img_pattern.findall(html)

        # 提取碑帖来源信息
        source_pattern = re.compile(r'title=["\']([^"\']*(?:碑|帖|铭|颂)[^"\']*)["\']', re.I)
        sources = source_pattern.findall(html)

        downloaded = 0
        for i, img_url in enumerate(imgs):
            if downloaded >= 10:  # 每个字最多10张
                break
            if not img_url.startswith('http'):
                continue
            # 过滤非书法图片
            if any(kw in img_url for kw in ['logo', 'banner', 'ad', 'icon']):
                continue

            filename = f"{char}_{downloaded:03d}.png"
            filepath = output_dir / filename
            try:
                urllib.request.urlretrieve(img_url, filepath)
                source_name = sources[downloaded] if downloaded < len(sources) else "未知碑帖"
                results.append({
                    "char": char,
                    "source": source_name,
                    "style": "lishu",
                    "image": filename,
                    "url": img_url,
                })
                downloaded += 1
                print(f"  下载: {char} -> {filename} ({source_name})")
            except Exception as e:
                print(f"  下载失败: {img_url} - {e}")

    except Exception as e:
        print(f"  采集失败 [{char}]: {e}")

    return results


def update_index(new_entries: list[dict]):
    """更新字库索引"""
    index = {}
    if INDEX_FILE.exists():
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            index = json.load(f)

    for entry in new_entries:
        char = entry['char']
        if char not in index:
            index[char] = []
        # 避免重复
        existing_images = {e['image'] for e in index[char]}
        if entry['image'] not in existing_images:
            index[char].append(entry)

    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n字库索引已更新: {len(index)} 个字")


def main():
    parser = argparse.ArgumentParser(description='碑帖单字采集工具')
    parser.add_argument('--chars', type=str, required=True, help='要采集的汉字')
    parser.add_argument('--source', type=str, default='sfds', choices=['sfds', 'shufazidian', 'all'],
                        help='数据源')
    parser.add_argument('--output', type=str, default=str(CHAR_DIR), help='输出目录')
    parser.add_argument('--delay', type=float, default=1.0, help='请求间隔（秒）')
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    chars = list(set(args.chars))  # 去重
    print(f"开始采集 {len(chars)} 个字: {''.join(chars)}")
    print(f"数据源: {args.source}")
    print(f"输出目录: {output_dir}\n")

    all_entries = []

    for char in chars:
        print(f"[{char}] (U+{ord(char):04X})")

        if args.source in ('sfds', 'all'):
            entries = scrape_sfds(char, output_dir)
            all_entries.extend(entries)

        if args.source in ('shufazidian', 'all'):
            entries = scrape_shufazidian(char, output_dir)
            all_entries.extend(entries)

        if not any(e['char'] == char for e in all_entries):
            print(f"  未找到碑帖图片")

        time.sleep(args.delay)

    if all_entries:
        update_index(all_entries)
        print(f"\n共采集 {len(all_entries)} 张碑帖字图片")
    else:
        print("\n未采集到任何图片，可能需要检查网络或数据源")


if __name__ == '__main__':
    main()
