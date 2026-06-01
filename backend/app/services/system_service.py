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
import re
import shutil
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

SERVICES = [
    {"name": "postfix", "display": "Postfix"},
    {"name": "dovecot", "display": "Dovecot"},
    {"name": "roundcube", "display": "Roundcube"},
    {"name": "nginx", "display": "Nginx"},
    {"name": "mysql", "display": "MySQL/MariaDB"},
    {"name": "redis-server", "display": "Redis"},
    {"name": "rspamd", "display": "Rspamd"},
    {"name": "opendkim", "display": "OpenDKIM"},
    {"name": "clamav-daemon", "display": "ClamAV"},
    {"name": "amavis", "display": "Amavis"},
]


class SystemService:
    async def _run_cmd(self, cmd: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def _run_bash(self, cmd: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def get_system_info(self) -> dict:
        info: dict[str, Any] = {}
        try:
            rc, out, err = await self._run_cmd(["hostname"])
            info["hostname"] = out.strip() if rc == 0 else "unknown"
        except Exception:
            info["hostname"] = "unknown"

        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            info["os"] = line.split("=", 1)[1].strip().strip('"')
                            break
            else:
                info["os"] = os.uname().sysname
        except Exception:
            info["os"] = "unknown"

        try:
            rc, out, err = await self._run_cmd(["uname", "-r"])
            info["kernel"] = out.strip() if rc == 0 else "unknown"
        except Exception:
            info["kernel"] = "unknown"

        try:
            rc, out, err = await self._run_cmd(["uptime", "-p"])
            info["uptime"] = out.strip() if rc == 0 else "unknown"
        except Exception:
            info["uptime"] = "unknown"

        try:
            with open("/proc/cpuinfo") as f:
                content = f.read()
            model_match = re.search(r"model name\s+:\s+(.+)", content)
            info["cpu_model"] = model_match.group(1).strip() if model_match else "unknown"
            count_match = re.search(r"^processor\s+:\s+\d+", content, re.MULTILINE)
            info["cpu_cores"] = content.count("processor\t:") if count_match else os.cpu_count() or 0
        except Exception:
            info["cpu_model"] = "unknown"
            info["cpu_cores"] = os.cpu_count() or 0

        mem = await self.get_memory_usage()
        info["total_ram"] = mem.get("total", 0)
        info["used_ram"] = mem.get("used", 0)

        disk = await self.get_disk_usage("/")
        info["total_disk"] = disk.get("total", 0)
        info["used_disk"] = disk.get("used", 0)

        return info

    async def get_cpu_usage(self) -> float:
        try:
            rc, out, err = await self._run_bash(
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1"
            )
            if rc == 0 and out.strip():
                return float(out.strip())
            with open("/proc/stat") as f:
                line = f.readline()
            parts = line.split()
            if len(parts) >= 5:
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                total = user + nice + system + idle
                return round(((total - idle) / total) * 100, 1)
        except Exception as e:
            logger.error("Error getting CPU usage: %s", e)
        return 0.0

    async def get_memory_usage(self) -> dict:
        result: dict = {"total": 0, "used": 0, "free": 0, "percent": 0}
        try:
            rc, out, err = await self._run_cmd(["free", "-b"])
            if rc == 0:
                lines = out.splitlines()
                for line in lines:
                    if line.startswith("Mem:"):
                        parts = line.split()
                        if len(parts) >= 3:
                            result["total"] = int(parts[1])
                            result["free"] = int(parts[3])
                            result["used"] = result["total"] - result["free"]
                            if result["total"] > 0:
                                result["percent"] = round(
                                    (result["used"] / result["total"]) * 100, 1
                                )
                        break
        except Exception as e:
            logger.error("Error getting memory usage: %s", e)
        return result

    async def get_disk_usage(self, path: str = "/") -> dict:
        result: dict = {"total": 0, "used": 0, "free": 0, "percent": 0}
        try:
            usage = shutil.disk_usage(path)
            result["total"] = usage.total
            result["used"] = usage.used
            result["free"] = usage.free
            if usage.total > 0:
                result["percent"] = round((usage.used / usage.total) * 100, 1)
        except Exception as e:
            logger.error("Error getting disk usage: %s", e)
        return result

    async def get_per_domain_disk_usage(self) -> list:
        domains: list[dict] = []
        vmail_base = "/var/vmail"
        try:
            if not os.path.exists(vmail_base):
                return domains
            for item in os.listdir(vmail_base):
                domain_path = os.path.join(vmail_base, item)
                if os.path.isdir(domain_path):
                    total_size = 0
                    mailbox_count = 0
                    for root, dirs, files in os.walk(domain_path):
                        for f in files:
                            try:
                                total_size += os.path.getsize(os.path.join(root, f))
                            except OSError:
                                pass
                        maildirs = [d for d in dirs if d.endswith("/Maildir") or "Maildir" in d]
                        mailbox_count += len(maildirs) if maildirs else 0

                    domain_info = {
                        "domain": item,
                        "path": domain_path,
                        "size_bytes": total_size,
                        "size_human": self._bytes_to_human(total_size),
                        "mailbox_count": mailbox_count or len(
                            [d for d in os.listdir(domain_path)
                             if os.path.isdir(os.path.join(domain_path, d))]
                        ),
                    }
                    domains.append(domain_info)
        except Exception as e:
            logger.error("Error getting per-domain disk usage: %s", e)
        return sorted(domains, key=lambda d: d["size_bytes"], reverse=True)

    async def get_per_mailbox_disk_usage(self, domain: str) -> list:
        mailboxes: list[dict] = []
        domain_path = f"/var/vmail/{domain}"
        try:
            if not os.path.exists(domain_path):
                return mailboxes
            for item in os.listdir(domain_path):
                mailbox_path = os.path.join(domain_path, item)
                if os.path.isdir(mailbox_path):
                    total_size = 0
                    for root, dirs, files in os.walk(mailbox_path):
                        for f in files:
                            try:
                                total_size += os.path.getsize(os.path.join(root, f))
                            except OSError:
                                pass
                    email = f"{item}@{domain}"
                    mailboxes.append({
                        "email": email,
                        "path": mailbox_path,
                        "size_bytes": total_size,
                        "size_human": self._bytes_to_human(total_size),
                    })
        except Exception as e:
            logger.error("Error getting mailbox disk usage: %s", e)
        return sorted(mailboxes, key=lambda m: m["size_bytes"], reverse=True)

    def _bytes_to_human(self, bytes_val: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"

    async def get_service_status(self, service_name: str) -> dict:
        result: dict = {
            "name": service_name,
            "active": False,
            "running": False,
            "enabled": False,
        }
        try:
            rc, out, err = await self._run_cmd([
                "systemctl", "is-active", service_name
            ])
            result["active"] = out.strip() == "active"
            result["running"] = out.strip() == "active"

            rc2, out2, err2 = await self._run_cmd([
                "systemctl", "is-enabled", service_name
            ])
            result["enabled"] = out2.strip() == "enabled"
        except Exception as e:
            logger.error("Error getting service status: %s", e)
        return result

    async def get_all_services_status(self) -> list:
        statuses = []
        for svc in SERVICES:
            status = await self.get_service_status(svc["name"])
            status["display"] = svc["display"]
            statuses.append(status)
        return statuses

    async def control_service(
        self, service_name: str, action: str
    ) -> bool:
        try:
            rc, out, err = await self._run_cmd([
                "systemctl", action, service_name
            ])
            if rc != 0:
                logger.error("Failed to %s %s: %s", action, service_name, err)
                return False
            return True
        except Exception as e:
            logger.error("Error controlling service %s: %s", service_name, e)
            return False

    async def get_logs(self, service: str, lines: int = 100) -> list:
        try:
            rc, out, err = await self._run_bash(
                f"journalctl -u {service} --no-pager -n {lines} 2>/dev/null || "
                f"tail -n {lines} /var/log/{service}.log 2>/dev/null || echo ''"
            )
            if rc != 0:
                return []
            return [line for line in out.splitlines() if line.strip()]
        except Exception as e:
            logger.error("Error reading logs for %s: %s", service, e)
            return []

    async def get_network_usage(self) -> dict:
        result: dict = {
            "bytes_sent": 0,
            "bytes_recv": 0,
            "interfaces": [],
        }
        try:
            rc, out, err = await self._run_bash(
                "cat /proc/net/dev | tail -n +3"
            )
            if rc == 0:
                for line in out.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 10:
                        iface = parts[0].rstrip(":")
                        recv_bytes = int(parts[1])
                        sent_bytes = int(parts[9])
                        if iface != "lo":
                            result["bytes_recv"] += recv_bytes
                            result["bytes_sent"] += sent_bytes
                            result["interfaces"].append({
                                "name": iface,
                                "sent": sent_bytes,
                                "recv": recv_bytes,
                            })
        except Exception as e:
            logger.error("Error getting network usage: %s", e)
        return result

    async def get_uptime(self) -> str:
        try:
            rc, out, err = await self._run_cmd(["uptime", "-p"])
            if rc == 0 and out.strip():
                return out.strip()
            with open("/proc/uptime") as f:
                uptime_seconds = float(f.read().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            parts = []
            if days > 0:
                parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            return "up " + ", ".join(parts) if parts else "up < 1 minute"
        except Exception as e:
            logger.error("Error getting uptime: %s", e)
            return "unknown"
