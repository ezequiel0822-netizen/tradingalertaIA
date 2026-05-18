from app.collectors.sec_collector import SECFiling


BULLISH_FORMS = {"8-K", "10-Q", "10-K", "6-K"}
RISK_FORMS = {"S-1", "S-3", "424B5", "424B3", "SC 13D", "SC 13G", "NT 10-Q", "NT 10-K"}

POSITIVE_DESCRIPTORS = {
    "results",
    "earnings",
    "agreement",
    "contract",
    "acquisition",
    "buyback",
    "repurchase",
    "dividend",
}

RISK_DESCRIPTORS = {
    "offering",
    "prospectus",
    "resignation",
    "delisting",
    "bankruptcy",
    "going concern",
    "notice",
}


def analyze_filings(filings: list[SECFiling]) -> tuple[str, int, list[str]]:
    if not filings:
        return "no_recent_filings", 0, ["Sin filings SEC recientes detectados."]

    score = 0
    reasons: list[str] = []
    forms = [filing.form.upper() for filing in filings]

    for filing in filings:
        form = filing.form.upper()
        description = filing.description.lower()
        if form in BULLISH_FORMS:
            score += 4
        if form in RISK_FORMS:
            score -= 12
        if any(word in description for word in POSITIVE_DESCRIPTORS):
            score += 8
        if any(word in description for word in RISK_DESCRIPTORS):
            score -= 14

    if forms:
        reasons.append("Filings recientes: " + ", ".join(forms[:5]) + ".")
    for filing in filings[:3]:
        description = filing.description or filing.primary_document or "sin descripcion"
        reasons.append(f"SEC {filing.form} {filing.filing_date}: {description}.")

    label = "filing_watch"
    if score >= 12:
        label = "positive_filing_catalyst"
    elif score <= -15:
        label = "filing_risk"

    return label, max(-100, min(100, score)), reasons[:5]
