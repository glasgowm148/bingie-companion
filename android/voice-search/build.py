#!/usr/bin/env python3
"""Build the Kodi voice search helper APK (runs on the Mac; never contacts the TV).

    python android/voice-search/build.py [--sdk ~/Library/Android/sdk] [--out output/voice-search]

Needs Android build-tools 34.0.0 (aapt2, d8, zipalign, apksigner), platforms;android-30
(android.jar) and a JDK 11+ (javac --release 8). The signing key is created on first use in
~/Library/Application Support/KodiManager/kodivoice.jks with a random password next to it
(kodivoice.pass, mode 600); keep both, since an update must be signed with the same key.

Steps: aapt2 links the manifest against android.jar (no resources), javac compiles src/, d8
dexes it, the dex is added to the APK, zipalign aligns it and apksigner signs it (v2 + v3).
"""
import argparse
import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "kodivoice"
BUILD_TOOLS = "34.0.0"
PLATFORM = "android-30"
KEY_DIR = Path.home() / ".local/share/bingie-companion/signing"


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def keystore(keytool):
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    store, secret = KEY_DIR / (NAME + ".jks"), KEY_DIR / (NAME + ".pass")
    if not store.exists():
        password = secrets.token_urlsafe(24)
        secret.write_text(password)
        os.chmod(secret, 0o600)
        run(keytool, "-genkeypair", "-keystore", store, "-storepass:file", secret, "-keypass:file", secret,
            "-alias", NAME, "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000",
            "-dname", "CN=Kodi voice search, O=Bingie Companion")
        os.chmod(store, 0o600)
    return store, secret


def version_name():
    text = (HERE / "AndroidManifest.xml").read_text()
    return text.split('android:versionName="', 1)[1].split('"', 1)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sdk", type=Path, default=Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Library/Android/sdk"))))
    parser.add_argument("--java-home", type=Path, default=Path(os.environ.get("JAVA_HOME", "")) if os.environ.get("JAVA_HOME") else None)
    parser.add_argument("--out", type=Path, default=HERE.parents[1] / "output" / "voice-search")
    args = parser.parse_args(argv)
    tools = args.sdk / "build-tools" / BUILD_TOOLS
    android_jar = args.sdk / "platforms" / PLATFORM / "android.jar"
    for needed in (tools / "aapt2", tools / "d8", tools / "zipalign", tools / "apksigner", android_jar):
        if not needed.exists():
            sys.exit("missing %s" % needed)
    java_bin = (args.java_home / "bin") if args.java_home else None
    javac = (java_bin / "javac") if java_bin else shutil.which("javac")
    keytool = (java_bin / "keytool") if java_bin else shutil.which("keytool")
    env = dict(os.environ)
    if args.java_home:
        env["JAVA_HOME"] = str(args.java_home)
    args.out.mkdir(parents=True, exist_ok=True)
    apk = args.out / ("%s-%s.apk" % (NAME, version_name()))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "classes").mkdir()
        (tmp / "dex").mkdir()
        run(tools / "aapt2", "link", "-I", android_jar, "--manifest", HERE / "AndroidManifest.xml",
            "-o", tmp / "base.apk")
        sources = sorted(str(p) for p in (HERE / "src").rglob("*.java"))
        run(javac, "--release", "8", "-Xlint:-options", "-classpath", android_jar, "-d", tmp / "classes", *sources, env=env)
        classes = sorted(str(p) for p in (tmp / "classes").rglob("*.class"))
        run(tools / "d8", "--release", "--min-api", "26", "--lib", android_jar, "--output", tmp / "dex", *classes, env=env)
        with zipfile.ZipFile(tmp / "base.apk") as src, zipfile.ZipFile(tmp / "unsigned.apk", "w") as dst:
            for info in src.infolist():
                dst.writestr(info, src.read(info.filename))
            dex = zipfile.ZipInfo("classes.dex", date_time=(2026, 1, 1, 0, 0, 0))
            dex.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(dex, (tmp / "dex" / "classes.dex").read_bytes())
        run(tools / "zipalign", "-f", "-p", "4", tmp / "unsigned.apk", tmp / "aligned.apk")
        store, secret = keystore(keytool)
        run(tools / "apksigner", "sign", "--ks", store, "--ks-pass", "file:%s" % secret, "--ks-key-alias", NAME,
            "--v1-signing-enabled", "false", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
            "--out", apk, tmp / "aligned.apk", env=env)
        run(tools / "apksigner", "verify", "--verbose", apk, env=env)
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    (apk.parent / (apk.name + ".sha256")).write_text("%s  %s\n" % (digest, apk.name))
    print("%s\nsha256 %s" % (apk, digest))


if __name__ == "__main__":
    main()
