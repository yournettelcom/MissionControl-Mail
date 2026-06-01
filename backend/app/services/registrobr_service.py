# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class RegistrobrService:
    BASE_URL = "https://registro.br/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def _request(
        self, method: str, endpoint: str, data: dict | None = None
    ) -> dict:
        url = f"{self.BASE_URL}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    timeout=30.0,
                )
                if response.status_code == 404:
                    return {"success": True, "registered": False, "result": {}}
                response.raise_for_status()
                result = response.json()
                return {"success": True, "result": result}
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Registro.br HTTP error %s: %s",
                    e.response.status_code,
                    e.response.text,
                )
                return {"success": False, "error": str(e), "registered": False}
            except httpx.RequestError as e:
                logger.error("Registro.br request error: %s", e)
                return {"success": False, "error": str(e)}
            except json.JSONDecodeError as e:
                logger.error("Registro.br parse error: %s", e)
                return {"success": False, "error": str(e)}
            except Exception as e:
                logger.error("Registro.br unexpected error: %s", e)
                return {"success": False, "error": str(e)}

    async def check_domain(self, domain: str) -> dict:
        result = await self._request("GET", f"/domain/{domain}")
        if result.get("success"):
            data = result.get("result", {})
            registered = (
                data.get("status", "") != "AVAILABLE"
                if data
                else False
            )
            return {
                "success": True,
                "domain": domain,
                "registered": registered,
                "owner": data.get("owner", {}).get("name", "") if data else "",
                "owner_cnpj": data.get("owner", {}).get("cnpj_cpf", "") if data else "",
                "status": data.get("status", "") if data else "",
                "expires": data.get("expires", "") if data else "",
            }
        return {
            "success": False,
            "domain": domain,
            "registered": False,
            "error": result.get("error", ""),
        }

    async def get_dns_status(self, domain: str) -> dict:
        result = await self._request("GET", f"/domain/{domain}/dns")
        if result.get("success"):
            data = result.get("result", {})
            return {
                "success": True,
                "domain": domain,
                "dns_servers": data.get("dns_servers", []) if data else [],
                "status": data.get("status", "") if data else "",
            }
        return {
            "success": False,
            "domain": domain,
            "dns_servers": [],
            "error": result.get("error", ""),
        }

    async def get_domain_info(self, domain: str) -> dict:
        result = await self._request("GET", f"/domain/{domain}")
        if result.get("success"):
            data = result.get("result", {})
            if data:
                return {
                    "success": True,
                    "domain": domain,
                    "expiration": data.get("expires", ""),
                    "status": data.get("status", ""),
                    "owner": data.get("owner", {}).get("name", ""),
                    "owner_cnpj": data.get("owner", {}).get("cnpj_cpf", ""),
                    "owner_email": data.get("owner", {}).get("email", ""),
                    "created": data.get("created", ""),
                    "dns_servers": data.get("dns_servers", []),
                    "registrar": data.get("registrar", ""),
                    "ticket": data.get("ticket", ""),
                }
            return {
                "success": True,
                "domain": domain,
                "expiration": "",
                "status": "AVAILABLE",
            }
        return {
            "success": False,
            "domain": domain,
            "error": result.get("error", ""),
        }

    async def check_zone_status(self, domain: str) -> dict:
        result = await self._request("GET", f"/domain/{domain}/zone")
        if result.get("success"):
            data = result.get("result", {})
            return {
                "success": True,
                "domain": domain,
                "zone_status": data.get("status", "") if data else "",
                "last_check": data.get("last_check", "") if data else "",
                "dns_servers": data.get("dns_servers", []) if data else [],
            }
        return {
            "success": False,
            "domain": domain,
            "zone_status": "",
            "error": result.get("error", ""),
        }

    async def suggest_dns(self, domain: str) -> list:
        suggestions: list[dict] = []
        result = await self._request("GET", f"/domain/{domain}/suggestions")
        if result.get("success"):
            data = result.get("result", [])
            if isinstance(data, list):
                suggestions = data
        if not suggestions:
            suggestions = [
                {"type": "A", "name": domain, "content": "127.0.0.1", "ttl": 3600},
                {"type": "AAAA", "name": domain, "content": "::1", "ttl": 3600},
                {"type": "MX", "name": domain, "content": f"mail.{domain}", "priority": 10, "ttl": 3600},
                {"type": "TXT", "name": domain, "content": f"v=spf1 mx ~all", "ttl": 3600},
                {"type": "CNAME", "name": f"mail.{domain}", "content": domain, "ttl": 3600},
                {"type": "CNAME", "name": f"webmail.{domain}", "content": domain, "ttl": 3600},
            ]
        return suggestions
