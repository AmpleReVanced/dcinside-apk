#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


PATCHES_REPO = "AmpleReVanced/revanced-patches"
CLI_REPO = "MorpheApp/morphe-cli"
APKEDITOR_REPO = "REAndroid/APKEditor"
PACKAGE_NAME = "com.dcinside.app.android"
APKPURE_PAGE = (
    "https://apkpure.com/kr/%EB%94%94%EC%8B%9C%EC%9D%B8%EC%82%AC%EC%9D%B4%EB%93%9C-dcinside/"
    f"{PACKAGE_NAME}/download"
)
APKPURE_APP_VERSION_API = "https://api.pureapk.com/m/v3/cms/app_version"
APKPURE_ARCH = "arm64-v8a"
APKPURE_HL = os.environ.get("APKPURE_HL", "en-US")
APKPURE_X_CV = os.environ.get("APKPURE_X_CV", "3172501")
APKPURE_X_SV = os.environ.get("APKPURE_X_SV", "29")
APKPURE_X_ABIS = os.environ.get("APKPURE_X_ABIS", APKPURE_ARCH)
APKPURE_X_GP = os.environ.get("APKPURE_X_GP", "1")
KEYSTORE_ALIAS = os.environ.get("KEYSTORE_ALIAS") or os.environ.get("SIGNING_KEYSTORE_ALIAS") or "revanced"
KEYSTORE_PASSWORD = os.environ.get("KEYSTORE_PASSWORD") or os.environ.get("SIGNING_KEYSTORE_PASSWORD") or "tlqkftorl01!"
SIGNER_NAME = os.environ.get("SIGNER_NAME") or KEYSTORE_ALIAS
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class BuildError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[dcinside] {message}", flush=True)


def token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def request(
    url: str,
    *,
    accept: str | None = None,
    referer: str | None = None,
    use_token: bool = False,
) -> urllib.request.Request:
    headers = {
        "User-Agent": UA,
        "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-CH-UA": '"Not/A)Brand";v="8", "Chromium";v="126"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    if use_token and token():
        headers["Authorization"] = f"Bearer {token()}"
    return urllib.request.Request(url, headers=headers)


def curl_headers(*, accept: str | None = None, referer: str | None = None, use_token: bool = False) -> list[str]:
    headers = [
        "Accept: " + (accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Accept-Language: ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control: no-cache",
        "Pragma: no-cache",
        'Sec-CH-UA: "Not/A)Brand";v="8", "Chromium";v="126"',
        "Sec-CH-UA-Mobile: ?0",
        'Sec-CH-UA-Platform: "Windows"',
        "Sec-Fetch-Dest: document",
        "Sec-Fetch-Mode: navigate",
        "Sec-Fetch-Site: none",
        "Sec-Fetch-User: ?1",
        "Upgrade-Insecure-Requests: 1",
    ]
    if referer:
        headers.append(f"Referer: {referer}")
    if use_token and token():
        headers.append(f"Authorization: Bearer {token()}")
    return headers


def curl_cmd(url: str, *, accept: str | None = None, referer: str | None = None, use_token: bool = False) -> list[str]:
    cmd = [
        "curl",
        "-fsSL",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "20",
        "--max-time",
        "180",
        "-A",
        UA,
    ]
    for header in curl_headers(accept=accept, referer=referer, use_token=use_token):
        cmd.extend(["-H", header])
    cmd.append(url)
    return cmd


def curl_read(url: str, *, accept: str | None = None, referer: str | None = None, use_token: bool = False) -> bytes:
    return subprocess.check_output(curl_cmd(url, accept=accept, referer=referer, use_token=use_token))


def read_url(url: str, *, accept: str | None = None, use_token: bool = False) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request(url, accept=accept, use_token=use_token)) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last_error = exc
            time.sleep(2**attempt)
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(2**attempt)
    log(f"urllib failed for {url}; retrying with curl ({last_error})")
    return curl_read(url, accept=accept, use_token=use_token)


def download_with_curl(
    url: str,
    output: Path,
    *,
    accept: str | None = None,
    referer: str | None = None,
    use_token: bool = False,
) -> None:
    cmd = curl_cmd(url, accept=accept, referer=referer, use_token=use_token)
    cmd.extend(["-o", str(output)])
    run(cmd)


def github_api(path: str) -> Any:
    if path.startswith("https://"):
        url = path
    else:
        url = f"https://api.github.com{path}"
    data = read_url(url, accept="application/vnd.github+json", use_token=True)
    return json.loads(data.decode("utf-8"))


def latest_release(repo: str, *, include_prereleases: bool) -> dict[str, Any]:
    if include_prereleases:
        releases = github_api(f"/repos/{repo}/releases?per_page=20")
        for release in releases:
            if not release.get("draft"):
                return release
        raise BuildError(f"No non-draft releases found for {repo}")
    return github_api(f"/repos/{repo}/releases/latest")


def release_by_tag(repo: str, tag: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(tag, safe="")
    return github_api(f"/repos/{repo}/releases/tags/{encoded}")


def current_repo_release_exists(tag: str) -> bool:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return False
    try:
        release_by_tag(repo, tag)
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def resolve_patches_release(tag_name: str | None) -> dict[str, Any]:
    if tag_name:
        return release_by_tag(PATCHES_REPO, tag_name)
    return latest_release(PATCHES_REPO, include_prereleases=True)


def write_outputs(path: str | None, values: dict[str, str]) -> None:
    if not path:
        for key, value in values.items():
            print(f"{key}={value}")
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            if "\n" in value:
                delim = f"EOF_{key}_{hashlib.sha256(value.encode()).hexdigest()[:12]}"
                fh.write(f"{key}<<{delim}\n{value}\n{delim}\n")
            else:
                fh.write(f"{key}={value}\n")


def check(args: argparse.Namespace) -> None:
    release = resolve_patches_release(args.patches_tag)
    tag = release["tag_name"]
    exists = current_repo_release_exists(tag)
    should_build = args.force or not exists
    write_outputs(
        args.github_output,
        {
            "should_build": str(should_build).lower(),
            "patches_tag": tag,
            "prerelease": str(bool(release.get("prerelease"))).lower(),
            "upstream_url": release["html_url"],
            "reason": "force" if args.force else ("new" if not exists else "already-built"),
        },
    )
    log(f"upstream={tag} prerelease={release.get('prerelease')} should_build={should_build}")


def asset_download_url(release: dict[str, Any], patterns: list[str]) -> tuple[str, str]:
    assets = release.get("assets", [])
    for pattern in patterns:
        rx = re.compile(pattern, re.IGNORECASE)
        for asset in assets:
            name = asset.get("name", "")
            if rx.search(name):
                return asset["browser_download_url"], name
    names = ", ".join(asset.get("name", "") for asset in assets)
    raise BuildError(f"No matching asset on {release['html_url']}. Assets: {names}")


def download_file(url: str, output: Path, *, referer: str | None = None, use_token: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.stat().st_size > 0:
        log(f"{output} already exists")
        return

    tmp = output.with_suffix(output.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    log(f"downloading {url}")
    try:
        with urllib.request.urlopen(
            request(url, accept="application/octet-stream", referer=referer, use_token=use_token),
            timeout=120,
        ) as response:
            with open(tmp, "wb") as fh:
                shutil.copyfileobj(response, fh)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        log(f"urllib failed for {url}; retrying with curl ({exc})")
        download_with_curl(
            url,
            tmp,
            accept="application/octet-stream",
            referer=referer,
            use_token=use_token,
        )
    tmp.replace(output)


def download_github_asset(release: dict[str, Any], patterns: list[str], output: Path) -> str:
    url, name = asset_download_url(release, patterns)
    download_file(url, output)
    return name


DOWNLOAD_RE = re.compile(
    rb"(X?APKJ).."
    rb"(https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}"
    rb"\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_+.~#?&//=]*)"
)


def apkpure_api_url() -> str:
    query = urllib.parse.urlencode({"hl": APKPURE_HL, "package_name": PACKAGE_NAME})
    return f"{APKPURE_APP_VERSION_API}?{query}"


def apkpure_api_headers() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Accept": "application/octet-stream,*/*;q=0.8",
        "Accept-Encoding": "identity",
        "x-cv": APKPURE_X_CV,
        "x-sv": APKPURE_X_SV,
        "x-abis": APKPURE_X_ABIS,
        "x-gp": APKPURE_X_GP,
    }


def fetch_apkpure_app_version() -> bytes:
    url = apkpure_api_url()
    log(f"fetching APKPure app_version API: {url}")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers=apkpure_api_headers())
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
            if not data:
                raise BuildError("APKPure app_version API returned an empty response")
            log(f"APKPure app_version API fetched {len(data)} bytes on attempt {attempt}/3")
            return data
        except Exception as exc:
            last_error = exc
            log(f"APKPure app_version API attempt {attempt}/3 failed: {type(exc).__name__}: {exc}")
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))

    raise BuildError(f"APKPure app_version API failed: {last_error}")


def clean_meta_value(value: str) -> str:
    return re.split(r"[\x00-\x1f\x7f]", value, maxsplit=1)[0]


def decode_url_meta(url: str) -> dict[str, str]:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    c_value = query.get("c", [""])[0]
    parts = c_value.split("|")
    if len(parts) < 3:
        return {}

    payload_b64 = parts[2]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        payload = base64.urlsafe_b64decode(payload_b64).decode("utf-8", errors="replace")
    except Exception:
        return {}

    return {key: clean_meta_value(value) for key, value in urllib.parse.parse_qsl(payload)}


def extract_apkpure_api_info(data: bytes) -> dict[str, str]:
    candidates: list[dict[str, str]] = []
    for match in DOWNLOAD_RE.finditer(data):
        marker = match.group(1).decode("ascii")
        url = match.group(2).decode("ascii", errors="replace")
        artifact_type = "xapk" if marker == "XAPKJ" else "apk"
        meta = decode_url_meta(url)
        version_name = meta.get("vn") or ""
        version_code = meta.get("vc") or ""
        meta_type = meta.get("t") or artifact_type

        if not version_name or not version_code:
            continue
        if meta_type and meta_type != artifact_type:
            continue

        candidates.append(
            {
                "version_name": version_name,
                "version_code": version_code,
                "download_url": url,
                "artifact_type": artifact_type,
                "source": "apkpure-api",
                "source_page": apkpure_api_url(),
                "web_page": APKPURE_PAGE,
                "architecture": APKPURE_X_ABIS,
                "size": meta.get("s") or "0",
            }
        )

    if not candidates:
        raise BuildError("Could not extract an APKPure APK/XAPK download URL from app_version API")

    latest = candidates[0]
    latest_candidates = [
        candidate
        for candidate in candidates
        if candidate["version_name"] == latest["version_name"]
        and candidate["version_code"] == latest["version_code"]
    ]
    artifact_type = "xapk" if any(candidate["artifact_type"] == "xapk" for candidate in latest_candidates) else "apk"
    latest_candidates = [candidate for candidate in latest_candidates if candidate["artifact_type"] == artifact_type]
    latest_candidates.sort(key=lambda candidate: int(candidate.get("size") or "0"), reverse=True)
    return latest_candidates[0]


def artifact_has_requested_abi(path: Path) -> bool:
    if APKPURE_ARCH not in APKPURE_X_ABIS:
        return True

    wanted = f"config.{APKPURE_ARCH.replace('-', '_')}.apk"
    split_abis = {
        "config.arm64_v8a.apk",
        "config.armeabi_v7a.apk",
        "config.armeabi.apk",
        "config.x86.apk",
        "config.x86_64.apk",
    }
    with zipfile.ZipFile(path) as archive:
        names = {Path(name).name for name in archive.namelist()}

    if wanted in names:
        return True
    if names & split_abis:
        return False
    return True


def fetch_apkpure_info() -> dict[str, str]:
    return extract_apkpure_api_info(fetch_apkpure_app_version())


def download_apkpure_artifact(app_info: dict[str, str], output: Path) -> None:
    url = app_info["download_url"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.stat().st_size > 0:
        log(f"{output} already exists")
        return

    log(f"downloading APKPure artifact: {url}")
    download_file(url, output, referer=APKPURE_PAGE)
    if output.stat().st_size == 0:
        output.unlink()
        raise BuildError(f"APKPure artifact download is empty: {output}")
    if not zipfile.is_zipfile(output):
        output.unlink()
        raise BuildError(f"APKPure artifact is not a valid APK/XAPK zip: {output}")
    if app_info["artifact_type"] == "xapk" and not artifact_has_requested_abi(output):
        output.unlink()
        raise BuildError(f"APKPure XAPK does not contain {APKPURE_ARCH}: {output}")


def run(cmd: list[str]) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def patches_commit(release: dict[str, Any]) -> str:
    target = str(release.get("target_commitish") or release.get("tag_name") or "")
    if re.fullmatch(r"[0-9a-fA-F]{8,40}", target):
        return target[:8].lower()

    for ref in (target, release.get("tag_name")):
        if not ref:
            continue
        encoded = urllib.parse.quote(str(ref), safe="")
        try:
            commit = github_api(f"/repos/{PATCHES_REPO}/commits/{encoded}")
        except urllib.error.HTTPError:
            continue
        sha = str(commit.get("sha") or "")
        if len(sha) >= 8:
            return sha[:8].lower()

    raise BuildError(f"Could not resolve patches commit for {release.get('tag_name')}")


def file_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unknown"


def prepare_keystore(work: Path) -> tuple[Path | None, str]:
    encoded = os.environ.get("SIGNING_KEYSTORE_BASE64") or os.environ.get("KEYSTORE_BASE64")
    if encoded:
        keystore_path = work / "signing" / "revanced.keystore"
        keystore_path.parent.mkdir(parents=True, exist_ok=True)
        keystore_path.write_bytes(base64.b64decode("".join(encoded.split())))
        return keystore_path, "secret"

    project_keystore = Path("revanced.keystore")
    if project_keystore.exists():
        return project_keystore, "file"

    return None, "morphe-default"


def merge_xapk(apkeditor: Path, xapk: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.stat().st_size > 0:
        log(f"{output} already exists")
        return
    run(["java", "-jar", str(apkeditor), "merge", "-i", str(xapk), "-o", str(output), "-clean-meta", "-f"])


def patch_apk(
    cli: Path,
    patches: Path,
    input_apk: Path,
    output_apk: Path,
    keystore: Path | None,
    extra_args: list[str] | None = None,
) -> None:
    if output_apk.exists():
        output_apk.unlink()

    cmd = [
        "java",
        "-jar",
        str(cli),
        "patch",
        "--patches",
        str(patches),
        "--purge",
        "-o",
        str(output_apk),
    ]
    if keystore:
        cmd.extend(
            [
                "--keystore",
                str(keystore),
                "--keystore-entry-password",
                KEYSTORE_PASSWORD,
                "--keystore-password",
                KEYSTORE_PASSWORD,
                "--signer",
                SIGNER_NAME,
                "--keystore-entry-alias",
                KEYSTORE_ALIAS,
            ]
        )
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(input_apk))
    run(cmd)

    if not output_apk.exists():
        raise BuildError(f"Morphe CLI did not create {output_apk}")

    generated_keystore = output_apk.with_suffix(".keystore")
    if generated_keystore.exists():
        generated_keystore.unlink()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_files(
    *,
    dist: Path,
    unclone_apk: Path,
    clone_apk: Path,
    metadata_path: Path,
    patches_release: dict[str, Any],
    cli_release: dict[str, Any],
    apkeditor_release: dict[str, Any] | None,
    patches_asset: str,
    cli_asset: str,
    apkeditor_asset: str | None,
    app_info: dict[str, str],
    input_kind: str,
    keystore_source: str,
) -> dict[str, str]:
    unclone_hash = sha256(unclone_apk)
    clone_hash = sha256(clone_apk)
    title = f"{app_info['version_name']} ({patches_release['tag_name']})"
    signer = SIGNER_NAME if keystore_source != "morphe-default" else "Morphe"
    alias = KEYSTORE_ALIAS if keystore_source != "morphe-default" else "Morphe"
    notes_lines = [
        f"# {title}",
        "",
        f"- DCInside: `{app_info['version_name']}` (`{app_info['version_code']}`, `{app_info['architecture']}`, `{input_kind.upper()}`)",
        f"- Source: [APKPure]({app_info.get('source_page', APKPURE_PAGE)})",
        f"- Patches: [{patches_release['tag_name']}]({patches_release['html_url']}) (`{patches_asset}`)",
        f"- Morphe CLI: [{cli_release['tag_name']}]({cli_release['html_url']}) (`{cli_asset}`)",
    ]
    if apkeditor_release and apkeditor_asset:
        notes_lines.append(
            f"- APKEditor: [{apkeditor_release['tag_name']}]({apkeditor_release['html_url']}) (`{apkeditor_asset}`)"
        )
    notes_lines.extend(
        [
            f"- APKPure URL: `{app_info['download_url']}`",
            f"- Unclone APK: `{unclone_apk.name}`",
            f"- Unclone SHA-256: `{unclone_hash}`",
            f"- Clone APK: `{clone_apk.name}`",
            f"- Clone SHA-256: `{clone_hash}`",
            "",
            patches_release.get("body") or "",
        ]
    )
    notes = "\n".join(notes_lines).rstrip() + "\n"

    apkeditor_metadata: dict[str, Any] = {"used": False}
    if apkeditor_release and apkeditor_asset:
        apkeditor_metadata = {
            "used": True,
            "repo": APKEDITOR_REPO,
            "tag": apkeditor_release["tag_name"],
            "asset": apkeditor_asset,
            "html_url": apkeditor_release["html_url"],
        }

    metadata = {
        "app": {
            "name": "DCInside",
            "package": PACKAGE_NAME,
            "version_name": app_info["version_name"],
            "version_code": app_info["version_code"],
            "architecture": app_info["architecture"],
            "source": app_info.get("source", "apkpure"),
            "source_page": app_info.get("source_page", APKPURE_PAGE),
            "web_page": app_info.get("web_page", APKPURE_PAGE),
            "download_url": app_info["download_url"],
            "input_type": input_kind,
        },
        "patches": {
            "repo": PATCHES_REPO,
            "tag": patches_release["tag_name"],
            "prerelease": bool(patches_release.get("prerelease")),
            "asset": patches_asset,
            "html_url": patches_release["html_url"],
        },
        "morphe_cli": {
            "repo": CLI_REPO,
            "tag": cli_release["tag_name"],
            "asset": cli_asset,
            "html_url": cli_release["html_url"],
        },
        "apkeditor": apkeditor_metadata,
        "artifacts": {
            "unclone": {
                "file": unclone_apk.name,
                "sha256": unclone_hash,
            },
            "clone": {
                "file": clone_apk.name,
                "sha256": clone_hash,
            },
        },
        "signing": {
            "keystore_source": keystore_source,
            "alias": alias,
            "signer": signer,
        },
    }

    notes_path = dist / "RELEASE_NOTES.md"
    notes_path.write_text(notes, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "release_title": title,
        "release_notes": str(notes_path),
        "metadata": str(metadata_path),
        "unclone_apk": str(unclone_apk),
        "clone_apk": str(clone_apk),
    }


def build(args: argparse.Namespace) -> None:
    work = Path(args.work_dir)
    dist = Path(args.dist_dir)
    bins = work / "bins"
    work.mkdir(parents=True, exist_ok=True)
    dist.mkdir(parents=True, exist_ok=True)

    patches_release = resolve_patches_release(args.patches_tag)
    cli_release = latest_release(CLI_REPO, include_prereleases=False)

    app_info = fetch_apkpure_info()
    artifact_type = app_info["artifact_type"]
    log(
        f"Using latest APKPure API {artifact_type.upper()} {app_info['architecture']} release: "
        f"version={app_info['version_name']} versionCode={app_info['version_code']}"
    )

    patches_file = bins / "patches.mpp"
    cli_file = bins / "morphe-cli.jar"
    apkeditor_file = bins / "apkeditor.jar"
    patches_asset = download_github_asset(patches_release, [r"^patches.*\.mpp$"], patches_file)
    cli_asset = download_github_asset(cli_release, [r"^morphe-cli.*-all\.jar$"], cli_file)
    apkeditor_release = latest_release(APKEDITOR_REPO, include_prereleases=False) if artifact_type == "xapk" else None
    apkeditor_asset = (
        download_github_asset(apkeditor_release, [r"^APKEditor.*\.jar$"], apkeditor_file)
        if apkeditor_release
        else None
    )
    keystore, keystore_source = prepare_keystore(work)

    last_commit = patches_commit(patches_release)
    version_part = file_part(app_info["version_name"])
    artifact = work / f"{PACKAGE_NAME}-{app_info['version_code']}-{app_info['architecture']}.{artifact_type}"
    merged = work / f"{PACKAGE_NAME}-{app_info['version_code']}-{app_info['architecture']}-merged.apk"
    unclone_apk = dist / f"dcinside-{version_part}-revanced-{last_commit}-unclone.apk"
    clone_apk = dist / f"dcinside-{version_part}-revanced-{last_commit}-clone.apk"
    metadata_path = dist / "metadata.json"

    download_apkpure_artifact(app_info, artifact)
    input_apk = artifact
    if artifact_type == "xapk":
        merge_xapk(apkeditor_file, artifact, merged)
        input_apk = merged

    log("Building Unclone APK...")
    patch_apk(cli_file, patches_file, input_apk, unclone_apk, keystore)
    log(f"Unclone APK generated: {unclone_apk}")

    log("Building Clone APK...")
    patch_apk(
        cli_file,
        patches_file,
        input_apk,
        clone_apk,
        keystore,
        [
            "-e",
            "Change package name",
            "-OupdateProviders=true",
            "-OupdatePermissions=true",
            "-e",
            "Custom Branding",
            "-OcustomName=DC ReVanced",
            "-OcustomIcon=Bundled",
        ],
    )
    log(f"Clone APK generated: {clone_apk}")

    outputs = write_release_files(
        dist=dist,
        unclone_apk=unclone_apk,
        clone_apk=clone_apk,
        metadata_path=metadata_path,
        patches_release=patches_release,
        cli_release=cli_release,
        apkeditor_release=apkeditor_release,
        patches_asset=patches_asset,
        cli_asset=cli_asset,
        apkeditor_asset=apkeditor_asset,
        app_info=app_info,
        input_kind=artifact_type,
        keystore_source=keystore_source,
    )
    outputs.update(
        {
            "patches_tag": patches_release["tag_name"],
            "prerelease": str(bool(patches_release.get("prerelease"))).lower(),
            "app_version": app_info["version_name"],
            "app_version_code": app_info["version_code"],
            "last_commit": last_commit,
        }
    )
    write_outputs(args.github_output, outputs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build patched DCInside APK releases")
    sub = parser.add_subparsers(dest="command", required=True)

    check_parser = sub.add_parser("check", help="Check whether the latest upstream patches release needs a build")
    check_parser.add_argument("--patches-tag", default=None, help="Use a specific AmpleReVanced patches tag")
    check_parser.add_argument("--force", action="store_true", help="Build even if this repository already has the release")
    check_parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    check_parser.set_defaults(func=check)

    build_parser = sub.add_parser("build", help="Download, merge, patch, and prepare release artifacts")
    build_parser.add_argument("--patches-tag", default=None, help="Use a specific AmpleReVanced patches tag")
    build_parser.add_argument("--work-dir", default="work")
    build_parser.add_argument("--dist-dir", default="dist")
    build_parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    build_parser.set_defaults(func=build)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
