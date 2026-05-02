#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import hashlib
import html
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
APKPURE_ARCH = "arm64-v8a"
APKPURE_SV = os.environ.get("APKPURE_SV", "23")
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


def read_url(url: str, *, accept: str | None = None, use_token: bool = False) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request(url, accept=accept, use_token=use_token)) as response:
                return response.read()
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise BuildError(f"Could not read {url}")


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
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    tmp.replace(output)


def download_github_asset(release: dict[str, Any], patterns: list[str], output: Path) -> str:
    url, name = asset_download_url(release, patterns)
    download_file(url, output)
    return name


def fetch_apkpure_page() -> str:
    return read_url(APKPURE_PAGE).decode("utf-8", errors="replace")


def extract_apkpure_info(page: str) -> dict[str, str]:
    unescaped = html.unescape(page)
    version_code = ""
    version_name = ""

    link_rx = re.compile(r"https://d\.apkpure\.com/b/XAPK/[^\"'\s<>]+")
    for raw_link in link_rx.findall(unescaped):
        parsed = urllib.parse.urlparse(raw_link)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith(f"/{PACKAGE_NAME}") and query.get("nc", [""])[0] == APKPURE_ARCH:
            version_code = query.get("versionCode", [""])[0]
            version_name = query.get("version", [""])[0]
            break

    if not version_code:
        arm64_block = re.search(
            rf"(?s){re.escape(APKPURE_ARCH)}.*?(\d+(?:\.\d+)+)\((\d+)\)XAPK",
            unescaped,
        )
        if arm64_block:
            version_name, version_code = arm64_block.groups()

    if not version_code:
        generic = re.search(r"versionCode=(\d+)", unescaped)
        if generic:
            version_code = generic.group(1)

    if not version_name and version_code:
        by_code = re.search(rf"(\d+(?:\.\d+)+)\({re.escape(version_code)}\)", unescaped)
        if by_code:
            version_name = by_code.group(1)

    if not version_name:
        title = re.search(r"Download APK\s+(\d+(?:\.\d+)+)", unescaped)
        if title:
            version_name = title.group(1)

    if not version_code:
        raise BuildError("Could not extract APKPure versionCode for the arm64-v8a XAPK")
    if not version_name:
        version_name = version_code

    download_url = (
        f"https://d.apkpure.com/b/XAPK/{PACKAGE_NAME}"
        f"?versionCode={version_code}&nc={APKPURE_ARCH}&sv={APKPURE_SV}"
    )
    return {
        "version_name": version_name,
        "version_code": version_code,
        "download_url": download_url,
    }


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
    apkeditor_release: dict[str, Any],
    patches_asset: str,
    cli_asset: str,
    apkeditor_asset: str,
    app_info: dict[str, str],
    keystore_source: str,
) -> dict[str, str]:
    unclone_hash = sha256(unclone_apk)
    clone_hash = sha256(clone_apk)
    title = f"{app_info['version_name']} ({patches_release['tag_name']})"
    signer = SIGNER_NAME if keystore_source != "morphe-default" else "Morphe"
    alias = KEYSTORE_ALIAS if keystore_source != "morphe-default" else "Morphe"
    notes = "\n".join(
        [
            f"# {title}",
            "",
            f"- DCInside: `{app_info['version_name']}` (`{app_info['version_code']}`, `{APKPURE_ARCH}`)",
            f"- Patches: [{patches_release['tag_name']}]({patches_release['html_url']}) (`{patches_asset}`)",
            f"- Morphe CLI: [{cli_release['tag_name']}]({cli_release['html_url']}) (`{cli_asset}`)",
            f"- APKEditor: [{apkeditor_release['tag_name']}]({apkeditor_release['html_url']}) (`{apkeditor_asset}`)",
            f"- APKPure URL: `{app_info['download_url']}`",
            f"- Unclone APK: `{unclone_apk.name}`",
            f"- Unclone SHA-256: `{unclone_hash}`",
            f"- Clone APK: `{clone_apk.name}`",
            f"- Clone SHA-256: `{clone_hash}`",
            "",
            patches_release.get("body") or "",
        ]
    ).rstrip() + "\n"

    metadata = {
        "app": {
            "name": "DCInside",
            "package": PACKAGE_NAME,
            "version_name": app_info["version_name"],
            "version_code": app_info["version_code"],
            "architecture": APKPURE_ARCH,
            "source_url": app_info["download_url"],
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
        "apkeditor": {
            "repo": APKEDITOR_REPO,
            "tag": apkeditor_release["tag_name"],
            "asset": apkeditor_asset,
            "html_url": apkeditor_release["html_url"],
        },
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
    apkeditor_release = latest_release(APKEDITOR_REPO, include_prereleases=False)

    patches_file = bins / "patches.mpp"
    cli_file = bins / "morphe-cli.jar"
    apkeditor_file = bins / "apkeditor.jar"
    patches_asset = download_github_asset(patches_release, [r"^patches.*\.mpp$"], patches_file)
    cli_asset = download_github_asset(cli_release, [r"^morphe-cli.*-all\.jar$"], cli_file)
    apkeditor_asset = download_github_asset(apkeditor_release, [r"^APKEditor.*\.jar$"], apkeditor_file)
    keystore, keystore_source = prepare_keystore(work)

    app_info = extract_apkpure_info(fetch_apkpure_page())
    last_commit = patches_commit(patches_release)
    version_part = file_part(app_info["version_name"])
    xapk = work / f"{PACKAGE_NAME}-{app_info['version_code']}-{APKPURE_ARCH}.xapk"
    merged = work / f"{PACKAGE_NAME}-{app_info['version_code']}-{APKPURE_ARCH}-merged.apk"
    unclone_apk = dist / f"dcinside-{version_part}-revanced-{last_commit}-unclone.apk"
    clone_apk = dist / f"dcinside-{version_part}-revanced-{last_commit}-clone.apk"
    metadata_path = dist / "metadata.json"

    download_file(app_info["download_url"], xapk, referer=APKPURE_PAGE)
    merge_xapk(apkeditor_file, xapk, merged)
    log("Building Unclone APK...")
    patch_apk(cli_file, patches_file, merged, unclone_apk, keystore)
    log(f"Unclone APK generated: {unclone_apk}")

    log("Building Clone APK...")
    patch_apk(
        cli_file,
        patches_file,
        merged,
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
