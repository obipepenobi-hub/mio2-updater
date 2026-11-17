# Anleitung: Mio² über das Update-Repo ausliefern und in Liams Appstore aufnehmen

Für die Claude-Sitzung, die an Mio² arbeitet, und für Liam. Stand: 17.11.2026.

## Kurz gesagt

- Neue Versionen von Mio² erscheinen künftig in diesem **Update-Repo** (`obipepenobi-hub/mio2-updater`,
  öffentlich, nur Releases). Der Programmcode bleibt in `obipepenobi-hub/mio2-app`.
- Die App prüft hier auf Updates, lädt die APK, vergleicht die SHA-256-Prüfsumme und übergibt sie dem
  System-Installer.
- Jede Version geht zusätzlich in **Liams Appstore** (Ordner `incoming-apks/`). Für das allererste
  Listing braucht der Store einmalig eine neue Store-Version (Signer-Pinning), siehe Abschnitt 6.

## 1. Eckdaten

| | |
|---|---|
| App | Mio² (Web-App, als Android-WebView-App verpackt) |
| Paketname | `com.liamkkm.mio` – **nie ändern**, sonst ist es für Android eine andere App |
| Code-Repo | `obipepenobi-hub/mio2-app` (öffentlich) |
| Update-Repo | `obipepenobi-hub/mio2-updater` (öffentlich, nur Releases) |
| Dateien pro Release | `Mio2.apk`, `SHA256SUMS.txt`, `android-update.json` |
| Version | Datei `VERSION` (x.y.z) im Code-Repo · Tag `vX.Y.Z` · `versionCode = major*10000 + minor*100 + patch` |
| Signierschlüssel | der bisherige private Schlüssel `android/keystore/mio2.jks` – bleibt wie er ist, nie ins Git |
| Zertifikat (SHA-256) | `cb7262ff13a69140945a4539d94e7305ec32c755ea2ab5f8489253911a581450` |
| Sicherungen des Schlüssels | `D:\Backups\mio2-signing\` und `G:\Backups\mio2-signing\` |
| Lokaler Klon dieses Repos | `F:\claude programmiren\mio2-updater` |

## 2. So entsteht ein Release (nach der Umstellung)

1. `VERSION` hochzählen und die APK mit dem privaten Schlüssel bauen (das macht `release.py` schon).
2. Im lokalen Klon dieses Repos ausführen:

   ```
   python tools/publish_release.py PFAD/zur/Mio2.apk "Was ist neu" --appstore
   ```

   Das Skript prüft die APK, **bevor** etwas veröffentlicht wird: Paketname, Version (x.y.z, versionCode passt),
   nicht debuggable, Signatur gültig **und** exakt der Schlüssel aus der Tabelle oben, Version neuer als das
   letzte Release. Dann legt es `SHA256SUMS.txt` und `android-update.json` an, erstellt das Release `vX.Y.Z`
   und legt die APK als `mio2-X.Y.Z.apk` in `liams-appstore/incoming-apks/`.
   Mit `--dry-run` wird nur geprüft, mit `--appstore` weggelassen bleibt der Appstore unberührt.
3. Danach der Appstore-Sitzung sagen: **„Schau im apk-Ordner nach, es gibt ein Update.“**

Voraussetzungen: Python 3.8+, Android-SDK build-tools, git, `gh auth login` (alles auf Liams PC vorhanden).

## 3. Umstellung von `mio2-app` auf `mio2-updater` (einmalig)

Installierte Apps (bis 1.0.4) fragen nur die Releases von `mio2-app` ab. Damit sie das Umstellungs-Update
finden, gilt genau diese Reihenfolge:

1. Updater im Code ändern (Abschnitt 4) und als **1.0.5** bauen.
2. 1.0.5 **zuerst in `mio2-app`** veröffentlichen (die Brücke, wie bisher mit `gh release create`, Datei `Mio2.apk`),
   **danach** mit dem Skript aus Abschnitt 2 in `mio2-updater`.
3. Ab 1.0.6 nur noch in `mio2-updater` veröffentlichen.
4. `mio2-app` erst dann privat stellen o. Ä., wenn alle Geräte mit Mio² mindestens 1.0.5 haben – sonst finden alte
   Apps nie wieder ein Update.

## 4. Anforderungen an den Updater (`Updater.kt`)

Der vorhandene `Updater.kt` ist die Grundlage. Er soll danach:

1. **Quelle:** `https://github.com/obipepenobi-hub/mio2-updater/releases/latest/download/android-update.json`
   lesen (kein API-Limit). Inhalt: `version`, `versionCode`, `url`, `size`, `sha256`.
   Antwort 404 (noch kein Release) heißt „kein Update“, kein Fehlerdialog.
2. Nur dann ein Update anbieten, wenn `versionCode` im JSON größer ist als die installierte
   (`packageManager.getPackageInfo(packageName, 0).longVersionCode`).
3. **Download-Adresse prüfen** (sie kommt aus dem Netz, ist also nicht vertrauenswürdig): `https`, Host `github.com`,
   Pfad beginnt mit `/obipepenobi-hub/mio2-updater/releases/download/`, kein `..`, kein Port, keine Zugangsdaten.
   Nach Weiterleitungen muss der Host `github.com` oder `*.githubusercontent.com` sein.
   Vorlage: `UpdateUrlPolicy.kt` im Repo `obipepenobi-hub/impulskauf-stopper`.
4. In `cacheDir/updates/` speichern (nie auf externen Speicher), alte Dateien vorher löschen, Größenlimit
   (z. B. 150 MB), Abbruch bei mehr Bytes als angekündigt.
5. **SHA-256 prüfen:** Prüfsumme der heruntergeladenen Datei == `sha256` aus dem JSON, sonst Datei löschen und eine
   verständliche Meldung zeigen.
6. **Vor dem Installer** prüfen, dass Paketname und Signer der heruntergeladenen APK zur installierten App passen
   (`getPackageArchiveInfo(..., GET_SIGNING_CERTIFICATES)`, vor Android 9 `GET_SIGNATURES`); Vorlage:
   `UpdateInstaller.signatureAcceptable` im Impulskauf-Stopper-Repo. Android prüft beim Installieren sowieso, so gibt es
   aber eine klare Meldung statt „App nicht installiert“.
7. Installation wie bisher über FileProvider + `ACTION_VIEW`, `canRequestPackageInstalls()` beachten.
8. Repo-Besitzer und -Name sind Konstanten im Code, nichts davon aus Netzantworten übernehmen.

## 5. `release.py` anpassen

- Der Teil „`git commit` / `git tag` / `git push`“ bleibt für den Programmcode in `mio2-app`.
- Statt `gh release create … mio2-app` künftig am Ende aufrufen:
  `python ../mio2-updater/tools/publish_release.py dist/Mio2.apk "<Notiz>" --appstore`
  (nur für 1.0.5 zusätzlich das alte `gh release create` in `mio2-app` als Brücke behalten, siehe Abschnitt 3).
- Der Schlüssel (`android/keystore/`) steht in `.gitignore` – vor jedem `git add -A` kurz prüfen, dass keine
  `.jks`/`.properties`-Datei dabei ist.

## 6. In Liams Appstore aufnehmen

Der Store installiert nur Apps, deren Signer **im Store-Code** hinterlegt ist (`security/TrustedSigners.kt`).
Darum braucht Mio² einmalig einen Eintrag und damit eine neue Store-Version. Das macht die Appstore-Sitzung
(Projekt `LiamsAppstore`), und eine Store-Version veröffentlicht sie nur nach Rückfrage bei Liam:

1. In `TrustedSigners.kt` ergänzen:
   `"com.liamkkm.mio" to setOf("cb7262ff13a69140945a4539d94e7305ec32c755ea2ab5f8489253911a581450")`
2. In `apps.json` eine Kategorie `reisen` anlegen (falls gewünscht) und die App eintragen. Vorschlag (Texte
   anpassen):

   ```json
   {
     "id": "mio2",
     "packageName": "com.liamkkm.mio",
     "name": "Mio²",
     "author": "dir",
     "category": "reisen",
     "version": "1.0.5", "versionCode": 10005, "sizeBytes": 0,
     "teaser": "Reise-Spots aus TikTok und Instagram sammeln.",
     "description": "Sammle Reise-Spots aus TikToks und Instagram-Reels auf einer Karte. Videolinks einfach über das Teilen-Menü an Mio² schicken.",
     "tags": ["Kein Konto", "Karte", "Teilen-Menü"],
     "permissions": [
       { "label": "Internet für Karte, Ortsnamen und Update-Check", "manifestName": "INTERNET" },
       { "label": "Netzwerkstatus", "manifestName": "ACCESS_NETWORK_STATE" },
       { "label": "Standort (Spots in deiner Nähe)", "manifestName": "ACCESS_FINE_LOCATION" },
       { "label": "Ungefährer Standort", "manifestName": "ACCESS_COARSE_LOCATION" },
       { "label": "Updates installieren (mit deiner Bestätigung)", "manifestName": "REQUEST_INSTALL_PACKAGES" }
     ],
     "changelog": [], "reviews": [], "iconUrl": "", "screenshots": [],
     "apkUrl": "https://github.com/obipepenobi-hub/liams-appstore/releases/download/mio2-v1.0.5/mio2-v1.0.5.apk",
     "apkSha256": "<aus tools/apk-info.sh>",
     "minSdk": 26, "installs": 0
   }
   ```
3. Ablauf pro Version steht in der README von Liams Appstore („Eine neue Version einer gelisteten App
   veröffentlichen“): `incoming-apks/` → `bash tools/apk-info.sh <apk>` (der Signer muss „hinterlegt“ sein) →
   Prerelease `mio2-vX.Y.Z` im Store-Repo → `apps.json` (`version`, `versionCode`, `sizeBytes`, `apkUrl`,
   `apkSha256`) → Datei aus `incoming-apks/` löschen.

## 7. Checkliste

- [ ] Updater nach Abschnitt 4 umgebaut, Version 1.0.5 gebaut
- [ ] 1.0.5 in `mio2-app` (Brücke) **und** in `mio2-updater` veröffentlicht
- [ ] `release.py` nach Abschnitt 5 angepasst
- [ ] Update von 1.0.4 auf 1.0.5 auf dem Handy getestet (Update-Popup, Installation)
- [ ] Appstore-Sitzung: Signer in `TrustedSigners.kt`, Store-Version, Katalogeintrag
- [ ] Schlüssel an einem dritten Ort gesichert (USB-Stick/Passwort-Manager), nicht nur auf diesem PC

## 8. Stand

Erledigt: Update-Repo angelegt, Release-Skript getestet (Trockenlauf mit der 1.0.4-APK), Schlüssel geprüft
(das Zertifikat im Keystore ist dasselbe wie in der veröffentlichten APK) und doppelt gesichert.
Offen: Punkte aus der Checkliste.
