# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import logging
import os
import socket
import ssl
from datetime import datetime, timezone
from typing import Any

from .postfix_service import PostfixService
from .dovecot_service import DovecotService
from .system_service import SystemService

logger = logging.getLogger(__name__)

REQUIRED_PORTS = {
    25: "SMTP",
    143: "IMAP",
    465: "SMTPS",
    587: "Submission",
    993: "IMAPS",
}

POSTFIX_CONFIG_CHECK = "postconf -n 2>/dev/null | head -1"


class HealthService:
    def __init__(self):
        self.postfix = PostfixService()
        self.dovecot = DovecotService()
        self.system = SystemService()

    async def _run_bash(self, cmd: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    def _check_port(self, port: int) -> dict:
        result = {"port": port, "service": REQUIRED_PORTS.get(port, "unknown"), "open": False}
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result["open"] = sock.connect_ex(("127.0.0.1", port)) == 0
            sock.close()
        except Exception:
            result["open"] = False
        return result

    def _check_tls(self, port: int) -> dict:
        result = {"port": port, "tls_ok": False, "cert_expiry_days": None, "cert_issuer": None, "error": None}
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            if port == 587:
                sock.sendall(b"EHLO localhost\r\n")
                resp = sock.recv(4096)
                sock.sendall(b"STARTTLS\r\n")
                resp = sock.recv(4096)
            with ctx.wrap_socket(sock, server_hostname="localhost") as ssock:
                cert = ssock.getpeercert()
                result["tls_ok"] = True
                if cert:
                    result["cert_issuer"] = dict(cert.get("issuer", [])).get("organizationName", "unknown")
                    not_after = cert.get("notAfter", "")
                    if not_after:
                        try:
                            expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                            result["cert_expiry_days"] = (expiry - datetime.now(timezone.utc)).days
                        except ValueError:
                            pass
        except Exception as e:
            result["error"] = str(e)[:100]
        return result

    async def full_health_check(self) -> dict:
        results: dict[str, Any] = {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {},
            "ports": [],
            "tls": [],
            "postfix_config": {},
            "dns": {},
            "storage": {},
            "queue": {},
        }

        svc_postfix = await self.postfix.get_status()
        svc_dovecot = await self.dovecot.get_status()
        results["services"]["postfix"] = {"running": svc_postfix}
        results["services"]["dovecot"] = {"running": svc_dovecot}

        results["services"]["rspamd"] = {"running": False}
        rc, out, _ = await self._run_bash("systemctl is-active rspamd 2>/dev/null")
        if out.strip() == "active":
            results["services"]["rspamd"]["running"] = True
            rc, out, _ = await self._run_bash("rspamc stat 2>/dev/null | head -1")
            results["services"]["rspamd"]["stat"] = out.strip() if out.strip() else None

        results["services"]["apache2"] = {"running": False}
        rc, out, _ = await self._run_bash("systemctl is-active apache2 2>/dev/null || echo 'inactive'")
        results["services"]["apache2"]["running"] = out.strip() == "active"

        for port in REQUIRED_PORTS:
            results["ports"].append(self._check_port(port))

        for port in [465, 587, 993]:
            results["tls"].append(self._check_tls(port))

        results["postfix_config"]["valid"] = False
        rc, out, err = await self._run_bash("postfix check 2>&1 || sudo postfix check 2>&1")
        error_text = (err or out).strip()[:200]
        results["postfix_config"]["valid"] = rc == 0
        if not results["postfix_config"]["valid"] and "superuser" not in error_text.lower() and "reserved" not in error_text.lower():
            results["postfix_config"]["error"] = error_text

        rc, out, _ = await self._run_bash("postconf virtual_mailbox_maps 2>/dev/null")
        vmm = out.replace("virtual_mailbox_maps = ", "").strip() if out.strip() else "none"
        rc2, out2, _ = await self._run_bash("postconf virtual_mailbox_domains 2>/dev/null")
        vmd = out2.replace("virtual_mailbox_domains = ", "").strip() if out2.strip() else "none"
        if vmd and vmd.startswith("$"):
            vmd = vmm
        results["postfix_config"]["virtual_domains"] = vmd
        results["postfix_config"]["virtual_mailbox_maps"] = vmm

        q = await self.postfix.get_queue_status()
        results["queue"] = q

        results["storage"]["vmail_exists"] = os.path.isdir("/var/vmail") or os.path.isdir("/opt/missioncontrol/vmail")
        rc, out, _ = await self._run_bash("df -h /var/vmail 2>/dev/null | tail -1")
        if out.strip():
            parts = out.split()
            if len(parts) >= 5:
                results["storage"]["disk_used"] = parts[2]
                results["storage"]["disk_avail"] = parts[3]
                results["storage"]["disk_pct"] = parts[4]

        rc, out, _ = await self._run_bash("hostname -f 2>/dev/null || hostname 2>/dev/null")
        results["hostname"] = out.strip() if out.strip() else "unknown"

        results["status"] = "healthy"
        if not svc_postfix or not svc_dovecot:
            results["status"] = "unhealthy"
        elif any(p["open"] is False for p in results["ports"]):
            results["status"] = "degraded"

        return results

    async def diagnose_delivery(self, test_email: str) -> dict:
        result: dict[str, Any] = {
            "target": test_email,
            "steps": {},
            "overall": "unknown",
        }

        mx_ok = False
        rc, out, _ = await self._run_bash(f"dig MX {test_email.split('@')[1]} +short 2>/dev/null | head -3")
        mx_records = [line.strip() for line in out.splitlines() if line.strip()] if out.strip() else []
        result["steps"]["mx_lookup"] = {"found": len(mx_records) > 0, "records": mx_records}

        if mx_records:
            mx_target = mx_records[0].rstrip(".")
            rc, out, _ = await self._run_bash(f"dig A {mx_target} +short 2>/dev/null | head -1")
            mx_ip = out.strip()
            result["steps"]["mx_resolve"] = {"ip": mx_ip or "unresolved"}

            if mx_ip:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    port_open = sock.connect_ex((mx_ip, 25)) == 0
                    sock.close()
                    result["steps"]["smtp_connect"] = {"reachable": port_open}
                except Exception as e:
                    result["steps"]["smtp_connect"] = {"reachable": False, "error": str(e)[:100]}

        rc, out, _ = await self._run_bash(f"dig TXT {test_email.split('@')[1]} +short 2>/dev/null")
        spf_records = [line.strip().strip('"') for line in out.splitlines() if "v=spf1" in line]
        result["steps"]["spf"] = {"found": len(spf_records) > 0, "records": spf_records}

        dkim_domain = f"default._domainkey.{test_email.split('@')[1]}"
        rc, out, _ = await self._run_bash(f"dig TXT {dkim_domain} +short 2>/dev/null")
        dkim_records = [line.strip() for line in out.splitlines() if line.strip()]
        result["steps"]["dkim"] = {"found": len(dkim_records) > 0}

        dmarc_domain = f"_dmarc.{test_email.split('@')[1]}"
        rc, out, _ = await self._run_bash(f"dig TXT {dmarc_domain} +short 2>/dev/null")
        dmarc_records = [line.strip().strip('"') for line in out.splitlines() if "v=DMARC1" in line]
        result["steps"]["dmarc"] = {"found": len(dmarc_records) > 0, "records": dmarc_records}

        all_steps_ok = all(s.get("found", False) or s.get("reachable", False) for s in result["steps"].values() if isinstance(s, dict))
        result["overall"] = "ok" if all_steps_ok else "issues_found"

        return result

    async def auto_repair(self) -> dict:
        report: dict[str, Any] = {"actions_taken": [], "errors": []}

        svc_postfix = await self.postfix.get_status()
        if not svc_postfix:
            rc, out, _ = await self._run_bash("systemctl start postfix 2>/dev/null || sudo systemctl start postfix 2>/dev/null")
            if rc == 0:
                report["actions_taken"].append("postfix: started after being stopped")
                await asyncio.sleep(1)
                rc, out, _ = await self._run_bash("postfix check 2>&1")
                if rc != 0:
                    report["errors"].append(f"postfix: config error after start: {out.strip()[:200]}")
            else:
                report["errors"].append("postfix: failed to start")

        svc_dovecot = await self.dovecot.get_status()
        if not svc_dovecot:
            rc, out, _ = await self._run_bash("systemctl start dovecot 2>/dev/null || sudo systemctl start dovecot 2>/dev/null")
            if rc == 0:
                report["actions_taken"].append("dovecot: started after being stopped")
            else:
                report["errors"].append("dovecot: failed to start")

        rc, out, _ = await self._run_bash("systemctl is-active rspamd 2>/dev/null")
        if out.strip() != "active":
            rc, out, _ = await self._run_bash("systemctl start rspamd 2>/dev/null || sudo systemctl start rspamd 2>/dev/null")
            if rc == 0:
                report["actions_taken"].append("rspamd: started after being stopped")
            else:
                report["errors"].append("rspamd: failed to start")

        for port in REQUIRED_PORTS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                rc, out, _ = await self._run_bash(f"ss -tlnp | grep ':{port} '")
                if not out.strip():
                    report["errors"].append(f"port {port} ({REQUIRED_PORTS[port]}): not listening")
            sock.close()

        rc, out, _ = await self._run_bash("sudo postfix check 2>&1")
        if rc != 0:
            if "superuser" not in out.lower() and "reserved" not in out.lower():
                report["errors"].append(f"postfix: config check failed: {out.strip()[:200]}")

        return report
