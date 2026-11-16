# Karaca Connect Client

Unofficial asynchronous Python client for the Karaca Connect cloud service.

> **Alpha** — This library is extracted from the community Home Assistant integration at
> [Azadglr/karaca-connect-unofficial](https://github.com/Azadglr/karaca-connect-unofficial).
> It has been tested with simulated API responses but has **not yet been independently
> authenticated against the live Karaca service** in this extracted form.

This project is not affiliated with or endorsed by Karaca. The service API is not publicly documented;
its behavior and availability can change without notice. Currently the original community integration
reports verified support for the Karaca Çaysever Robotea Pro Connect 4in1 only.

## Installation

```bash
pip install karaca-connect-client
```

## Read-only example

```python
import asyncio
import getpass
from aiohttp import ClientSession
from karaca_connect_client import KaracaClient

async def main():
    email = input("Karaca Connect email: ")
    password = getpass.getpass("Karaca Connect password: ")
    async with ClientSession() as session:
        client = KaracaClient(session, email=email, password=password)
        devices = await client.get_devices()
        for device in devices:
            print(device.get("id"), device.get("label"))
        # In multi-device accounts, pass device_id=... explicitly.
        # No device mode or settings are changed by this example.

asyncio.run(main())
```

The caller owns the `aiohttp.ClientSession` and is responsible for securing account credentials.
Please do not paste credentials, tokens, or device details into public issues.

## Functions

- Authenticate and renew tokens when the cloud API rejects expired authorization
- List devices, retrieve device details and notification settings
- Set device modes and notification settings (optional; supported capabilities may differ by model)
- Distinguish authentication, connectivity, rate-limit, cloud availability and API errors
- Refuse to silently select a device when more than one device is present

## Development

```bash
python -m pip install -e . pytest
python -m pytest tests
```

## Release policy

Source code and GitHub release tags are public. Publishing to PyPI is performed solely
by the `publish.yml` GitHub Actions workflow using PyPI Trusted Publishing. The version
in `pyproject.toml` must match the release tag without its leading `v`.

**Initial alpha release:** `v0.1.0a1`. No credentials or API tokens are stored in this repository.

License: MIT.
