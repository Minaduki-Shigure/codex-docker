#!/usr/bin/env python3
"""Resolve official inputs, then verify a complete Codex release package."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import urllib.request

BASE_TAG = "docker.io/library/node:24-bookworm-slim"
TARGETS = {
    "amd64": "x86_64-unknown-linux-musl",
    "arm64": "aarch64-unknown-linux-musl",
}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
RELEASE = re.compile(r"rust-v([0-9]+\.[0-9]+\.[0-9]+)\Z")


def read_release():
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "codex-docker"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "https://api.github.com/repos/openai/codex/releases/latest", headers=headers
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def release_inputs(release):
    tag = release["tag_name"]
    match = RELEASE.fullmatch(tag)
    if not match or release["draft"] or release["prerelease"]:
        raise ValueError("Expected an official stable Codex release")
    prefix = f"https://github.com/openai/codex/releases/download/{tag}/"
    assets = {asset["name"]: asset for asset in release["assets"]}
    packages = {}
    for arch, target in TARGETS.items():
        name = f"codex-package-{target}.tar.gz"
        packages[arch] = {}
        for key, filename in (("archive", name), ("signature", name + ".sigstore")):
            asset = assets[filename]
            if asset["browser_download_url"] != prefix + filename:
                raise ValueError("Unexpected release asset URL")
            if not DIGEST.fullmatch(asset.get("digest") or ""):
                raise ValueError("Release asset has no SHA-256 digest")
            packages[arch][key] = {
                "url": asset["browser_download_url"],
                "digest": asset["digest"],
            }
    return {
        "codex_version": match[1],
        "release_tag": tag,
        "packages": packages,
    }


def resolve(path):
    inputs = release_inputs(read_release())
    manifest = json.loads(subprocess.check_output(
        ["docker", "buildx", "imagetools", "inspect", BASE_TAG,
         "--format", "{{json .Manifest}}"], text=True
    ))
    digest = manifest["digest"]
    if not DIGEST.fullmatch(digest):
        raise ValueError("Invalid base image digest")
    platforms = {
        (m.get("platform", {}).get("os"), m.get("platform", {}).get("architecture"))
        for m in manifest["manifests"]
    }
    if not {("linux", arch) for arch in TARGETS}.issubset(platforms):
        raise ValueError("Base image must support both amd64 and arm64")
    inputs["base_image"] = f"{BASE_TAG}@{digest}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inputs, indent=2) + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for key in ("base_image", "codex_version", "release_tag"):
                output.write(f"{key}={inputs[key]}\n")
    print(f"Codex {inputs['codex_version']}; base {inputs['base_image']}")


def download(asset, destination):
    # Curl handles transient failures and host proxy settings. No tokens go to assets.
    subprocess.run([
        "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "3",
        "--proto", "=https", "--proto-redir", "=https",
        "--output", str(destination), asset["url"],
    ], check=True)
    with destination.open("rb") as stream:
        actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != asset["digest"]:
        raise ValueError(f"Checksum mismatch: {destination.name}")


def extract(archive, destination):
    # Python's data filter rejects traversal and links escaping the package root.
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as package:
        package.extractall(destination, filter="data")
    for name in ("codex", "codex-code-mode-host"):
        if not os.access(destination / "bin" / name, os.X_OK):
            raise ValueError(f"Missing executable in full package: {name}")


def fetch(path, arch):
    inputs = json.loads(path.read_text())
    tag = inputs["release_tag"]
    if not RELEASE.fullmatch(tag):
        raise ValueError("Invalid release tag")
    assets = inputs["packages"][arch]
    prefix = f"https://github.com/openai/codex/releases/download/{tag}/"
    for asset in assets.values():
        if not asset["url"].startswith(prefix) or not DIGEST.fullmatch(asset["digest"]):
            raise ValueError("Invalid locked asset")
    archive = path.parent / "codex.tar.gz"
    signature = path.parent / "codex.sigstore"
    download(assets["archive"], archive)
    download(assets["signature"], signature)
    identity = f"https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/{tag}"
    subprocess.run([
        "cosign", "verify-blob", "--bundle", str(signature),
        "--certificate-identity", identity,
        "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
        str(archive),
    ], check=True)
    extract(archive, path.parent / "package")
    print(f"Verified official Codex package for linux/{arch}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("resolve", "fetch"))
    parser.add_argument("--lock", type=Path, default=Path("dist/build-inputs.json"))
    parser.add_argument("--arch", choices=TARGETS)
    args = parser.parse_args()
    if args.command == "resolve":
        resolve(args.lock)
    elif args.arch:
        fetch(args.lock, args.arch)
    else:
        parser.error("fetch requires --arch")
