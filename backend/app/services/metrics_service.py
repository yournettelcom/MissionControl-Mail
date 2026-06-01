# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from .system_service import SystemService

logger = logging.getLogger(__name__)

MAIL_LOG = "/var/log/mail.log"


class MetricsService:
    def __init__(self):
        self.system_service = SystemService()

    async def get_current_metrics(self) -> dict:
        metrics: dict[str, Any] = {
            "cpu": {},
            "memory": {},
            "disk": {},
            "network": {},
            "services": [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            cpu_tasks = [self.system_service.get_cpu_usage()]
            mem_tasks = [self.system_service.get_memory_usage()]
            disk_tasks = [self.system_service.get_disk_usage("/")]
            net_tasks = [self.system_service.get_network_usage()]
            svc_tasks = [self.system_service.get_all_services_status()]

            cpu_result = await cpu_tasks[0]
            mem_result = await mem_tasks[0]
            disk_result = await disk_tasks[0]
            net_result = await net_tasks[0]
            svc_result = await svc_tasks[0]

            metrics["cpu"] = {"percent": cpu_result}
            metrics["memory"] = mem_result
            metrics["disk"] = disk_result
            metrics["network"] = net_result
            metrics["services"] = svc_result

        except Exception as e:
            logger.error("Error getting current metrics: %s", e)
        return metrics

    async def get_traffic_stats(self) -> dict:
        stats: dict[str, Any] = {
            "sent_count": 0,
            "received_count": 0,
            "last_hour": {"sent": 0, "received": 0},
            "today": {"sent": 0, "received": 0},
            "this_week": {"sent": 0, "received": 0},
        }
        try:
            if not os.path.exists(MAIL_LOG):
                return stats

            rc, out, err = await self._run_bash(
                f"tail -n 50000 {MAIL_LOG} 2>/dev/null || echo ''"
            )
            if rc != 0:
                return stats

            now = datetime.utcnow()
            hour_ago = now - timedelta(hours=1)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = now - timedelta(days=now.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

            for line in out.splitlines():
                if "postfix/smtpd" in line and "client=" in line:
                    stats["received_count"] += 1
                elif "postfix/smtp" in line and "status=sent" in line:
                    stats["sent_count"] += 1

                timestamp_match = re.match(
                    r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line
                )
                if timestamp_match:
                    try:
                        log_time = datetime.strptime(
                            f"{now.year} {timestamp_match.group(1)}",
                            "%Y %b %d %H:%M:%S",
                        )
                    except ValueError:
                        continue

                    if log_time > hour_ago:
                        if "postfix/smtpd" in line and "client=" in line:
                            stats["last_hour"]["received"] += 1
                        elif "postfix/smtp" in line and "status=sent" in line:
                            stats["last_hour"]["sent"] += 1

                    if log_time > today_start:
                        if "postfix/smtpd" in line and "client=" in line:
                            stats["today"]["received"] += 1
                        elif "postfix/smtp" in line and "status=sent" in line:
                            stats["today"]["sent"] += 1

                    if log_time > week_start:
                        if "postfix/smtpd" in line and "client=" in line:
                            stats["this_week"]["received"] += 1
                        elif "postfix/smtp" in line and "status=sent" in line:
                            stats["this_week"]["sent"] += 1

        except Exception as e:
            logger.error("Error parsing traffic stats: %s", e)
        return stats

    async def get_queue_history(self) -> list:
        history: list[dict] = []
        try:
            audit_log = "/var/log/mail.log.1"
            log_files = [MAIL_LOG]
            if os.path.exists(audit_log):
                log_files.append(audit_log)

            for log_file in log_files:
                if not os.path.exists(log_file):
                    continue
                rc, out, err = await self._run_bash(
                    f"grep 'postfix/qmgr' {log_file} 2>/dev/null || echo ''"
                )
                if rc != 0 or not out.strip():
                    continue

                hourly_counts: dict[str, dict] = {}
                for line in out.splitlines():
                    ts_match = re.match(
                        r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2})", line
                    )
                    if not ts_match:
                        continue
                    hour_key = ts_match.group(1)
                    if hour_key not in hourly_counts:
                        hourly_counts[hour_key] = {
                            "active": 0,
                            "deferred": 0,
                            "removed": 0,
                        }
                    if "removed" in line:
                        hourly_counts[hour_key]["removed"] += 1
                    elif "deferred" in line:
                        hourly_counts[hour_key]["deferred"] += 1
                    else:
                        hourly_counts[hour_key]["active"] += 1

                for hour_key, counts in sorted(hourly_counts.items()):
                    entry = {
                        "timestamp": f"2025 {hour_key}",
                        "queue_size": counts["active"],
                        "deferred": counts["deferred"],
                        "removed": counts["removed"],
                    }
                    history.append(entry)
        except Exception as e:
            logger.error("Error getting queue history: %s", e)
        return history

    async def _run_bash(self, cmd: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()
