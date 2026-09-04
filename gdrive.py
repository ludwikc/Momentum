# gdrive.py
# Minimal Google Drive helper for uploading voice recordings to a Shared Drive.
#
# A service account can only write to a *Shared Drive* (not a personal "My Drive").
# Configure via environment variables (see .env):
#   GDRIVE_SA_JSON  - absolute path to the service-account JSON key file
#   GDRIVE_FOLDER_ID - id of the destination folder inside the Shared Drive
#
# If either is unset, is_configured() returns False and the caller should fall
# back to keeping the recording locally.

import hashlib
import os
import logging

logger = logging.getLogger("momentum_bot.gdrive")

# drive.file is enough to create/manage files the service account itself uploads.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def is_configured() -> bool:
    """True only when both the key file and target folder are set."""
    sa_path = os.getenv("GDRIVE_SA_JSON")
    return bool(sa_path and os.path.exists(sa_path) and os.getenv("GDRIVE_FOLDER_ID"))


def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_path = os.getenv("GDRIVE_SA_JSON")
    if not sa_path or not os.path.exists(sa_path):
        raise RuntimeError(f"GDRIVE_SA_JSON not set or file missing: {sa_path!r}")

    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_file(local_path: str, name: str | None = None,
                mime_type: str = "audio/mpeg") -> dict:
    """Upload a file to the configured Shared Drive folder.

    Blocking (network + disk) — call via asyncio.to_thread from async code.
    Returns the created file resource:
        {"id": ..., "webViewLink": ..., "md5Checksum": ..., "size": ...}.
    md5Checksum is Drive's MD5 of the stored bytes — compare it against
    local_md5() to confirm the upload arrived intact before deleting the local copy.
    """
    from googleapiclient.http import MediaFileUpload

    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("GDRIVE_FOLDER_ID not set")

    service = _get_service()
    name = name or os.path.basename(local_path)
    metadata = {"name": name, "parents": [folder_id]}
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)

    file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink, md5Checksum, size",
        supportsAllDrives=True,  # required to write into a Shared Drive
    ).execute()

    logger.info("Uploaded %s to Drive (id=%s)", name, file.get("id"))
    return file


def find_files(name_contains: str, *, page_size: int = 50) -> list[dict]:
    """Files in Drive whose name contains the substring (only files this SA created).

    Blocking — call via asyncio.to_thread. Returns [{"id", "name", "webViewLink",
    "mimeType"}, ...] sorted by name. Escapes ' and \\ for the Drive query.
    """
    escaped = name_contains.replace("\\", "\\\\").replace("'", "\\'")
    service = _get_service()
    result = service.files().list(
        q=f"name contains '{escaped}' and trashed = false",
        fields="files(id, name, webViewLink, mimeType)",
        pageSize=page_size,
        orderBy="name",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return result.get("files", [])


def local_md5(path: str) -> str:
    """MD5 hex digest of a local file, matching Drive's md5Checksum field.

    Blocking (disk read) — call via asyncio.to_thread from async code.
    """
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
