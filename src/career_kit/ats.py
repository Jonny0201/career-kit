"""Read-only payload parsers; official identity and live fetching are separate."""

from __future__ import annotations

import ipaddress
import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from career_kit.errors import ContractError
from career_kit.canonical_json import canonical_sha256


ADAPTERS = {
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
    "generic",
}
_TAG = re.compile(r"<[^>]+>")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = unescape(_TAG.sub(" ", str(value)))
    result = " ".join(text.split())
    return result or None


def _list_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                candidate = item.get("name") or item.get("label") or item.get("city")
            else:
                candidate = item
            if candidate:
                result.append(str(candidate))
        return result
    if isinstance(value, dict):
        candidate = value.get("name") or value.get("label") or value.get("city")
        return [str(candidate)] if candidate else []
    return [str(value)]


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ContractError(
            "JOB_SOURCE_URL_INVALID",
            "job source URL must be credential-free absolute HTTPS",
            {"url": url},
        )
    host = parsed.hostname.casefold()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ContractError("JOB_SOURCE_URL_INVALID", "local job source URL is forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ContractError(
            "JOB_SOURCE_URL_INVALID", "non-public job source IP is forbidden"
        )


def build_adapter_url(adapter: str, locator: str) -> str:
    if adapter not in ADAPTERS:
        raise ContractError("ATS_ADAPTER_UNSUPPORTED", "ATS adapter is unsupported")
    if adapter == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{quote(locator, safe='')}/jobs?content=true"
    elif adapter == "lever":
        url = f"https://api.lever.co/v0/postings/{quote(locator, safe='')}?mode=json"
    elif adapter == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{quote(locator, safe='')}"
    elif adapter == "smartrecruiters":
        url = f"https://api.smartrecruiters.com/v1/companies/{quote(locator, safe='')}/postings?limit=100"
    else:
        url = locator
    validate_public_url(url)
    if adapter == "workday" and not (
        urlparse(url).hostname or ""
    ).casefold().endswith((".myworkdayjobs.com", ".workdayjobs.com")):
        raise ContractError(
            "JOB_SOURCE_URL_INVALID",
            "Workday locator must use an official Workday jobs host",
        )
    return url


class _GenericHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._json_ld = False
        self._script_text: list[str] = []
        self.json_documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value for key, value in attrs}
        if tag.casefold() == "a" and values.get("href"):
            self._anchor_href = urljoin(self.base_url, str(values["href"]))
            self._anchor_text = []
        if tag.casefold() == "script" and str(values.get("type") or "").casefold() == "application/ld+json":
            self._json_ld = True
            self._script_text = []

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_text.append(data)
        if self._json_ld:
            self._script_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._anchor_href is not None:
            label = " ".join("".join(self._anchor_text).split())
            self.links.append((self._anchor_href, label))
            self._anchor_href = None
            self._anchor_text = []
        if tag.casefold() == "script" and self._json_ld:
            try:
                self.json_documents.append(json.loads("".join(self._script_text)))
            except json.JSONDecodeError:
                pass
            self._json_ld = False
            self._script_text = []


class ATSParser:
    def parse(self, adapter: str, data: bytes, source_url: str) -> tuple[list[dict[str, Any]], list[str], bool]:
        validate_public_url(source_url)
        if adapter not in ADAPTERS:
            raise ContractError("ATS_ADAPTER_UNSUPPORTED", "ATS adapter is unsupported")
        if adapter == "generic":
            return self._generic(data, source_url)
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(
                "ATS_PAYLOAD_INVALID", "ATS adapter expected UTF-8 JSON"
            ) from exc
        method = getattr(self, f"_{adapter}")
        jobs = method(payload)
        for job in jobs:
            for field in ("job_url", "apply_url"):
                if job.get(field):
                    job[field] = urljoin(source_url, str(job[field]))
        return jobs, [], False

    def _greenhouse(self, payload: Any) -> list[dict[str, Any]]:
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ContractError("ATS_PAYLOAD_INVALID", "Greenhouse jobs array is missing")
        return [
            {
                "external_job_id": str(item.get("id")),
                "requisition_id": str(item["requisition_id"]) if item.get("requisition_id") is not None else None,
                "title": str(item.get("title") or ""),
                "locations": _list_text(item.get("location")) or _list_text(item.get("offices")),
                "description": _text(item.get("content")),
                "job_url": str(item.get("absolute_url") or ""),
                "apply_url": str(item.get("absolute_url") or ""),
                "posted_at_utc": item.get("first_published"),
                "updated_at_utc": item.get("updated_at"),
                "employment_type": None,
                "work_mode": None,
                "extensions": {
                    "internal_job_id": item.get("internal_job_id"),
                    "departments": item.get("departments", []),
                    "metadata": item.get("metadata"),
                },
            }
            for item in jobs
            if isinstance(item, dict) and item.get("id") is not None and item.get("title")
        ]

    def _lever(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ContractError("ATS_PAYLOAD_INVALID", "Lever payload must be an array")
        result = []
        for item in payload:
            if not isinstance(item, dict) or not item.get("id") or not item.get("text"):
                continue
            categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
            result.append(
                {
                    "external_job_id": str(item["id"]),
                    "requisition_id": None,
                    "title": str(item["text"]),
                    "locations": _list_text(categories.get("location") or item.get("workplaceType")),
                    "description": _text(item.get("descriptionPlain") or item.get("description")),
                    "job_url": str(item.get("hostedUrl") or ""),
                    "apply_url": str(item.get("applyUrl") or item.get("hostedUrl") or ""),
                    "posted_at_utc": None,
                    "updated_at_utc": None,
                    "employment_type": categories.get("commitment"),
                    "work_mode": item.get("workplaceType"),
                    "extensions": {"team": categories.get("team"), "department": categories.get("department")},
                }
            )
        return result

    def _ashby(self, payload: Any) -> list[dict[str, Any]]:
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ContractError("ATS_PAYLOAD_INVALID", "Ashby jobs array is missing")
        return [
            {
                "external_job_id": str(item.get("id") or item.get("jobPostingId")),
                "requisition_id": str(item["requisitionId"]) if item.get("requisitionId") is not None else None,
                "title": str(item.get("title") or ""),
                "locations": _list_text(item.get("location") or item.get("locations")),
                "description": _text(item.get("descriptionPlain") or item.get("descriptionHtml") or item.get("description")),
                "job_url": str(item.get("jobUrl") or item.get("jobPostingUrl") or ""),
                "apply_url": str(item.get("applyUrl") or item.get("jobUrl") or item.get("jobPostingUrl") or ""),
                "posted_at_utc": item.get("publishedAt") or item.get("publishedDate"),
                "updated_at_utc": item.get("updatedAt"),
                "employment_type": item.get("employmentType"),
                "work_mode": item.get("workplaceType") or ("remote" if item.get("isRemote") else None),
                "extensions": {"department": item.get("department"), "team": item.get("team")},
            }
            for item in jobs
            if isinstance(item, dict) and (item.get("id") or item.get("jobPostingId")) and item.get("title")
        ]

    def _smartrecruiters(self, payload: Any) -> list[dict[str, Any]]:
        jobs = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ContractError("ATS_PAYLOAD_INVALID", "SmartRecruiters content array is missing")
        result = []
        for item in jobs:
            if not isinstance(item, dict) or not (item.get("id") or item.get("uuid")):
                continue
            location = item.get("location") if isinstance(item.get("location"), dict) else {}
            location_text = ", ".join(
                str(location[key]) for key in ("city", "region", "country") if location.get(key)
            )
            result.append(
                {
                    "external_job_id": str(item.get("id") or item.get("uuid")),
                    "requisition_id": str(item["id"]) if item.get("id") is not None else None,
                    "title": str(item.get("name") or item.get("title") or ""),
                    "locations": [location_text] if location_text else [],
                    "description": _text(item.get("jobAd") or item.get("description")),
                    "job_url": str(item.get("ref") or ""),
                    "apply_url": str(item.get("ref") or ""),
                    "posted_at_utc": item.get("releasedDate"),
                    "updated_at_utc": item.get("updatedDate"),
                    "employment_type": (item.get("typeOfEmployment") or {}).get("label") if isinstance(item.get("typeOfEmployment"), dict) else None,
                    "work_mode": "remote" if item.get("remote") is True else None,
                    "extensions": {"department": item.get("department"), "function": item.get("function")},
                }
            )
        return result

    def _workday(self, payload: Any) -> list[dict[str, Any]]:
        detail = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            external_path = detail.get("externalUrl") or detail.get("externalPath")
            title = detail.get("title") or detail.get("jobTitle")
            if not external_path or not title:
                raise ContractError(
                    "ATS_PAYLOAD_INVALID",
                    "Workday detail payload lacks title or external URL",
                )
            return [
                {
                    "external_job_id": str(
                        detail.get("jobPostingId")
                        or detail.get("jobReqId")
                        or detail.get("id")
                    ),
                    "requisition_id": (
                        str(detail["jobReqId"])
                        if detail.get("jobReqId") is not None
                        else None
                    ),
                    "title": str(title),
                    "locations": _list_text(detail.get("location")),
                    "description": _text(detail.get("jobDescription")),
                    "job_url": str(external_path),
                    "apply_url": str(external_path),
                    "posted_at_utc": detail.get("startDate") or detail.get("postedOn"),
                    "updated_at_utc": None,
                    "employment_type": detail.get("timeType"),
                    "work_mode": detail.get("remoteType"),
                    "extensions": {
                        "workday_id": detail.get("id"),
                        "job_posting_site_id": detail.get("jobPostingSiteId"),
                        "can_apply": detail.get("canApply"),
                        "posted": detail.get("posted"),
                    },
                }
            ]
        jobs = payload.get("jobPostings") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ContractError("ATS_PAYLOAD_INVALID", "Workday jobPostings array is missing")
        result = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            external_path = item.get("externalPath") or item.get("jobPath")
            title = item.get("title") or item.get("jobTitle")
            if not external_path or not title:
                continue
            result.append(
                {
                    "external_job_id": str(item.get("bulletFields", [external_path])[0] if item.get("bulletFields") else external_path),
                    "requisition_id": str(item["jobReqId"]) if item.get("jobReqId") is not None else None,
                    "title": str(title),
                    "locations": _list_text(item.get("locationsText") or item.get("location")),
                    "description": _text(item.get("jobDescription")),
                    "job_url": str(external_path),
                    "apply_url": str(external_path),
                    "posted_at_utc": item.get("postedOn") or item.get("startDate"),
                    "updated_at_utc": None,
                    "employment_type": item.get("timeType"),
                    "work_mode": item.get("remoteType"),
                    "extensions": {"bullet_fields": item.get("bulletFields", [])},
                }
            )
        return result

    def _generic(self, data: bytes, source_url: str) -> tuple[list[dict[str, Any]], list[str], bool]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("ATS_PAYLOAD_INVALID", "generic careers HTML must be UTF-8") from exc
        parser = _GenericHTMLParser(source_url)
        parser.feed(text)
        embedded = self._embedded_vacancies(text, source_url)
        if embedded:
            return embedded, [], False
        jobs: list[dict[str, Any]] = []
        documents: list[Any] = []
        for value in parser.json_documents:
            if isinstance(value, list):
                documents.extend(value)
            elif isinstance(value, dict) and isinstance(value.get("@graph"), list):
                documents.extend(value["@graph"])
            else:
                documents.append(value)
        for item in documents:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            identifier = item.get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value")
            location = item.get("jobLocation")
            jobs.append(
                {
                    "external_job_id": str(identifier or canonical_sha256(item)[:24]),
                    "requisition_id": str(identifier) if identifier else None,
                    "title": str(item.get("title") or ""),
                    "locations": _list_text(location),
                    "description": _text(item.get("description")),
                    "job_url": str(item.get("url") or source_url),
                    "apply_url": str(item.get("url") or source_url),
                    "posted_at_utc": item.get("datePosted"),
                    "updated_at_utc": None,
                    "employment_type": item.get("employmentType"),
                    "work_mode": item.get("jobLocationType"),
                    "extensions": {},
                }
            )
        if jobs:
            return jobs, [], False
        link_jobs = []
        seen_links: set[str] = set()
        for href, label in parser.links:
            parsed = urlparse(href)
            lowered_label = label.casefold()
            path = parsed.path.casefold().rstrip("/")
            looks_like_job_path = bool(
                re.search(r"/jobs?/[^/]+$", path)
            )
            explicit_job_label = any(
                token in lowered_label for token in (" job", "position", "opening")
            )
            if (
                label
                and href not in seen_links
                and not parsed.fragment
                and (looks_like_job_path or explicit_job_label)
            ):
                seen_links.add(href)
                link_jobs.append(
                    {
                        "external_job_id": canonical_sha256({"href": href})[:24],
                        "requisition_id": None,
                        "title": label,
                        "locations": [],
                        "description": None,
                        "job_url": href,
                        "apply_url": href,
                        "posted_at_utc": None,
                        "updated_at_utc": None,
                        "employment_type": None,
                        "work_mode": None,
                        "extensions": {"discovery_only": True},
                    }
                )
        warning = "generic_page_requires_detail_fetch_or_manual_takeover"
        return link_jobs, [warning], False

    @staticmethod
    def _embedded_vacancies(text: str, source_url: str) -> list[dict[str, Any]]:
        """Parse a bounded official `const vacancies = [...]` data payload."""

        marker = re.search(r"\bconst\s+vacancies\s*=\s*", text)
        if marker is None:
            return []
        start = text.find("[", marker.end())
        if start < 0:
            return []
        try:
            values, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            return []
        if not isinstance(values, list):
            return []
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in values:
            if not isinstance(item, dict) or item.get("id") is None or not item.get("title"):
                continue
            external_job_id = str(item["id"])
            if external_job_id in seen:
                continue
            url = urljoin(source_url, str(item.get("url") or ""))
            if not urlparse(url).hostname:
                continue
            location = str(item.get("location") or "")
            lowered_location = location.casefold()
            remote = "home based" in lowered_location or "remote" in lowered_location
            onsite = "office based" in lowered_location or "on-site" in lowered_location
            work_mode = "hybrid" if remote and onsite else "remote" if remote else "onsite" if onsite else None
            seen.add(external_job_id)
            jobs.append(
                {
                    "external_job_id": external_job_id,
                    "requisition_id": external_job_id,
                    "title": str(item["title"]),
                    "locations": [location] if location else [],
                    "description": _text(item.get("description")),
                    "job_url": url,
                    "apply_url": url,
                    "posted_at_utc": item.get("date"),
                    "updated_at_utc": None,
                    "employment_type": item.get("employment"),
                    "work_mode": work_mode,
                    "extensions": {
                        "departments": item.get("departments", []),
                        "skills": item.get("skills", []),
                        "management": item.get("management"),
                    },
                }
            )
        return jobs
