---
title: HTTPS
description: Warum der Hub über HTTPS erreichbar sein sollte und was sich dann ändert.
---

Labelyard selbst spricht einfaches HTTP auf Port 8000. HTTPS kommt vom Reverse Proxy davor, der auch das Zertifikat besorgt (Let's Encrypt in den Beispielen für Traefik und Caddy, bei Pangolin dessen eigenes).

## Warum das wichtig ist

- **Die Kamera braucht es.** Browser erlauben die Kamera nur auf einer sicheren Seite oder auf `localhost`. Zum Scannen mit dem Handy brauchst du deshalb die `https`-Adresse; ohne sie bietet dir die Scan-Seite an, stattdessen ein Foto des Codes zu wählen.
- **Die Cookies hängen davon ab.** Beginnt `LABELYARD_PUBLIC_URL` mit `https`, sind die Sitzungs-Cookies `Secure` und tragen das Präfix `__Host-`. Ein Browser schickt sie dann nicht über einfaches `http`, also öffne den Hub genau unter der eingestellten Adresse.
- **Die App-Installation braucht es.** Handys installieren eine Progressive Web App nur von einer sicheren Adresse.

## Checkliste

1. Der Proxy beendet TLS für deinen Hostnamen und leitet an `labelyard:8000` weiter.
2. `LABELYARD_PUBLIC_URL` ist die `https`-Adresse, ohne Pfad.
3. `PROXY_IP` (und damit `FORWARDED_ALLOW_IPS`) ist die feste Adresse des Proxys, damit der Hub die echten Client-Adressen sieht.
4. `curl -fsS https://<dein-host>/healthz` antwortet von außen mit `"status": "ok"`.

Innerhalb deines eigenen Stacks dürfen andere Container den Hub weiter direkt unter `http://labelyard:8000` mit einem API-Schlüssel aufrufen; die öffentliche Adresse zählt nur für Browser.
