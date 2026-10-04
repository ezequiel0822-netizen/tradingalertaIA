# Evaluación de las ramas del carry (B4, B5, DEX, Ethena, lending) — 2026-10-04

> **Origen y estatus.** Informe de un agente de research lanzado en la sesión del
> 2026-10-04, después del NO PASA de H-FC1. Los números los calculó el agente desde
> APIs públicas sin key (no son cifras de blogs), pero **no fueron reproducidos de forma
> independiente**: tratarlos como evaluación previa, no como veredicto pre-registrado.
> Scripts del agente (sin revisión de código): `research/ramas_carry_scripts/`. Datos
> crudos (fuera de git): `trading_data/ramas_carry/`.
>
> **⚠️ Contaminación declarada:** el agente ya miró la ventana 2024-10 → 2026-09 de todas
> estas series. Para cualquier pre-registro futuro de estas ramas, esa ventana cuenta como
> IN-SAMPLE: el test honesto es hacia adelante (paper-tracking) o en 2023-05 → 2024-09.

## Conclusión

Solo una rama muestra una prima persistente: **perp-perp con short en Hyperliquid y long
en Binance (B4b)**. Aun así es DUDOSA: en BTC queda por debajo de la tasa libre medida
sobre capital, y en ETH la supera por poco y con riesgo de DEX. Las demás quedan ≈ EFFR o
debajo, y no justifican backtest.

| Rama | Prima actual (2026) | Datos gratis | Veredicto previo |
|---|---|---|---|
| B4a funding entre CEX, BTC/ETH | spread ≈ 0 (−0.5 a +0.7 pp), signo ~50/50 | Sí (Binance; Bybit desde 2020; OKX en zips mensuales; Bitget solo 90 días) | NO VALE |
| B4a funding entre CEX, altcoins | +0.8 a +1.7 pp, ruido (autocorrelación ≈ 0.1); girar cuesta 3.6-7.5 %/año | Igual | NO VALE |
| **B4b short Hyperliquid / long Binance** | BTC +2.1 pp, ETH +3.8 pp sobre nocional; BTC comprimiéndose (11.5 → 2.4 por trimestre) | Sí (Hyperliquid horario desde 2023-05) | **DUDOSO (único candidato)** |
| B3 spot-perp en Hyperliquid / dYdX | Hyperliquid BTC 5.1, ETH 5.8 % (≈ EFFR sobre capital); dYdX negativo en 2026 | Sí | NO VALE |
| B5 trimestrales de Binance | BTC 4.8-5.1 % hoy; rolls de los últimos 4 trimestres 4.07 % bruto | Sí (data.binance.vision) | NO VALE (≈ EFFR y determinista) |
| B5 CME | ~5 % vs 4.5 % T-bill (abr-2026); open interest en mínimos de 14 meses | No (de pago) | NO VALE |
| Ethena sUSDe | 4.1 % YTD, 4.8 % a 30 días; 81 % del respaldo en cash | Sí | NO VALE (≈ T-bill tokenizado + riesgo) |
| Lending / Earn (Aave, Binance, OKX) | 2.7-3.7 % | Sí | NO VALE (benchmark de efectivo) |

Tasa libre de referencia (NY Fed): EFFR 3.88 % al 2026-10-01; media 2026 YTD 3.65 %; 2025 4.21 %.

## Hallazgos clave

- **Compresión confirmada por los propios recolectores del carry:** Ethena tiene hoy el
  81.1 % de su respaldo ($4.93B) en "Liquid Cash" y solo ~19 % en carry cubierto
  ([API de Ethena](https://ethena.fi/api/positions/current/collateral)); el supply de
  USDe cayó de $14.7B a $6.4B tras el crash del 10-oct-2025. La actividad de basis en CME
  cayó a mínimos de 14 meses
  ([The Block](https://www.theblock.co/post/396722/cme-bitcoin-futures-activity-slumps-to-14-month-low-as-basis-trade-unwind-drains-institutional-demand)).
- **B4b, el mecanismo:** la fórmula de Hyperliquid ancla el funding a una tasa base de
  0.01 % cada 8 h (≈ 11.6 % APR) y paga cada hora
  ([docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)); imprime
  exactamente esa tasa en el 50-56 % de las horas, contra 18-27 % de Binance.
  Rendimiento sobre capital ≈ spread × L/2 con margen en ambos venues: BTC con 3x ~3.2 %
  bruto (debajo de EFFR); ETH con 3x ~5.7 % bruto, ~1.5-1.8 pp sobre EFFR antes de
  rebalanceos y colas. Riesgos: liquidación de una pata sin margen cruzado, ADL (el
  10-oct-2025 Hyperliquid hizo ~35k cierres por ADL y cortó coberturas delta-neutral),
  puente/smart contract, USDC vs USDT.
- **B4a:** aun con previsión perfecta del mejor venue cada día, el techo en 2026 sería
  6.8-8.5 % APR; una regla causal simple da 1.2-2.1 % bruto pero gira de signo 36-75
  veces en 2 años y los costos se lo comen.
- **B5:** el retorno a vencimiento es determinista (basis de entrada menos costos); hoy ≈
  EFFR ± 0.5. Útil como alerta ("basis a 6 meses − EFFR > 3 pp"), no como estrategia.

## Ejecutabilidad para residentes de México (fuentes como las dio el agente)

- OKX: sí; su Risk & Compliance Disclosure (8-jul-2026) restringe derivados solo en AU,
  BR, KR y UK ([OKX](https://www.okx.com/help/risk-compliance-disclosure)).
- Bybit: fuentes secundarias dicen que México no está restringido; página oficial no verificada.
- Hyperliquid: sin KYC; bloquea por IP a EE.UU., Ontario y sancionados; México no
  restringido según fuentes secundarias; requiere wallet propia y USDC puenteado.
- Ethena: mint/redeem solo para entidades en whitelist; retail en mercado secundario.

## Recomendación del agente y siguiente paso

1. Única rama con pre-registro justificado: **B4b (BTC + ETH)**, con apalancamiento por
   pata fijado de antemano (2-3x), retorno sobre capital total contra EFFR, costos,
   liquidación y rebalanceo simulados con datos horarios. Expectativa: BTC no pasa, ETH
   marginal.
2. Por la contaminación, el test honesto es un **paper-tracking hacia adelante de 6 meses**
   más el tramo 2023-05 → 2024-09 como chequeo secundario.
3. Descartar sin backtest: B4a, B5, spot-perp en DEX, Ethena. Lending/Earn solo como
   benchmark de dónde estacionar efectivo.
