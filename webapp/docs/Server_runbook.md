# Market Big Picture Watch — Ubuntu production runbook

Consolidated record of the production deployment: Ubuntu server setup,
Cloudflare domain + Tunnel, and day-to-day maintenance.

---

## 1. Facts of the deployment

| Item | Value |
|---|---|
| Host | `eyeswrkstn1`, Ubuntu, user `zpan` |
| App root | `/srv/marketwatch` |
| Interpreter | `/srv/marketwatch/.venv/bin/python` (Python 3.14.4) |
| Pins observed | numpy 2.3.5, pandas 2.3.3 |
| Port | 8000 |
| Bind | `config.ini` → `host = auto` → resolves to `::` (IPv6) |
| systemd unit | `marketwatch` → `/etc/systemd/system/marketwatch.service` |
| Public URL | `https://app.einnia.com` |
| Domain | `einnia.com`, registered at Cloudflare Registrar |
| Tunnel ID | `082e219a-3dc2-4519-921b-a49f09cd17d7` |
| Route | `app.einnia.com` → `http://[::]:8000` |
| Config file | `/srv/marketwatch/config.ini` (holds the FRED API key) |
| Data cache | `/srv/marketwatch/data` |
| Scheduler | `MW_UPDATE_HOURS = 6,19` at `MW_UPDATE_MINUTE = 20` |

The Windows box is R&D only. This machine is production.

---

## 2. Everyday operations

```bash
sudo systemctl restart marketwatch     # restart
sudo systemctl stop marketwatch        # stop
sudo systemctl start marketwatch       # start
systemctl status marketwatch           # is it alive
sudo systemctl disable marketwatch     # stop starting at boot
sudo systemctl enable  marketwatch     # start at boot again
```

Logs:

```bash
journalctl -u marketwatch -f                  # follow live
journalctl -u marketwatch -n 100 --no-pager   # last 100 lines
journalctl -u marketwatch --since "1 hour ago"
journalctl -u cloudflared -n 50 --no-pager    # tunnel side
```

Liveness check — always use loopback, not the public URL:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' 'http://[::1]:8000/healthz'
```

`active (running)` in systemctl only means the process started. The curl is
what proves uvicorn actually bound the port.

Diagnostics — shows every config value and where it came from:

```bash
cd /srv/marketwatch && ./.venv/bin/python run.py doctor
```

Subcommands: `run.py` (serve), `update`, `selftest`, `doctor`, `setup`.
`run.py --help` lists them.

To deploy a new version, see §6 — stage beside, verify, swap by rename.

---

## 3. How the server was built

### 3.1 systemd unit

```ini
# /etc/systemd/system/marketwatch.service
[Unit]
Description=Market Big Picture Watch
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=zpan
WorkingDirectory=/srv/marketwatch
ExecStart=/srv/marketwatch/.venv/bin/python run.py
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now marketwatch
```

`ExecStart` points at the **venv** interpreter, not the system one. `run.py`
compares `sys.prefix` to decide whether to re-exec itself into the venv;
launched this way it sees it is already inside and skips the re-exec, so
systemd tracks a single process.

`Restart=on-failure` plus the app's own startup catch-up means a crash or
reboot self-heals without a missed refresh.

### 3.2 The IPv6 binding quirk — read this before debugging a 502

`config.ini` has `host = auto`. `_resolve_host()` in `run.py` maps `auto` to
`::` when IPv6 is available, `0.0.0.0` when it is not. An explicit value is
honoured verbatim.

**Consequence: bound to `::`, the app is IPv6-only.**
`curl http://127.0.0.1:8000` gets connection-refused. Use `http://[::1]:8000`.

*Why:* a raw Linux `::` socket with `IPV6_V6ONLY` cleared does serve IPv4
clients — but asyncio does not leave it cleared. `asyncio.base_events`
explicitly calls `setsockopt(IPPROTO_IPV6, IPV6_V6ONLY, True)` on every
AF_INET6 listener, so uvicorn's `::` bind is genuinely IPv6-only. If IPv4
clients must reach the app, set `host = 0.0.0.0` explicitly.

This is why the Cloudflare route targets an IPv6 address rather than
`http://localhost:8000`. It is set to `http://[::]:8000`; connecting to the
unspecified address `::` reaches loopback, so it behaves like `[::1]:8000`
while staying correct if the bind address changes.

**If you ever switch to `host = 127.0.0.1` (§5 item 2), the route must change
in the same maintenance window** — a `[::]` route cannot reach an IPv4-only
listener. Expect a brief 502 between the two edits.

---

## 4. How Cloudflare was set up

### 4.1 Domain

`einnia.com` registered directly at Cloudflare Registrar (at-cost, no markup),
so the zone was created automatically on the Free plan — no nameserver step.

Registrant contact must be ASCII only. **Verify the ICANN registrant email**
when it arrives: unverified means ICANN puts the domain on hold and Cloudflare
swaps in parking nameservers days later, with no obvious signal about the cause.

### 4.2 Tunnel

Created in the dashboard at **Networking → Tunnels → Create Tunnel**,
remotely-managed (config lives at Cloudflare; the connector holds only a token).

Connector install on Ubuntu:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list

sudo apt-get update && sudo apt-get install cloudflared
sudo cloudflared service install <TUNNEL_TOKEN>
```

The token is a credential — it lives in
`/etc/systemd/system/cloudflared.service`. Anyone holding it can attach a
connector to the tunnel.

**Why this works behind CGNAT:** `cloudflared` dials outbound to Cloudflare and
Cloudflare pushes requests down that open connection. Nothing connects *to* the
server, so CGNAT, absent public IPv4 and a rotating prefix are all irrelevant.
DDNS is no longer needed — the hostname resolves to Cloudflare anycast.

Egress needed: TCP and UDP **7844** outbound.

### 4.3 Route

**Networking → Tunnels → [tunnel] → Routes → Add route → Published application**

| Field | Value |
|---|---|
| Hostname | `app` + `einnia.com` |
| Service URL | `http://[::]:8000` |

Cloudflare wrote the proxied CNAME to `<TUNNEL_ID>.cfargotunnel.com`
automatically. Do not touch the DNS tab.

Route config changes push down the live connection within seconds — no restart.

### 4.4 Access (authentication)

`app.einnia.com` sits behind a Cloudflare Access self-hosted application.

| Item | Value |
|---|---|
| Login method | One-time PIN (email code) |
| Policy | `Policy_Allow`, ID `db75f9c1-d4ba-43f2-842b-521f3895a1c9` |
| Rule | `Include: Emails` → explicit allow-list |
| Login page | Customised, with branding assets |
| Asset origin | `assets.einniatechnologies.workers.dev` (e.g. `Einnia.png`) |

Unauthenticated requests are rejected at the Cloudflare edge and never reach
the server.

**Adding a user:** Zero Trust → **Access controls → Policies** → `Policy_Allow`
→ **Configure** → add the address to the `Emails` value list → save. No server
change, no restart. The new user receives a one-time code at that address on
first visit.

The allow-list is the only thing standing between the internet and the
dashboard — one-time PIN by itself issues a code to *any* address, so a rule of
`Everyone` would be equivalent to no authentication at all. Keep the rule
scoped to explicit addresses.

Access branding assets live on a Workers origin rather than behind the tunnel,
because the Access login page renders before the tunnel is reached and cannot
pull files from the protected application.

Cloudflare Access has no username/password option — it does not store
passwords. App-level accounts with passwords are a separate layer belonging to
the subscription service, and would sit *behind* Access, not replace it.

**Consequence for monitoring:** `https://app.einnia.com/healthz` now returns
`302` (redirect to login), not `200`. Use the loopback check in §2 for
liveness. External uptime monitoring would need a separate Access application
scoped to `/healthz` with a **Bypass** policy.

---

## 5. Outstanding — not yet done

Tracked here so a later session does not assume the deployment is finished.

1. **SSL/TLS mode** → set to **Full (strict)**. Then *Always Use HTTPS* on,
   Minimum TLS 1.2. Never *Flexible* (redirect loops). No certificate is
   needed on the server.
2. **Bind lockdown.** Two edits that must happen together, since each breaks
   the other:
   ```bash
   sudo sed -i 's/^host = auto/host = 127.0.0.1/' /srv/marketwatch/config.ini
   sudo systemctl restart marketwatch
   curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz
   ```
   Then change the route's Service URL to `http://127.0.0.1:8000`. Expect a
   brief 502 between the two steps. **Both edits are required**: the route
   currently targets `http://[::]:8000`, which cannot reach an IPv4-only
   listener, so changing `config.ini` alone takes the site down.
3. **Retire the old path:** delete the router port-forward; keep the DDNS
   record a week as rollback, then remove it.
4. **`ufw`:** once the app is on loopback and cloudflared is outbound-only,
   `sudo ufw default deny incoming` plus SSH from the LAN costs nothing.
5. **Cache rule:** bypass cache for `/api/*` so the scheduled refresh is
   never served stale from an edge PoP.
6. **Rate limiting** on `/api/login` etc. once the subscription service ships.
7. **Selftest on Python 3.14.4.** Pins were validated on CPython 3.11–3.13;
   3.14 itself has not been hash-checked. The app runs, but the selftest hash
   is what confirms the *arithmetic* still matches the Windows R&D box:
   ```bash
   ./.venv/bin/python run.py selftest --expect <combined> --expect-input <input>
   ```
   Take both hashes from a run on the Windows box. Exit 0 = match, 1 =
   arithmetic differs, 2 = inputs differ so the comparison is invalid.
8. **Data cache freshness.** `doctor` reported `last update ?` with cached
   JSON files present. Confirm the scheduler has actually fired and written
   fresh data rather than serving whatever shipped with the deploy.
9. **Schedule timezone.** This box runs on UTC, so `update_hours = 6,19` fires
   at 06:20/19:20 UTC while the Windows box fires at 06:20/19:20 local — five
   hours apart. Set `update_timezone = America/Chicago` in `config.ini` on
   both machines to align them.

---

## 6. Upgrading to a new version

### 6.1 The shape of it

Stage the new version **beside** the live one, do all the slow work while the
old one is still serving, then cut over with a rename. Downtime is a couple of
seconds and rollback is the same rename backwards.

The tempting alternative — stop the service, copy the new files over the top,
start it again — works, but it does the slow parts (dependency install,
verification) inside the outage, and it has three specific hazards:

- **`config.ini` is in the zip.** Copying over the top replaces production
  config with shipped defaults. Today the shipped file already carries the
  FRED key, so the damage is limited to anything you have customised —
  `update_timezone`, `host`, `port`, `admin_token`.
- **Overwriting does not delete.** Files removed in a newer version survive.
  v6.2.0 dropped `register_task.bat`, `update_data.bat` and `.env.example`; a
  leftover `.env` is still read as a legacy config layer.
- **Nothing installs dependencies.** New code against old packages either
  works by luck or fails at import. `run.py setup` installs the pins *and*
  import-checks them.

### 6.2 What is code and what is state

Everything in the zip is code and can be replaced wholesale, with two
exceptions to carry across by hand:

| Path | Why it must survive |
|---|---|
| `config.ini` | FRED API key and every production setting |
| `data/` | the cache. Without it the dashboard is blank for 15-25 minutes while the startup catch-up rebuilds |

`.venv/` is not in the zip. The staged tree builds its own.

### 6.3 Ownership — the rule that matters

You do **not** need to fix permissions on every upgrade, provided you never
*create* files with `sudo`:

| Operation | Effect on ownership |
|---|---|
| `mv` within one filesystem | preserved — it is a rename, the inode is untouched |
| `cp -a` | preserved |
| `sudo cp -r`, `sudo unzip`, `sudo tar -x` | **new files owned by root** |

So `sudo mv` in the swap below is safe, while `sudo unzip` is what breaks
things: root-owned files under `data/` mean the scheduler cannot write its
cache, and the failure shows up hours later as stale data rather than as an
error. Extract as `zpan`.

Check with `ls -ld /srv/marketwatch /srv/marketwatch/data`. If anything is not
`zpan`, fix it once with `sudo chown -R zpan:zpan /srv/marketwatch`.

Keep the staging directory under `/srv`, on the **same filesystem** as the
live tree (`df /srv /home` to confirm) — `mv` is only an atomic rename within
one filesystem.

### 6.4 What systemd does and does not notice

- It does **not** watch your application files. Replacing them is invisible to
  it; there is nothing to refuse and nothing to reload.
- `systemctl daemon-reload` is only needed when the **unit file** in
  `/etc/systemd/system/` changes. An app upgrade does not touch it.
- `Restart=on-failure` with `RestartSec=10s` means a broken upgrade produces a
  restart loop, and after a few rapid failures systemd stops trying with
  *"start request repeated too quickly"*. That message describes systemd
  giving up, not the cause — read `journalctl -u marketwatch -n 100` for the
  real error.
- `active (running)` only means the process started. The loopback curl is what
  proves uvicorn bound the port.

### 6.5 The procedure

Take both hashes from a `run.py selftest` on the dev box first — they are
needed in the verification step.

```bash
NEW=/srv/marketwatch.new
LIVE=/srv/marketwatch

# ---- 1. stage.  The service keeps running throughout this section. ----
sudo rm -rf $NEW && sudo mkdir -p $NEW && sudo chown zpan:zpan $NEW
unzip -q ~/MarketWatch_webapp_vX.Y.Z.zip -d $NEW      # as zpan, NOT sudo

# ---- 2. carry across the two things that are not code ----
cp $LIVE/config.ini $NEW/config.ini
cp -a $LIVE/data/. $NEW/data/

# ---- 3. build and verify the new tree, old one still serving ----
cd $NEW
python3 run.py setup            # installs pins, then import-checks them
./.venv/bin/python run.py doctor
./.venv/bin/python run.py selftest \
      --expect <combined-from-dev> --expect-input <input-from-dev>

# ---- 4. cut over.  This is the whole outage, about two seconds. ----
sudo systemctl stop marketwatch
sudo rm -rf /srv/marketwatch.prev
sudo mv $LIVE /srv/marketwatch.prev
sudo mv $NEW  $LIVE
sudo systemctl start marketwatch

# ---- 5. confirm ----
curl -sS -o /dev/null -w '%{http_code}\n' 'http://[::]:8000/healthz'
journalctl -u marketwatch -n 30 --no-pager
```

Step 3 is the point of the whole exercise: if the dependencies fail to
install, the app fails to import, the config does not parse or the arithmetic
does not match dev, you find out **before** stopping anything. A failure there
costs nothing — you simply do not run step 4.

Nothing on the Cloudflare side changes for an app upgrade; the tunnel points
at a port, not a version. Touch the route only if the port or the bind address
changes.

### 6.6 Rollback

```bash
sudo systemctl stop marketwatch
sudo mv /srv/marketwatch /srv/marketwatch.bad
sudo mv /srv/marketwatch.prev /srv/marketwatch
sudo systemctl start marketwatch
curl -sS -o /dev/null -w '%{http_code}\n' 'http://[::]:8000/healthz'
```

Under ten seconds, because `.prev` still has its own working `.venv`. Keep it
until the new version has survived a scheduled update cycle, then delete it —
each tree carries a virtualenv of a few hundred MB.

### 6.7 Verifying against the dev box

The dev box is Windows on Python 3.12; production is Linux on 3.14. **Testing
on dev does not test the interpreter that will run in production** — that is
exactly how a `pandas-datareader` / `distutils` import failure reached this
server once. Two steps in §6.5 close the gap, both before any downtime:

- `run.py setup` import-checks every dependency against the *production*
  interpreter and refuses to finish if the app cannot be imported.
- `run.py selftest --expect ... --expect-input ...` confirms the arithmetic
  still matches dev. Exit **0** match, **1** inputs match but the arithmetic
  differs, **2** inputs differ so the comparison is invalid — meaning the two
  boxes are not on the same version and nothing can be concluded yet.

### 6.8 Notes

- A virtualenv survives its parent directory being renamed. `run.py` always
  invokes `.venv/bin/python -m pip`, never the console scripts, whose shebangs
  hold an absolute path and do go stale.
- Back up `config.ini` before anything else:
  `sudo cp /srv/marketwatch/config.ini ~/config.ini.$(date +%F)`. It holds the
  FRED API key; if it is ever lost, regenerate at
  `fredaccount.stlouisfed.org/apikey`.
- Restarting within a minute of a scheduled slot will skip that slot — a cron
  fire time already in the past when the scheduler starts is not run.
  `startup_catchup_hours` covers it if the cache is old enough; otherwise the
  next slot does.

## 7. Maintaining the tunnel

```bash
sudo apt-get update && sudo apt-get install --only-upgrade cloudflared
sudo systemctl restart cloudflared
systemctl status cloudflared
```

Keep `--no-autoupdate` in the unit (the installer sets it) so cloudflared is
patched with the rest of the system rather than surprising the box mid-session.

If Cloudflare rotates its package signing key and `apt update` reports a
signature error, re-fetch the key using the current snippet at
`https://pkg.cloudflare.com/`.

Enable `unattended-upgrades` for OS security patches.

---

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `502` / error `1033` at `app.einnia.com` | Tunnel up, origin dial failed. `journalctl -u cloudflared -n 30` names the address it tried. Usually the Service URL is `127.0.0.1` while the app is bound `::` — use `[::1]`. |
| `curl 127.0.0.1:8000` refused, `[::1]` works | Expected while bound `::`. See §3.2. |
| systemd says running, nothing serves | uvicorn failed after start. `journalctl -u marketwatch -n 100`. |
| `status=203/EXEC` | Wrong path in `ExecStart`; check the venv interpreter exists. |
| Public URL returns `302` after Access is on | Correct — Access redirects to login. Use the loopback check for liveness. |
| `network is unreachable` to `…:7844` | No IPv4 egress. Add `--edge-ip-version 6` **before** `tunnel run` in the cloudflared unit. Not currently needed — this box has working IPv4 egress. |
| Connector flaps, IPv4 otherwise fine | Outbound UDP/7844 blocked. Add `--protocol http2`. |
| Site dies days after registration, NS wrong | ICANN registrant email never verified. |
| Redirect loop | SSL/TLS set to *Flexible*. Use Full (strict). |
| Scheduled update seems not to run | Check the timezone. `run.py doctor` prints `MW_UPDATE_TIMEZONE`; an empty value means the machine's own clock, and a server on UTC fires hours away from a desktop on local time. |
| After an upgrade: "start request repeated too quickly" | systemd gave up after a restart loop. That message is the symptom, not the cause — `journalctl -u marketwatch -n 100` has the real error. Roll back with §6.6. |
| After an upgrade: data stops refreshing, no error | Files under `data/` are root-owned, so the scheduler cannot write. Caused by extracting or copying with `sudo`. `sudo chown -R zpan:zpan /srv/marketwatch`, then see §6.3. |
| After an upgrade: a setting reverted on its own | `config.ini` was overwritten by the one in the zip. Restore from the backup in §6.8 and re-apply. |

Port 8000 already in use after a manual launch:

```bash
ss -ltnp | grep 8000     # find the stray process, kill it, then restart the unit
```
