#!/usr/bin/env python3
"""Veröffentlicht eine geprüfte APK als Release dieses Update-Repos (optional auch im Appstore).

  python tools/publish_release.py PFAD/zur/app.apk "Was ist neu" [--appstore] [--dry-run]

Vor dem Veröffentlichen wird die APK geprüft, damit nie ein falscher Build beim In-App-Updater
oder im Appstore landet:
  * Paketname, versionName (x.y.z) und versionCode stehen in der APK selbst; der versionCode muss
    major*10000 + minor*100 + patch sein
  * die APK ist nicht debuggable
  * apksigner bestätigt die Signatur UND der Signer ist genau der private Release-Schlüssel
    (SIGNER_SHA256 unten) - nie ein Debug-Schlüssel
  * die Version ist neuer als das aktuelle Release dieses Repos
Danach entstehen SHA256SUMS.txt und android-update.json (die der In-App-Updater liest) und das
GitHub-Release v<version>. Mit --appstore landet die APK zusätzlich in incoming-apks/ von Liams
Appstore (danach der Appstore-Sitzung sagen: "Schau im apk-Ordner nach, es gibt ein Update.").
--dry-run macht nur die Prüfungen und veröffentlicht nichts.

Voraussetzungen: Python 3.8+, Android-SDK build-tools (aapt2, apksigner), git, `gh auth login`.
Nach einer Schlüsselrotation muss die Signer-Prüfung (signer_digests) angepasst werden.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# ---- nur dieser Block unterscheidet die Update-Repos ---------------------------------------
REPO = "obipepenobi-hub/mio2-updater"
APP_NAME = "Mio²"
APK_ASSET = "Mio2.apk"                # Dateiname im Release; der In-App-Updater lädt diese Datei
PACKAGE = "com.liamkkm.mio"           # applicationId der App - ändert sich nie
SIGNER_SHA256 = "cb7262ff13a69140945a4539d94e7305ec32c755ea2ab5f8489253911a581450"
STORE_APK_NAME = "mio2-{version}.apk"  # Dateiname in liams-appstore/incoming-apks/
# ----------------------------------------------------------------------------------------------
STORE_REPO = "obipepenobi-hub/liams-appstore"

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def fail(message):
    print(f"\nABBRUCH: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)


def version_tuple(text):
    parts = text.strip().lstrip("v").split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def find_build_tools():
    roots = [
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"),
        str(Path.home() / "Android" / "Sdk"),
    ]
    wanted = os.environ.get("BUILD_TOOLS_VERSION")
    for root in roots:
        if not root:
            continue
        base = Path(root) / "build-tools"
        if not base.is_dir():
            continue
        versions = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: version_tuple(d.name), reverse=True)
        if wanted:
            versions = [d for d in versions if d.name == wanted]
        if versions:
            return versions[0]
    fail("Android build-tools nicht gefunden. ANDROID_HOME setzen (oder BUILD_TOOLS_VERSION prüfen).")


def tool(build_tools, name):
    for suffix in (".exe", ".bat", ""):
        candidate = build_tools / (name + suffix)
        if candidate.is_file():
            return str(candidate)
    fail(f"{name} fehlt in {build_tools}")


def inspect_apk(apk, aapt2):
    result = run([aapt2, "dump", "badging", apk])
    if result.returncode != 0:
        fail(f"aapt2 konnte die APK nicht lesen:\n{result.stderr or result.stdout}")
    text = result.stdout
    match = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", text)
    if not match:
        fail("Paketname und Version sind aus der APK nicht lesbar.")
    return match.group(1), int(match.group(2)), match.group(3), "application-debuggable" in text


def signer_digests(apk, apksigner):
    result = run([apksigner, "verify", "--print-certs", apk])
    text = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        fail(f"apksigner: Die Signatur der APK ist ungültig oder fehlt:\n{text.strip()}")
    return {d.lower() for d in re.findall(r"certificate SHA-256 digest: ([0-9a-fA-F]{64})", text)}


def latest_release_tag():
    result = run(["gh", "release", "view", "--repo", REPO, "--json", "tagName"])
    if result.returncode == 0:
        return json.loads(result.stdout)["tagName"]
    error = (result.stderr or "").lower()
    if "not found" in error and "could not resolve" not in error:
        return None  # das Repo hat noch kein Release
    fail(f"Die Releases von {REPO} sind nicht lesbar (gh angemeldet? Repo vorhanden?):\n{result.stderr.strip()}")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def published_info_matches(version, sha256):
    url = f"https://github.com/{REPO}/releases/latest/download/android-update.json"
    for _ in range(6):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                info = json.loads(response.read().decode("utf-8"))
            if info.get("version") == version and info.get("sha256") == sha256:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def upload_to_appstore(apk, version):
    work = Path(tempfile.mkdtemp(prefix="appstore-"))
    checkout = work / "store"
    cloned = run(["git", "clone", "--quiet", "--depth", "1", f"https://github.com/{STORE_REPO}.git", str(checkout)])
    if cloned.returncode != 0:
        fail(f"Der Appstore ließ sich nicht klonen:\n{cloned.stderr.strip()}")
    target = checkout / "incoming-apks" / STORE_APK_NAME.format(version=version)
    shutil.copyfile(apk, target)
    identity = []
    if not run(["git", "config", "user.name"], cwd=checkout).stdout.strip():
        identity = ["-c", "user.name=liam", "-c", "user.email=obipepenobi-hub@users.noreply.github.com"]
    run(["git", "add", str(target.relative_to(checkout))], cwd=checkout)
    committed = run(["git", *identity, "commit", "--quiet", "-m", f"Add {APP_NAME} {version} release APK"], cwd=checkout)
    if committed.returncode != 0:
        fail(f"Commit im Appstore-Klon fehlgeschlagen:\n{committed.stderr.strip() or committed.stdout.strip()}")
    for _ in range(3):
        pushed = run(["git", "push", "--quiet", "origin", "HEAD:main"], cwd=checkout)
        if pushed.returncode == 0:
            shutil.rmtree(work, ignore_errors=True)
            return
        run(["git", *identity, "pull", "--rebase", "--quiet", "origin", "main"], cwd=checkout)
    fail(f"Push in den Appstore fehlgeschlagen:\n{pushed.stderr.strip()}\n(Klon zum Nachsehen: {checkout})")


def main():
    parser = argparse.ArgumentParser(description="Prüft eine APK und veröffentlicht sie als Release dieses Update-Repos.")
    parser.add_argument("apk", help="Pfad zur signierten Release-APK")
    parser.add_argument("notes", nargs="?", default="Verbesserungen und Fehlerbehebungen", help="Was ist neu")
    parser.add_argument("--appstore", action="store_true", help="APK zusätzlich in liams-appstore/incoming-apks/ ablegen")
    parser.add_argument("--dry-run", action="store_true", help="nur prüfen, nichts veröffentlichen")
    args = parser.parse_args()

    apk = Path(args.apk).resolve()
    if not apk.is_file():
        fail(f"APK nicht gefunden: {apk}")
    for needed in ("gh", "git"):
        if not shutil.which(needed):
            fail(f"'{needed}' ist nicht installiert oder nicht im PATH.")

    build_tools = find_build_tools()
    package, version_code, version, debuggable = inspect_apk(str(apk), tool(build_tools, "aapt2"))
    print(f"APK:        {apk.name} ({apk.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Paket:      {package}")
    print(f"Version:    {version} (versionCode {version_code})")

    if package != PACKAGE:
        fail(f"Paketname {package} passt nicht zu {PACKAGE}. Die applicationId darf sich nie ändern - "
             f"oder PACKAGE oben im Skript ist noch nicht auf die echte applicationId gesetzt.")
    if debuggable:
        fail("Die APK ist debuggable - das ist kein Release-Build.")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"versionName muss x.y.z sein, ist aber '{version}'.")
    major, minor, patch = (int(p) for p in version.split("."))
    if version_code != major * 10000 + minor * 100 + patch:
        fail(f"versionCode {version_code} passt nicht zu {version} (erwartet {major * 10000 + minor * 100 + patch}).")

    digests = signer_digests(str(apk), tool(build_tools, "apksigner"))
    if digests != {SIGNER_SHA256}:
        fail("Die APK ist nicht mit dem privaten Release-Schlüssel signiert.\n"
             f"  erwartet: {SIGNER_SHA256}\n  gefunden: {', '.join(sorted(digests)) or '-'}")
    print(f"Signatur:   OK (Zertifikat {SIGNER_SHA256[:12]}...)")

    latest = latest_release_tag()
    if latest is not None and version_tuple(version) <= version_tuple(latest):
        fail(f"Version {version} ist nicht neuer als das aktuelle Release {latest}.")
    print(f"Vorher:     {latest or 'noch kein Release'}")

    work = Path(tempfile.mkdtemp(prefix="publish-"))
    try:
        asset = work / APK_ASSET
        shutil.copyfile(apk, asset)
        sha256 = sha256_of(asset)
        size = asset.stat().st_size
        sums = work / "SHA256SUMS.txt"
        sums.write_text(f"{sha256}  {APK_ASSET}\n", encoding="utf-8", newline="\n")
        meta = work / "android-update.json"
        meta.write_text(json.dumps({
            "version": version,
            "versionCode": version_code,
            "url": f"https://github.com/{REPO}/releases/download/v{version}/{APK_ASSET}",
            "size": size,
            "sha256": sha256,
        }, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"SHA-256:    {sha256}")

        if args.dry_run:
            print(f"\nDRY-RUN: alles geprüft. Würde Release v{version} in {REPO} anlegen"
                  + (" und die APK in den Appstore legen." if args.appstore else "."))
            return

        created = run(["gh", "release", "create", f"v{version}", str(asset), str(sums), str(meta),
                       "--repo", REPO, "--title", f"{APP_NAME} {version}", "--notes", args.notes, "--latest"])
        if created.returncode != 0:
            fail(f"Release konnte nicht angelegt werden:\n{created.stderr.strip()}")
        print(f"\nRelease v{version} angelegt: https://github.com/{REPO}/releases/tag/v{version}")
        if published_info_matches(version, sha256):
            print("Kontrolle:  android-update.json im neuesten Release stimmt.")
        else:
            print("WARNUNG: android-update.json war nach 30 s noch nicht abrufbar/gleich - später prüfen.")

        if args.appstore:
            upload_to_appstore(str(apk), version)
            print(f"Appstore:   {STORE_APK_NAME.format(version=version)} liegt in {STORE_REPO}/incoming-apks/.")
            print('            Jetzt der Appstore-Sitzung sagen: "Schau im apk-Ordner nach, es gibt ein Update."')
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
