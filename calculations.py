"""
German pension simulation calculations.

Tax law references:
- §22 EStG: Ertragsanteil for private pensions
- §3 Nr. 1a EStG: ALG I tax-free but Progressionsvorbehalt
- §19 EStG: Versorgungsfreibetrag for Betriebsrente
- GKV Beitragsbemessungsgrenze 2024: 5175 €/month
- Pflegeversicherung: 3.4% (4.0% without children, +0.6% for childless since 2023 -> 4.0%)
"""

from datetime import date
from dateutil.relativedelta import relativedelta
import math

# ---------------------------------------------------------------------------
# Constants (2024 values)
# ---------------------------------------------------------------------------
GKV_RATE = 0.146          # 14.6 % allgemeiner Beitrag
PV_RATE_WITH_CHILDREN = 0.034   # 3.4 %
PV_RATE_NO_CHILDREN = 0.040     # 4.0 %
BBG_GKV_MONTHLY = 5175.0        # Beitragsbemessungsgrenze KV/PV
GRUNDFREIBETRAG = 11784.0       # Grundfreibetrag 2024 (single)
VERSORGUNGSFREIBETRAG_MAX = 1800.0   # §19 Abs.2 EStG Betriebsrente max (2024, year 2006+)
VERSORGUNGSFREIBETRAG_ZUSCHLAG = 540.0  # Zuschlag zum Versorgungsfreibetrag 2024

ABSCHLAG_PER_MONTH = 0.003   # 0.3 % per month before Regelaltersgrenze

# Taxable fraction of gesetzliche Rente by retirement year (§22 Nr.1 Satz 3 EStG)
def _rente_steuerpflichtiger_anteil(year: int) -> float:
    if year <= 2005:
        return 0.50
    if year >= 2058:
        return 1.00
    if year <= 2020:
        return 0.50 + (year - 2005) * 0.02
    return 0.80 + (year - 2020) * 0.01


# ---------------------------------------------------------------------------
# Income tax (§32a EStG, simplified 2024)
# ---------------------------------------------------------------------------
def _est_single(z: float) -> float:
    """German income tax for single filer (annual taxable income z)."""
    if z <= GRUNDFREIBETRAG:
        return 0.0
    elif z <= 17005:
        y = (z - GRUNDFREIBETRAG) / 10000
        return (979.18 * y + 1400) * y
    elif z <= 66760:
        y = (z - 17005) / 10000
        return (192.59 * y + 2397) * y + 1025.38
    elif z <= 277825:
        return 0.42 * z - 10602.13
    else:
        return 0.45 * z - 18936.88


def income_tax_annual(taxable_income: float, married: bool = False) -> float:
    """Annual income tax including Soli (if applicable)."""
    if married:
        # Ehegattensplitting
        tax = _est_single(taxable_income / 2) * 2
    else:
        tax = _est_single(taxable_income)
    tax = max(0.0, tax)
    # Solidaritätszuschlag (ab 2021 weitgehend abgeschafft für normale Renter)
    soli_freigrenze = 18130.0 if not married else 36260.0
    if tax > soli_freigrenze:
        soli = (tax - soli_freigrenze) * 0.199 if tax < soli_freigrenze / 0.9 else tax * 0.055
        tax += max(0, soli)
    return tax


# ---------------------------------------------------------------------------
# GKV / PKV / Pflegeversicherung
# ---------------------------------------------------------------------------
def gkv_beitrag_rentner(
    gesetzliche_rente_gross: float,
    betriebsrente_gross: float,
    zusatzbeitrag_pct: float = 1.7,
    has_children: bool = True,
) -> tuple[float, float]:
    """
    Returns (KV-Beitrag, PV-Beitrag) per month for a statutory insured pensioner.
    Betriebsrente is fully KV-relevant above Freigrenze (€176.75/month 2024).
    Gesetzliche Rente: half rate (RV pays the other half).
    """
    FREIGRENZE_BETRIEBSRENTE = 176.75  # 1/20 of monthly Bezugsgröße 2024

    gkv_rate_total = (GKV_RATE + zusatzbeitrag_pct / 100)

    # Gesetzliche Rente: pensioner pays half
    kv_rente = min(gesetzliche_rente_gross, BBG_GKV_MONTHLY) * gkv_rate_total / 2

    # Betriebsrente: only above Freigrenze, full contribution
    br_relevant = max(0.0, betriebsrente_gross - FREIGRENZE_BETRIEBSRENTE)
    kv_betriebsrente = min(br_relevant, max(0, BBG_GKV_MONTHLY - gesetzliche_rente_gross)) * gkv_rate_total

    kv = kv_rente + kv_betriebsrente

    # Pflegeversicherung: pensioner pays full (no employer)
    pv_rate = PV_RATE_WITH_CHILDREN if has_children else PV_RATE_NO_CHILDREN
    pv_base = min(gesetzliche_rente_gross + betriebsrente_gross, BBG_GKV_MONTHLY)
    pv = pv_base * pv_rate

    return round(kv, 2), round(pv, 2)


def gkv_beitrag_aktiv(
    einkommen_monthly: float,
    zusatzbeitrag_pct: float = 1.7,
    has_children: bool = True,
) -> tuple[float, float]:
    """KV + PV for voluntary/freiwillige GKV member (pre-retirement, no employer)."""
    gkv_rate_total = (GKV_RATE + zusatzbeitrag_pct / 100)
    kv = min(einkommen_monthly, BBG_GKV_MONTHLY) * gkv_rate_total
    pv_rate = PV_RATE_WITH_CHILDREN if has_children else PV_RATE_NO_CHILDREN
    pv = min(einkommen_monthly, BBG_GKV_MONTHLY) * pv_rate
    return round(kv, 2), round(pv, 2)


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------
def calculate_pension_plan(params: dict) -> dict:
    """
    Simulate month by month from today until age_end.

    params keys (all monetary values in €/month unless noted):
    --- Person 1 ---
    p1_birth_year, p1_birth_month
    p1_pension_age          desired retirement age (years, float ok: 63.5)
    p1_gesetzliche_rente    gross monthly at Regelaltersgrenze 67
    p1_betriebsrente        gross monthly
    p1_rv1_amount, p1_rv1_tax_pct, p1_rv1_start_age  private Rentenversicherung 1
    p1_rv2_amount, p1_rv2_tax_pct, p1_rv2_start_age
    p1_rv3_amount, p1_rv3_tax_pct, p1_rv3_start_age
    --- Person 2 (optional) ---
    two_persons             bool
    p2_birth_year, p2_birth_month
    p2_pension_age
    p2_gesetzliche_rente
    p2_betriebsrente
    p2_rv1_amount ... (same structure)
    --- Health insurance ---
    kv_type                 "gesetzlich" | "privat"
    gkv_zusatzbeitrag       % (default 1.7)
    pkv_amount              €/month (if privat)
    pkv_pv_amount           €/month Pflegeversicherung (if privat)
    has_children            bool (affects PV rate)
    married                 bool (tax splitting)
    --- Capital ---
    capital_start           total capital today (€)
    capital_return_pct      annual return % (before drawdown)
    capital_floor           minimum capital to keep (€)
    capital_floor_age       age at which floor applies (for person 1)
    capital_drawdown_mode   "auto" | "fixed"
    capital_drawdown_fixed  fixed monthly drawdown (if mode=fixed)
    --- Pre-retirement income ---
    abfindung_monthly       monthly amount
    abfindung_start         "YYYY-MM" (or empty)
    abfindung_end           "YYYY-MM"
    alg_monthly             monthly ALG I
    alg_start               "YYYY-MM"
    alg_end                 "YYYY-MM"
    --- Simulation ---
    age_end                 simulate until this age of person 1 (default 90)
    """

    today = date.today()

    def _birth(year, month):
        return date(int(year), int(month), 1)

    def _age_at(birth: date, d: date) -> float:
        return (d - birth).days / 365.25

    def _date_from_ym(ym: str) -> date | None:
        if not ym:
            return None
        y, m = ym.split("-")
        return date(int(y), int(m), 1)

    # --- Person 1 ---
    p1_birth = _birth(params.get("p1_birth_year", 1963), params.get("p1_birth_month", 1))
    p1_pension_age = float(params.get("p1_pension_age", 67))
    p1_regalter = 67.0
    p1_pension_date = p1_birth + relativedelta(months=int(p1_pension_age * 12))
    p1_pension_date = p1_pension_date.replace(day=1)

    # Abschläge / abschlagsfreie Rente (besonders langjährig Versicherte)
    p1_abschlagsfrei = bool(params.get("p1_abschlagsfrei", False))
    p1_beitragsjahre = float(params.get("p1_beitragsjahre", 45) or 45)

    if p1_abschlagsfrei and p1_pension_age < p1_regalter:
        # Kein Abschlag, aber weniger Entgeltpunkte durch fehlende Beitragsjahre
        missing_years = p1_regalter - p1_pension_age
        factor_p1 = p1_beitragsjahre / (p1_beitragsjahre + missing_years)
        abschlag_p1 = 0.0
    else:
        months_early_p1 = max(0, (p1_regalter - p1_pension_age) * 12)
        abschlag_p1 = min(months_early_p1 * ABSCHLAG_PER_MONTH, 0.144)
        factor_p1 = 1 - abschlag_p1

    p1_gesetzliche_rente = float(params.get("p1_gesetzliche_rente", 0)) * factor_p1
    p1_betriebsrente = float(params.get("p1_betriebsrente", 0))

    # Private Rentenversicherungen person 1
    p1_rvs = []
    for i in range(1, 4):
        amt = float(params.get(f"p1_rv{i}_amount", 0) or 0)
        tax_pct = float(params.get(f"p1_rv{i}_tax_pct", 18) or 18)
        start_age = float(params.get(f"p1_rv{i}_start_age", 67) or 67)
        if amt > 0:
            start_date = (p1_birth + relativedelta(months=int(start_age * 12))).replace(day=1)
            p1_rvs.append({"amount": amt, "tax_pct": tax_pct / 100, "start_date": start_date})

    # --- Person 2 ---
    two_persons = bool(params.get("two_persons", False))
    p2_birth = None
    p2_pension_date = None
    p2_gesetzliche_rente = 0.0
    p2_betriebsrente = 0.0
    p2_rvs = []

    if two_persons:
        p2_birth = _birth(params.get("p2_birth_year", 1965), params.get("p2_birth_month", 1))
        p2_pension_age = float(params.get("p2_pension_age", 67))
        months_early_p2 = max(0, (67.0 - p2_pension_age) * 12)
        abschlag_p2 = min(months_early_p2 * ABSCHLAG_PER_MONTH, 0.144)
        factor_p2 = 1 - abschlag_p2
        p2_pension_date = (p2_birth + relativedelta(months=int(p2_pension_age * 12))).replace(day=1)
        p2_gesetzliche_rente = float(params.get("p2_gesetzliche_rente", 0)) * factor_p2
        p2_betriebsrente = float(params.get("p2_betriebsrente", 0))
        for i in range(1, 4):
            amt = float(params.get(f"p2_rv{i}_amount", 0) or 0)
            tax_pct = float(params.get(f"p2_rv{i}_tax_pct", 18) or 18)
            start_age = float(params.get(f"p2_rv{i}_start_age", 67) or 67)
            if amt > 0:
                start_date = (p2_birth + relativedelta(months=int(start_age * 12))).replace(day=1)
                p2_rvs.append({"amount": amt, "tax_pct": tax_pct / 100, "start_date": start_date})

    # --- Insurance ---
    kv_type = params.get("kv_type", "gesetzlich")
    gkv_zb = float(params.get("gkv_zusatzbeitrag", 1.7) or 1.7)
    pkv_amount = float(params.get("pkv_amount", 0) or 0)
    pkv_pv_amount = float(params.get("pkv_pv_amount", 0) or 0)
    p2_pkv_amount = float(params.get("p2_pkv_amount", 0) or 0)
    p2_pkv_pv_amount = float(params.get("p2_pkv_pv_amount", 0) or 0)
    has_children = bool(params.get("has_children", True))
    married = bool(params.get("married", False))

    # --- Capital ---
    capital = float(params.get("capital_start", 0) or 0)
    capital_return_pct = float(params.get("capital_return_pct", 3) or 3)
    capital_floor = float(params.get("capital_floor", 0) or 0)
    capital_floor_age = float(params.get("capital_floor_age", 85) or 85)
    drawdown_mode = params.get("capital_drawdown_mode", "fixed")
    drawdown_fixed = float(params.get("capital_drawdown_fixed", 0) or 0)

    monthly_return = (1 + capital_return_pct / 100) ** (1 / 12) - 1
    ABGELTUNGSTEUER = 0.25  # 25 % Kapitalertragssteuer auf Entnahmen

    # --- Pre-retirement income ---
    abfindung_monthly = float(params.get("abfindung_monthly", 0) or 0)
    abfindung_start = _date_from_ym(params.get("abfindung_start", ""))
    abfindung_end = _date_from_ym(params.get("abfindung_end", ""))
    alg_monthly = float(params.get("alg_monthly", 0) or 0)
    alg_start = _date_from_ym(params.get("alg_start", ""))
    alg_end = _date_from_ym(params.get("alg_end", ""))

    # --- Sonderkapitalentnahme threshold ---
    net_target = float(params.get("net_target", 0) or 0)  # 0 = deactivated

    # --- Simulation range ---
    age_end = float(params.get("age_end", 95) or 95)
    end_date = (p1_birth + relativedelta(months=int(age_end * 12))).replace(day=1)

    # Retirement year of person 1 for taxable fraction calculation
    p1_retirement_year = p1_pension_date.year
    p1_renten_stpfl_anteil = _rente_steuerpflichtiger_anteil(p1_retirement_year)
    if two_persons and p2_pension_date:
        p2_retirement_year = p2_pension_date.year
        p2_renten_stpfl_anteil = _rente_steuerpflichtiger_anteil(p2_retirement_year)
    else:
        p2_renten_stpfl_anteil = 0

    monthly_results = []
    annual_results = {}   # keyed by year int
    cur = today.replace(day=1)
    capital_prev_month = capital  # track capital before return for annual return calc

    # Summary ages
    summary_ages = [None, 63, 65, 67, 70, 75, 80]
    summary_dates = {}
    for a in summary_ages:
        if a is None:
            summary_dates["jetzt"] = today.replace(day=1)
        else:
            d = (p1_birth + relativedelta(months=int(a * 12))).replace(day=1)
            summary_dates[str(a)] = d
    summary_results = {}

    while cur <= end_date:
        p1_age = _age_at(p1_birth, cur)
        p1_retired = cur >= p1_pension_date
        p2_retired = two_persons and p2_pension_date and cur >= p2_pension_date

        # --- Income ---
        p1_rente = p1_gesetzliche_rente if p1_retired else 0.0
        p1_br = p1_betriebsrente if p1_retired else 0.0
        p1_rv_income = sum(rv["amount"] for rv in p1_rvs if cur >= rv["start_date"])

        p2_rente = p2_gesetzliche_rente if p2_retired else 0.0
        p2_br = p2_betriebsrente if p2_retired else 0.0
        p2_rv_income = sum(rv["amount"] for rv in p2_rvs if cur >= rv["start_date"])

        abfindung = (
            abfindung_monthly
            if abfindung_start and abfindung_end and abfindung_start <= cur <= abfindung_end
            else 0.0
        )
        alg = (
            alg_monthly
            if alg_start and alg_end and alg_start <= cur <= alg_end
            else 0.0
        )

        total_pension_gross = p1_rente + p1_br + p1_rv_income + p2_rente + p2_br + p2_rv_income

        # Capital: apply return then drawdown
        capital_before_return = capital
        capital *= 1 + monthly_return
        monthly_capital_return = capital - capital_before_return

        floor_active = p1_age >= capital_floor_age
        effective_floor = capital_floor if floor_active else 0.0

        if drawdown_mode == "fixed":
            cap_drawdown_gross = min(drawdown_fixed, max(0, capital - effective_floor))
        else:
            cap_drawdown_gross = 0.0

        cap_drawdown_tax = round(cap_drawdown_gross * ABGELTUNGSTEUER, 2)
        cap_drawdown_net = cap_drawdown_gross - cap_drawdown_tax
        capital -= cap_drawdown_gross

        # --- KV / PV ---
        if kv_type == "gesetzlich":
            kv, pv = gkv_beitrag_rentner(
                p1_rente + p2_rente,
                p1_br + p2_br,
                gkv_zb,
                has_children,
            ) if (p1_retired or p2_retired) else gkv_beitrag_aktiv(
                abfindung + alg,
                gkv_zb,
                has_children,
            )
        else:
            kv = pkv_amount
            pv = pkv_pv_amount
        # Person 2 PKV (always added on top when two_persons and amounts set)
        if two_persons:
            kv += p2_pkv_amount
            pv += p2_pkv_pv_amount

        # --- Income tax (annual basis, computed monthly) ---
        # Taxable amounts (annual)
        ann_p1_rente_stpfl = p1_rente * 12 * p1_renten_stpfl_anteil
        ann_p2_rente_stpfl = p2_rente * 12 * p2_renten_stpfl_anteil

        # Versorgungsfreibetrag for Betriebsrente (simplified: use 2024 values)
        vfb = min(VERSORGUNGSFREIBETRAG_MAX, (p1_br + p2_br) * 12 * 0.144)
        vfb_zuschlag = min(VERSORGUNGSFREIBETRAG_ZUSCHLAG, 432)
        ann_br_stpfl = max(0, (p1_br + p2_br) * 12 - vfb - vfb_zuschlag)

        # Private Renten: only taxable portion
        ann_rv_stpfl = sum(rv["amount"] * 12 * rv["tax_pct"] for rv in p1_rvs if cur >= rv["start_date"])
        ann_rv_stpfl += sum(rv["amount"] * 12 * rv["tax_pct"] for rv in p2_rvs if cur >= rv["start_date"])

        # ALG: Progressionsvorbehalt (simplified: add to income for rate calculation)
        ann_alg = alg * 12
        ann_abfindung = abfindung * 12

        # Werbungskosten-Pauschbetrag für Renten: 102 €/year
        wk_pausch = 102.0 * (1 + (1 if two_persons else 0))

        ann_taxable = max(
            0,
            ann_p1_rente_stpfl
            + ann_p2_rente_stpfl
            + ann_br_stpfl
            + ann_rv_stpfl
            + ann_abfindung
            - wk_pausch,
        )

        # Progressionsvorbehalt: ALG erhöht den Steuersatz
        if ann_alg > 0 and ann_taxable > 0:
            tax_with_alg = income_tax_annual(ann_taxable + ann_alg, married)
            tax_without_alg = income_tax_annual(ann_taxable, married)
            # Rate from combined, applied to taxable only
            rate = tax_with_alg / (ann_taxable + ann_alg) if (ann_taxable + ann_alg) > 0 else 0
            ann_tax = ann_taxable * rate
        else:
            ann_tax = income_tax_annual(ann_taxable, married)

        monthly_tax = ann_tax / 12

        # --- Net income ---
        total_gross = total_pension_gross + abfindung + alg + cap_drawdown_net
        total_deductions = monthly_tax + kv + pv
        net = total_gross - total_deductions

        # --- Sonderkapitalentnahme: top up net to net_target ---
        sonder_gross = 0.0
        sonder_net = 0.0
        sonder_tax = 0.0
        if net_target > 0 and net < net_target:
            gap = net_target - net
            # gross needed: gap / (1 - Abgeltungsteuer)
            needed_gross = gap / (1 - ABGELTUNGSTEUER)
            available = max(0.0, capital - effective_floor)
            sonder_gross = min(needed_gross, available)
            sonder_tax = round(sonder_gross * ABGELTUNGSTEUER, 2)
            sonder_net = sonder_gross - sonder_tax
            capital -= sonder_gross
            net += sonder_net

        row = {
            "date": cur.strftime("%Y-%m"),
            "p1_age": round(p1_age, 1),
            "p1_retired": p1_retired,
            "p2_retired": p2_retired,
            # Inflows
            "p1_rente": round(p1_rente, 2),
            "p1_betriebsrente": round(p1_br, 2),
            "p1_rv": round(p1_rv_income, 2),
            "p2_rente": round(p2_rente, 2),
            "p2_betriebsrente": round(p2_br, 2),
            "p2_rv": round(p2_rv_income, 2),
            "abfindung": round(abfindung, 2),
            "alg": round(alg, 2),
            "capital_drawdown_gross": round(cap_drawdown_gross, 2),
            "capital_drawdown_tax": round(cap_drawdown_tax, 2),
            "capital_drawdown_net": round(cap_drawdown_net, 2),
            "sonder_entnahme_gross": round(sonder_gross, 2),
            "sonder_entnahme_tax": round(sonder_tax, 2),
            "sonder_entnahme": round(sonder_net, 2),   # net received
            "total_gross": round(total_gross + sonder_net, 2),
            # Deductions
            "tax": round(monthly_tax, 2),
            "kv": round(kv, 2),
            "pv": round(pv, 2),
            "total_deductions": round(total_deductions, 2),
            # Net
            "net": round(net, 2),
            "capital": round(capital, 2),
            "monthly_capital_return": round(monthly_capital_return, 2),
        }
        monthly_results.append(row)

        # --- Annual capital aggregation ---
        yr = cur.year
        if yr not in annual_results:
            annual_results[yr] = {
                "year": yr,
                "start_capital": round(capital_before_return, 2),
                "return_sum": 0.0,
                "drawdown_gross": 0.0,
                "drawdown_tax": 0.0,
                "sonder_gross": 0.0,
                "sonder_tax": 0.0,
                "end_capital": 0.0,
            }
        annual_results[yr]["return_sum"] += monthly_capital_return
        annual_results[yr]["drawdown_gross"] += cap_drawdown_gross
        annual_results[yr]["drawdown_tax"] += cap_drawdown_tax
        annual_results[yr]["sonder_gross"] += sonder_gross
        annual_results[yr]["sonder_tax"] += sonder_tax
        annual_results[yr]["end_capital"] = round(capital, 2)

        # Capture summary snapshots
        for label, snap_date in summary_dates.items():
            if cur == snap_date or (cur <= snap_date < cur + relativedelta(months=1)):
                summary_results[label] = {
                    "net": round(net, 2),
                    "capital": round(capital, 2),
                    "age": round(p1_age, 1),
                }

        cur += relativedelta(months=1)

    # Fill missing summary entries with nearest available
    for label, snap_date in summary_dates.items():
        if label not in summary_results and monthly_results:
            # find closest
            closest = min(monthly_results, key=lambda r: abs(
                date(int(r["date"][:4]), int(r["date"][5:7]), 1) - snap_date
            ))
            summary_results[label] = {
                "net": closest["net"],
                "capital": closest["capital"],
                "age": closest["p1_age"],
            }

    # Finalize annual rows
    annual_list = []
    for yr in sorted(annual_results):
        a = annual_results[yr]
        total_drawdown_gross = a["drawdown_gross"] + a["sonder_gross"]
        total_drawdown_tax = a["drawdown_tax"] + a["sonder_tax"]
        annual_list.append({
            "year": yr,
            "start_capital": round(a["start_capital"], 0),
            "return_sum": round(a["return_sum"], 0),
            "regular_drawdown_gross": round(a["drawdown_gross"], 0),
            "sonder_drawdown_gross": round(a["sonder_gross"], 0),
            "total_drawdown_gross": round(total_drawdown_gross, 0),
            "total_drawdown_tax": round(total_drawdown_tax, 0),
            "total_drawdown_net": round(total_drawdown_gross - total_drawdown_tax, 0),
            "end_capital": round(a["end_capital"], 0),
        })

    p1_abschlagsfrei_info = ""
    if p1_abschlagsfrei and p1_pension_age < p1_regalter:
        missing_years = p1_regalter - p1_pension_age
        p1_abschlagsfrei_info = (
            f"Abschlagsfrei: {p1_beitragsjahre:.0f} Beitragsjahre, "
            f"{missing_years:.1f} fehlende Jahre → "
            f"Rentenminderung {(1-factor_p1)*100:.1f} %"
        )

    return {
        "monthly": monthly_results,
        "annual": annual_list,
        "summary": summary_results,
        "meta": {
            "p1_pension_date": p1_pension_date.strftime("%Y-%m"),
            "p1_abschlag_pct": round(abschlag_p1 * 100, 2),
            "p1_renten_stpfl_anteil_pct": round(p1_renten_stpfl_anteil * 100, 1),
            "p1_abschlagsfrei": p1_abschlagsfrei,
            "p1_abschlagsfrei_info": p1_abschlagsfrei_info,
            "p1_rente_faktor": round(factor_p1 * 100, 2),
        },
    }
