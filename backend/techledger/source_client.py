"""Fetch metadata from a small, explicit set of public documentation sources."""

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from techledger.config import SOURCE_MAX_BYTES, SOURCE_MAX_REDIRECTS, SOURCE_TIMEOUT_SECONDS


class SourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchedSource:
    url: str
    title: str
    excerpt: str
    content_sha256: str
    content_type: str
    byte_size: int
    text_content: str = ""


def normalize_url(value: str) -> tuple[str, str]:
    """Return a canonical URL only for the four approved source families."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise SourceError("invalid_url", "来源 URL 无效") from exc

    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise SourceError("source_not_allowed", "仅允许指定的 HTTPS 官方来源")

    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    approved = (
        host == "docs.langchain.com" and path.startswith("/oss/python/langgraph/"),
        host == "docs.crewai.com" and bool(re.match(r"^/(?:v[^/]+/)?en/", path)),
        host == "github.com" and path.startswith("/langchain-ai/langgraph/releases"),
        host == "github.com" and path.startswith("/crewAIInc/crewAI/releases"),
    )
    if not any(approved):
        raise SourceError("source_not_allowed", "来源不在首批官方资料白名单内")

    # Fragments and queries are not part of a source identity.
    return urlunsplit(("https", host, path.rstrip("/") or "/", "", "")), host


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._title = False
        self._skip = 0
        self._main_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "main":
            self._main_depth += 1
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "aside"}:
            self._skip += 1
        if tag == "title":
            self._title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "aside"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._title:
            self.title_parts.append(cleaned)
        elif self._main_depth:
            self.text_parts.append(cleaned)


def _metadata(data: bytes, content_type: str, url: str) -> FetchedSource:
    text = data.decode("utf-8", errors="replace")
    if content_type == "text/html":
        extractor = _TextExtractor()
        extractor.feed(text)
        title = " ".join(extractor.title_parts).strip() or url
        normalized = " ".join(extractor.text_parts)
        if not normalized:
            raise SourceError("empty_main_content", "来源页面缺少可提取的正文")
        excerpt = normalized[:500]
    else:
        title = url
        normalized = " ".join(text.split())
        excerpt = normalized[:500]
    return FetchedSource(
        url=url,
        title=title[:500],
        excerpt=excerpt,
        content_sha256=hashlib.sha256(data).hexdigest(),
        content_type=content_type,
        byte_size=len(data),
        text_content=normalized,
    )


def fetch_source(url: str) -> FetchedSource:
    """Fetch only approved URLs; validate every redirect and cap response bytes."""
    current, _ = normalize_url(url)
    try:
        with httpx.Client(timeout=SOURCE_TIMEOUT_SECONDS, follow_redirects=False) as client:
            for _ in range(SOURCE_MAX_REDIRECTS + 1):
                with client.stream("GET", current, headers={"Accept": "text/html,text/plain"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceError("redirect_missing", "来源跳转缺少目标地址")
                        current, _ = normalize_url(urljoin(current, location))
                        continue
                    if response.status_code != 200:
                        raise SourceError("upstream_error", f"来源返回 HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type not in {"text/html", "text/plain"}:
                        raise SourceError("unsupported_content", "来源不是 HTML 或纯文本")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > SOURCE_MAX_BYTES:
                            raise SourceError("source_too_large", "来源超过大小限制")
                        chunks.append(chunk)
                    return _metadata(b"".join(chunks), content_type, current)
            raise SourceError("too_many_redirects", "来源跳转次数过多")
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        raise SourceError("source_unavailable", "来源暂时无法访问") from exc
