#!/usr/bin/env python3
"""Build and search a provenance-preserving U.S. immigration-law corpus.

Only Python's standard library is required. PDF text extraction uses the system
``pdftotext`` executable when present; the authenticated/original files remain
available even when text extraction is not possible.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import textwrap
import time
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
ORIGINAL_DIR = DATA_DIR / "original"
EXTRACTED_DIR = DATA_DIR / "extracted"
TEXT_DIR = DATA_DIR / "text"
REPORT_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "catalog.sqlite"

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "caption", "dd", "div",
    "dl", "dt", "fieldset", "figcaption", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".xml", ".zip"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str, limit: int = 90) -> str:
    value = urllib.parse.unquote(value).strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value).strip("-.")
    return (value or "document")[:limit]


def normalized_url(url: str) -> str:
    parts = urllib.parse.urlsplit(html.unescape(url.strip()))
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    path = urllib.parse.quote(path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="=&;%:+,/?@[]")
    return urllib.parse.urlunsplit((scheme, host, path, query, ""))


def extension_for(content_type: str, url: str) -> str:
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if ext and len(ext) <= 7:
        return ext
    content_type = content_type.split(";", 1)[0].lower()
    fixed = {
        "text/html": ".html", "application/xhtml+xml": ".html",
        "application/pdf": ".pdf", "application/xml": ".xml", "text/xml": ".xml",
        "application/json": ".json", "text/plain": ".txt", "text/csv": ".csv",
        "application/zip": ".zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }
    return fixed.get(content_type) or mimetypes.guess_extension(content_type) or ".bin"


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip_depth += 1
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = True
        if tag in BLOCK_TAGS:
            self.text.append("\n")
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
        if tag in BLOCK_TAGS:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.text.append(data)
        if self.in_title:
            self.title_parts.append(data)


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.splitlines()]
    out: list[str] = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def xml_text(data: bytes | Path) -> str:
    output = io.StringIO()
    source: io.BytesIO | Path = io.BytesIO(data) if isinstance(data, bytes) else data
    try:
        for _event, elem in ET.iterparse(source, events=("end",)):
            if elem.text and elem.text.strip():
                output.write(elem.text)
                output.write("\n")
            if elem.tail and elem.tail.strip():
                output.write(elem.tail)
                output.write("\n")
            elem.clear()
        return output.getvalue().strip()
    except ET.ParseError:
        raw = data if isinstance(data, bytes) else data.read_bytes()
        value = raw.decode("utf-8", errors="replace")
        return normalize_text(html.unescape(re.sub(r"<[^>]+>", " ", value)))


def parse_html(data: bytes, encoding: str = "utf-8") -> tuple[str, str, list[str]]:
    parser = TextHTMLParser()
    parser.feed(data.decode(encoding, errors="replace"))
    title = normalize_text(" ".join(parser.title_parts))
    return title, normalize_text("".join(parser.text)), parser.links


def pdf_text(path: Path) -> str:
    binary = shutil.which("pdftotext")
    if not binary:
        return ""
    result = subprocess.run(
        [binary, "-layout", "-enc", "UTF-8", str(path), "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode not in {0, 1}:
        return ""
    return normalize_text(result.stdout.decode("utf-8", errors="replace"))


def docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read("word/document.xml")
        return xml_text(data)
    except (KeyError, OSError, zipfile.BadZipFile):
        return ""


def extract_text(data: bytes, path: Path, content_type: str) -> tuple[str, str, list[str]]:
    ctype = content_type.lower().split(";", 1)[0]
    ext = path.suffix.lower()
    if ctype in {"text/html", "application/xhtml+xml"} or ext in {".html", ".htm"}:
        return parse_html(data)
    if ctype in {"application/xml", "text/xml"} or ext == ".xml":
        return "", xml_text(data), []
    if ctype == "application/pdf" or ext == ".pdf":
        return "", pdf_text(path), []
    if ext == ".docx" or "wordprocessingml" in ctype:
        return "", docx_text(path), []
    if ctype.startswith("text/") or ext in {".txt", ".csv", ".json"}:
        return "", normalize_text(data.decode("utf-8", errors="replace")), []
    return "", "", []


def json_links(data: bytes) -> list[str]:
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    links: list[str] = []
    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key).lower())
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and key in {"url", "href", "link"}:
            links.append(value)
    visit(payload)
    return links


class CorpusDB:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(path)
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.cx.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
              id INTEGER PRIMARY KEY,
              source_id TEXT NOT NULL,
              parent_id INTEGER REFERENCES documents(id),
              url TEXT NOT NULL UNIQUE,
              final_url TEXT,
              title TEXT,
              agency TEXT,
              authority_tier TEXT,
              category TEXT,
              content_type TEXT,
              retrieved_at TEXT,
              source_last_modified TEXT,
              etag TEXT,
              sha256 TEXT,
              byte_size INTEGER,
              original_path TEXT,
              text_path TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              error TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS documents_source_idx ON documents(source_id);
            CREATE INDEX IF NOT EXISTS documents_sha_idx ON documents(sha256);
            CREATE TABLE IF NOT EXISTS fetch_log (
              id INTEGER PRIMARY KEY,
              document_id INTEGER REFERENCES documents(id),
              attempted_at TEXT NOT NULL,
              status_code INTEGER,
              outcome TEXT NOT NULL,
              message TEXT
            );
            CREATE TABLE IF NOT EXISTS links (
              from_document_id INTEGER NOT NULL REFERENCES documents(id),
              to_url TEXT NOT NULL,
              relation TEXT NOT NULL DEFAULT 'link',
              PRIMARY KEY(from_document_id, to_url)
            );
            CREATE TABLE IF NOT EXISTS citations (
              document_id INTEGER NOT NULL REFERENCES documents(id),
              kind TEXT NOT NULL,
              citation TEXT NOT NULL,
              PRIMARY KEY(document_id, kind, citation)
            );
            CREATE TABLE IF NOT EXISTS document_topics (
              document_id INTEGER NOT NULL REFERENCES documents(id),
              topic TEXT NOT NULL,
              hits INTEGER NOT NULL,
              PRIMARY KEY(document_id, topic)
            );
            CREATE TABLE IF NOT EXISTS source_inventory (
              source_id TEXT NOT NULL,
              url TEXT NOT NULL,
              last_modified TEXT,
              discovered_at TEXT NOT NULL,
              PRIMARY KEY(source_id, url)
            );
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY,
              profile TEXT NOT NULL,
              source_id TEXT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              status TEXT NOT NULL,
              fetched INTEGER NOT NULL DEFAULT 0,
              failed INTEGER NOT NULL DEFAULT 0,
              message TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
              document_id UNINDEXED, title, body, url UNINDEXED,
              source_id UNINDEXED, agency UNINDEXED, category UNINDEXED,
              tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        self.cx.commit()

    def existing(self, url: str) -> sqlite3.Row | None:
        return self.cx.execute("SELECT * FROM documents WHERE url=?", (url,)).fetchone()

    def upsert_pending(self, source: dict[str, Any], url: str, parent_id: int | None = None) -> int:
        self.cx.execute(
            """
            INSERT INTO documents(source_id,parent_id,url,title,agency,authority_tier,category,status)
            VALUES(?,?,?,?,?,?,?,'pending')
            ON CONFLICT(url) DO UPDATE SET source_id=excluded.source_id,
              parent_id=COALESCE(excluded.parent_id,documents.parent_id),
              agency=excluded.agency, authority_tier=excluded.authority_tier,
              category=excluded.category
            """,
            (source["id"], parent_id, url, source.get("title"), source.get("agency"),
             source.get("authority_tier"), source.get("category")),
        )
        row = self.cx.execute("SELECT id FROM documents WHERE url=?", (url,)).fetchone()
        self.cx.commit()
        assert row is not None
        return int(row[0])

    def mark_failure(self, document_id: int, message: str, status_code: int | None = None) -> None:
        now = utc_now()
        self.cx.execute("UPDATE documents SET status='error',error=?,retrieved_at=? WHERE id=?", (message[:3000], now, document_id))
        self.cx.execute(
            "INSERT INTO fetch_log(document_id,attempted_at,status_code,outcome,message) VALUES(?,?,?,?,?)",
            (document_id, now, status_code, "error", message[:3000]),
        )
        self.cx.commit()

    def store_document(
        self, document_id: int, *, final_url: str, title: str, content_type: str,
        last_modified: str | None, etag: str | None, sha256: str, byte_size: int,
        original_path: Path, text_path: Path | None, body: str, metadata: dict[str, Any],
        topics: dict[str, int], citations: list[tuple[str, str]],
    ) -> None:
        now = utc_now()
        self.cx.execute(
            """UPDATE documents SET final_url=?,title=COALESCE(NULLIF(?,''),title),content_type=?,
               retrieved_at=?,source_last_modified=?,etag=?,sha256=?,byte_size=?,original_path=?,
               text_path=?,status='ok',error=NULL,metadata_json=? WHERE id=?""",
            (final_url, title, content_type, now, last_modified, etag, sha256, byte_size,
             str(original_path.relative_to(ROOT)), str(text_path.relative_to(ROOT)) if text_path else None,
             json.dumps(metadata, sort_keys=True), document_id),
        )
        self.cx.execute("DELETE FROM document_fts WHERE document_id=?", (str(document_id),))
        row = self.cx.execute("SELECT title,url,source_id,agency,category FROM documents WHERE id=?", (document_id,)).fetchone()
        assert row is not None
        if body:
            self.cx.execute(
                "INSERT INTO document_fts(document_id,title,body,url,source_id,agency,category) VALUES(?,?,?,?,?,?,?)",
                (str(document_id), row["title"] or "", body, row["url"], row["source_id"], row["agency"] or "", row["category"] or ""),
            )
        self.cx.execute("DELETE FROM document_topics WHERE document_id=?", (document_id,))
        self.cx.executemany(
            "INSERT INTO document_topics(document_id,topic,hits) VALUES(?,?,?)",
            [(document_id, topic, hits) for topic, hits in topics.items()],
        )
        self.cx.execute("DELETE FROM citations WHERE document_id=?", (document_id,))
        self.cx.executemany(
            "INSERT OR IGNORE INTO citations(document_id,kind,citation) VALUES(?,?,?)",
            [(document_id, kind, cite) for kind, cite in citations],
        )
        self.cx.execute(
            "INSERT INTO fetch_log(document_id,attempted_at,status_code,outcome,message) VALUES(?,?,200,'ok',NULL)",
            (document_id, now),
        )
        self.cx.commit()


class RateLimiter:
    def __init__(self) -> None:
        self.last: dict[str, float] = {}

    def wait(self, url: str, delay: float) -> None:
        host = urllib.parse.urlsplit(url).netloc.lower()
        elapsed = time.monotonic() - self.last.get(host, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last[host] = time.monotonic()


class Builder:
    def __init__(
        self, config: dict[str, Any], topics: dict[str, list[str]],
        max_docs: int | None = None, refresh: bool = False,
    ) -> None:
        self.config = config
        self.policy = config["retrieval_policy"]
        self.topics = topics
        self.db = CorpusDB()
        self.limiter = RateLimiter()
        self.max_docs = max_docs
        self.refresh = refresh
        self.fetched = 0
        self.failed = 0

    def at_limit(self) -> bool:
        return self.max_docs is not None and self.fetched >= self.max_docs

    def request(
        self, source: dict[str, Any], url: str, *, data: bytes | None = None,
        extra_headers: dict[str, str] | None = None, existing_url: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        delay = float(source.get("delay_seconds", self.policy["default_delay_seconds"]))
        headers = {"User-Agent": self.policy["user_agent"], "Accept-Encoding": "identity"}
        if extra_headers:
            headers.update(extra_headers)
        existing = self.db.existing(existing_url or url) if data is None else None
        if existing and existing["status"] == "ok":
            if existing["etag"]:
                headers["If-None-Match"] = existing["etag"]
            if existing["source_last_modified"]:
                headers["If-Modified-Since"] = existing["source_last_modified"]
        retries = int(self.policy["retries"])
        context = None
        if source.get("extra_ca_file"):
            context = ssl.create_default_context()
            context.load_verify_locations(cafile=str(ROOT / source["extra_ca_file"]))
        for attempt in range(retries):
            self.limiter.wait(url, delay)
            request = urllib.request.Request(url, headers=headers, data=data)
            try:
                with urllib.request.urlopen(request, timeout=self.policy["timeout_seconds"], context=context) as response:
                    length = response.headers.get("Content-Length")
                    if length and int(length) > int(self.policy["max_file_bytes"]):
                        raise RuntimeError(f"Content-Length {length} exceeds configured maximum")
                    data = response.read(int(self.policy["max_file_bytes"]) + 1)
                    if len(data) > int(self.policy["max_file_bytes"]):
                        raise RuntimeError("response exceeds configured maximum")
                    return data, {
                        "final_url": response.geturl(),
                        "content_type": response.headers.get("Content-Type", "application/octet-stream"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "etag": response.headers.get("ETag"),
                        "status": getattr(response, "status", 200),
                    }
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and existing and existing["original_path"]:
                    path = ROOT / existing["original_path"]
                    return path.read_bytes(), {
                        "final_url": existing["final_url"] or url,
                        "content_type": existing["content_type"] or "application/octet-stream",
                        "last_modified": existing["source_last_modified"], "etag": existing["etag"],
                        "status": 304,
                    }
                if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 == retries:
                    raise
                time.sleep(min(2 ** attempt, 20))
            except (OSError, TimeoutError) as exc:
                if attempt + 1 == retries:
                    raise
                time.sleep(min(2 ** attempt, 20))
        raise RuntimeError("unreachable")

    def topic_hits(self, text: str) -> dict[str, int]:
        lower = text.lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", lower)
        result: dict[str, int] = {}
        for topic, needles in self.topics.items():
            hits = 0
            for needle in needles:
                plain_needle = needle.lower()
                literal_hits = lower.count(plain_needle)
                hits += literal_hits
                normalized_needle = re.sub(r"[^a-z0-9]+", " ", plain_needle).strip()
                if not literal_hits and normalized_needle:
                    hits += normalized.count(normalized_needle)
            if hits:
                result[topic] = hits
        return result

    def citations(self, text: str) -> list[tuple[str, str]]:
        patterns = [
            ("usc", re.compile(r"\b\d+\s+U\.?\s*S\.?\s*C\.?\s*(?:§{1,2}\s*)?[0-9A-Za-z][0-9A-Za-z.()_-]*", re.I)),
            ("cfr", re.compile(r"\b\d+\s+C\.?\s*F\.?\s*R\.?\s*(?:§{1,2}\s*)?[0-9A-Za-z][0-9A-Za-z.()_-]*", re.I)),
            ("ina", re.compile(r"\bINA\s*(?:§{1,2}|sections?)?\s*[0-9]{3}[A-Za-z]?(?:\([a-zA-Z0-9]+\))*", re.I)),
            ("in_decision", re.compile(r"\b\d{1,2}\s+I\s*&\s*N\s+Dec\.?\s+\d+", re.I)),
            ("case_reporter", re.compile(r"\b\d{1,4}\s+(?:U\.S\.|S\.\s*Ct\.|F\.\s*(?:2d|3d|4th)|F\.\s*Supp\.\s*(?:2d|3d)?)\s+\d+", re.I)),
        ]
        seen: set[tuple[str, str]] = set()
        for kind, pattern in patterns:
            for match in pattern.finditer(text):
                value = re.sub(r"\s+", " ", match.group(0)).strip(" .,;")
                seen.add((kind, value))
                if len(seen) >= 10000:
                    return sorted(seen)
        return sorted(seen)

    def local_path(self, source_id: str, url: str, content_type: str, digest: str) -> Path:
        name = Path(urllib.parse.urlsplit(url).path).name
        ext = extension_for(content_type, url)
        if not name or name in {"dl", "download"}:
            name = f"document{ext}"
        elif not Path(name).suffix:
            name += ext
        target = ORIGINAL_DIR / source_id / f"{digest[:16]}-{slug(name)}"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def text_path(self, source_id: str, digest: str, name: str) -> Path:
        target = TEXT_DIR / source_id / f"{digest[:16]}-{slug(name)}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def is_plain_zip(path: Path, content_type: str | None) -> bool:
        """Exclude ZIP-container formats such as DOCX from archive expansion."""
        media_type = (content_type or "").lower().split(";", 1)[0]
        return path.suffix.lower() == ".zip" or media_type in {
            "application/zip", "application/x-zip-compressed"
        }

    def fetch_one(
        self, source: dict[str, Any], url: str, *, parent_id: int | None = None,
        title_hint: str = "", metadata: dict[str, Any] | None = None,
        request_url: str | None = None, request_data: bytes | None = None,
        request_headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, str, list[str]] | None:
        url = normalized_url(url)
        document_id = self.db.upsert_pending(source, url, parent_id)
        existing = self.db.existing(url)
        if existing and existing["status"] == "ok" and existing["original_path"] and not self.refresh:
            path = ROOT / existing["original_path"]
            if path.exists():
                data = path.read_bytes()
                if self.is_plain_zip(path, existing["content_type"]):
                    child_status = self.db.cx.execute(
                        "SELECT COUNT(*) total,SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) incomplete FROM documents WHERE parent_id=?",
                        (document_id,),
                    ).fetchone()
                    if child_status and (child_status["total"] == 0 or child_status["incomplete"]):
                        self.index_archive(source, document_id, path, existing["sha256"])
                links: list[str] = []
                if (existing["content_type"] or "").lower().startswith("text/html") or path.suffix.lower() in {".html", ".htm"}:
                    _title, _body, links = parse_html(data)
                elif "json" in (existing["content_type"] or "").lower() or path.suffix.lower() == ".json":
                    links = json_links(data)
                return document_id, data, existing["final_url"] or url, links
        if self.at_limit():
            return None
        try:
            data, response = self.request(
                source, request_url or url, data=request_data,
                extra_headers=request_headers, existing_url=url,
            )
            ctype = response["content_type"]
            digest = hashlib.sha256(data).hexdigest()
            path = self.local_path(source["id"], response["final_url"], ctype, digest)
            if not path.exists() or path.stat().st_size != len(data):
                path.write_bytes(data)
            extracted_title, body, links = extract_text(data, path, ctype)
            if "json" in ctype.lower() or path.suffix.lower() == ".json":
                links.extend(json_links(data))
            title = extracted_title or title_hint or source.get("title", "")
            txt_path = None
            if body:
                txt_path = self.text_path(source["id"], digest, Path(path).stem)
                txt_path.write_text(body, encoding="utf-8")
            all_metadata = {"requested_url": url, "response_status": response["status"]}
            if metadata:
                all_metadata.update(metadata)
            self.db.store_document(
                document_id, final_url=response["final_url"], title=title, content_type=ctype,
                last_modified=response["last_modified"], etag=response["etag"], sha256=digest,
                byte_size=len(data), original_path=path, text_path=txt_path, body=body,
                metadata=all_metadata, topics=self.topic_hits(f"{title}\n{body}"),
                citations=self.citations(body),
            )
            self.fetched += 1
            if self.is_plain_zip(path, ctype):
                self.index_archive(source, document_id, path, digest)
            return document_id, data, response["final_url"], links
        except Exception as exc:  # each failed URL must be recorded and must not abort a long sync
            self.db.mark_failure(document_id, f"{type(exc).__name__}: {exc}", getattr(exc, "code", None))
            self.failed += 1
            print(f"ERROR {url}: {exc}", file=sys.stderr)
            return None

    def index_archive(self, source: dict[str, Any], parent_id: int, path: Path, archive_digest: str) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir() or member.file_size > int(self.policy["max_file_bytes"]):
                        continue
                    parts = Path(member.filename).parts
                    if not parts or member.filename.startswith(("/", "\\")) or ".." in parts:
                        continue
                    out = EXTRACTED_DIR / source["id"] / archive_digest[:16] / Path(*parts)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if not out.exists() or out.stat().st_size != member.file_size:
                        with archive.open(member) as source_file, out.open("wb") as target_file:
                            shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
                    hasher = hashlib.sha256()
                    with out.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            hasher.update(block)
                    digest = hasher.hexdigest()
                    virtual_url = f"archive://{archive_digest}/{urllib.parse.quote(member.filename)}"
                    child_id = self.db.upsert_pending(source, virtual_url, parent_id)
                    ctype = mimetypes.guess_type(member.filename)[0] or "application/octet-stream"
                    if out.suffix.lower() == ".xml" or ctype in {"application/xml", "text/xml"}:
                        title, body = "", xml_text(out)
                    else:
                        data = out.read_bytes()
                        title, body, _links = extract_text(data, out, ctype)
                    txt_path = None
                    if body:
                        txt_path = self.text_path(source["id"], digest, member.filename)
                        txt_path.write_text(body, encoding="utf-8")
                    self.db.store_document(
                        child_id, final_url=virtual_url, title=title or member.filename,
                        content_type=ctype, last_modified=None, etag=None, sha256=digest,
                        byte_size=member.file_size, original_path=out, text_path=txt_path, body=body,
                        metadata={"archive_parent_id": parent_id, "archive_member": member.filename},
                        topics=self.topic_hits(f"{member.filename}\n{body}"), citations=self.citations(body),
                    )
        except (OSError, zipfile.BadZipFile) as exc:
            print(f"WARN archive {path}: {exc}", file=sys.stderr)

    def run_source(self, source: dict[str, Any]) -> None:
        print(f"SOURCE {source['id']}: {source['title']}")
        kind = source["kind"]
        if kind == "crawl":
            self.crawl(source)
        elif kind == "uscode_current":
            self.uscode_current(source)
        elif kind == "ecfr_titles":
            for title in source["titles"]:
                if self.at_limit():
                    break
                self.fetch_one(source, source["url_template"].format(title=title), title_hint=f"eCFR Title {title}")
        elif kind == "sitemap_inventory":
            self.sitemap_inventory(source)
        elif kind == "federal_register":
            self.federal_register(source)
        elif kind == "govinfo_search":
            self.govinfo_search(source)
        else:
            raise ValueError(f"Unsupported source kind: {kind}")

    def crawl(self, source: dict[str, Any]) -> None:
        allowed = re.compile(source["allowed_page_regex"], re.I)
        documents = re.compile(source["document_url_regex"], re.I) if source.get("document_url_regex") else None
        max_depth = int(source.get("max_depth", 0))
        seed_hosts = {urllib.parse.urlsplit(url).netloc.lower() for url in source["seeds"]}
        queue: list[tuple[str, int, int | None]] = [(normalized_url(url), 0, None) for url in source["seeds"]]
        seen: set[str] = set()
        while queue and not self.at_limit():
            url, depth, parent_id = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            result = self.fetch_one(source, url, parent_id=parent_id)
            if not result:
                continue
            document_id, _data, final_url, links = result
            for raw_link in links:
                linked = normalized_url(urllib.parse.urljoin(final_url, raw_link))
                if not linked.startswith(("http://", "https://")):
                    continue
                linked_parts = urllib.parse.urlsplit(linked)
                is_document = bool(documents and documents.search(linked)) or (
                    linked_parts.netloc.lower() in seed_hosts
                    and Path(linked_parts.path).suffix.lower() in DOCUMENT_EXTENSIONS
                )
                relation = "attachment" if is_document else "link"
                self.db.cx.execute(
                    "INSERT OR IGNORE INTO links(from_document_id,to_url,relation) VALUES(?,?,?)",
                    (document_id, linked, relation),
                )
                if is_document and source.get("download_linked_documents", False):
                    if linked not in seen and not self.at_limit():
                        seen.add(linked)
                        self.fetch_one(source, linked, parent_id=document_id)
                elif depth < max_depth and allowed.search(linked) and linked not in seen:
                    queue.append((linked, depth + 1, document_id))
            self.db.cx.commit()

    def uscode_current(self, source: dict[str, Any]) -> None:
        result = self.fetch_one(source, source["index_url"], title_hint="U.S. Code downloads and release points")
        if not result:
            return
        parent_id, data, final_url, _links = result
        text = data.decode("utf-8", errors="replace")
        link_pattern = re.compile(
            r'href=["\'](?P<href>releasepoints/us/pl/(?P<congress>\d+)/(?P<law>\d+)/(?P<fmt>xml|htm|pdf)_usc(?P<title>\d+)@(?P=congress)-(?P=law)\.zip)', re.I,
        )
        matches = [m.groupdict() for m in link_pattern.finditer(text)]
        if not matches:
            raise RuntimeError("No OLRC release-point links found")
        release = max((int(m["congress"]), int(m["law"])) for m in matches)
        wanted_titles = set(range(1, 55)) if source["titles"] == "all" else {int(x) for x in source["titles"]}
        wanted: set[tuple[int, str]] = {(title, fmt) for title in wanted_titles for fmt in source["formats"]}
        for title, formats in source.get("extra_formats", {}).items():
            wanted.update((int(title), fmt) for fmt in formats)
        chosen: dict[tuple[int, str], dict[str, str]] = {}
        for match in matches:
            key = (int(match["title"]), match["fmt"].lower())
            if (int(match["congress"]), int(match["law"])) == release and key in wanted:
                chosen[key] = match
        for (title, fmt), match in sorted(chosen.items()):
            if self.at_limit():
                break
            url = urllib.parse.urljoin(final_url, match["href"])
            self.fetch_one(
                source, url, parent_id=parent_id,
                title_hint=f"United States Code Title {title} ({fmt.upper()}), through Public Law {release[0]}-{release[1]}",
                metadata={"release_congress": release[0], "release_public_law": release[1], "usc_title": title, "format": fmt},
            )

    def sitemap_inventory(self, source: dict[str, Any]) -> None:
        pending = list(source["sitemaps"])
        seen: set[str] = set()
        while pending and not self.at_limit():
            url = normalized_url(pending.pop(0))
            if url in seen:
                continue
            seen.add(url)
            result = self.fetch_one(source, url, title_hint=f"Sitemap {url}")
            if not result:
                continue
            _doc_id, data, _final, _links = result
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                continue
            is_index = root.tag.rsplit("}", 1)[-1].lower() == "sitemapindex"
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1].lower() != "loc" or not element.text:
                    continue
                loc = normalized_url(element.text)
                if is_index:
                    pending.append(loc)
                else:
                    self.db.cx.execute(
                        "INSERT OR REPLACE INTO source_inventory(source_id,url,last_modified,discovered_at) VALUES(?,?,NULL,?)",
                        (source["id"], loc, utc_now()),
                    )
            self.db.cx.commit()

    def federal_register(self, source: dict[str, Any]) -> None:
        for term in source["terms"]:
            page = 1
            while not self.at_limit():
                params = urllib.parse.urlencode({
                    "per_page": source.get("per_page", 1000), "page": page,
                    "conditions[term]": term, "order": "oldest",
                })
                url = f"{source['api_url']}?{params}"
                result = self.fetch_one(source, url, title_hint=f"Federal Register API query: {term}", metadata={"query": term, "page": page})
                if not result:
                    break
                parent_id, data, _final, _links = result
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    break
                rows = payload.get("results", [])
                for row in rows:
                    for fmt in source.get("download_formats", ["raw_text", "pdf"]):
                        doc_url = row.get(f"{fmt}_url")
                        if doc_url and not self.at_limit():
                            self.fetch_one(
                                source, doc_url, parent_id=parent_id, title_hint=row.get("title", ""),
                                metadata={"federal_register_document_number": row.get("document_number"), "query": term, "format": fmt},
                            )
                if not rows or not payload.get("next_page_url"):
                    break
                page += 1

    def catalog_document(
        self, source: dict[str, Any], url: str, title: str, metadata: dict[str, Any],
    ) -> int:
        document_id = self.db.upsert_pending(source, normalized_url(url))
        self.db.cx.execute(
            """UPDATE documents SET title=?,status='cataloged',error=NULL,metadata_json=?
               WHERE id=? AND status!='ok'""",
            (title, json.dumps(metadata, sort_keys=True), document_id),
        )
        self.db.cx.commit()
        return document_id

    def govinfo_search(self, source: dict[str, Any]) -> None:
        api_key = os.environ.get("GOVINFO_API_KEY") or source.get("api_key") or "DEMO_KEY"
        headers = {"Content-Type": "application/json", "X-Api-Key": api_key}
        download = bool(source.get("download_documents", False))
        seen_results: set[str] = set()
        for query in source["queries"]:
            offset = "*"
            page = 1
            while not self.at_limit():
                payload = {
                    "query": query, "pageSize": str(source.get("page_size", 1000)),
                    "offsetMark": offset,
                    "sorts": [{"field": "publishdate", "sortOrder": "ASC"}],
                    "historical": True,
                }
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                logical = f"https://api.govinfo.gov/search/corpus/{hashlib.sha256(query.encode()).hexdigest()[:16]}/{page}"
                result = self.fetch_one(
                    source, logical, title_hint=f"GovInfo search: {query}",
                    metadata={"query": query, "page": page, "offset_mark": offset},
                    request_url=source["api_url"], request_data=body, request_headers=headers,
                )
                if not result:
                    break
                query_doc_id, data, _final, _links = result
                try:
                    response = json.loads(data)
                except json.JSONDecodeError:
                    break
                rows = response.get("results", [])
                for row in rows:
                    package = row.get("packageId")
                    granule = row.get("granuleId")
                    if not package:
                        continue
                    key = granule or package
                    if key in seen_results:
                        continue
                    seen_results.add(key)
                    if granule:
                        public_pdf = f"https://www.govinfo.gov/content/pkg/{package}/pdf/{granule}.pdf"
                    else:
                        public_pdf = f"https://www.govinfo.gov/content/pkg/{package}/pdf/{package}.pdf"
                    meta = {
                        "package_id": package, "granule_id": granule,
                        "collection_code": row.get("collectionCode"),
                        "date_issued": row.get("dateIssued"),
                        "last_modified": row.get("lastModified"),
                        "government_author": row.get("governmentAuthor"),
                        "result_link": row.get("resultLink"), "matched_query": query,
                    }
                    if download and not self.at_limit():
                        self.fetch_one(
                            source, public_pdf, parent_id=query_doc_id,
                            title_hint=row.get("title", ""), metadata=meta,
                        )
                    else:
                        self.catalog_document(source, public_pdf, row.get("title", ""), meta)
                next_offset = response.get("offsetMark")
                if not rows or not next_offset or next_offset == offset:
                    break
                offset = next_offset
                page += 1


def selected_sources(config: dict[str, Any], profile: str, source_ids: list[str] | None) -> list[dict[str, Any]]:
    sources = [source for source in config["sources"] if profile in source.get("profiles", [])]
    if source_ids:
        wanted = set(source_ids)
        missing = wanted - {source["id"] for source in config["sources"]}
        if missing:
            raise SystemExit(f"Unknown source id(s): {', '.join(sorted(missing))}")
        sources = [source for source in config["sources"] if source["id"] in wanted]
    return sources


def write_reports(db: CorpusDB) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = db.cx.execute("SELECT * FROM documents ORDER BY source_id,id").fetchall()
    with (REPORT_DIR / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "id", "source_id", "title", "agency", "authority_tier", "category", "url",
            "retrieved_at", "source_last_modified", "content_type", "byte_size", "sha256",
            "original_path", "text_path", "status", "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})
    checksums: list[str] = []
    for row in rows:
        if row["status"] == "ok" and row["sha256"] and row["original_path"]:
            checksums.append(f"{row['sha256']}  {row['original_path']}")
    (REPORT_DIR / "checksums.sha256").write_text("\n".join(checksums) + ("\n" if checksums else ""), encoding="utf-8")
    by_source = db.cx.execute(
        """SELECT source_id,COUNT(*) docs,SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) ok,
           SUM(CASE WHEN status='cataloged' THEN 1 ELSE 0 END) cataloged,
           SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) errors,COALESCE(SUM(byte_size),0) bytes
           FROM documents GROUP BY source_id ORDER BY source_id"""
    ).fetchall()
    topics = db.cx.execute(
        "SELECT topic,COUNT(*) documents,SUM(hits) hits FROM document_topics GROUP BY topic ORDER BY topic"
    ).fetchall()
    inventory_count = db.cx.execute("SELECT COUNT(*) FROM source_inventory").fetchone()[0]
    top_level = db.cx.execute("SELECT COUNT(*) FROM documents WHERE parent_id IS NULL").fetchone()[0]
    archive_members = db.cx.execute("SELECT COUNT(*) FROM documents WHERE url LIKE 'archive://%'").fetchone()[0]
    linked_descendants = len(rows) - top_level - archive_members
    lines = [
        "# Corpus audit", "", f"Generated: {utc_now()}", "",
        f"Documents/records: {len(rows):,}",
        f"Top-level records: {top_level:,}",
        f"Linked crawl/API descendants: {linked_descendants:,}",
        f"Extracted archive members: {archive_members:,}",
        f"Original bytes: {sum((row['byte_size'] or 0) for row in rows):,}",
        f"Sitemap inventory URLs: {inventory_count:,}", "", "## Sources", "",
        "| Source | Records | Downloaded/OK | Cataloged only | Errors | Bytes |", "|---|---:|---:|---:|---:|---:|",
    ]
    lines.extend(f"| {row['source_id']} | {row['docs']:,} | {row['ok']:,} | {row['cataloged']:,} | {row['errors']:,} | {row['bytes']:,} |" for row in by_source)
    lines += ["", "## Topic coverage", "", "| Topic | Documents | Term hits |", "|---|---:|---:|"]
    lines.extend(f"| {row['topic']} | {row['documents']:,} | {row['hits']:,} |" for row in topics)
    lines += [
        "", "## Interpretation", "",
        "An OK record means the source was retrieved and checksummed; it does not mean the source is current forever, complete, binding, or still good law.",
        "The authority_tier field distinguishes binding law from precedent, nonbinding policy/guidance, procedure, and discovery inventories.",
    ]
    (REPORT_DIR / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(db: CorpusDB) -> int:
    bad = 0
    rows = db.cx.execute("SELECT id,original_path,sha256 FROM documents WHERE status='ok' AND original_path IS NOT NULL").fetchall()
    for row in rows:
        path = ROOT / row["original_path"]
        if not path.exists():
            print(f"MISSING {row['id']} {path}")
            bad += 1
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            print(f"MISMATCH {row['id']} {path}")
            bad += 1
    print(f"verified={len(rows)-bad} failed={bad}")
    return 1 if bad else 0


ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "bright_cyan": "\033[1;36m",
    "bright_yellow": "\033[1;33m",
}


def color_enabled(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never" or os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def paint(value: str, style: str, enabled: bool) -> str:
    return f"{ANSI[style]}{value}{ANSI['reset']}" if enabled else value


def human_label(value: str | None) -> str:
    return (value or "Unknown").replace("_", " ").strip().title()


def authority_style(authority: str | None) -> str:
    return {
        "binding_law": "green",
        "current_regulatory_text": "green",
        "binding_agency_precedent": "magenta",
        "judicial_opinion": "blue",
        "agency_policy": "yellow",
        "cataloged": "dim",
    }.get(authority or "", "cyan")


def highlighted_snippet(value: str, enabled: bool) -> str:
    """Render the FTS snippet's [match] markers without changing its content."""
    if enabled:
        return re.sub(
            r"\[([^]]+)]",
            lambda match: paint(match.group(1), "bright_yellow", True),
            value,
        )
    return re.sub(r"\[([^]]+)]", r"«\1»", value)


def print_search_results(
    query: str, rows: list[sqlite3.Row], source_id: str | None, color_mode: str,
) -> None:
    enabled = color_enabled(color_mode)
    width = max(50, min(shutil.get_terminal_size(fallback=(92, 24)).columns, 120))
    heading = paint("IMMIGRATION CORPUS SEARCH", "bright_cyan", enabled)
    print(heading)
    print(paint("─" * width, "cyan", enabled))
    print(f"{paint('Query:', 'bold', enabled)}   {query}")
    if source_id:
        print(f"{paint('Source:', 'bold', enabled)}  {source_id}")
    noun = "result" if len(rows) == 1 else "results"
    print(f"{paint('Found:', 'bold', enabled)}   {len(rows)} {noun}")

    if not rows:
        print()
        print(paint("No matching documents found.", "yellow", enabled))
        return

    for position, row in enumerate(rows, 1):
        print()
        number = paint(f"{position}.", "bright_yellow", enabled)
        title = paint(row["title"] or "Untitled document", "bold", enabled)
        print(f"{number} {title}")

        agency = row["agency"] or "Unknown agency"
        source = paint(row["source_id"], "cyan", enabled)
        print(f"   {paint('Source', 'dim', enabled)}     {agency} · {source}")

        category = human_label(row["category"])
        authority = human_label(row["authority_tier"])
        authority = paint(authority, authority_style(row["authority_tier"]), enabled)
        print(f"   {paint('Document', 'dim', enabled)}   {category} · {authority}")

        snippet = " ".join((row["snippet"] or "").split())
        if snippet:
            wrapped = textwrap.fill(
                snippet, width=width, initial_indent="   Match      ",
                subsequent_indent="              ", break_long_words=False,
                break_on_hyphens=False,
            )
            print(highlighted_snippet(wrapped, enabled))

        print(f"   {paint('Web', 'dim', enabled)}        {paint(row['url'], 'blue', enabled)}")
        if row["original_path"]:
            local_path = str((ROOT / row["original_path"]).resolve())
            print(f"   {paint('Local file', 'dim', enabled)} {local_path}")

    print()
    print(paint("Tip: add --json for machine-readable JSON Lines output.", "dim", enabled))


def search_rows(
    db: CorpusDB, query: str, limit: int, source_id: str | None,
) -> list[sqlite3.Row]:
    query = query.replace('\\"', '"')
    where = "document_fts MATCH ?"
    if source_id:
        where += " AND d.source_id=?"
    statement = f"""SELECT d.id,d.title,d.source_id,d.agency,d.category,d.authority_tier,d.url,d.original_path,
        snippet(document_fts,2,'[',']',' … ',24) snippet,bm25(document_fts) rank
        FROM document_fts JOIN documents d ON d.id=CAST(document_fts.document_id AS INTEGER)
        WHERE {where} ORDER BY rank LIMIT ?"""
    def params(value: str) -> list[Any]:
        return [value, source_id, limit] if source_id else [value, limit]
    try:
        rows = db.cx.execute(statement, params(query)).fetchall()
    except sqlite3.OperationalError as exc:
        if "fts5: syntax error" not in str(exc):
            raise
        tokens = re.findall(r"[A-Za-z0-9]+", query)
        if not tokens:
            raise
        rows = db.cx.execute(statement, params('"' + " ".join(tokens) + '"')).fetchall()
    return list(rows)


def search(
    db: CorpusDB, query: str, limit: int, source_id: str | None, *,
    json_output: bool = False, color_mode: str = "auto",
) -> None:
    rows = search_rows(db, query, limit, source_id)
    if json_output:
        for row in rows:
            print(json.dumps(dict(row), ensure_ascii=False))
        return
    print_search_results(query, rows, source_id, color_mode)


def list_sources(config: dict[str, Any]) -> None:
    for source in config["sources"]:
        print(f"{source['id']}\t{','.join(source.get('profiles', []))}\t{source['authority_tier']}\t{source['title']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="retrieve and index configured sources")
    sync.add_argument("--profile", choices=["core", "expanded"], default="core")
    sync.add_argument("--source", action="append", dest="sources", help="source id; repeatable")
    sync.add_argument("--max-docs", type=int, help="stop after this many network fetches (for testing)")
    sync.add_argument("--refresh", action="store_true", help="conditionally re-fetch already downloaded URLs")
    find = sub.add_parser("search", help="full-text search using SQLite FTS5 query syntax")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=20)
    find.add_argument("--source")
    find.add_argument("--json", action="store_true", help="emit one JSON object per result")
    find.add_argument(
        "--color", choices=["auto", "always", "never"], default="auto",
        help="colored human output: auto for terminals (default), always, or never",
    )
    sub.add_parser("audit", help="write manifest, checksum list, and coverage report")
    sub.add_parser("verify", help="verify local files against cataloged SHA-256 checksums")
    sub.add_parser("list-sources", help="list configured collections")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_json(CONFIG_DIR / "sources.json")
    topics = load_json(CONFIG_DIR / "topics.json")
    if args.command == "list-sources":
        list_sources(config)
        return 0
    db = CorpusDB()
    if args.command == "search":
        search(
            db, args.query, args.limit, args.source,
            json_output=args.json, color_mode=args.color,
        )
        return 0
    if args.command == "audit":
        write_reports(db)
        print(f"wrote {REPORT_DIR / 'manifest.csv'} and {REPORT_DIR / 'audit.md'}")
        return 0
    if args.command == "verify":
        return verify(db)
    if args.command == "sync":
        sources = selected_sources(config, args.profile, args.sources)
        builder = Builder(config, topics, args.max_docs, args.refresh)
        started = utc_now()
        for source in sources:
            if builder.at_limit():
                break
            builder.run_source(source)
        write_reports(builder.db)
        print(f"started={started} finished={utc_now()} fetched={builder.fetched} failed={builder.failed}")
        return 2 if builder.failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
