# WebScraping Website Monitor

This project monitors a target website, strips non-content HTML (scripts/styles/meta), compares the result with a cached snapshot, and sends email alerts when changes are detected.

## Project structure

```text
WebScraping/
├── .env.example
├── certificates/
│   └── zscaler-root-ca.pem
├── requirements.txt
├── run_monitor.py
├── scripts/
│   └── run_monitor.ps1
├── src/
│   └── webscraping/
│       ├── __init__.py
│       ├── mailer.py
│       └── monitor.py
├── testing/
│   ├── __init__.py
│   ├── test_monitor.py
│   └── certifi_path.py
├── main.py
├── main_bs.py
└── mails.py
```

## What was restructured and why

1. Core logic moved to `src\webscraping\monitor.py` and mail logic to `src\webscraping\mailer.py` to separate concerns.
2. Added `run_monitor.py` as a stable CLI entrypoint, so running no longer depends on PyCharm run configurations.
3. Added `scripts\run_monitor.ps1` for Windows automation (Task Scheduler / background execution).
4. Cache files are now stored in `cache\` (configurable by `CACHE_DIR`) instead of cluttering project root.
5. `main.py`, `main_bs.py`, and `mails.py` were kept as compatibility wrappers.
6. `.gitignore` was updated to ignore virtual environments, cache files, and Python cache artifacts.

## Setup

1. Create and activate a virtual environment (recommended):
   - PowerShell:
     - `python -m venv .venv`
     - `.\.venv\Scripts\Activate.ps1`
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Create `.env` from `.env.example` and fill real values:
   - SMTP values are required for email sending.
   - `WEBSITE_URL` and `WEBSITE_NAME` are required unless passed in CLI.

## Sanlam / Zscaler SSL setup

On the Sanlam network, Zscaler performs HTTPS inspection. The monitor may therefore receive a certificate signed by the **Zscaler Root CA**, rather than the website's public certificate. Python Requests uses Certifi's CA bundle by default, not the Windows certificate store, which causes an `unable to get local issuer certificate` error even when Windows trusts Zscaler.

This project uses a project-local copy of the trusted Zscaler root certificate at `certificates\zscaler-root-ca.pem`. `.env` points Requests to it with:

```dotenv
REQUESTS_CA_BUNDLE=certificates/zscaler-root-ca.pem
ALLOW_INSECURE_SSL_FALLBACK=false
```

Relative certificate paths are resolved from the project directory, so this configuration works whether you launch it with `run_monitor.py`, the PowerShell launcher, or Task Scheduler.

If the certificate file is missing or Zscaler rotates its root certificate, export the already trusted root from the current user's Windows certificate store:

```powershell
$certificateDirectory = Join-Path $PWD "certificates"
New-Item -ItemType Directory -Path $certificateDirectory -Force | Out-Null
$rootCertificate = Get-ChildItem Cert:\CurrentUser\Root |
    Where-Object { $_.Subject -like "*CN=Zscaler Root CA*" } |
    Select-Object -First 1
if (-not $rootCertificate) { throw "Zscaler Root CA was not found in the current user Root store." }

$derPath = Join-Path $certificateDirectory "zscaler-root-ca.cer"
$pemPath = Join-Path $certificateDirectory "zscaler-root-ca.pem"
Export-Certificate -Cert $rootCertificate -FilePath $derPath -Type CERT -Force | Out-Null
certutil -encode $derPath $pemPath | Out-Null
Remove-Item -LiteralPath $derPath -Force
```

Do not download and trust a certificate directly from the website, edit Certifi's `cacert.pem`, or leave `ALLOW_INSECURE_SSL_FALLBACK=true`. Disabling verification accepts invalid or intercepted certificates and defeats the protection TLS provides.

## Running (works with or without PyCharm)

### PowerShell

Open PowerShell and run:

```powershell
cd C:\dev\devprojects\WebScraping
.\.venv\Scripts\python.exe run_monitor.py
```

The monitor treats `WEBSITE_URL` as the base URL and checks its `/collections/all` page every `CHECK_INTERVAL_SECONDS` seconds. Stop it with `Ctrl+C`.

This does not require virtual-environment activation, so it works when PowerShell blocks unsigned `Activate.ps1` scripts. If you prefer to activate the environment for the current PowerShell window only, run `Set-ExecutionPolicy -Scope Process Bypass` first, then run `.\.venv\Scripts\Activate.ps1`.

Before leaving it running, verify that email delivery works:

```powershell
.\.venv\Scripts\python.exe run_monitor.py --send-test-email
```

### Normal continuous monitoring

```powershell
python run_monitor.py
```

### One check only

```powershell
python run_monitor.py --once
```

### Send a real SMTP test email

```powershell
python run_monitor.py --send-test-email
```

This verifies the SMTP credentials and recipient configuration without waiting for a website change or an available product.

Automated unit tests do **not** send real email; they use a mocked SMTP sender. Use `--send-test-email` when you need to verify actual delivery. For Gmail, `SMTP_APP_PASSWORD` must be a valid Gmail App Password (not your normal Gmail password).

### Override `.env` values from CLI

```powershell
python run_monitor.py --website-url "https://example.com" --website-name "example_pg1" --interval-seconds 120
```

### Example: Monitor BuyYourDevice.co.za

To monitor the BuyYourDevice laptop collection page and send private email alerts:

```powershell
python run_monitor.py --website-url "https://www.buyyourdevice.co.za" --website-name "www.buyyourdevice.co.za_pg1" --private-email-mode "ACTIVATE_PRIVATE_EMAIL"
```

This will:
- Fetch the laptop collection page from BuyYourDevice
- Cache the content locally
- Check for changes on the interval specified in `.env` (default: 300 seconds)
- Send alerts to `PRIVATE_EMAIL_RECIPIENTS` instead of regular `EMAIL_RECIPIENTS` because `--private-email-mode "ACTIVATE_PRIVATE_EMAIL"` matches the `PRIVATE_EMAIL_TRIGGER` setting

## Run independently from PyCharm

To run even when PyCharm is closed, use one of these:

1. Run from a normal terminal:
   - `python run_monitor.py`
2. Use the included PowerShell script:
   - `.\scripts\run_monitor.ps1`
3. Register in **Windows Task Scheduler** (recommended for always-on):
   - **Program/script:** `powershell.exe`
   - **Arguments:** `-ExecutionPolicy Bypass -File "C:\dev\devprojects\WebScraping\scripts\run_monitor.ps1"`
   - Configure trigger (startup/logon) and run whether user is logged in or not.

The monitor now loads `.env` from project root and resolves paths from project files, so it is not tied to PyCharm’s working directory.

## Testing

A comprehensive test suite (`testing\test_monitor.py`) covers:
- HTML cleanup (script/style/meta tag removal)
- Argument parsing and validation
- Runtime configuration resolution (args override environment)
- SMTP configuration and email sending
- Website fetching, caching, and change detection
- Private email mode triggering

Run tests:

```powershell
python -m unittest testing.test_monitor -v
```

Current coverage: 34 tests, all passing.

To print the location of the installed Certifi bundle for diagnostics only:

```powershell
python testing\certifi_path.py
```

## Environment variables

Key variables from `.env.example`:

- `WEBSITE_URL`, `WEBSITE_NAME`
- `EMAIL_RECIPIENTS`
- `PRIVATE_EMAIL_RECIPIENTS`, `PRIVATE_EMAIL_TRIGGER`, `PRIVATE_EMAIL_MODE`
- `SMTP_SERVER`, `SMTP_PORT`, `SMTP_SENDER_EMAIL`, `SMTP_APP_PASSWORD`
- `ALERT_SUBJECT`, `ALERT_MESSAGE_TEMPLATE`
- `CHECK_INTERVAL_SECONDS`, `REQUEST_TIMEOUT_SECONDS`
- `NOT_LAPTOPS` — set to `true` to alert when any product card on the configured collection page does not have the `grid-view-item--sold-out` class
- `REQUESTS_CA_BUNDLE` — optional PEM CA bundle; use `certificates/zscaler-root-ca.pem` on a Sanlam/Zscaler laptop
- `ALLOW_INSECURE_SSL_FALLBACK` — keep this `false`; only enable temporarily for isolated troubleshooting
- `CACHE_DIR`
