"""
曹全碑字图采集器 - 从 sfds.cn (书法大师/国学大师) 采集碑帖单字图片

工作流程:
1. 访问 https://www.sfds.cn/{HEX}/ 获取字的书法页面
2. 提取 m 变量、m2/gr cookie
3. 在页面中找到曹全碑对应的条目ID
4. POST /getpic2.php 获取图片路径
5. 从 pic.39017.com 下载图片

用法:
    python scrape_sfds.py --chars "永和九年" --stele 曹全碑
    python scrape_sfds.py --chars "永和九年" --stele all
"""
import argparse
import json
import math
import os
import random
import re
import time
import urllib.request
import urllib.parse
from http.cookiejar import CookieJar
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"
CHAR_DIR = DATA_DIR / "characters" / "lishu"
INDEX_FILE = DATA_DIR / "lishu_index.json"

# 经典隶书碑帖
STELES = ['曹全碑', '礼器碑', '乙瑛碑', '张迁碑', '史晨碑', '石门颂', '西狭颂', '华山庙碑']

BASE_URL = "https://www.sfds.cn"
PIC_BASE = "https://pic.39017.com:446/sfpic/sf/"


def fetch_char_page(char: str) -> tuple[str, dict]:
    """获取字的书法页面，返回 (html, cookies_dict)"""
    hex_code = format(ord(char), 'X')
    url = f"{BASE_URL}/{hex_code}/"

    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })

    resp = opener.open(req, timeout=15)
    html = resp.read().decode('utf-8', errors='ignore')

    cookies = {}
    for cookie in cj:
        cookies[cookie.name] = cookie.value

    return html, cookies


def extract_page_vars(html: str) -> dict:
    """从页面中提取 m, m2, gr 等变量"""
    result = {}

    # 提取 var m='...'
    m_match = re.search(r"var\s+m\s*=\s*'([^']*)'", html)
    if m_match:
        result['m'] = m_match.group(1)

    # 提取 setCookie('gr','...')
    gr_match = re.search(r"setCookie\('gr'\s*,\s*'([^']*)'\s*\)", html)
    if gr_match:
        result['gr'] = gr_match.group(1)

    # 提取 m2 from cookie set in JS
    m2_match = re.search(r"setCookie\('m2'\s*,\s*'([^']*)'\s*\)", html)
    if m2_match:
        result['m2'] = m2_match.group(1)

    return result


def find_stele_entries(html: str, char: str, stele_name: str = '曹全碑') -> list[dict]:
    """在页面中查找指定碑帖的条目"""
    hex_code = format(ord(char), 'X')
    entries = []

    # 匹配模式: /{HEX}/{ID}.html" ... title="字,碑帖名"
    pattern = rf'/{hex_code}/(\d+)\.html[^>]*title="[^"]*{re.escape(stele_name)}[^"]*"'
    matches = re.finditer(pattern, html)

    for match in matches:
        entry_id = match.group(1)
        entries.append({
            'id': entry_id,
            'stele': stele_name,
            'char': char,
        })

    # 也尝试另一种模式
    if not entries:
        pattern2 = rf'/{hex_code}/(\d+)\.html'
        id_matches = re.findall(pattern2, html)

        # 查找隶书区域
        lishu_section = re.search(r'隶书.*?(?=楷书|行书|草书|篆书|$)', html, re.DOTALL)
        if lishu_section:
            section = lishu_section.group(0)
            for eid in id_matches:
                if eid in section and stele_name in section:
                    entries.append({
                        'id': eid,
                        'stele': stele_name,
                        'char': char,
                    })

    return entries


def fetch_image_url(char: str, entry_ids: list[str], page_vars: dict, cookies: dict) -> list[str]:
    """通过 getpic2.php 获取图片URL"""
    hex_code = format(ord(char), 'X')

    m_val = page_vars.get('m', '')
    m2_val = page_vars.get('m2', cookies.get('m2', ''))
    gr_val = page_vars.get('gr', cookies.get('gr', ''))

    timestamp = str(int(time.time() * 1000))
    bt = str(math.ceil(500 + random.random() * 200 + 310))

    data = urllib.parse.urlencode({
        'timeStamp': timestamp,
        'p': ','.join(entry_ids),
        'bt': bt,
        'm': m_val + m2_val,
        'f': '2',
        'zi': char,
    }).encode('utf-8')

    cookie_str = '; '.join([
        f'zm={urllib.parse.quote(char)}',
        f'm2={m2_val}',
        f'gr={gr_val}',
    ])

    req = urllib.request.Request(
        f"{BASE_URL}/getpic2.php",
        data=data,
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Cookie': cookie_str,
            'Referer': f'{BASE_URL}/{hex_code}/',
            'Origin': BASE_URL,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode('utf-8', errors='ignore')
            paths = [p.strip() for p in result.split(',') if p.strip()]
            return [PIC_BASE + p for p in paths if p.endswith('.png') or p.endswith('.jpg')]
    except Exception as e:
        print(f"    获取图片URL失败: {e}")
        return []


def download_image(url: str, filepath: Path) -> bool:
    """下载图片"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': BASE_URL,
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            with open(filepath, 'wb') as f:
                f.write(resp.read())
        return True
    except Exception as e:
        print(f"    下载失败 {url}: {e}")
        return False


def update_index(entries: list[dict]):
    """更新字库索引"""
    index = {}
    if INDEX_FILE.exists():
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            index = json.load(f)

    for entry in entries:
        char = entry['char']
        if char not in index:
            index[char] = []
        existing = {e.get('image') for e in index[char]}
        if entry.get('image') not in existing:
            index[char].append(entry)

    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def scrape_char(char: str, stele_name: str = '曹全碑', output_dir: Path = CHAR_DIR) -> list[dict]:
    """采集单个字的碑帖图片"""
    print(f"\n[{char}] U+{ord(char):04X}")

    # Step 1: 获取页面
    try:
        html, cookies = fetch_char_page(char)
    except Exception as e:
        print(f"  页面获取失败: {e}")
        return []

    # Step 2: 提取变量
    page_vars = extract_page_vars(html)
    if not page_vars.get('m'):
        print(f"  未能提取页面变量")

    # Step 3: 查找碑帖条目
    steles_to_search = STELES if stele_name == 'all' else [stele_name]
    all_results = []

    for stele in steles_to_search:
        entries = find_stele_entries(html, char, stele)
        if not entries:
            continue

        print(f"  {stele}: 找到 {len(entries)} 个条目")
        entry_ids = [e['id'] for e in entries]

        # Step 4: 获取图片URL
        image_urls = fetch_image_url(char, entry_ids, page_vars, cookies)

        if not image_urls:
            print(f"    未获取到图片URL，尝试直接构造...")
            continue

        # Step 5: 下载图片
        for j, url in enumerate(image_urls):
            filename = f"{char}_{stele}_{j:02d}.png"
            filepath = output_dir / filename

            if filepath.exists():
                print(f"    跳过已有: {filename}")
                all_results.append({
                    'char': char,
                    'stele': stele,
                    'style': 'lishu',
                    'image': filename,
                })
                continue

            if download_image(url, filepath):
                print(f"    下载成功: {filename}")
                all_results.append({
                    'char': char,
                    'stele': stele,
                    'style': 'lishu',
                    'image': filename,
                    'url': url,
                })

    if not all_results:
        print(f"  未找到碑帖图片")

    return all_results


def main():
    parser = argparse.ArgumentParser(description='碑帖单字采集工具 (sfds.cn)')
    parser.add_argument('--chars', type=str, required=True, help='要采集的汉字')
    parser.add_argument('--stele', type=str, default='曹全碑',
                        help=f'碑帖名称，可选: {", ".join(STELES)}, all')
    parser.add_argument('--output', type=str, default=str(CHAR_DIR))
    parser.add_argument('--delay', type=float, default=2.0, help='请求间隔秒数')
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    chars = list(dict.fromkeys(args.chars))  # 去重保序
    print(f"采集 {len(chars)} 个字: {''.join(chars)}")
    print(f"碑帖: {args.stele}")
    print(f"输出: {output_dir}")

    all_entries = []
    for char in chars:
        entries = scrape_char(char, args.stele, output_dir)
        all_entries.extend(entries)
        time.sleep(args.delay)

    if all_entries:
        update_index(all_entries)
        print(f"\n完成! 共采集 {len(all_entries)} 张图片")
    else:
        print("\n未采集到图片。网站可能需要浏览器环境或有反爬限制。")
        print("建议: 手动访问 sfds.cn 确认页面结构，或使用 Selenium 方案。")


if __name__ == '__main__':
    main()
