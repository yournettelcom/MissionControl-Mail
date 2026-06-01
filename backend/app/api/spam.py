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
import subprocess
import json
import os
import re
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user, require_admin
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/spam", tags=["Spam Filtering"])


async def _run_rspamd_cmd(cmd: list) -> str:
    try:
        result = await asyncio.to_thread(lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=15))
        return result.stdout.strip()
    except Exception as e:
        return str(e)


@router.get("/stats")
async def spam_stats(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    output = await _run_rspamd_cmd(["rspamc", "stat"])
    lines = output.split("\n")
    stats = {
        "total_scanned": 0,
        "ham": 0,
        "spam": 0,
        "spam_percent": 0.0,
        "actions": {},
        "spam_found": 0,
        "ham_found": 0,
        "phishing_found": 0,
        "false_positives": 0,
        "score_distribution": [
            {"range": "0-1", "count": 0},
            {"range": "1-2", "count": 0},
            {"range": "2-3", "count": 0},
            {"range": "3-5", "count": 0},
            {"range": "5-7", "count": 0},
            {"range": "7-9", "count": 0},
            {"range": "9-10", "count": 0},
        ],
        "daily_trend": [
            {"day": "Seg", "spam": 0, "ham": 0},
            {"day": "Ter", "spam": 0, "ham": 0},
            {"day": "Qua", "spam": 0, "ham": 0},
            {"day": "Qui", "spam": 0, "ham": 0},
            {"day": "Sex", "spam": 0, "ham": 0},
            {"day": "Sab", "spam": 0, "ham": 0},
            {"day": "Dom", "spam": 0, "ham": 0},
        ],
        "last_training": None,
    }
    for line in lines:
        low = line.strip().lower()
        if "messages scanned" in low:
            parts = line.split(":")
            if len(parts) > 1:
                try:
                    stats["total_scanned"] = int(parts[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
        elif low.startswith("messages treated as spam"):
            parts = line.split(":")
            if len(parts) > 1:
                try:
                    val = parts[1].strip().split(",")[0].strip()
                    stats["spam_found"] = stats["spam"] = int(val)
                except (ValueError, IndexError):
                    pass
        elif low.startswith("messages treated as ham"):
            parts = line.split(":")
            if len(parts) > 1:
                try:
                    val = parts[1].strip().split(",")[0].strip()
                    stats["ham_found"] = stats["ham"] = int(val)
                except (ValueError, IndexError):
                    pass
    total = stats["ham"] + stats["spam"]
    if total > 0:
        stats["spam_percent"] = round(stats["spam"] / total * 100, 2)
    return stats


@router.post("/scan")
async def scan_message(
    message_id: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    output = await _run_rspamd_cmd(["rspamc", "symbols", message_id])
    return {"message_id": message_id, "result": output, "timestamp": datetime.now().isoformat()}


@router.get("/quarantine")
async def list_quarantine(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    quarantine_dir = "/var/lib/rspamd/quarantine"
    items = []
    try:
        if await asyncio.to_thread(os.path.exists, quarantine_dir):
            all_files = await asyncio.to_thread(os.listdir, quarantine_dir)
            files = sorted(all_files, reverse=True)[skip:skip + limit]
            for f in files:
                fpath = os.path.join(quarantine_dir, f)
                stat = await asyncio.to_thread(os.stat, fpath)
                items.append({
                    "id": f,
                    "filename": f,
                    "from": "",
                    "to": "",
                    "subject": "",
                    "date": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "score": 0,
                    "path": fpath,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                })
    except Exception as e:
        logger.warning(f"Could not read quarantine: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read quarantine: {str(e)}")
    return {"total": len(items), "messages": items, "items": items}


@router.put("/quarantine/{message_id}/release")
async def release_quarantine(
    message_id: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    output = await _run_rspamd_cmd(["rspamc", "release", message_id])
    return {"message_id": message_id, "status": "released", "output": output}


@router.put("/quarantine/{message_id}/delete")
async def delete_quarantine(
    message_id: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    quarantine_dir = "/var/lib/rspamd/quarantine"
    try:
        if not re.match(r"^[a-zA-Z0-9_.-]+$", message_id):
            raise HTTPException(status_code=400, detail="Invalid message_id format")
        fpath = os.path.realpath(os.path.join(quarantine_dir, message_id))
        if not fpath.startswith(os.path.realpath(quarantine_dir)):
            raise HTTPException(status_code=400, detail="Invalid path")
        if await asyncio.to_thread(os.path.exists, fpath):
            await asyncio.to_thread(os.remove, fpath)
            return {"message_id": message_id, "status": "deleted"}
        else:
            raise HTTPException(status_code=404, detail="Message not found in quarantine")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/train")
async def train_filter(
    request: Request,
    message_path: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    if classification is None:
        try:
            body = await request.json()
            if isinstance(body, dict):
                classification = body.get("type") or body.get("classification", "spam")
                if not message_path:
                    files = body.get("files") or []
                    message_path = files[0] if files else None
        except Exception:
            classification = "spam"
    if not message_path:
        return {"classification": classification, "message_path": None, "output": "No message path provided", "status": "skipped"}
    if classification == "spam":
        output = await _run_rspamd_cmd(["rspamc", "learn_spam", message_path])
    else:
        output = await _run_rspamd_cmd(["rspamc", "learn_ham", message_path])
    return {"classification": classification, "message_path": message_path, "output": output}


@router.post("/train/upload")
async def train_filter_upload(
    classification: str = Query("spam", pattern="^(ham|spam)$"),
    files: List[UploadFile] = File(...),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in files:
            safe_name = os.path.basename(f.filename or "email.eml")
            fpath = os.path.join(tmpdir, safe_name)
            fpath = os.path.realpath(fpath)
            if not fpath.startswith(os.path.realpath(tmpdir)):
                results.append({"filename": f.filename, "error": "Invalid filename"})
                continue
            content = await f.read()
            with open(fpath, "wb") as out:
                out.write(content)
            if classification == "spam":
                output = await _run_rspamd_cmd(["rspamc", "learn_spam", fpath])
            else:
                output = await _run_rspamd_cmd(["rspamc", "learn_ham", fpath])
            results.append({"filename": f.filename, "output": output})
    return {"classification": classification, "results": results}


@router.get("/settings")
async def get_spam_settings(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    config_paths = [
        "/etc/rspamd/rspamd.conf",
        "/etc/rspamd/rspamd.conf.local",
    ]
    configs = {}
    for path in config_paths:
        try:
            content = await asyncio.to_thread(lambda: open(path, "r").read())
            configs[path] = content
        except FileNotFoundError:
            continue
        except PermissionError:
            configs[path] = "Permission denied"
    return {
        "configs": configs,
        "threshold": 5,
        "provider": "minimax",
        "api_key": "",
        "model": "minimax-spam-detection-v1",
    }


@router.put("/settings")
async def update_spam_settings(
    request: Request,
    config_key: Optional[str] = Query(None),
    config_value: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    try:
        body = await request.json()
        if isinstance(body, dict):
            for k, v in body.items():
                config_key, config_value = k, str(v)
    except Exception:
        pass
    if not config_key or not config_value:
        raise HTTPException(status_code=400, detail="config_key and config_value are required")
    config_path = "/etc/rspamd/rspamd.conf.local"
    try:
        await asyncio.to_thread(lambda: open(config_path, "a").write(f"\n{config_key} = {config_value};\n"))
        await _run_rspamd_cmd(["systemctl", "reload", "rspamd"])
        return {"key": config_key, "value": config_value, "message": "Spam settings updated"}
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
