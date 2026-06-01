# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class CloudflareService:
    api_base = "https://api.cloudflare.com/client/v4"

    def __init__(self, api_token: str):
        self.api_token = api_token
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, endpoint: str, data: dict | None = None
    ) -> dict:
        url = f"{self.api_base}{endpoint}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=data,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()
                if not result.get("success", False):
                    errors = result.get("errors", [])
                    logger.error("Cloudflare API error: %s", errors)
                    return {"success": False, "errors": errors}
                return result
            except httpx.HTTPStatusError as e:
                logger.error(
                    "HTTP error %s: %s", e.response.status_code, e.response.text
                )
                return {"success": False, "errors": [{"message": str(e)}]}
            except httpx.RequestError as e:
                logger.error("Request error: %s", e)
                return {"success": False, "errors": [{"message": str(e)}]}
            except Exception as e:
                logger.error("Unexpected error: %s", e)
                return {"success": False, "errors": [{"message": str(e)}]}

    async def _paginated_request(
        self, method: str, endpoint: str, params: dict | None = None
    ) -> list:
        all_items = []
        page = 1
        per_page = 50
        while True:
            query_params = params or {}
            query_params.update({"page": page, "per_page": per_page})
            query_string = "&".join(
                f"{k}={v}" for k, v in query_params.items()
            )
            separator = "&" if "?" in endpoint else "?"
            paginated_endpoint = f"{endpoint}{separator}{query_string}"
            result = await self._request(method, paginated_endpoint)
            if not result.get("success", False):
                break
            items = result.get("result", [])
            all_items.extend(items)
            total_pages = result.get("result_info", {}).get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
        return all_items

    async def test_connection(self) -> dict:
        result = await self._request("GET", "/user/token/verify")
        if not result.get("success", False):
            return {"success": False, "email": None, "zones_count": 0}
        user_info = result.get("result", {})
        zones = await self.list_zones()
        return {
            "success": True,
            "email": user_info.get("email", ""),
            "zones_count": len(zones),
        }

    async def list_zones(self) -> list:
        zones_raw = await self._paginated_request("GET", "/zones")
        zones = []
        for z in zones_raw:
            zones.append({
                "id": z.get("id"),
                "name": z.get("name"),
                "status": z.get("status"),
                "plan": z.get("plan", {}).get("name", "Free"),
            })
        return zones

    async def get_zone(self, zone_id: str) -> dict:
        result = await self._request("GET", f"/zones/{zone_id}")
        if not result.get("success", False):
            return {}
        z = result.get("result", {})
        return {
            "id": z.get("id"),
            "name": z.get("name"),
            "status": z.get("status"),
            "plan": z.get("plan", {}).get("name", "Free"),
            "name_servers": z.get("name_servers", []),
            "original_name_servers": z.get("original_name_servers", []),
            "created_on": z.get("created_on"),
            "modified_on": z.get("modified_on"),
        }

    async def list_dns_records(
        self, zone_id: str, record_type: str | None = None
    ) -> list:
        params = {}
        if record_type:
            params["type"] = record_type
        records_raw = await self._paginated_request(
            "GET", f"/zones/{zone_id}/dns_records", params
        )
        records = []
        for r in records_raw:
            records.append({
                "id": r.get("id"),
                "type": r.get("type"),
                "name": r.get("name"),
                "content": r.get("content"),
                "ttl": r.get("ttl"),
                "proxied": r.get("proxied", False),
                "priority": r.get("priority"),
                "created_on": r.get("created_on"),
            })
        return records

    async def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 120,
        proxied: bool = False,
    ) -> dict:
        payload = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if record_type in ("MX", "SRV"):
            payload["priority"] = 10
        result = await self._request(
            "POST", f"/zones/{zone_id}/dns_records", payload
        )
        return result.get("result", {})

    async def update_dns_record(
        self, zone_id: str, record_id: str, data: dict
    ) -> dict:
        payload = {
            "type": data.get("type", ""),
            "name": data.get("name", ""),
            "content": data.get("content", ""),
            "ttl": data.get("ttl", 120),
            "proxied": data.get("proxied", False),
        }
        result = await self._request(
            "PUT", f"/zones/{zone_id}/dns_records/{record_id}", payload
        )
        return result.get("result", {})

    async def delete_dns_record(self, zone_id: str, record_id: str) -> bool:
        result = await self._request(
            "DELETE", f"/zones/{zone_id}/dns_records/{record_id}"
        )
        return result.get("success", False)

    async def create_mx_record(
        self,
        zone_id: str,
        domain: str,
        mail_server: str,
        priority: int = 10,
    ) -> dict:
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="MX",
            name=domain,
            content=mail_server,
            ttl=120,
        )

    async def create_spf_record(
        self,
        zone_id: str,
        domain: str,
        spf_value: str | None = None,
    ) -> dict:
        if spf_value is None:
            spf_value = f"v=spf1 mx include:_spf.{domain} ~all"
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="TXT",
            name=domain,
            content=spf_value,
            ttl=120,
        )

    async def create_dkim_record(
        self,
        zone_id: str,
        domain: str,
        selector: str,
        public_key: str,
    ) -> dict:
        dkim_key = public_key
        if not dkim_key.startswith("v=DKIM1"):
            dkim_key = f"v=DKIM1; p={public_key}"
        dkim_key = dkim_key.replace("\n", "").replace("\r", "")
        record_name = f"{selector}._domainkey.{domain}"
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="TXT",
            name=record_name,
            content=dkim_key,
            ttl=120,
        )

    async def create_dmarc_record(
        self,
        zone_id: str,
        domain: str,
        policy: str = "quarantine",
    ) -> dict:
        dmarc_value = f"v=DMARC1; p={policy}; sp={policy}; rua=mailto:dmarc@{domain}; ruf=mailto:dmarc@{domain}; fo=1"
        return await self.create_dns_record(
            zone_id=zone_id,
            record_type="TXT",
            name=f"_dmarc.{domain}",
            content=dmarc_value,
            ttl=120,
        )

    async def purge_cache(
        self, zone_id: str, urls: list | None = None
    ) -> bool:
        payload: dict[str, Any] = {"purge_everything": True}
        if urls:
            payload = {"files": urls}
        result = await self._request(
            "POST", f"/zones/{zone_id}/purge_cache", payload
        )
        return result.get("success", False)
