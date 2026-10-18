#!/usr/bin/env python3
"""Validate sitemap, canonical URLs, metadata, and crawlable internal links."""

from collections import deque
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.canonical = []
        self.descriptions = []
        self.h1 = 0
        self.robots = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h1':
            self.h1 += 1
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical.append(attrs['href'])
        if tag == 'meta' and attrs.get('name') == 'description':
            self.descriptions.append(attrs.get('content', ''))
        if tag == 'meta' and attrs.get('name') == 'robots':
            self.robots = attrs.get('content', '')


def check(root: Path) -> None:
    config = json.loads(re.fullmatch(r'window\.IMMIGRATION_SITE = (.*);\s*',
                                   (root / 'assets/site-config.js').read_text()).group(1))
    base = config['base_url']
    namespace = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [entry.text for entry in ET.parse(root / 'sitemap.xml').findall('s:url/s:loc', namespace)]
    assert len(urls) == len(set(urls)), 'Duplicate sitemap URLs'
    assert base in urls and base + 'browse/' in urls
    parsers = {}
    titles = []
    for url in urls:
        assert url.startswith(base) and not urlsplit(url).query and not urlsplit(url).fragment
        path = root / url.removeprefix(base) / 'index.html'
        assert path.is_file(), f'Missing sitemap page: {url}'
        content = path.read_text()
        head = content.split('</head>', 1)[0]
        measurement_id = config['google_analytics_id']
        if measurement_id:
            loader = f'<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>'
            configure = f"gtag('config', '{measurement_id}');"
            assert head.count(loader) == 1, f'Missing or repeated Google tag: {url}'
            assert head.count(configure) == 1, f'Missing or repeated Analytics configuration: {url}'
            assert head.index(loader) < 2_000_000, f'Google tag too deep in source: {url}'
            assert 'assets/analytics.js' not in head, f'Duplicate Analytics loader: {url}'
        else:
            assert 'googletagmanager.com/gtag/js' not in head, f'Analytics enabled without ID: {url}'
        parser = Page()
        parser.feed(content)
        assert parser.canonical == [url], f'Invalid canonical: {url}'
        assert len(parser.descriptions) == 1 and parser.descriptions[0], f'Invalid description: {url}'
        assert parser.h1 == 1, f'Expected one primary heading: {url}'
        assert 'noindex' not in parser.robots, f'Sitemap includes noindex page: {url}'
        title = re.search(r'<title>(.*?)</title>', content, re.S).group(1)
        assert title.strip()
        titles.append(title)
        for script in re.findall(r'<script type="application/ld\+json">(.*?)</script>', content, re.S):
            json.loads(script)
        for href in parser.links:
            linked = urljoin(url, href)
            target = urlsplit(linked)
            if not linked.startswith(base):
                continue
            relative = target.path.removeprefix(urlsplit(base).path)
            destination = root / relative
            if relative == '' or relative.endswith('/'):
                destination = destination / 'index.html'
            assert destination.is_file(), f'Broken internal link from {url}: {href}'
        parsers[url] = parser
    reachable = set()
    pending = deque([base])
    while pending:
        url = pending.popleft()
        if url in reachable:
            continue
        reachable.add(url)
        for href in parsers[url].links:
            linked = urljoin(url, href)
            if linked in parsers and linked not in reachable:
                pending.append(linked)
    assert reachable == set(urls), 'Sitemap contains orphaned pages'
    home = (root / 'index.html').read_text()
    assert 'type="file"' not in home and 'Choose search files' not in home
    assert 'loadOnlineSearch();' in home and 'browse-title' in home
    assert 'noindex' in (root / '404.html').read_text()
    print(json.dumps({'sitemap_pages': len(urls), 'reachable_pages': len(reachable),
                      'unique_titles': len(set(titles)), 'analytics_configured': bool(config['google_analytics_id'])}))


if __name__ == '__main__':
    check(Path(sys.argv[1] if len(sys.argv) > 1 else '_site'))
