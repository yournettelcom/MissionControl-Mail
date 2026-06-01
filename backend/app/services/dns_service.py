# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import base64
import logging
import re
import socket
import subprocess
import tempfile
import time
from typing import Any, Optional

from .cloudflare_service import CloudflareService
from .registrobr_service import RegistrobrService

logger = logging.getLogger(__name__)


class DnsService:
    def __init__(
        self,
        cloudflare_service: CloudflareService | None = None,
        registrobr_service: RegistrobrService | None = None,
    ):
        self.cloudflare = cloudflare_service
        self.registrobr = registrobr_service or RegistrobrService()

    async def generate_dkim_keypair(self) -> tuple[str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "openssl", "genrsa", "2048",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            private_key = stdout.decode()

            with tempfile.NamedTemporaryFile(mode="w", suffix=".key") as f:
                f.write(private_key)
                f.flush()
                proc2 = await asyncio.create_subprocess_exec(
                    "openssl", "rsa", "-pubout", "-in", f.name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout2, stderr2 = await proc2.communicate()
                public_key_pem = stdout2.decode()
        except Exception as e:
            logger.error("Error generating DKIM keypair: %s", e)
            private_key = ""

        if not private_key:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            private_key = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()
            public_key_pem = key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode()

        public_key_lines = public_key_pem.splitlines()
        pubkey_body = "".join(
            line for line in public_key_lines
            if not line.startswith("-----")
        )
        return private_key, pubkey_body

    async def generate_dmarc_value(
        self, policy: str = "quarantine", reporting_email: str | None = None
    ) -> str:
        dmarc = f"v=DMARC1; p={policy}; sp={policy}; pct=100"
        if reporting_email:
            dmarc += f"; rua=mailto:{reporting_email}; ruf=mailto:{reporting_email}"
            dmarc += "; fo=1"
        return dmarc

    async def generate_spf_value(
        self,
        include_domains: list | None = None,
        mail_servers: list | None = None,
    ) -> str:
        parts = ["v=spf1"]
        if include_domains:
            for d in include_domains:
                parts.append(f"include:{d}")
        if mail_servers:
            for s in mail_servers:
                ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
                if ip_pattern.match(s):
                    parts.append(f"ip4:{s}")
                else:
                    parts.append(f"mx:{s}")
        parts.append("~all")
        return " ".join(parts)

    async def wizard(
        self,
        domain: str,
        mail_server_hostname: str,
        cloudflare_token: str | None = None,
    ) -> dict:
        report: dict[str, Any] = {
            "domain": domain,
            "mail_server": mail_server_hostname,
            "steps": {},
            "status": "pending",
        }

        try:
            whois_check = await self.registrobr.check_domain(domain)
            report["steps"]["domain_check"] = whois_check
            if not whois_check.get("registered", False):
                report["status"] = "domain_not_registered"
                return report

            dkim_private, dkim_public = await self.generate_dkim_keypair()
            selector = f"dkim.{domain.replace('.', '_')}"
            report["steps"]["dkim_generated"] = {
                "selector": selector,
                "public_key_length": len(dkim_public),
            }

            if cloudflare_token:
                self.cloudflare = CloudflareService(cloudflare_token)
                conn_test = await self.cloudflare.test_connection()
                report["steps"]["cloudflare_connection"] = conn_test
                if not conn_test.get("success", False):
                    report["status"] = "cloudflare_auth_failed"
                    return report

                zones = await self.cloudflare.list_zones()
                zone_id = None
                for z in zones:
                    if z["name"] == domain or domain.endswith("." + z["name"]):
                        zone_id = z["id"]
                        break

                if not zone_id:
                    report["status"] = "zone_not_found"
                    return report

                report["steps"]["zone_found"] = {"zone_id": zone_id, "zone_name": domain}

                mail_server_ip = None
                try:
                    mail_server_ip = socket.gethostbyname(mail_server_hostname)
                except OSError:
                    pass

                if mail_server_ip:
                    await self.cloudflare.create_dns_record(
                        zone_id=zone_id, record_type="A",
                        name=f"mail.{domain}", content=mail_server_ip,
                    )
                    await self.cloudflare.create_dns_record(
                        zone_id=zone_id, record_type="A",
                        name=domain, content=mail_server_ip,
                    )
                    report["steps"]["a_records"] = f"Created A records for {domain} and mail.{domain} -> {mail_server_ip}"

                mx = await self.cloudflare.create_mx_record(
                    zone_id=zone_id, domain=domain,
                    mail_server=mail_server_hostname,
                )
                report["steps"]["mx_record"] = mx

                spf_value = await self.generate_spf_value(
                    mail_servers=[mail_server_hostname]
                )
                spf = await self.cloudflare.create_spf_record(
                    zone_id=zone_id, domain=domain,
                    spf_value=spf_value,
                )
                report["steps"]["spf_record"] = spf

                dkim_dns = await self.cloudflare.create_dkim_record(
                    zone_id=zone_id, domain=domain,
                    selector=selector, public_key=dkim_public,
                )
                report["steps"]["dkim_record"] = dkim_dns

                dmarc_value = await self.generate_dmarc_value(
                    policy="quarantine",
                    reporting_email=f"dmarc@{domain}",
                )
                dmarc = await self.cloudflare.create_dmarc_record(
                    zone_id=zone_id, domain=domain,
                )
                report["steps"]["dmarc_record"] = dmarc

                await self.cloudflare.purge_cache(zone_id)
                report["steps"]["cache_purged"] = True

            propagation = await self.check_propagation(
                domain, "MX", mail_server_hostname
            )
            report["steps"]["propagation"] = propagation

            full_report = await self.get_dns_report(domain)
            report["dns_report"] = full_report
            report["status"] = "completed"

        except Exception as e:
            logger.error("DNS wizard error: %s", e)
            report["status"] = "error"
            report["error"] = str(e)

        return report

    async def check_propagation(
        self, domain: str, record_type: str, expected_value: str
    ) -> dict:
        result: dict = {"resolved": False, "actual_values": [], "matching": False}
        try:
            actual = await self.resolve_dns(domain, record_type)
            result["actual_values"] = actual
            if actual:
                result["resolved"] = True
                if expected_value:
                    for value in actual:
                        if expected_value in value or value in expected_value:
                            result["matching"] = True
                            break
        except Exception as e:
            logger.error("Error checking propagation: %s", e)
        return result

    async def resolve_dns(self, domain: str, record_type: str) -> list:
        results = []
        try:
            dns_type_map = {
                "A": "a",
                "AAAA": "aaaa",
                "MX": "mx",
                "TXT": "txt",
                "NS": "ns",
                "CNAME": "cname",
                "SOA": "soa",
                "PTR": "ptr",
            }
            dnstype = dns_type_map.get(record_type, "any")
            proc = await asyncio.create_subprocess_exec(
                "dig", "+short", "-t", dnstype, domain,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and stdout:
                for line in stdout.decode().splitlines():
                    line = line.strip()
                    if line:
                        results.append(line)
        except FileNotFoundError:
            try:
                if record_type == "MX":
                    _, _, _, _, sockaddr = socket.getaddrinfo(
                        domain, 25, socket.AF_INET, socket.SOCK_STREAM
                    )[0]
                    results.append(sockaddr[0])
            except Exception:
                pass
        except Exception as e:
            logger.error("Error resolving DNS: %s", e)
        return results

    async def get_dns_report(self, domain: str) -> dict:
        report: dict[str, Any] = {
            "domain": domain,
            "mx": {"present": False, "records": [], "correct": False},
            "spf": {"present": False, "records": [], "valid": False},
            "dkim": {"present": False, "records": [], "valid": False},
            "dmarc": {"present": False, "records": [], "valid": False},
            "ptr": {"present": False, "records": [], "valid": False},
            "smtp_banner": {"checked": False, "banner": "", "valid": False},
        }

        try:
            mx_records = await self.resolve_dns(domain, "MX")
            if mx_records:
                report["mx"]["present"] = True
                report["mx"]["records"] = mx_records
                for mx in mx_records:
                    if "mail" in mx or domain.split(".")[0] in mx:
                        report["mx"]["correct"] = True

            txt_records = await self.resolve_dns(domain, "TXT")
            for txt in txt_records:
                if txt.startswith("v=spf1"):
                    report["spf"]["present"] = True
                    report["spf"]["records"].append(txt)
                    if "mx" in txt or "include" in txt:
                        report["spf"]["valid"] = True

            dkim_records = await self.resolve_dns(
                f"_domainkey.{domain}", "TXT"
            )
            if dkim_records:
                report["dkim"]["present"] = True
                report["dkim"]["records"] = dkim_records
                for dkim in dkim_records:
                    if "v=DKIM1" in dkim or "p=" in dkim:
                        report["dkim"]["valid"] = True

            dmarc_records = await self.resolve_dns(
                f"_dmarc.{domain}", "TXT"
            )
            if dmarc_records:
                report["dmarc"]["present"] = True
                report["dmarc"]["records"] = dmarc_records
                for dmarc in dmarc_records:
                    if "v=DMARC1" in dmarc:
                        report["dmarc"]["valid"] = True

            try:
                ip = socket.gethostbyname(f"mail.{domain}")
                ptr_records = await self.resolve_dns(
                    socket.gethostbyaddr(ip)[0], "PTR"
                )
                if ptr_records:
                    report["ptr"]["present"] = True
                    report["ptr"]["records"] = ptr_records
            except (OSError, socket.gaierror, socket.herror):
                pass

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(f"mail.{domain}", 25), timeout=5
                )
                banner = await asyncio.wait_for(reader.readline(), timeout=5)
                report["smtp_banner"]["checked"] = True
                report["smtp_banner"]["banner"] = banner.decode().strip()
                if domain.split(".")[0] in banner.decode().lower():
                    report["smtp_banner"]["valid"] = True
                writer.close()
            except Exception:
                pass

        except Exception as e:
            logger.error("Error getting DNS report: %s", e)

        return report
