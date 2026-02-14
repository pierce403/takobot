from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_ENS_RPC_URL = "https://ethereum.publicnode.com"
DEFAULT_ENS_RPC_URLS = [DEFAULT_ENS_RPC_URL, "https://eth.llamarpc.com"]


def resolve_recipient(recipient: str, rpc_urls: list[str]) -> str:
    if recipient.startswith("0x"):
        return recipient
    if recipient.endswith(".eth"):
        from web3 import Web3

        def resolve_web3bio(name: str) -> str:
            endpoint = f"https://api.web3.bio/ns/{quote(name)}"
            request = Request(endpoint, headers={"Content-Type": "application/json"}, method="GET")
            with urlopen(request, timeout=10) as response:
                if response.status >= 400:
                    raise RuntimeError(f"web3.bio returned {response.status} {response.reason}")
                data = response.read()
            results: Any = json.loads(data.decode("utf-8"))
            results_list = results if isinstance(results, list) else []
            first = results_list[0] if results_list else {}
            address_value = first.get("address") if isinstance(first, dict) else None
            address = address_value if isinstance(address_value, str) else None
            if not address:
                raise RuntimeError(f"web3.bio did not resolve {name}")
            return address

        last_error: Exception | None = None
        for rpc_url in rpc_urls:
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if not web3.is_connected():
                    last_error = RuntimeError(f"Unable to reach ENS RPC at {rpc_url}")
                    continue
                address = web3.ens.address(recipient)
                if address:
                    return address
                last_error = RuntimeError(f"ENS name did not resolve: {recipient}")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        try:
            return resolve_web3bio(recipient)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"ENS resolution failed via {', '.join(rpc_urls)}: {last_error}; "
                f"web3.bio error: {exc}"
            ) from exc
    return recipient

