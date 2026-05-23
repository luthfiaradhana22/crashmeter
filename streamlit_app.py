import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os
from datetime import datetime, timedelta
from html.parser import HTMLParser

# ─────────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Crashmeter v3.0",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}
.stApp { background-color: #0a0e1a; }

/* Header */
.cm-header { 
    border-bottom: 1px solid #1e2d45; 
    padding-bottom: 1rem; 
    margin-bottom: 1.5rem;
}
.cm-title { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.1rem; font-weight: 500; 
    color: #4a9eff; letter-spacing: 0.05em;
    margin: 0;
}
.cm-subtitle { color: #4a5568; font-size: 0.8rem; margin: 2px 0 0; }

/* Score display */
.score-block {
    background: #0f1629;
    border: 1px solid #1e2d45;
    border-radius: 12px;
    padding: 1.5rem;
    text-align: center;
}
.score-num { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 4rem; font-weight: 500; line-height: 1;
}
.score-denom { font-size: 1.5rem; color: #4a5568; }
.score-badge {
    display: inline-block;
    padding: 4px 16px; border-radius: 20px;
    font-size: 0.78rem; font-weight: 500;
    margin-top: 8px; letter-spacing: 0.03em;
}

/* Param cards */
.param-card {
    background: #0f1629;
    border: 1px solid #1e2d45;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 10px;
}
.param-card.danger { border-left: 3px solid #ef4444; }
.param-card.safe   { border-left: 3px solid #22c55e; }
.param-card.warn   { border-left: 3px solid #eab308; }
.param-id { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem; color: #4a5568; letter-spacing: 0.08em;
}
.param-name { font-size: 0.85rem; color: #94a3b8; margin: 2px 0; }
.param-value { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.4rem; font-weight: 500; margin: 2px 0;
}
.param-zona { font-size: 0.75rem; color: #64748b; }

/* Log table */
.log-table { 
    font-family: 'IBM Plex Mono', monospace; 
    font-size: 0.8rem;
}

/* Misc */
.stButton button {
    background: #1e2d45 !important;
    color: #4a9eff !important;
    border: 1px solid #2d4a6e !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
    border-radius: 8px !important;
}
.stButton button:hover {
    background: #2d4a6e !important;
}
[data-testid="stSidebar"] {
    background-color: #080c18 !important;
    border-right: 1px solid #1e2d45;
}
</style>
""", unsafe_allow_html=True)

LOG_FILE = "crashmeter_log.csv"

# ─────────────────────────────────────────────
#  SIDEBAR — CONFIG
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Config")
    
    fred_key = st.text_input(
        "FRED API Key",
        value=st.secrets.get("FRED_API_KEY", ""),
        type="password",
        help="Daftar gratis di fred.stlouisfed.org"
    )
    
    inversion_end = st.date_input(
        "Tanggal inversi berakhir",
        value=datetime(2026, 3, 1),
        help="Update manual jika ada inversi baru"
    )
    
    st.markdown("---")
    st.markdown("### 📖 Panduan skor")
    st.markdown("""
    | Skor | Status |
    |------|--------|
    | 0–1  | ✅ Aman |
    | 2    | ⚠️ Waspada |
    | 3    | 🚨 Exit window |
    | 4    | 🔴 Critical |
    """)
    
    st.markdown("---")
    st.markdown("### ⚠️ Limitasi")
    st.markdown("""
    <div style='font-size:0.78rem; color:#4a5568; line-height:1.6'>
    Tidak mendeteksi:<br>
    • Event-triggered (Covid, geopolitik)<br>
    • Private Credit crisis<br>
    Pantau HY OAS spike tiba-tiba sebagai early warning tambahan.
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  DATA FETCHING
# ─────────────────────────────────────────────
def fred_get(series_id, api_key, n_obs=5, start_date=None):
    url = 'https://api.stlouisfed.org/fred/series/observations'
    p = {'series_id': series_id, 'api_key': api_key,
         'file_type': 'json', 'sort_order': 'desc', 'limit': n_obs}
    if start_date:
        p.update({'observation_start': start_date, 'sort_order': 'asc', 'limit': 10})
    r = requests.get(url, params=p, timeout=15)
    r.raise_for_status()
    obs = r.json().get('observations', [])
    return [(o['date'], float(o['value'])) for o in obs if o['value'] not in ('.', 'nan')]

def get_cape():
    class P(HTMLParser):
        def __init__(self):
            super().__init__(); self.cap = False; self.val = None
        def handle_starttag(self, tag, attrs):
            if dict(attrs).get('id') == 'current-value': self.cap = True
        def handle_data(self, d):
            if self.cap and self.val is None:
                s = d.strip().replace(',', '')
                if s:
                    try: self.val = float(s)
                    except: pass
                    self.cap = False
    try:
        r = requests.get('https://www.multpl.com/shiller-pe',
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        parser = P(); parser.feed(r.text)
        return parser.val
    except:
        return None

@st.cache_data(ttl=3600)  # cache 1 jam
def fetch_all_data(api_key, inversion_end_str):
    results = {}
    errors  = []

    try:
        yc = fred_get('T10Y3M', api_key)
        results['t10y3m']   = yc[0][1]
        results['yc_date']  = yc[0][0]
    except Exception as e:
        errors.append(f"T10Y3M: {e}")
        results['t10y3m'] = None

    try:
        hy = fred_get('BAMLH0A0HYM2', api_key)
        results['hy_now']  = hy[0][1]
        results['hy_date'] = hy[0][0]
        six_m = (datetime.today() - timedelta(days=182)).strftime('%Y-%m-%d')
        hy6   = fred_get('BAMLH0A0HYM2', api_key, start_date=six_m)
        results['hy_6m']   = hy6[0][1] if hy6 else hy[0][1]
    except Exception as e:
        errors.append(f"HY OAS: {e}")
        results['hy_now'] = results['hy_6m'] = None

    cape = get_cape()
    if cape is None and os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE)
        if 'cape' in df.columns and len(df):
            cape = float(df['cape'].iloc[-1])
    results['cape'] = cape or 41.66

    results['errors'] = errors
    return results

# ─────────────────────────────────────────────
#  SCORING
# ─────────────────────────────────────────────
def hitung_skor(t10y3m, hy_now, hy_6m, cape, inversion_end):
    params = {}

    a1 = 0 if t10y3m > 0.5 else 1
    if t10y3m > 1.0:   zona = 'Aman'
    elif t10y3m > 0.5: zona = 'Transisi (0.5–1.0)'
    else:              zona = 'BERBAHAYA'
    params['A1'] = {'label': 'Yield Curve T10Y-3M', 'nilai': f'{t10y3m:.3f}',
                    'skor': a1, 'zona': zona, 'severity': 'danger' if a1 else 'safe'}

    months = (datetime.today() - inversion_end).days / 30.4
    a2 = 1 if months < 18 else 0
    params['A2'] = {'label': 'Pasca-inversi 18 bln', 'nilai': f'{months:.1f} bln',
                    'skor': a2, 'zona': f'Sisa {max(0,18-months):.1f} bln lagi' if a2 else 'Sudah >18 bln',
                    'severity': 'danger' if a2 else 'safe'}

    vel_bps = abs((hy_now - hy_6m) * 100)
    b1 = 0 if vel_bps < 150 else 1
    params['B1'] = {'label': 'HY OAS Velocity (6 bln)', 'nilai': f'{vel_bps:.0f} bps',
                    'skor': b1, 'zona': 'Aman (<150 bps)' if b1 == 0 else '🚨 SPIKE >150 bps!',
                    'severity': 'danger' if b1 else 'safe'}

    hy_bps = hy_now * 100
    b2 = 0 if hy_bps < 550 else 1
    params['B2'] = {'label': 'HY OAS Level', 'nilai': f'{hy_bps:.0f} bps',
                    'skor': b2, 'zona': 'Aman (<550 bps)' if b2 == 0 else '🚨 DANGER >550 bps!',
                    'severity': 'danger' if b2 else 'safe'}

    c = 1 if cape > 35 else 0
    params['C'] = {'label': 'Shiller CAPE', 'nilai': f'{cape:.2f}',
                   'skor': c, 'zona': f'Overvalued — Dotcom peak: 44.19' if c else 'Aman (<35)',
                   'severity': 'danger' if c else ('warn' if cape > 30 else 'safe')}

    total = sum(p['skor'] for p in params.values())
    return params, total

def status_info(total):
    return [
        ('✅ AMAN',          '#22c55e', '#052e16'),
        ('✅ AMAN',          '#22c55e', '#052e16'),
        ('⚠️  WASPADA',      '#eab308', '#1c1200'),
        ('🚨 EXIT WINDOW',   '#f97316', '#1c0a00'),
        ('🔴 CRITICAL',      '#ef4444', '#1c0000'),
    ][min(total, 4)]

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
def simpan_log(params, total, t10y3m, hy_now, hy_6m, cape, inv_end):
    status, _, _ = status_info(total)
    row = {
        'date': datetime.today().strftime('%Y-%m-%d'),
        'inversion_end': inv_end,
        't10y3m': round(t10y3m, 4),
        'hy_oas_pct': round(hy_now, 4),
        'hy_oas_6m_pct': round(hy_6m, 4),
        'cape': round(cape, 2),
        **{f'skor_{k.lower()}': v['skor'] for k, v in params.items()},
        'total': total,
        'status': status
    }
    df_new = pd.DataFrame([row])
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE)
        df = df[df['date'] != row['date']]
        df = pd.concat([df, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(LOG_FILE, index=False)
    return df

# ─────────────────────────────────────────────
#  GAUGE CHART
# ─────────────────────────────────────────────
def buat_gauge(total):
    fig, ax = plt.subplots(figsize=(5, 3))
    fig.patch.set_facecolor('#0f1629')
    ax.set_facecolor('#0f1629')
    ax.axis('off')
    ax.set_aspect('equal')

    for start, end, color in [(0,1,'#22c55e'),(1,2,'#eab308'),(2,3,'#f97316'),(3,4,'#ef4444')]:
        t = np.linspace(np.pi-(start/4)*np.pi, np.pi-(end/4)*np.pi, 60)
        ro, ri = 0.88, 0.52
        ax.fill(np.concatenate([np.cos(t)*ro, np.cos(t[::-1])*ri]),
                np.concatenate([np.sin(t)*ro, np.sin(t[::-1])*ri]),
                color=color, alpha=0.9)

    # Tick marks
    for i in range(5):
        angle = np.pi - (i/4)*np.pi
        ax.plot([np.cos(angle)*0.89, np.cos(angle)*0.96],
                [np.sin(angle)*0.89, np.sin(angle)*0.96],
                color='#0f1629', lw=2)

    angle = np.pi - (min(total,4)/4)*np.pi
    ax.annotate('', xy=(np.cos(angle)*0.72, np.sin(angle)*0.72), xytext=(0,0),
                arrowprops=dict(arrowstyle='->', color='white', lw=2.5))
    ax.add_patch(plt.Circle((0,0), 0.07, color='white', zorder=5))

    clr = ['#22c55e','#22c55e','#eab308','#f97316','#ef4444'][min(total,4)]
    ax.text(0, -0.18, f'{total}/4', ha='center', color=clr, fontsize=28, fontweight='bold',
            fontfamily='monospace')

    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-0.4, 1.05)
    plt.tight_layout(pad=0)
    return fig

# ─────────────────────────────────────────────
#  MAIN UI
# ─────────────────────────────────────────────
st.markdown('<div class="cm-header"><p class="cm-title">CRASHMETER v3.0</p><p class="cm-subtitle">Market Crash Risk Indicator — S&P500 Systemic Analysis</p></div>', unsafe_allow_html=True)

if not fred_key:
    st.warning("Masukkan FRED API Key di sidebar untuk mulai. Daftar gratis di [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)")
    st.stop()

# Refresh button
col_refresh, col_time = st.columns([1, 4])
with col_refresh:
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()

# Fetch
with st.spinner("Mengambil data dari FRED..."):
    inv_end_str = inversion_end.strftime('%Y-%m-%d')
    data = fetch_all_data(fred_key, inv_end_str)

if data['errors']:
    for e in data['errors']:
        st.error(f"Error fetching {e}")

if data['t10y3m'] is None or data['hy_now'] is None:
    st.error("Gagal ambil data dari FRED. Cek API key atau koneksi.")
    st.stop()

params, total = hitung_skor(
    data['t10y3m'], data['hy_now'], data['hy_6m'],
    data['cape'], inversion_end
)
status_label, status_color, status_bg = status_info(total)

# Auto-save log
df_log = simpan_log(params, total, data['t10y3m'], data['hy_now'],
                    data['hy_6m'], data['cape'], inv_end_str)

# ── Layout utama ──
col_gauge, col_params = st.columns([1, 2], gap="large")

with col_gauge:
    st.pyplot(buat_gauge(total), use_container_width=True)
    st.markdown(f"""
    <div style='text-align:center; margin-top:-10px'>
        <span class="score-badge" style="background:{status_bg}; color:{status_color}; border:1px solid {status_color}33">
            {status_label}
        </span>
    </div>
    <div style='text-align:center; margin-top:12px; font-size:0.75rem; color:#4a5568'>
        Data per {data.get('yc_date','—')}
    </div>
    """, unsafe_allow_html=True)

with col_params:
    for key, p in params.items():
        icon = "🔴" if p['skor'] else "🟢"
        color = "#ef4444" if p['skor'] else "#22c55e"
        val_color = "#ef4444" if p['skor'] else "#4a9eff"
        st.markdown(f"""
        <div class="param-card {p['severity']}">
            <div style="display:flex; justify-content:space-between; align-items:flex-start">
                <div>
                    <div class="param-id">{key}</div>
                    <div class="param-name">{p['label']}</div>
                    <div class="param-value" style="color:{val_color}">{p['nilai']}</div>
                    <div class="param-zona">{p['zona']}</div>
                </div>
                <div style="font-size:1.4rem">{icon}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── Trend chart ──
st.markdown("---")
st.markdown("#### 📈 Trend skor")

if len(df_log) > 1:
    df_trend = df_log.copy()
    df_trend['date'] = pd.to_datetime(df_trend['date'])
    df_trend = df_trend.sort_values('date')

    fig2, ax2 = plt.subplots(figsize=(12, 3.5))
    fig2.patch.set_facecolor('#0f1629')
    ax2.set_facecolor('#0f1629')

    ax2.step(df_trend['date'], df_trend['total'], color='#4a9eff', lw=2, where='post')
    ax2.fill_between(df_trend['date'], df_trend['total'], step='post', alpha=0.12, color='#4a9eff')
    ax2.axhline(3, color='#f97316', lw=1, ls='--', alpha=0.7, label='Exit window (3)')
    ax2.axhline(2, color='#eab308', lw=1, ls='--', alpha=0.7, label='Waspada (2)')

    ax2.set_ylim(-0.3, 4.5)
    ax2.set_yticks([0,1,2,3,4])
    ax2.set_yticklabels(['0','1','2','3','4'], color='#4a5568', fontsize=9, fontfamily='monospace')
    ax2.tick_params(colors='#4a5568', labelsize=9)
    for sp in ax2.spines.values(): sp.set_color('#1e2d45')
    ax2.legend(loc='upper left', facecolor='#0f1629', edgecolor='#1e2d45',
               labelcolor='#94a3b8', fontsize=8)
    plt.tight_layout()
    st.pyplot(fig2, use_container_width=True)
else:
    st.caption("Trend akan muncul setelah ada lebih dari 1 data. Buka lagi besok! 📅")

# ── Log table ──
st.markdown("---")
st.markdown("#### 🗂️ Riwayat")

if len(df_log):
    display_cols = ['date','t10y3m','hy_oas_pct','cape','total','status']
    available = [c for c in display_cols if c in df_log.columns]
    st.dataframe(
        df_log[available].sort_values('date', ascending=False).head(30),
        use_container_width=True,
        hide_index=True
    )
    csv = df_log.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Download log CSV", csv, "crashmeter_log.csv", "text/csv")
