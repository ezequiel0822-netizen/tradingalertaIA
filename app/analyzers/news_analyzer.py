from app.collectors.news_collector import NewsItem


POSITIVE_KEYWORDS = {
    "beats",
    "beat",
    "surges",
    "jumps",
    "rallies",
    "upgrade",
    "raises",
    "record",
    "growth",
    "profit",
    "partnership",
    "contract",
    "approval",
    "launch",
}

NEGATIVE_KEYWORDS = {
    "misses",
    "miss",
    "falls",
    "drops",
    "plunges",
    "downgrade",
    "cuts",
    "lawsuit",
    "probe",
    "warning",
    "recall",
    "loss",
    "slump",
}

EVENT_KEYWORDS = {
    "earnings",
    "revenue",
    "sales",
    "guidance",
    "conference",
    "call",
    "presentation",
    "deliveries",
    "forecast",
}


def analyze_news(items: list[NewsItem]) -> tuple[str, int, list[str]]:
    if not items:
        return "no_recent_news", 0, ["Sin titulares recientes disponibles."]

    score = 0
    reasons: list[str] = []
    event_hits: set[str] = set()
    positive_hits = 0
    negative_hits = 0

    for item in items:
        title = item.title.lower()
        if any(keyword in title for keyword in POSITIVE_KEYWORDS):
            positive_hits += 1
        if any(keyword in title for keyword in NEGATIVE_KEYWORDS):
            negative_hits += 1
        for keyword in EVENT_KEYWORDS:
            if keyword in title:
                event_hits.add(keyword)

    score += positive_hits * 12
    score -= negative_hits * 14
    score += min(len(event_hits) * 6, 18)

    if positive_hits:
        reasons.append(f"{positive_hits} titular(es) con sesgo positivo.")
    if negative_hits:
        reasons.append(f"{negative_hits} titular(es) con sesgo negativo/riesgo.")
    if event_hits:
        reasons.append("Eventos detectados: " + ", ".join(sorted(event_hits)) + ".")

    top_titles = [item.title for item in items[:3]]
    for title in top_titles:
        reasons.append(f"Titular: {title}")

    label = "neutral_news"
    if score >= 20:
        label = "positive_catalyst"
    elif score <= -18:
        label = "negative_catalyst"
    elif event_hits:
        label = "event_watch"

    return label, max(-100, min(100, score)), reasons[:7]
