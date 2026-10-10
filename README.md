# Docker Mail Notifier

Überwacht die Docker-Container eines Hosts und schickt eine E-Mail, sobald einer abstürzt, neu startet oder „unhealthy“ wird. Eingerichtet wird alles im Webinterface – inklusive Verlauf aller Ereignisse.

- **Fertiges Image** auf GHCR (`linux/amd64`, `linux/arm64`) – kein eigenes Bauen nötig
- **Webinterface** im schlichten Apple-Stil, mit Dark Mode und eigener Ansicht für Mobilgeräte
- **Login** mit Admin-Konto, Sperre nach Fehlversuchen
- **Verlauf** mit Filter, Suche, Exit-Code und den letzten Log-Zeilen
- **Versteht, was passiert ist:** unterscheidet Absturz, automatischen Neustart, manuellen Neustart und gewolltes Stoppen
- **Kein Mail-Sturm:** Sperrzeit pro Container bei Absturzschleifen
- **Sicher aufgesetzt:** nur lesender Docker-Zugriff über einen Socket-Proxy, SMTP-Passwort verschlüsselt gespeichert

## Installation in Portainer

1. **Stacks → Add stack**, Name z. B. `docker-mail-notifier`.
2. Entweder **Repository** wählen
   - Repository URL: `https://github.com/flowoy96/docker-mail-notifier`
   - Compose path: `docker-compose.yml`

   oder den Inhalt der [docker-compose.yml](docker-compose.yml) in den **Web editor** kopieren.
3. Unter **Environment variables** am besten `SECRET_KEY` setzen (beliebige lange Zeichenkette, z. B. aus `openssl rand -base64 32`). Optional `PORT` und `TZ`.
4. **Deploy the stack**.
5. `http://<host>:8080` öffnen, Admin-Konto anlegen, unter **Einstellungen** SMTP-Server und Empfänger eintragen und **Testmail senden**.

> Das Admin-Konto legt an, wer die Seite zuerst öffnet – also direkt nach dem Start erledigen. Alternativ das Konto per `ADMIN_USER` / `ADMIN_PASSWORD` vorgeben.

Ohne Portainer:

```bash
curl -O https://raw.githubusercontent.com/flowoy96/docker-mail-notifier/main/docker-compose.yml
docker compose up -d
```

## Welche Ereignisse werden erkannt?

| Ereignis | Bedeutung | E-Mail (Standard) |
| --- | --- | --- |
| Abgestürzt | Container endet mit Fehlercode, ohne dass ihn jemand gestoppt hat | ✅ |
| Speicherlimit überschritten | OOM-Kill durch den Kernel | ✅ |
| Automatisch neu gestartet | Docker startet den Container per Restart-Richtlinie neu | ✅ |
| Manuell neu gestartet | `docker restart`, Portainer, Compose | ✅ |
| Healthcheck fehlgeschlagen | Status wechselt auf „unhealthy“ | ✅ |
| Wieder gesund | Healthcheck ist nach einem Fehler wieder erfolgreich | ✅ |
| Gestoppt | Container wurde manuell gestoppt | – |
| Regulär beendet | Container beendet sich selbst mit Exit-Code 0 | – |
| Gestartet | Container wurde gestartet | – |

Im Verlauf landen immer alle Ereignisse; für welche eine E-Mail verschickt wird, legst du in den Einstellungen fest. Bei Abstürzen und Healthcheck-Fehlern enthält die E-Mail die letzten Log-Zeilen des Containers (abschaltbar).

Einzelne Container lassen sich im Webinterface stummschalten oder dauerhaft per Label:

```yaml
labels:
  mail-notifier.ignore: "true"
```

## SMTP-Zugangsdaten

Empfohlen ist die Eingabe im **Webinterface**:

- Das Passwort wird verschlüsselt in der Datenbank gespeichert (Fernet/AES) und nie wieder an den Browser ausgeliefert.
- Der Schlüssel stammt aus `SECRET_KEY`. Damit liegen Schlüssel (Stack-Konfiguration) und Datenbank (Volume) getrennt – ein Backup des Volumes allein verrät das Passwort nicht.
- Ohne `SECRET_KEY` wird ein Schlüssel erzeugt und neben der Datenbank abgelegt. Das funktioniert, schützt aber nur davor, dass das Passwort im Klartext in der Datenbank steht.

Wer die Zugangsdaten lieber gar nicht im Webinterface haben möchte, kann sie per Umgebungsvariable (oder Docker Secret über `SMTP_PASSWORD_FILE`) vorgeben. Die Felder sind dann im Webinterface gesperrt.

Unabhängig davon: Für den Versand am besten ein eigenes Postfach bzw. ein App-Passwort verwenden, nicht das Hauptpasswort deines E-Mail-Kontos.

Gängige Einstellungen:

| Anbieter | Server | Port | Verschlüsselung |
| --- | --- | --- | --- |
| Gmail (App-Passwort) | `smtp.gmail.com` | 587 | STARTTLS |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | STARTTLS |
| GMX | `mail.gmx.net` | 587 | STARTTLS |
| WEB.DE | `smtp.web.de` | 587 | STARTTLS |
| iCloud (App-Passwort) | `smtp.mail.me.com` | 587 | STARTTLS |

## Umgebungsvariablen

Alle Variablen sind optional.

| Variable | Standard | Beschreibung |
| --- | --- | --- |
| `PORT` | `8080` | Port des Webinterface auf dem Host |
| `TZ` | `Europe/Berlin` | Zeitzone für Zeitangaben in E-Mails |
| `SECRET_KEY` | – | Schlüssel für das verschlüsselte SMTP-Passwort (empfohlen) |
| `ADMIN_USER`, `ADMIN_PASSWORD` | – | Admin-Konto beim ersten Start anlegen, statt im Browser |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | – | SMTP fest vorgeben (`SMTP_SECURITY`: `starttls`, `ssl` oder `none`) |
| `MAIL_TO` | – | Empfänger fest vorgeben, mehrere mit Komma getrennt |
| `HOST_LABEL` | – | Host-Name im Betreff fest vorgeben |
| `TRUST_PROXY` | `false` | Hinter einem Reverse Proxy `X-Forwarded-*` auswerten |
| `COOKIE_SECURE` | `false` | Session-Cookie nur über HTTPS senden (bei HTTPS-Aufrufen automatisch) |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Adresse der Docker-API (in der `docker-compose.yml` auf den Socket-Proxy gesetzt) |

`SECRET_KEY`, `ADMIN_PASSWORD` und `SMTP_PASSWORD` können auch als Datei übergeben werden (`…_FILE=/run/secrets/…`).

Die mitgelieferte `docker-compose.yml` reicht `PORT`, `TZ` und `SECRET_KEY` durch. Weitere Variablen trägst du dort im Abschnitt `environment` des Dienstes `notifier` ein.

## Sicherheit

- **Docker-Zugriff nur lesend:** Der Notifier spricht nicht direkt mit dem Docker-Socket, sondern über [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), der nur Container-Informationen und Ereignisse freigibt. Selbst wenn das Webinterface angegriffen würde, lassen sich darüber keine Container starten, stoppen oder verändern. Der Proxy hängt in einem internen Netz ohne Verbindung nach außen.
- **Container gehärtet:** läuft als unprivilegierter Benutzer, mit schreibgeschütztem Dateisystem und ohne Capabilities.
- **Login:** Passwörter werden mit scrypt gehasht, nach 5 Fehlversuchen ist die IP 15 Minuten gesperrt, Sitzungen laufen über ein `HttpOnly`-/`SameSite=Strict`-Cookie.
- **HTTPS:** Das Webinterface spricht selbst nur HTTP. Wenn es außerhalb deines Heimnetzes erreichbar sein soll, gehört es hinter einen Reverse Proxy mit TLS (Nginx Proxy Manager, Traefik, Caddy) – dann `TRUST_PROXY=true` setzen.
- **Log-Zeilen in E-Mails** können vertrauliche Daten enthalten. In den Einstellungen lässt sich die Anzahl auf „Keine“ stellen.

## Passwort vergessen

```bash
docker exec docker-mail-notifier python -m app.cli reset-admin
```

Danach kann im Browser ein neues Admin-Konto angelegt werden. Einstellungen und Verlauf bleiben erhalten.

## Aktualisieren

In Portainer den Stack öffnen und **Pull and redeploy** bzw. **Re-pull image and redeploy** wählen. Auf der Kommandozeile:

```bash
docker compose pull && docker compose up -d
```

Einstellungen und Verlauf liegen im Volume `data` und bleiben erhalten.

## Ohne Socket-Proxy

Wer nur einen Container möchte, kann den Docker-Socket direkt einbinden. Der Notifier braucht dann Root-Rechte, um den Socket lesen zu können, und hat darüber theoretisch vollen Zugriff auf Docker – deshalb ist die Variante mit Proxy der Standard.

```yaml
services:
  notifier:
    image: ghcr.io/flowoy96/docker-mail-notifier:latest
    container_name: docker-mail-notifier
    restart: unless-stopped
    user: root
    environment:
      DOCKER_HOST: unix:///var/run/docker.sock
      TZ: Europe/Berlin
    ports:
      - "8080:8080"
    volumes:
      - data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro

volumes:
  data:
```

## Entwicklung

```bash
docker build -t docker-mail-notifier .
docker run --rm -v "$PWD/tests:/srv/tests:ro" docker-mail-notifier python -m unittest discover -s tests
```

Das Backend ist Python (Starlette, httpx), die Oberfläche kommt ohne Framework und Build-Schritt aus. Bei jedem Push auf `main` baut GitHub Actions das Image und veröffentlicht es auf GHCR.

## Lizenz

[MIT](LICENSE)
