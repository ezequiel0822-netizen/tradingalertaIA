import json
import logging
from typing import Any

import requests

from app.config.settings import Settings
from app.database.models import SecuritySummary


logger = logging.getLogger(__name__)


def _as_flag(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _to_tax(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0 < number <= 1:
        return round(number * 100, 4)
    return number


class GoPlusCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/0.1"})

    def check_token(self, chain: str, token_address: str) -> SecuritySummary:
        chain_id = self.settings.goplus_chain_ids.get(chain)
        if not chain_id:
            return SecuritySummary(raw_summary="GoPlus unavailable for this chain")

        url = f"{self.settings.goplus_base_url}/token_security/{chain_id}"
        params = {"contract_addresses": token_address}
        try:
            response = self.session.get(
                url, params=params, timeout=self.settings.request_timeout_seconds
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("GoPlus security check failed for %s:%s: %s", chain, token_address, exc)
            return SecuritySummary(raw_summary="GoPlus request failed")

        result = payload.get("result") or {}
        raw = result.get(token_address.lower()) or result.get(token_address) or {}
        if not raw:
            return SecuritySummary(raw_summary="GoPlus returned no data")

        return self._parse_security(raw)

    def _parse_security(self, raw: dict[str, Any]) -> SecuritySummary:
        buy_tax = _to_tax(raw.get("buy_tax"))
        sell_tax = _to_tax(raw.get("sell_tax"))
        honeypot = _as_flag(raw.get("is_honeypot"))
        blacklist = _as_flag(raw.get("is_blacklisted")) or _as_flag(raw.get("blacklist"))
        mintable = _as_flag(raw.get("is_mintable"))
        owner_change_balance = _as_flag(raw.get("owner_change_balance"))
        can_take_back_ownership = _as_flag(raw.get("can_take_back_ownership"))
        hidden_owner = _as_flag(raw.get("hidden_owner"))
        cannot_sell_all = _as_flag(raw.get("cannot_sell_all"))
        external_call = _as_flag(raw.get("external_call"))
        open_source = raw.get("is_open_source")
        is_proxy = _as_flag(raw.get("is_proxy"))

        tax_risk = any(tax is not None and tax >= 20 for tax in (buy_tax, sell_tax))
        owner_risk = owner_change_balance or can_take_back_ownership or hidden_owner
        contract_risk = (
            blacklist
            or mintable
            or cannot_sell_all
            or external_call
            or is_proxy
            or str(open_source) == "0"
        )
        critical = honeypot or blacklist or cannot_sell_all or tax_risk or owner_risk

        owner_status = "risky" if owner_risk else "ok"
        mint_risk = "risky" if mintable else "ok"
        blacklist_risk = "risky" if blacklist else "ok"

        risk_bits = []
        if honeypot:
            risk_bits.append("honeypot")
        if blacklist:
            risk_bits.append("blacklist")
        if tax_risk:
            risk_bits.append("high_tax")
        if owner_risk:
            risk_bits.append("owner_risk")
        if contract_risk:
            risk_bits.append("contract_risk")

        return SecuritySummary(
            honeypot_status="possible_honeypot" if honeypot else "not_detected",
            buy_tax=buy_tax,
            sell_tax=sell_tax,
            owner_status=owner_status,
            mint_risk=mint_risk,
            blacklist_risk=blacklist_risk,
            contract_risk="risky" if contract_risk else "ok",
            is_critical=critical,
            raw_summary=json.dumps(
                {
                    "risks": risk_bits or ["none_detected"],
                    "is_open_source": open_source,
                    "is_proxy": raw.get("is_proxy"),
                    "cannot_sell_all": raw.get("cannot_sell_all"),
                },
                ensure_ascii=False,
            ),
        )
