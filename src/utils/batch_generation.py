"""Input parsing and gateway requests for resilient batch image generation."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests


@dataclass(frozen=True)
class BatchTask:
    id: str
    prompt: str
    filename: str
    image: Path | None = None
    role: str | None = None


def _safe_png_filename(value: str, *, index: int) -> str:
    filename = Path(value)
    if filename.name != value:
        raise ValueError(f"task {index}: filename must not contain directories")
    if not filename.stem:
        raise ValueError(f"task {index}: filename must not be empty")
    return f"{filename.stem}.png"


def _task_from_mapping(raw: Any, *, index: int, base_dir: Path) -> BatchTask:
    if not isinstance(raw, dict):
        raise ValueError(f"task {index}: expected an object")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"task {index}: prompt must be a non-empty string")
    task_id = raw.get("id") or raw.get("assetId") or f"task-{index:03d}"
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"task {index}: id must be a non-empty string")
    filename = raw.get("filename") or raw.get("name") or task_id
    if not isinstance(filename, str):
        raise ValueError(f"task {index}: filename must be a string")
    image_value = raw.get("image") or raw.get("input_image")
    if image_value is not None and (not isinstance(image_value, str) or not image_value.strip()):
        raise ValueError(f"task {index}: image must be a non-empty string when provided")
    image = (base_dir / image_value).resolve() if image_value else None
    role = raw.get("role")
    if role is not None and not isinstance(role, str):
        raise ValueError(f"task {index}: role must be a string")
    return BatchTask(
        id=task_id.strip(),
        prompt=prompt.strip(),
        filename=_safe_png_filename(filename, index=index),
        image=image,
        role=role,
    )


def _validate_unique_tasks(tasks: list[BatchTask]) -> list[BatchTask]:
    ids = [task.id for task in tasks]
    filenames = [task.filename.casefold() for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Task IDs must be unique")
    if len(filenames) != len(set(filenames)):
        raise ValueError("Task filenames must be unique")
    return tasks


def load_batch_tasks(task_file: Path) -> list[BatchTask]:
    """Load plain text, JSONL, JSON task arrays, or legacy assets manifests."""
    try:
        text = task_file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"Could not read task file: {exc}") from exc

    suffix = task_file.suffix.lower()
    base_dir = task_file.parent
    if suffix in {".txt", ".prompt", ".prompts"}:
        prompts = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        return _validate_unique_tasks([BatchTask(f"task-{index:03d}", prompt, f"task-{index:03d}.png") for index, prompt in enumerate(prompts, start=1)])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if suffix == ".jsonl":
            tasks: list[BatchTask] = []
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    tasks.append(_task_from_mapping(json.loads(line), index=line_number, base_dir=base_dir))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"line {line_number}: invalid JSONL: {exc.msg}") from exc
            return _validate_unique_tasks(tasks)
        raise ValueError("Task file must be .txt, .jsonl, or valid JSON")

    raw_tasks = payload.get("assets") if isinstance(payload, dict) and "assets" in payload else payload
    if not isinstance(raw_tasks, list):
        raise ValueError("JSON task file must be an array or an object with an assets array")
    return _validate_unique_tasks([_task_from_mapping(raw, index=index, base_dir=base_dir) for index, raw in enumerate(raw_tasks, start=1)])


def with_default_image(tasks: Iterable[BatchTask], image: Path | None) -> list[BatchTask]:
    if image is None:
        return list(tasks)
    return [
        BatchTask(task.id, task.prompt, task.filename, image=task.image or image, role=task.role)
        for task in tasks
    ]


def command_line_tasks(prompts: list[str], *, image: Path | None) -> list[BatchTask]:
    return [
        BatchTask(
            id=f"prompt-{index:03d}",
            prompt=prompt.strip(),
            filename=f"prompt-{index:03d}.png",
            image=image,
        )
        for index, prompt in enumerate(prompts, start=1)
        if prompt.strip()
    ]


def select_tasks(
    tasks: Iterable[BatchTask],
    *,
    roles: set[str],
    ids: set[str],
    skip_existing_in: Path | None,
    completed_ids: set[str],
) -> list[BatchTask]:
    selected: list[BatchTask] = []
    for task in tasks:
        if roles and task.role not in roles:
            continue
        if ids and task.id not in ids:
            continue
        if task.id in completed_ids:
            continue
        if skip_existing_in and (skip_existing_in / task.filename).exists():
            continue
        selected.append(task)
    return selected


def completed_task_ids(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()
    completed: set[str] = set()
    for line in state_file.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("status") == "succeeded" and isinstance(event.get("id"), str):
            completed.add(event["id"])
    return completed


def append_state(state_file: Path, *, task: BatchTask, status: str, **details: Any) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    event = {"id": task.id, "filename": task.filename, "status": status, "at": int(time.time()), **details}
    with state_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _image_mime_type(image_path: Path) -> str:
    with image_path.open("rb") as source:
        signature = source.read(12)
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if signature.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        return "image/webp"
    raise RuntimeError(f"reference image is not a supported PNG, JPEG, or WebP file: {image_path}")


def _decode_response(response: requests.Response) -> bytes:
    if response.status_code != 200:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"gateway returned HTTP {response.status_code}: {detail[:300]}")
    try:
        return base64.b64decode(response.json()["data"][0]["b64_json"], validate=True)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"gateway returned invalid image data: {exc}") from exc


def generate_task(task: BatchTask, *, api_url: str, api_token: str | None, timeout_seconds: int) -> bytes:
    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
    try:
        if task.image:
            if not task.image.is_file():
                raise RuntimeError(f"reference image does not exist: {task.image}")
            mime_type = _image_mime_type(task.image)
            with task.image.open("rb") as reference:
                response = requests.post(
                    api_url.rstrip("/").replace("/generations", "/edits"),
                    headers=headers,
                    data={"model": "gemini-web-image", "prompt": task.prompt, "n": "1", "size": "auto", "response_format": "b64_json"},
                    files={"image": (task.image.name, reference, mime_type)},
                    timeout=timeout_seconds,
                )
        else:
            response = requests.post(
                api_url,
                headers={**headers, "Content-Type": "application/json"},
                json={"model": "gemini-web-image", "prompt": task.prompt, "n": 1, "size": "auto", "response_format": "b64_json"},
                timeout=timeout_seconds,
            )
    except requests.RequestException as exc:
        raise RuntimeError(f"gateway request failed: {exc}") from exc
    return _decode_response(response)


def retry_generate_task(task: BatchTask, *, api_url: str, api_token: str | None, timeout_seconds: int, attempts: int, retry_delay_seconds: float) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return generate_task(task, api_url=api_url, api_token=api_token, timeout_seconds=timeout_seconds)
        except RuntimeError as exc:
            last_error = exc
            if attempt < attempts:
                print(f"  Retry {attempt + 1}/{attempts} in {retry_delay_seconds:g}s: {exc}", flush=True)
                time.sleep(retry_delay_seconds)
    raise RuntimeError(f"all {attempts} attempt(s) failed: {last_error}") from last_error
