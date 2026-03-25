/**
 * Vercel Serverless Function: 碑帖字图代理
 *
 * 架构设计:
 * ┌──────────┐    /api/stele-image?char=永&stele=礼器碑
 * │ Frontend │ ──────────────────────────────────────────►┌──────────────┐
 * │ (Canvas) │ ◄──────────── image/png ──────────────────│  Vercel Edge  │
 * └──────────┘                                           │  Serverless   │
 *                                                        │  Function     │
 *                                                        └──────┬───────┘
 *                                                               │ 1. Check edge cache
 *                                                               │ 2. Fetch sfds.cn page
 *                                                               │ 3. Parse stele image URL
 *                                                               │ 4. Proxy image back
 *                                                               │ 5. Set cache headers
 *                                                               ▼
 *                                                        ┌──────────────┐
 *                                                        │  sfds.cn     │
 *                                                        │  (书法大师)   │
 *                                                        └──────────────┘
 *
 * 缓存策略:
 * - Vercel Edge Cache: 30天 (同一个字+碑帖组合永远不变)
 * - 浏览器缓存: 7天
 * - 首次请求: ~1-2秒 (fetch + parse + proxy)
 * - 缓存命中: <50ms
 */

const https = require('https');
const http = require('http');

// 支持的碑帖列表
const VALID_STELES = [
  '曹全碑', '礼器碑', '乙瑛碑', '张迁碑', '史晨碑', '石门颂', '西狭颂', '华山庙碑',
  '鲜于璜碑', '衡方碑', '封龙山碑', '孔宙碑', '张景碑', '朝侯小子碑',
];

function fetchUrl(url, options = {}) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,image/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        ...options.headers,
      },
      timeout: 10000,
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        // Follow redirect
        fetchUrl(res.headers.location, options).then(resolve).catch(reject);
        return;
      }
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        resolve({
          status: res.statusCode,
          headers: res.headers,
          body: Buffer.concat(chunks),
        });
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// 从 sfds.cn 页面解析碑帖图片
function parseSteleImages(html, char, steleName) {
  const results = [];

  // 匹配模式: <img ... title="字,碑帖名" ... src="..." ...>
  // 或: <a href="...html" title="字,碑帖名"> 附近的图片
  const regex = new RegExp(
    `<(?:img|a)[^>]*title=["']${escapeRegex(char)}[,，]\\s*${escapeRegex(steleName)}[^"']*["'][^>]*>`,
    'gi'
  );

  // 也尝试更宽松的匹配
  const imgRegex = /<img[^>]+src=["']([^"']+)["'][^>]*title=["']([^"']+)["'][^>]*>/gi;
  const imgRegex2 = /<img[^>]+title=["']([^"']+)["'][^>]*src=["']([^"']+)["'][^>]*>/gi;

  let match;
  while ((match = imgRegex.exec(html)) !== null) {
    const [, src, title] = match;
    if (title.includes(steleName)) {
      results.push(normalizeImageUrl(src));
    }
  }
  while ((match = imgRegex2.exec(html)) !== null) {
    const [, title, src] = match;
    if (title.includes(steleName)) {
      results.push(normalizeImageUrl(src));
    }
  }

  // 去重
  return [...new Set(results)];
}

function normalizeImageUrl(src) {
  if (src.startsWith('//')) return 'https:' + src;
  if (src.startsWith('/')) return 'https://www.sfds.cn' + src;
  if (!src.startsWith('http')) return 'https://www.sfds.cn/' + src;
  return src;
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

module.exports = async function handler(req, res) {
  const { char, stele } = req.query;

  // 参数验证
  if (!char || char.length !== 1) {
    return res.status(400).json({ error: 'Missing or invalid char parameter (single character required)' });
  }

  if (!stele) {
    return res.status(400).json({ error: 'Missing stele parameter' });
  }

  // 如果只是查询有哪些碑帖有这个字
  if (stele === 'list') {
    return await listStelesForChar(char, res);
  }

  const codePoint = char.codePointAt(0);
  const hex = codePoint.toString(16).toUpperCase();

  try {
    // Step 1: Fetch the character's calligraphy page (隶书 section)
    const pageUrl = `https://www.sfds.cn/${hex}/`;
    const pageResp = await fetchUrl(pageUrl);

    if (pageResp.status !== 200) {
      return res.status(404).json({ error: `Character page not found for ${char}` });
    }

    const html = pageResp.body.toString('utf-8');

    // Step 2: Parse image URLs for the requested stele
    const imageUrls = parseSteleImages(html, char, stele);

    if (imageUrls.length === 0) {
      // Return info mode - list what steles ARE available
      return res.status(404).json({
        error: `No image found for ${char} in ${stele}`,
        char,
        stele,
        hint: 'Try stele=list to see available steles for this character',
      });
    }

    // Step 3: Fetch and proxy the first image
    const imgUrl = imageUrls[0];
    const imgResp = await fetchUrl(imgUrl, {
      headers: { 'Referer': 'https://www.sfds.cn/' },
    });

    if (imgResp.status !== 200) {
      return res.status(502).json({ error: 'Failed to fetch image from source' });
    }

    // Step 4: Return image with aggressive caching
    const contentType = imgResp.headers['content-type'] || 'image/png';
    res.setHeader('Content-Type', contentType);
    res.setHeader('Cache-Control', 'public, max-age=2592000, s-maxage=2592000, stale-while-revalidate=86400'); // 30 days
    res.setHeader('CDN-Cache-Control', 'public, max-age=2592000'); // Vercel edge: 30 days
    res.setHeader('X-Stele-Source', stele);
    res.setHeader('X-Stele-Char', char);
    res.setHeader('Access-Control-Allow-Origin', '*');

    return res.status(200).send(imgResp.body);

  } catch (err) {
    console.error(`Error fetching stele image for ${char}/${stele}:`, err.message);
    return res.status(500).json({ error: 'Internal error', message: err.message });
  }
};

// 列出一个字在哪些碑帖中有图片
async function listStelesForChar(char, res) {
  const hex = char.codePointAt(0).toString(16).toUpperCase();

  try {
    const pageResp = await fetchUrl(`https://www.sfds.cn/${hex}/`);
    if (pageResp.status !== 200) {
      return res.status(404).json({ error: 'Character not found' });
    }

    const html = pageResp.body.toString('utf-8');

    // Find all stele names mentioned in image titles
    const titleRegex = /title=["']([^"']+碑|[^"']+颂|[^"']+铭|[^"']+经)[^"']*["']/gi;
    const foundSteles = new Set();
    let match;
    while ((match = titleRegex.exec(html)) !== null) {
      const title = match[1];
      // Extract stele name from title like "永,曹全碑"
      const parts = title.split(/[,，]/);
      if (parts.length >= 2) {
        foundSteles.add(parts[parts.length - 1].trim());
      }
    }

    res.setHeader('Cache-Control', 'public, max-age=86400, s-maxage=86400');
    res.setHeader('Access-Control-Allow-Origin', '*');

    return res.status(200).json({
      char,
      steles: [...foundSteles].sort(),
      count: foundSteles.size,
    });

  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
