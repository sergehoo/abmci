"""
Statistiques et insights du tableau de bord Alliance Connect.

Le module expose deux fonctions :
- compute_period(request)        → résout la période choisie (start, end, label, prev_start, prev_end)
- build_dashboard_context(request, eglise)
                                  → renvoie un dict complet pour HomePageView

Hypothèses sur les modèles (vérifiées dans models.py) :
- Fidele.created_at / date_entree / date_bapteme / birthdate / situation_matrimoniale
        / sortie (1=parti) / is_deleted (1=inactif) / membre (0=visiteur, 1=actif, 2=FISS, 3=Sympathisant)
- Sacrement(type_sacrement IN {'BAP','MAR','...'}, date)
- Anniversaire(type_anniversaire='NAISS', date_anniversaire)
- Deces(date_deces, defunt)
- eden.Fiancailles(date_demande, date_ceremonie, statut)
- eden.Mariage(date_mariage)
- ProblemReport(category__slug='maladie' | 'deces', created_at)
- TransferHistory(date_transfert)
- Donation(status='success', amount, created_at)
"""
from __future__ import annotations

from calendar import monthrange
from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone


# ============================================================================
# 1) Résolution de période (filtre principal du dashboard)
# ============================================================================

PERIOD_LABELS = {
    'week':      'Cette semaine',
    'month':     'Ce mois-ci',
    'quarter':   'Ce trimestre',
    'semester':  'Ce semestre',
    'year':      'Cette année',
    'custom':    'Période personnalisée',
}


def _safe_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def compute_period(request) -> dict:
    """
    Lit ?period=... &from=YYYY-MM-DD &to=YYYY-MM-DD et retourne :
    {
        'period': str,
        'label': str,
        'start': date, 'end': date,
        'prev_start': date, 'prev_end': date,
        'date_from': str, 'date_to': str,
        'choices': [{value, label, active}, ...]
    }
    """
    today = timezone.localdate()
    period = (request.GET.get('period') or 'month').lower()
    if period not in PERIOD_LABELS:
        period = 'month'

    if period == 'week':
        # Lundi de la semaine courante
        start = today - timedelta(days=today.weekday())
        end   = start + timedelta(days=6)
    elif period == 'month':
        start = today.replace(day=1)
        last_day = monthrange(start.year, start.month)[1]
        end = start.replace(day=last_day)
    elif period == 'quarter':
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        # premier mois du trimestre suivant - 1 jour
        next_q_start_month = q * 3 + 4
        if next_q_start_month > 12:
            end = date(today.year, 12, 31)
        else:
            end = date(today.year, next_q_start_month, 1) - timedelta(days=1)
    elif period == 'semester':
        if today.month <= 6:
            start = date(today.year, 1, 1)
            end   = date(today.year, 6, 30)
        else:
            start = date(today.year, 7, 1)
            end   = date(today.year, 12, 31)
    elif period == 'year':
        start = date(today.year, 1, 1)
        end   = date(today.year, 12, 31)
    else:  # custom
        start = _safe_date(request.GET.get('from')) or today.replace(day=1)
        end   = _safe_date(request.GET.get('to'))   or today
        if end < start:
            start, end = end, start

    span = (end - start).days + 1
    prev_end   = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    choices = [
        {'value': k, 'label': v, 'active': k == period}
        for k, v in PERIOD_LABELS.items()
    ]

    return {
        'period':     period,
        'label':      PERIOD_LABELS[period],
        'start':      start,
        'end':        end,
        'prev_start': prev_start,
        'prev_end':   prev_end,
        'span_days':  span,
        'date_from':  start.isoformat(),
        'date_to':    end.isoformat(),
        'choices':    choices,
    }


# ============================================================================
# 2) Helpers communs
# ============================================================================

def _delta_pct(now_count: int, prev_count: int) -> dict:
    """Renvoie {'value': '+12 %', 'sign': 'up'|'down'|'flat'}."""
    if not prev_count:
        if now_count:
            return {'value': f"+{now_count}", 'sign': 'up'}
        return {'value': '', 'sign': 'flat'}
    diff = now_count - prev_count
    pct = round(diff / prev_count * 100)
    if pct > 0:
        return {'value': f"+{pct} %", 'sign': 'up'}
    if pct < 0:
        return {'value': f"{pct} %", 'sign': 'down'}
    return {'value': '0 %', 'sign': 'flat'}


def _count_in_range(qs, field: str, start: date, end: date) -> int:
    """count() filtré sur [start..end] (inclusif). field peut être DateField ou DateTimeField."""
    return qs.filter(**{f"{field}__gte": start, f"{field}__lte": end}).count()


def _sum_in_range(qs, date_field: str, value_field: str, start, end) -> int:
    return qs.filter(**{f"{date_field}__gte": start, f"{date_field}__lte": end}) \
             .aggregate(total=Sum(value_field))['total'] or 0


# ============================================================================
# 3) Construction du contexte
# ============================================================================

def build_dashboard_context(request, eglise=None) -> dict:
    """
    eglise : objet Eglise pour filtrer le périmètre, ou None pour le réseau entier.
    """
    # Imports locaux pour éviter les dépendances circulaires
    from fidele.models import (
        Fidele, Sacrement, Anniversaire, Deces, ProblemReport,
        TransferHistory, Donation, Department,
    )
    try:
        from event.models import Evenement
    except Exception:  # pragma: no cover
        Evenement = None
    try:
        from eden.models import Fiancailles, Mariage
    except Exception:  # pragma: no cover
        Fiancailles = Mariage = None

    period = compute_period(request)
    start, end       = period['start'], period['end']
    prev_start, prev_end = period['prev_start'], period['prev_end']
    today = timezone.localdate()

    # Périmètre
    fideles_qs = Fidele.objects.all()
    if eglise is not None:
        fideles_qs = fideles_qs.filter(eglise=eglise)

    sacrements_qs = Sacrement.objects.filter(fidele__in=fideles_qs)
    naissances_qs = Anniversaire.objects.filter(
        type_anniversaire='NAISS', fidele__in=fideles_qs,
    )
    deces_qs      = Deces.objects.filter(defunt__in=fideles_qs)
    fiancailles_qs = Fiancailles.objects.filter(
        Q(homme__in=fideles_qs) | Q(femme__in=fideles_qs)
    ) if Fiancailles else None
    mariages_eden_qs = Mariage.objects.filter(couple__in=fideles_qs).distinct() \
        if Mariage else None
    transfers_qs    = TransferHistory.objects.filter(fidele__in=fideles_qs)
    problems_qs     = ProblemReport.objects.filter(reporter__in=fideles_qs)
    donations_qs    = Donation.objects.filter(status='success')
    if eglise is not None:
        donations_qs = donations_qs.filter(user__fidele__eglise=eglise)
    events_qs = Evenement.objects.all() if Evenement else None
    if events_qs is not None and eglise is not None:
        events_qs = events_qs.filter(eglise=eglise)

    # ============================================================
    # 3.1 — KPIs principaux (sur la période)
    # ============================================================
    nouveaux_now  = _count_in_range(fideles_qs, 'created_at', start, end)
    nouveaux_prev = _count_in_range(fideles_qs, 'created_at', prev_start, prev_end)

    visit_now  = _count_in_range(fideles_qs.filter(membre=0), 'created_at', start, end)
    visit_prev = _count_in_range(fideles_qs.filter(membre=0), 'created_at', prev_start, prev_end)

    actif_now  = fideles_qs.filter(membre=1, is_deleted=0).count()
    actif_prev = actif_now  # pas de delta historique simple

    dons_now  = _sum_in_range(donations_qs, 'created_at', 'amount', start, end)
    dons_prev = _sum_in_range(donations_qs, 'created_at', 'amount', prev_start, prev_end)

    kpis_main = {
        'nouveaux':       {'value': nouveaux_now,  'delta': _delta_pct(nouveaux_now,  nouveaux_prev)},
        'visiteurs':      {'value': visit_now,     'delta': _delta_pct(visit_now,     visit_prev)},
        'membres_actifs': {'value': actif_now,     'delta': _delta_pct(actif_now,     actif_prev)},
        'dons':           {
            'value': f"{int(dons_now):,}".replace(',', ' '),
            'amount_raw': int(dons_now),
            'currency': 'FCFA',
            'delta': _delta_pct(int(dons_now), int(dons_prev)),
        },
    }

    # ============================================================
    # 3.2 — Sacrements (sur la période)
    # ============================================================
    bapt_now  = sacrements_qs.filter(type_sacrement='BAP', date__gte=start, date__lte=end).count()
    bapt_prev = sacrements_qs.filter(type_sacrement='BAP', date__gte=prev_start, date__lte=prev_end).count()

    if mariages_eden_qs is not None:
        mar_now  = mariages_eden_qs.filter(date_mariage__gte=start, date_mariage__lte=end).count()
        mar_prev = mariages_eden_qs.filter(date_mariage__gte=prev_start, date_mariage__lte=prev_end).count()
    else:
        mar_now  = sacrements_qs.filter(type_sacrement='MAR', date__gte=start, date__lte=end).count()
        mar_prev = sacrements_qs.filter(type_sacrement='MAR', date__gte=prev_start, date__lte=prev_end).count()

    if fiancailles_qs is not None:
        fia_now  = _count_in_range(fiancailles_qs, 'date_demande', start, end)
        fia_prev = _count_in_range(fiancailles_qs, 'date_demande', prev_start, prev_end)
        fia_en_cours = fiancailles_qs.filter(statut='En cours').count()
    else:
        fia_now = fia_prev = fia_en_cours = 0

    sacrements = {
        'baptemes':        {'value': bapt_now, 'delta': _delta_pct(bapt_now, bapt_prev)},
        'mariages':        {'value': mar_now,  'delta': _delta_pct(mar_now,  mar_prev)},
        'fiancailles':     {'value': fia_now,  'delta': _delta_pct(fia_now,  fia_prev),
                            'en_cours': fia_en_cours},
    }

    # ============================================================
    # 3.3 — Démographie
    # ============================================================
    naiss_now  = _count_in_range(naissances_qs, 'date_anniversaire', start, end)
    naiss_prev = _count_in_range(naissances_qs, 'date_anniversaire', prev_start, prev_end)
    deces_now  = _count_in_range(deces_qs,      'date_deces',         start, end)
    deces_prev = _count_in_range(deces_qs,      'date_deces',         prev_start, prev_end)

    maladies_now = problems_qs.filter(
        category__slug='maladie',
        created_at__gte=start, created_at__lte=end,
    ).count()
    maladies_prev = problems_qs.filter(
        category__slug='maladie',
        created_at__gte=prev_start, created_at__lte=prev_end,
    ).count()

    demographie = {
        'naissances': {'value': naiss_now, 'delta': _delta_pct(naiss_now, naiss_prev)},
        'deces':      {'value': deces_now, 'delta': _delta_pct(deces_now, deces_prev)},
        'maladies':   {'value': maladies_now, 'delta': _delta_pct(maladies_now, maladies_prev)},
    }

    # ============================================================
    # 3.4 — Engagement / mouvements
    # ============================================================
    partis      = fideles_qs.filter(sortie=1).count()
    inactifs    = fideles_qs.filter(is_deleted=1).count()
    transferts  = _count_in_range(transfers_qs, 'date_transfert', start, end)
    transferts_prev = _count_in_range(transfers_qs, 'date_transfert', prev_start, prev_end)

    # Divorces / séparations approximés via situation_matrimoniale
    divorces_count = fideles_qs.filter(
        situation_matrimoniale__in=('VEUF', 'VEUF ',),
    ).count()

    engagement = {
        'partis':     {'value': partis,     'delta': {'value': '', 'sign': 'flat'}},
        'inactifs':   {'value': inactifs,   'delta': {'value': '', 'sign': 'flat'}},
        'transferts': {'value': transferts, 'delta': _delta_pct(transferts, transferts_prev)},
        'divorces':   {'value': divorces_count, 'delta': {'value': '', 'sign': 'flat'},
                       'note': "Cumul actuel — situation matrimoniale 'séparé/veuf'"},
    }

    # ============================================================
    # 3.5 — Séries temporelles (12 derniers mois) pour les charts
    # ============================================================
    months_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
                 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

    first_of_month = today.replace(day=1)
    months = []
    for i in range(11, -1, -1):
        y, m = first_of_month.year, first_of_month.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))

    chart_labels = []
    series_baptemes  = []
    series_mariages  = []
    series_fiancailles = []
    series_naissances  = []
    series_deces       = []
    series_membres_cum = []

    for (y, m) in months:
        ms = date(y, m, 1)
        me = date(y, m, monthrange(y, m)[1])
        chart_labels.append(months_fr[m - 1])
        series_baptemes.append(
            sacrements_qs.filter(type_sacrement='BAP', date__gte=ms, date__lte=me).count()
        )
        if mariages_eden_qs is not None:
            series_mariages.append(
                mariages_eden_qs.filter(date_mariage__gte=ms, date_mariage__lte=me).count()
            )
        else:
            series_mariages.append(
                sacrements_qs.filter(type_sacrement='MAR', date__gte=ms, date__lte=me).count()
            )
        if fiancailles_qs is not None:
            series_fiancailles.append(
                fiancailles_qs.filter(date_demande__gte=ms, date_demande__lte=me).count()
            )
        else:
            series_fiancailles.append(0)
        series_naissances.append(
            naissances_qs.filter(date_anniversaire__gte=ms, date_anniversaire__lte=me).count()
        )
        series_deces.append(
            deces_qs.filter(date_deces__gte=ms, date_deces__lte=me).count()
        )
        next_start = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
        series_membres_cum.append(fideles_qs.filter(created_at__lt=next_start).count())

    # Répartition par âge des fidèles (donut)
    ages = []
    for f in fideles_qs.exclude(birthdate__isnull=True).values_list('birthdate', flat=True):
        ages.append((today - f).days // 365)

    age_buckets = OrderedDict([
        ('0-11',  0), ('12-17', 0), ('18-29', 0),
        ('30-44', 0), ('45-59', 0), ('60+',   0),
    ])
    for a in ages:
        if   a < 12:  age_buckets['0-11']  += 1
        elif a < 18:  age_buckets['12-17'] += 1
        elif a < 30:  age_buckets['18-29'] += 1
        elif a < 45:  age_buckets['30-44'] += 1
        elif a < 60:  age_buckets['45-59'] += 1
        else:         age_buckets['60+']   += 1

    # Répartition genre
    gender = {
        'homme':   fideles_qs.filter(sexe='Homme').count(),
        'femme':   fideles_qs.filter(sexe='Femme').count(),
        'inconnu': fideles_qs.filter(sexe__isnull=True).count() + fideles_qs.filter(sexe='').count(),
    }

    # Répartition statut matrimonial
    marital = (fideles_qs
               .exclude(situation_matrimoniale__isnull=True)
               .exclude(situation_matrimoniale='')
               .values('situation_matrimoniale')
               .annotate(c=Count('id'))
               .order_by('-c'))
    marital_data = {row['situation_matrimoniale'].strip(): row['c'] for row in marital}

    charts = {
        'labels': chart_labels,
        'baptemes':       series_baptemes,
        'mariages':       series_mariages,
        'fiancailles':    series_fiancailles,
        'naissances':     series_naissances,
        'deces':          series_deces,
        'membres_cum':    series_membres_cum,
        'age_labels':     list(age_buckets.keys()),
        'age_values':     list(age_buckets.values()),
        'gender':         gender,
        'marital':        marital_data,
    }

    # ============================================================
    # 3.6 — Activité récente (sur la période)
    # ============================================================
    activity = []
    for f in fideles_qs.filter(created_at__gte=start, created_at__lte=end) \
                       .order_by('-created_at')[:5]:
        activity.append({
            'kind': 'fidele', 'tone': 'emerald',
            'title': f"Nouveau fidèle : {f}",
            'when':  f.created_at,
        })
    for s in sacrements_qs.filter(date__gte=start, date__lte=end) \
                          .order_by('-date')[:5]:
        verbe = {'BAP': 'Baptême', 'MAR': 'Mariage', 'CEN': 'Sainte Cène',
                 'ONC': 'Onction', 'REC': 'Réconciliation'}.get(s.type_sacrement, 'Sacrement')
        activity.append({
            'kind': 'sacrement', 'tone': 'brand',
            'title': f"{verbe} de {s.fidele}",
            'when':  datetime.combine(s.date, datetime.min.time(), tzinfo=timezone.get_current_timezone()),
        })
    for d in deces_qs.filter(date_deces__gte=start, date_deces__lte=end) \
                     .order_by('-date_deces')[:3]:
        activity.append({
            'kind': 'deces', 'tone': 'rose',
            'title': f"Décès de {d.defunt}",
            'when':  datetime.combine(d.date_deces, datetime.min.time(), tzinfo=timezone.get_current_timezone()),
        })
    activity.sort(key=lambda x: x['when'], reverse=True)
    activity = activity[:8]

    # ============================================================
    # 3.7 — Insights automatiques (analyse intelligente)
    # ============================================================
    insights = generate_insights(
        kpis_main, sacrements, demographie, engagement, charts,
        period_label=period['label'],
    )

    # ============================================================
    # 3.8 — Membres récents (pour la card en bas)
    # ============================================================
    membres_recents = (
        fideles_qs.select_related('user')
                  .order_by('-created_at')[:6]
    )

    return {
        'period':         period,
        'kpis_main':      kpis_main,
        'sacrements':     sacrements,
        'demographie':    demographie,
        'engagement':     engagement,
        'charts':         charts,
        'activity':       activity,
        'insights':       insights,
        'membres_recents': membres_recents,
    }


# ============================================================================
# 4) Insights (analyse automatique – règles déterministes)
# ============================================================================

def generate_insights(kpis_main, sacrements, demographie, engagement, charts,
                      period_label: str) -> list[dict]:
    """
    Produit 3 à 5 insights factuels basés sur les chiffres.
    Chaque insight = {
        'tone':  'positive'|'warning'|'neutral'|'critical',
        'icon':  identifiant Lucide / SVG inline (ex: 'trending-up')
        'title': str (court),
        'text':  str (1-2 phrases),
    }
    """
    out: list[dict] = []

    def add(tone, icon, title, text):
        out.append({'tone': tone, 'icon': icon, 'title': title, 'text': text})

    # 1) Croissance des fidèles
    nv = kpis_main.get('nouveaux', {})
    delta_nv = nv.get('delta', {})
    if delta_nv.get('sign') == 'up' and nv.get('value', 0) >= 1:
        add('positive', 'trending-up',
            "Croissance soutenue",
            f"{nv['value']} nouvelle(s) inscription(s) sur la période ({delta_nv['value']} vs précédent). "
            "C'est un signal positif : capitalisez avec un suivi rapide des nouveaux fidèles.")
    elif delta_nv.get('sign') == 'down' and nv.get('value', 0) == 0:
        add('warning', 'alert-triangle',
            "Aucune nouvelle inscription",
            f"Aucun nouveau fidèle enregistré sur {period_label.lower()}. "
            "Envisagez une action d'évangélisation ou un événement d'invitation.")

    # 2) Sacrements
    bp = sacrements['baptemes']
    if bp['value'] > 0 and bp['delta'].get('sign') == 'up':
        add('positive', 'sparkles',
            "Pic de baptêmes",
            f"{bp['value']} baptême(s) célébré(s) ({bp['delta']['value']} vs période précédente). "
            "Préparez-vous à intégrer ces nouveaux baptisés dans la vie communautaire.")
    elif bp['value'] == 0:
        add('neutral', 'info',
            "Pas de baptême sur la période",
            "Aucun baptême enregistré. Vérifiez les sessions de préparation au baptême en cours.")

    # 3) Mariages / fiançailles
    fi = sacrements['fiancailles']
    if fi['en_cours'] > 0:
        add('positive', 'heart',
            "Couples en préparation",
            f"{fi['en_cours']} dossier(s) de fiançailles en cours. "
            "Pensez à programmer les sessions de préparation manquantes.")

    mar = sacrements['mariages']
    if mar['value'] > 0:
        add('positive', 'gift',
            "Mariages célébrés",
            f"{mar['value']} mariage(s) célébré(s). "
            "Pensez à un suivi pastoral du jeune couple à 3 et 6 mois.")

    # 4) Démographie
    de = demographie['deces']
    if de['value'] > 0:
        add('critical', 'alert-octagon',
            f"{de['value']} décès enregistré(s)",
            "Activez le protocole d'accompagnement pastoral des familles endeuillées.")
    md = demographie['maladies']
    if md['value'] >= 3:
        add('warning', 'activity',
            "Hausse des signalements de maladie",
            f"{md['value']} signalements de maladie sur la période. "
            "Coordonnez l'équipe de visites de réconfort.")

    # 5) Engagement / désengagement
    inactifs = engagement['inactifs']['value']
    if inactifs >= 5:
        add('warning', 'user-x',
            f"{inactifs} fidèle(s) inactif(s)",
            "Lancez une campagne de réengagement (appel personnel, visite à domicile).")

    transferts = engagement['transferts']['value']
    if transferts >= 1:
        add('neutral', 'arrow-right-left',
            f"{transferts} transfert(s) inter-églises",
            "Vérifiez la coordination avec les églises partenaires sur le suivi de ces fidèles.")

    # 6) Dons
    dons_raw = kpis_main['dons'].get('amount_raw', 0)
    dons_delta = kpis_main['dons']['delta']
    if dons_raw > 0 and dons_delta.get('sign') == 'up':
        add('positive', 'hand-coins',
            "Dons en hausse",
            f"Total des dons réussis : {kpis_main['dons']['value']} {kpis_main['dons']['currency']} "
            f"({dons_delta['value']} vs précédent).")
    elif dons_raw == 0:
        add('neutral', 'wallet',
            "Aucun don sur la période",
            "Pensez à rappeler aux fidèles l'importance de la libéralité ou à activer la campagne mensuelle.")

    # Limiter à 5 insights max
    return out[:5]
