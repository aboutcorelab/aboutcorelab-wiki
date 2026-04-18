#!/usr/bin/env python3
"""Build wiki static site data from markdown files."""
import os, re, json, glob
from datetime import date, datetime

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

WIKI_DIR = os.path.join(os.path.dirname(__file__), '..', 'wiki')
OUT = os.path.join(os.path.dirname(__file__), 'data.js')

def parse_frontmatter(content):
    """Parse YAML frontmatter. Uses PyYAML for nested structures (infobox, concept_meta, key_takeaways)
    and falls back to simple line parsing if yaml is unavailable."""
    fm = {}
    body = content
    if content.startswith('---'):
        end = content.find('---', 3)
        if end != -1:
            fm_raw = content[3:end].strip()
            body = content[end+3:].strip()
            if HAS_YAML:
                try:
                    parsed = yaml.safe_load(fm_raw)
                    if isinstance(parsed, dict):
                        fm = parsed
                except Exception:
                    fm = _parse_simple_fm(fm_raw)
            else:
                fm = _parse_simple_fm(fm_raw)
    return fm, body

def _parse_simple_fm(fm_raw):
    """Fallback line-based parser for simple flat frontmatter."""
    fm = {}
    for line in fm_raw.split('\n'):
        if ':' in line and not line.startswith(' '):
            k, v = line.split(':', 1)
            k = k.strip()
            v = v.strip()
            if v.startswith('['):
                try:
                    v = json.loads(v.replace("'", '"'))
                except Exception:
                    v = [x.strip().strip('"').strip("'") for x in v.strip('[]').split(',') if x.strip()]
            elif v.startswith('"') or v.startswith("'"):
                v = v.strip('"').strip("'")
            fm[k] = v
    return fm

def md_to_html(md):
    lines = md.split('\n')
    html_parts = []
    in_list = False
    in_table = False
    in_blockquote = False

    for line in lines:
        stripped = line.strip()

        # Skip images
        if stripped.startswith('![') or stripped.startswith('*출처:'):
            continue

        # Blockquote
        if stripped.startswith('>'):
            if not in_blockquote:
                if in_list:
                    html_parts.append('</ul>')
                    in_list = False
                html_parts.append('<blockquote>')
                in_blockquote = True
            text = stripped.lstrip('> ').strip()
            if text:
                html_parts.append(f'<p>{inline(text)}</p>')
            continue
        elif in_blockquote and stripped:
            html_parts.append('</blockquote>')
            in_blockquote = False
        elif in_blockquote and not stripped:
            html_parts.append('</blockquote>')
            in_blockquote = False
            continue

        # Headers (with slugified id anchors for TOC)
        if stripped.startswith('######'):
            if in_list: html_parts.append('</ul>'); in_list = False
            txt = stripped[6:].strip()
            html_parts.append(f'<h6 id="{slugify(txt)}">{inline(txt)}</h6>')
        elif stripped.startswith('#####'):
            if in_list: html_parts.append('</ul>'); in_list = False
            txt = stripped[5:].strip()
            html_parts.append(f'<h5 id="{slugify(txt)}">{inline(txt)}</h5>')
        elif stripped.startswith('####'):
            if in_list: html_parts.append('</ul>'); in_list = False
            txt = stripped[4:].strip()
            html_parts.append(f'<h4 id="{slugify(txt)}">{inline(txt)}</h4>')
        elif stripped.startswith('###'):
            if in_list: html_parts.append('</ul>'); in_list = False
            txt = stripped[3:].strip()
            html_parts.append(f'<h3 id="{slugify(txt)}">{inline(txt)}</h3>')
        elif stripped.startswith('##'):
            if in_list: html_parts.append('</ul>'); in_list = False
            txt = stripped[2:].strip()
            html_parts.append(f'<h2 id="{slugify(txt)}">{inline(txt)}</h2>')
        elif stripped.startswith('# '):
            continue  # Skip h1 (we render title separately)
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html_parts.append('<ul>')
                in_list = True
            html_parts.append(f'<li>{inline(stripped[2:])}</li>')
        elif stripped.startswith('|') and '|' in stripped[1:]:
            if '---' in stripped:
                continue
            if not in_table:
                if in_list: html_parts.append('</ul>'); in_list = False
                html_parts.append('<table>')
                in_table = True
                cells = [c.strip() for c in stripped.strip('|').split('|')]
                html_parts.append('<tr>' + ''.join(f'<th>{inline(c)}</th>' for c in cells) + '</tr>')
            else:
                cells = [c.strip() for c in stripped.strip('|').split('|')]
                html_parts.append('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in cells) + '</tr>')
        elif stripped == '' and in_table:
            html_parts.append('</table>')
            in_table = False
        elif stripped.startswith('---'):
            continue
        elif stripped:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            html_parts.append(f'<p>{inline(stripped)}</p>')

    if in_list: html_parts.append('</ul>')
    if in_table: html_parts.append('</table>')
    if in_blockquote: html_parts.append('</blockquote>')

    return '\n'.join(html_parts)

_slug_counter = {}

def slugify(text):
    """Generate a stable URL-friendly id from heading text. Preserves Unicode (Korean)."""
    # Strip markdown/HTML syntax fragments
    s = re.sub(r'[`*_\[\]\(\)|]', '', text).strip()
    # Collapse whitespace to dashes
    s = re.sub(r'\s+', '-', s)
    # Drop characters unsafe in ids
    s = re.sub(r'[^\w\-가-힣ㄱ-ㅎㅏ-ㅣ]', '', s, flags=re.UNICODE)
    s = s.strip('-').lower()
    if not s:
        s = 'section'
    # Dedupe within the same page render
    n = _slug_counter.get(s, 0)
    _slug_counter[s] = n + 1
    return s if n == 0 else f'{s}-{n}'

def extract_toc(html):
    """Extract h2/h3 headings from rendered HTML for TOC rendering."""
    toc = []
    # Non-greedy match up to the matching closing tag; content is single-line since md_to_html doesn't produce multiline headings
    for m in re.finditer(r'<(h[23])\s+id="([^"]+)">(.*?)</\1>', html):
        level = int(m.group(1)[1])
        tid = m.group(2)
        text = re.sub(r'<[^>]+>', '', m.group(3)).strip()
        toc.append({'level': level, 'id': tid, 'text': text})
    return toc

def compute_read_min(body_md):
    """Estimate read time in minutes. Korean ~400 chars/min, English ~250 words/min."""
    text = re.sub(r'[\s\n]+', ' ', re.sub(r'[#*`\[\]\(\)|>-]', ' ', body_md)).strip()
    hangul_chars = len(re.findall(r'[가-힣]', text))
    english_words = len(re.findall(r'\b[A-Za-z]{2,}\b', text))
    minutes = hangul_chars / 500.0 + english_words / 250.0
    return max(1, round(minutes))

def get_section(html, *headers):
    """Extract content of an <h2> section (up to next <h2> or end). Handles <h2 id="...">."""
    for h in headers:
        pat = re.compile(r'<h2[^>]*>\s*' + re.escape(h) + r'\s*</h2>(.*?)(?:<h2[^>]*>|$)', re.DOTALL | re.IGNORECASE)
        m = pat.search(html)
        if m:
            return m.group(1)
    return ''

def wrap_collapsibles(html, char_threshold=900, bullet_threshold=12):
    """Wrap h2 sections over size thresholds in <details> for progressive disclosure.
    Skips common short sections (Metadata, Quotable Passages, Related Sources, Related, Open Questions)
    which are usually short enough and users often want them open."""
    keep_open_titles = {
        'Metadata', 'metadata', 'Quotable Passages', 'quotable-passages',
        'Related', 'related', 'Related Sources', 'related-sources',
        'Open Questions', 'open-questions', 'TL;DR', 'tl;dr',
        'Definition', 'definition', 'Overview', 'overview',
        'Why It Matters', 'why-it-matters', 'Summary', 'summary',
    }
    # Split by h2 boundaries
    parts = re.split(r'(<h2[^>]*>.*?</h2>)', html)
    out = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        if re.match(r'<h2', chunk):
            # chunk is the h2 tag, next part is section body
            title_match = re.search(r'>([^<]+)</h2>', chunk)
            title = title_match.group(1).strip() if title_match else ''
            next_body = parts[i+1] if i+1 < len(parts) else ''
            body_text_len = len(re.sub(r'<[^>]+>', '', next_body))
            bullet_count = len(re.findall(r'<li>', next_body))
            is_long = body_text_len > char_threshold or bullet_count > bullet_threshold
            if is_long and title not in keep_open_titles:
                out.append(f'<details class="collapsible" open><summary>{title}</summary>{next_body}</details>')
            else:
                out.append(chunk)
                out.append(next_body)
            i += 2
        else:
            out.append(chunk)
            i += 1
    return ''.join(out)

def inline(text):
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Code
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    # Wikilinks [[path\|text]] (Obsidian escaped pipe in tables)
    text = re.sub(r'\[\[([^\]|\\]+)\\?\|([^\]]+)\]\]', r'<a class="wl" data-t="\1">\2</a>', text)
    # Wikilinks [[path]]
    text = re.sub(r'\[\[([^\]]+)\]\]', r'<a class="wl" data-t="\1">\1</a>', text)
    # External links [text](url)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    # Other links
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
    # Bare URLs (not already inside an href or tag)
    text = re.sub(r'(?<!href=")(?<!">)(https?://[^\s<\)\]"]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
    return text

pages = {}
TODAY = date.today()
for md_file in sorted(glob.glob(os.path.join(WIKI_DIR, '**', '*.md'), recursive=True)):
    rel = os.path.relpath(md_file, WIKI_DIR)
    if rel in ('index.md', 'log.md'):
        continue
    page_id = rel.replace('.md', '')
    # Skip template files from index/graph — they're schema references, not content
    if rel.startswith('templates/'):
        continue
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    fm, body = parse_frontmatter(content)
    # Reset slug counter per page so anchor ids don't collide across pages
    _slug_counter.clear()
    html = md_to_html(body)
    toc = extract_toc(html)
    html = wrap_collapsibles(html)
    read_min = compute_read_min(body)

    # Determine category
    parts = page_id.split('/')
    cat = parts[0] if len(parts) > 1 else 'overview'
    slug = parts[1] if len(parts) > 1 else parts[0]

    # Subcategory for sources
    subcat = ''
    tags = fm.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.strip('[]').split(',')]

    if cat == 'sources':
        if any('센싱' in str(t) or 'sensing' in str(t).lower() for t in tags) or '센싱' in slug or 'sensing' in slug.lower():
            subcat = 'sensing'
        elif any('논문' in str(t) or 'paper' in str(t).lower() for t in tags):
            subcat = 'paper'
        elif 'ai-weekly' in slug or 'ai-센싱' in slug:
            subcat = 'sensing'
        else:
            subcat = 'marketing'

    # Check source file path for subcategory
    src_list = fm.get('sources', [])
    if isinstance(src_list, str):
        src_list = [src_list]

    # Extract URL from frontmatter or body metadata section
    page_url = ''
    if fm.get('url'):
        page_url = fm['url']
    elif fm.get('source'):
        page_url = fm['source']
    if not page_url:
        url_match = re.search(r'\*\*(?:URL|원본 ?URL|출처 ?URL|소스 ?URL)[:]*\*\*[:]*\s*(https?://[^\s<\)\]]+)', body)
        if url_match:
            page_url = url_match.group(1)
    page_url = page_url.strip().rstrip(')')

    # Staleness in days relative to today (based on last_verified, fallback to updated)
    def _to_date(v):
        if isinstance(v, date):
            return v
        if isinstance(v, str) and len(v) >= 10:
            try:
                return datetime.strptime(v[:10], '%Y-%m-%d').date()
            except Exception:
                return None
        return None

    last_verified_raw = fm.get('last_verified') or fm.get('updated', '')
    lv_date = _to_date(last_verified_raw)
    stale_days = (TODAY - lv_date).days if lv_date else None

    infobox = fm.get('infobox') if isinstance(fm.get('infobox'), dict) else None
    concept_meta = fm.get('concept_meta') if isinstance(fm.get('concept_meta'), dict) else None
    takeaways = fm.get('key_takeaways') if isinstance(fm.get('key_takeaways'), list) else None

    pages[page_id] = {
        'id': page_id,
        'title': fm.get('title', slug),
        'type': fm.get('type', ''),
        'cat': cat,
        'subcat': subcat,
        'tags': tags if isinstance(tags, list) else [],
        'created': str(fm.get('created', '')),
        'updated': str(fm.get('updated', '')),
        'last_verified': str(last_verified_raw) if last_verified_raw else '',
        'stale_days': stale_days,
        'one_liner': fm.get('one_liner', ''),
        'publication_type': fm.get('publication_type', ''),
        'key_takeaways': takeaways,
        'infobox': infobox,
        'concept_meta': concept_meta,
        'toc': toc,
        'read_min': read_min,
        'url': page_url,
        'html': html,
    }

# Extract graph edges from wikilinks in raw markdown
graph_edges = []
seen_edges = set()
for md_file in sorted(glob.glob(os.path.join(WIKI_DIR, '**', '*.md'), recursive=True)):
    rel = os.path.relpath(md_file, WIKI_DIR)
    if rel in ('index.md', 'log.md'):
        continue
    page_id = rel.replace('.md', '')
    with open(md_file, 'r', encoding='utf-8') as f:
        raw = f.read()
    # Find all [[target|text]] and [[target]] wikilinks
    targets = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', raw)
    for t in targets:
        t = t.strip()
        if t in pages and page_id in pages:
            edge_key = tuple(sorted([page_id, t]))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                graph_edges.append({'source': page_id, 'target': t})

# Build graph nodes
graph_nodes = []
for pid, p in pages.items():
    # Count connections
    link_count = sum(1 for e in graph_edges if e['source'] == pid or e['target'] == pid)
    graph_nodes.append({
        'id': pid,
        'title': p['title'],
        'cat': p['cat'],
        'links': link_count,
    })

# Build BACKLINKS: { target_page_id: [source_page_id, ...] }
backlinks = {}
outgoing = {}  # { page_id: [target, ...] }
for md_file in sorted(glob.glob(os.path.join(WIKI_DIR, '**', '*.md'), recursive=True)):
    rel = os.path.relpath(md_file, WIKI_DIR)
    if rel in ('index.md', 'log.md'):
        continue
    page_id = rel.replace('.md', '')
    if page_id not in pages:
        continue
    with open(md_file, 'r', encoding='utf-8') as f:
        raw = f.read()
    targets = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', raw)
    out_set = set()
    for t in targets:
        t = t.strip()
        if t in pages and t != page_id:
            out_set.add(t)
            backlinks.setdefault(t, [])
            if page_id not in backlinks[t]:
                backlinks[t].append(page_id)
    outgoing[page_id] = list(out_set)

# Build LINK_COUNTS: { page_id: { out, in, total } }
link_counts = {}
for pid in pages:
    out_n = len(outgoing.get(pid, []))
    in_n = len(backlinks.get(pid, []))
    link_counts[pid] = {'out': out_n, 'in': in_n, 'total': out_n + in_n}

# Build RELATED_PAGES: { page_id: [{id, title, score}, ...] } (top 5)
page_tags = {}
page_neighbors = {}
for pid, p in pages.items():
    page_tags[pid] = set(p['tags']) if isinstance(p['tags'], list) else set()
    page_neighbors[pid] = set(outgoing.get(pid, [])) | set(backlinks.get(pid, []))

related_pages = {}
for pid in pages:
    scores = []
    my_tags = page_tags[pid]
    my_neighbors = page_neighbors[pid]
    for qid in pages:
        if qid == pid or qid in my_neighbors:
            continue
        shared_tags = len(my_tags & page_tags[qid])
        shared_neighbors = len(my_neighbors & page_neighbors[qid])
        score = shared_tags * 2 + shared_neighbors
        if score > 0:
            scores.append((score, qid))
    scores.sort(key=lambda x: -x[0])
    related_pages[pid] = [{'id': s[1], 'title': pages[s[1]]['title'], 'score': s[0]} for s in scores[:5]]

# Build QUALITY_SCORES: { page_id: { score, max, details } }
quality_scores = {}
for pid, p in pages.items():
    body = p['html']
    cat = p['cat']
    if cat == 'sources':
        s = 0
        details = {}
        # Summary length
        summary_html = get_section(body, 'Summary', '요약', '개요')
        if not summary_html:
            # Fallback: text before first <h2>
            sm = re.search(r'^(.*?)(?:<h2[^>]*>|$)', body, re.DOTALL)
            summary_html = sm.group(1) if sm else ''
        summary_len = len(re.sub(r'<[^>]+>', '', summary_html))
        details['summary'] = 2 if summary_len >= 200 else (1 if summary_len >= 100 else 0)
        s += details['summary']
        # Key Claims count (everything before the Entities/Concepts section)
        ent_match = re.search(r'<h2[^>]*>\s*Entities', body)
        claims_slice = body[:ent_match.start()] if ent_match else body
        claims = len(re.findall(r'<li>', claims_slice))
        details['claims'] = 2 if claims >= 8 else (1 if claims >= 4 else 0)
        s += details['claims']
        # Wikilink count
        wl_count = len(re.findall(r'class="wl"', body))
        details['wikilinks'] = 2 if wl_count >= 6 else (1 if wl_count >= 3 else 0)
        s += details['wikilinks']
        # Quotable Passages
        has_quotes = 1 if 'Quotable' in body or '인용' in body else 0
        details['quotes'] = has_quotes
        s += has_quotes
        # URL
        has_url = 1 if p.get('url') else 0
        details['url'] = has_url
        s += has_url
        # Related Sources
        has_related = body.count('Related Sources') + body.count('관련 소스')
        related_links = len(re.findall(r'class="wl".*?sources/', body[body.find('Related'):] if 'Related' in body else ''))
        details['related'] = 2 if related_links >= 3 else (1 if related_links >= 1 or has_related > 0 else 0)
        s += details['related']
        quality_scores[pid] = {'score': s, 'max': 10, 'details': details}
    elif cat == 'concepts':
        s = 0
        details = {}
        # Definition length
        def_text = re.sub(r'<[^>]+>', '', get_section(body, 'Definition', '정의'))
        details['definition'] = 2 if len(def_text) >= 100 else (1 if len(def_text) >= 50 else 0)
        s += details['definition']
        # Key Points count
        kp_html = get_section(body, 'Key Points', '핵심 포인트', '핵심')
        kp_count = len(re.findall(r'<li>', kp_html))
        details['key_points'] = 2 if kp_count >= 6 else (1 if kp_count >= 3 else 0)
        s += details['key_points']
        # Sources cited
        src_html = get_section(body, 'Sources', '소스')
        src_count = len(re.findall(r'class="wl"', src_html))
        if src_count == 0:
            src_count = len(re.findall(r'sources/', body))
        details['sources'] = 2 if src_count >= 3 else (1 if src_count >= 2 else 0)
        s += details['sources']
        # Related Concepts
        rc_html = get_section(body, 'Related Concepts', 'Related', '관련 개념', '관련')
        rc_count = len(re.findall(r'class="wl"', rc_html))
        details['related'] = 2 if rc_count >= 3 else (1 if rc_count >= 1 else 0)
        s += details['related']
        # Tensions substance
        tens_html = get_section(body, 'Tensions', '텐션', '긴장')
        tens_text = re.sub(r'<[^>]+>', '', tens_html)
        tens_has_source = bool(re.search(r'class="wl"', tens_html))
        details['tensions'] = 2 if len(tens_text) >= 100 and tens_has_source else (1 if len(tens_text) > 20 else 0)
        s += details['tensions']
        quality_scores[pid] = {'score': s, 'max': 10, 'details': details}
    elif cat == 'entities':
        s = 0
        details = {}
        # Overview length (inside <h2>Overview</h2> section)
        ov_html = get_section(body, 'Overview', '개요')
        ov_len = len(re.sub(r'<[^>]+>', '', ov_html))
        details['overview'] = 2 if ov_len >= 100 else (1 if ov_len >= 50 else 0)
        s += details['overview']
        # Key Facts
        kf_html = get_section(body, 'Key Facts', '핵심 사실', '주요 사실')
        facts = len(re.findall(r'<li>', kf_html)) if kf_html else len(re.findall(r'<li>', body))
        details['facts'] = 2 if facts >= 6 else (1 if facts >= 3 else 0)
        s += details['facts']
        # Wikilinks
        wl_count = len(re.findall(r'class="wl"', body))
        details['wikilinks'] = 2 if wl_count >= 4 else (1 if wl_count >= 2 else 0)
        s += details['wikilinks']
        # Sources cited
        src_count = len(re.findall(r'sources/', body))
        details['sources'] = 2 if src_count >= 3 else (1 if src_count >= 1 else 0)
        s += details['sources']
        # Open Questions
        oq_html = get_section(body, 'Open Questions', '미해결 질문', '미해결')
        oq_count = len(re.findall(r'<li>', oq_html))
        details['open_questions'] = 2 if oq_count >= 2 else (1 if oq_count >= 1 else 0)
        s += details['open_questions']
        quality_scores[pid] = {'score': s, 'max': 10, 'details': details}

# Build CREDIBILITY_DATA, CONTRADICTION_DATA, CLAIM_STATS from raw markdown
credibility_data = {}
contradiction_data = {}
claim_stats = {}

for md_file in sorted(glob.glob(os.path.join(WIKI_DIR, '**', '*.md'), recursive=True)):
    rel = os.path.relpath(md_file, WIKI_DIR)
    if rel in ('index.md', 'log.md'):
        continue
    page_id = rel.replace('.md', '')
    if page_id not in pages:
        continue
    with open(md_file, 'r', encoding='utf-8') as f:
        raw = f.read()

    # Extract credibility block from frontmatter
    cred_match = re.search(r'credibility_score:\s*(\d+)', raw)
    tier_match = re.search(r'credibility_tier:\s*"?([A-D])"?', raw)
    if cred_match and tier_match:
        cur = re.search(r'currency:\s*(\d)', raw)
        auth = re.search(r'authority:\s*(\d)', raw)
        meth = re.search(r'methodology:\s*(\d)', raw)
        corr = re.search(r'corroboration:\s*(\d)', raw)
        credibility_data[page_id] = {
            'score': int(cred_match.group(1)),
            'tier': tier_match.group(1),
            'currency': int(cur.group(1)) if cur else 0,
            'authority': int(auth.group(1)) if auth else 0,
            'methodology': int(meth.group(1)) if meth else 0,
            'corroboration': int(corr.group(1)) if corr else 0,
        }

    # Extract contradictions from frontmatter
    if 'contradictions:' in raw:
        contras = []
        for cm in re.finditer(r'-\s*type:\s*(\w+)\s*\n\s*claim:\s*"([^"]*)".*?status:\s*(\w+)', raw, re.DOTALL):
            cw_match = re.search(r'conflicts_with:\s*"([^"]*)"', cm.group(0))
            contras.append({
                'type': cm.group(1),
                'claim': cm.group(2),
                'conflicts_with': cw_match.group(1) if cw_match else '',
                'status': cm.group(3),
            })
        if contras:
            contradiction_data[page_id] = contras

    # Count claim verification markers in body
    body_text = raw[raw.find('---', 3)+3:] if raw.startswith('---') else raw
    high = len(re.findall(r'\[검증:\s*높음\]', body_text))
    mid = len(re.findall(r'\[검증:\s*중간\]', body_text))
    low_v = len(re.findall(r'\[검증:\s*낮음\]', body_text))
    disp = len(re.findall(r'\[검증:\s*분쟁\]', body_text))
    total_claims = high + mid + low_v + disp
    if total_claims > 0:
        claim_stats[page_id] = {'total': total_claims, 'high': high, 'medium': mid, 'low': low_v, 'disputed': disp}

# Build TAG_GROUPS: { page_id: primary_tag }, and inverted { tag: [page_ids] }
tag_counts = {}
for pid, p in pages.items():
    if not isinstance(p['tags'], list): continue
    for t in p['tags']:
        tag_counts[t] = tag_counts.get(t, 0) + 1

# Tags with >= 3 pages become groups; rest go into "기타"
MIN_GROUP_SIZE = 3
page_primary_tag = {}
tag_groups_by_cat = {}  # { cat: { tag: [page_ids] } }
for pid, p in pages.items():
    cat = p['cat']
    tag_groups_by_cat.setdefault(cat, {})
    tags = p['tags'] if isinstance(p['tags'], list) else []
    # Pick primary tag: first tag that forms a group (>= MIN_GROUP_SIZE)
    primary = None
    for t in tags:
        if tag_counts.get(t, 0) >= MIN_GROUP_SIZE:
            primary = t
            break
    if not primary:
        primary = '기타'
    page_primary_tag[pid] = primary
    tag_groups_by_cat[cat].setdefault(primary, []).append(pid)

# Build RECENT_PAGES (top 20 by updated date)
def parse_date(s):
    return s if isinstance(s, str) else ''
recent_pages = [pid for pid, p in sorted(pages.items(), key=lambda x: parse_date(x[1].get('updated', '')), reverse=True)][:20]

# Build POPULAR_PAGES (top 10 by backlink count, excluding overview)
popular_pages = [pid for pid, c in sorted(link_counts.items(), key=lambda x: -x[1]['in']) if pages.get(pid, {}).get('cat') != 'overview'][:10]

# Build LOW_QUALITY_PAGES (pages with quality score <= 5)
low_quality_pages = [pid for pid, q in quality_scores.items() if q['score'] <= 5][:30]

# Write data.js
with open(OUT, 'w', encoding='utf-8') as f:
    f.write('const WIKI_DATA = ')
    json.dump(pages, f, ensure_ascii=False, indent=None)
    f.write(';\nconst GRAPH_NODES = ')
    json.dump(graph_nodes, f, ensure_ascii=False, indent=None)
    f.write(';\nconst GRAPH_EDGES = ')
    json.dump(graph_edges, f, ensure_ascii=False, indent=None)
    f.write(';\nconst BACKLINKS = ')
    json.dump(backlinks, f, ensure_ascii=False, indent=None)
    f.write(';\nconst RELATED_PAGES = ')
    json.dump(related_pages, f, ensure_ascii=False, indent=None)
    f.write(';\nconst LINK_COUNTS = ')
    json.dump(link_counts, f, ensure_ascii=False, indent=None)
    f.write(';\nconst QUALITY_SCORES = ')
    json.dump(quality_scores, f, ensure_ascii=False, indent=None)
    f.write(';\nconst CREDIBILITY_DATA = ')
    json.dump(credibility_data, f, ensure_ascii=False, indent=None)
    f.write(';\nconst CONTRADICTION_DATA = ')
    json.dump(contradiction_data, f, ensure_ascii=False, indent=None)
    f.write(';\nconst CLAIM_STATS = ')
    json.dump(claim_stats, f, ensure_ascii=False, indent=None)
    f.write(';\nconst TAG_GROUPS = ')
    json.dump(tag_groups_by_cat, f, ensure_ascii=False, indent=None)
    f.write(';\nconst PAGE_PRIMARY_TAG = ')
    json.dump(page_primary_tag, f, ensure_ascii=False, indent=None)
    f.write(';\nconst RECENT_PAGES = ')
    json.dump(recent_pages, f, ensure_ascii=False, indent=None)
    f.write(';\nconst POPULAR_PAGES = ')
    json.dump(popular_pages, f, ensure_ascii=False, indent=None)
    f.write(';\nconst LOW_QUALITY_PAGES = ')
    json.dump(low_quality_pages, f, ensure_ascii=False, indent=None)
    f.write(';\n')

qs_scored = [v['score'] for v in quality_scores.values()]
avg_q = sum(qs_scored) / len(qs_scored) if qs_scored else 0
low_q = sum(1 for s in qs_scored if s <= 4)
print(f"Built {len(pages)} pages, {len(graph_nodes)} nodes, {len(graph_edges)} edges -> {OUT}")
cred_count = len(credibility_data)
contra_count = sum(len(v) for v in contradiction_data.values())
claim_count = sum(v['total'] for v in claim_stats.values())
print(f"Quality: avg={avg_q:.1f}/10, low(≤4)={low_q}, backlinks={len(backlinks)} pages with inbound links")
print(f"Credibility: {cred_count} scored, Contradictions: {contra_count}, Verified claims: {claim_count}")
