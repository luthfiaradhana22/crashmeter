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
.stApp { background-color: #f8f9fa; }

/* Header */
.cm-header { 
    border-bottom: 1px solid #e2e8f0; 
    padding-bottom: 1rem; 
    margin-bottom: 1.5rem;
}
.cm-title { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.1rem; font-weight: 500; 
    color: #1a56db; letter-spacing: 0.05em;
    margin: 0;
}
.cm-subtitle { color: #64748b; font-size: 0.8rem; margin: 2px 0 0; }

/* Score display */
.score-block {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1.5rem;
    text-align: center;
}
.score-num { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 4rem; font-weight: 500; line-height: 1;
}
.score-denom { font-size: 1.5rem; color: #94a3b8; }
.score-badge {
    display: inline-block;
    padding: 4px 16px; border-radius: 20px;
    font-size: 0.78rem; font-weight: 500;
    margin-top: 8px; letter-spacing: 0.03em;
}

/* Param cards */
.param-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 10px;
}
.param-card.danger { border-left: 3px solid #ef4444; }
.param-card.safe   { border-left: 3px solid #22c55e; }
.param-card.warn   { border-left: 3px solid #eab308; }
.param-id { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem; color: #94a3b8; letter-spacing: 0.08em;
}
.param-name { font-size: 0.85rem; color: #475569; margin: 2px 0; }
.param-value { 
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.4rem; font-weight: 500; margin: 2px 0;
}
.param-zona { font-size: 0.75rem; color: #94a3b8; }

/* Log table */
.log-table { 
    font-family: 'IBM Plex Mono', monospace; 
    font-size: 0.8rem;
}

/* Misc */
.stButton button {
    background: #ffffff !important;
    color: #1a56db !important;
    border: 1px solid #bfdbfe !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
    border-radius: 8px !important;
}
.stButton button:hover {
    background: #eff6ff !important;
}
[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #e2e8f0;
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
    
    # inversion_end ditentukan otomatis dari FRED data (lihat detect_inversion_end)
    st.info("📡 Tanggal akhir inversi ditentukan otomatis dari data FRED.", icon=None)
    
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
    <div style='font-size:0.78rem; color:#64748b; line-height:1.6'>
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

def detect_inversion_end(api_key):
    """
    Cari tanggal terakhir T10Y-3M crossover dari negatif ke positif.
    Ambil 4 tahun data, scan dari belakang, cari titik pertama
    di mana nilai berubah dari < 0 ke >= 0.
    """
    start = (datetime.today() - timedelta(days=4*365)).strftime('%Y-%m-%d')
    data = fred_get('T10Y3M', api_key, n_obs=1200, start_date=start)
    if not data:
        return None, None

    # data urut ascending (start_date mode)
    df = pd.DataFrame(data, columns=['date', 'value'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Scan dari akhir ke awal — cari crossover terakhir: sebelumnya < 0, sesudahnya >= 0
    inv_end_date = None
    for i in range(len(df)-1, 0, -1):
        if df.loc[i, 'value'] >= 0 and df.loc[i-1, 'value'] < 0:
            inv_end_date = df.loc[i, 'date'].date()
            break

    # Cek apakah saat ini masih inverted
    currently_inverted = df.iloc[-1]['value'] < 0

    return inv_end_date, currently_inverted


@st.cache_data(ttl=3600)  # cache 1 jam
def fetch_all_data(api_key):
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

    try:
        inv_end, currently_inverted = detect_inversion_end(api_key)
        results['inversion_end']        = inv_end
        results['currently_inverted']   = currently_inverted
    except Exception as e:
        errors.append(f"Inversion detection: {e}")
        results['inversion_end']      = None
        results['currently_inverted'] = False

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

    months = (datetime.today().date() - inversion_end).days / 30.4
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
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#ffffff')
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
                color='#ffffff', lw=2)

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
    data = fetch_all_data(fred_key)

# Tentukan inversion_end: otomatis dari FRED, fallback ke hardcoded
inversion_end = data.get('inversion_end')
if inversion_end is None:
    inversion_end = datetime(2026, 3, 1).date()
    st.warning("⚠️ Gagal deteksi otomatis tanggal akhir inversi — menggunakan fallback Mar 2026.")
inv_end_str = inversion_end.strftime('%Y-%m-%d')

# Tampilkan info inversi di sidebar
with st.sidebar:
    st.markdown("---")
    st.markdown("### 📅 Inversi yield curve")
    if data.get('currently_inverted'):
        st.error("🔴 Yield curve **masih inverted** saat ini")
    elif inversion_end:
        months_since = (datetime.today().date() - inversion_end).days / 30.4
        months_left  = max(0, 18 - months_since)
        st.markdown(f"**Inversi berakhir:** {inversion_end.strftime('%d %b %Y')}")
        st.markdown(f"**Sudah:** {months_since:.1f} bulan")
        if months_left > 0:
            st.warning(f"⚠️ Sisa waspada: **{months_left:.1f} bln** lagi")
        else:
            st.success("✅ Periode 18 bln sudah lewat")
    else:
        st.caption("Data inversi tidak tersedia")

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


# ── Tabs ──
tab1, tab2 = st.tabs(["📊 Dashboard", "🔬 Backtesting"])

with tab1:
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
        <div style='text-align:center; margin-top:12px; font-size:0.75rem; color:#94a3b8'>
            Data per {data.get('yc_date','—')}
        </div>
        """, unsafe_allow_html=True)

    EDUKASI = {
        'A1': {
            'judul': 'Apa itu Yield Curve T10Y-3M?',
            'isi': """
    **Analoginya:** Bayangkan pasien di ICU — kondisi terkontrol, ada infus, dokter jaga 24 jam. Tapi saat pasien pulang, barulah terlihat apakah benar-benar sudah sembuh.

    Yield obligasi jangka panjang (10 tahun) seharusnya *selalu lebih tinggi* dari jangka pendek (3 bulan) — risiko lebih lama = kompensasi lebih besar. Ini kondisi normal.

    Kalau yang terjadi sebaliknya → **inversi**. Artinya pasar "melihat sesuatu yang salah" di depan. The Fed biasanya turun tangan seperti tim medis ICU. Setelah inversi selesai dan pengawasan dilonggarkan, barulah tes sesungguhnya dimulai.

    **Cara baca skor:**
    - Spread > 1.0 → ✅ Aman, recovery solid
    - Spread 0.5–1.0 → ⚠️ Transisi, masih perlu dipantau  
    - Spread < 0.5 → 🔴 Berbahaya

    **Sumber:** [FRED T10Y3M](https://fred.stlouisfed.org/series/T10Y3M)
            """
        },
        'A2': {
            'judul': 'Kenapa 18 bulan setelah inversi masih dihitung?',
            'isi': """
    **Ini yang sering tidak dipahami:** bahaya bukan *saat* inversi terjadi, tapi justru *setelah* inversi selesai.

    Sejarah menunjukkan resesi hampir selalu datang 12–24 bulan *setelah* yield curve kembali normal. Ibarat pasien baru keluar ICU — belum tentu langsung fit.

    **18 bulan** adalah periode minimum yang dianggap aman untuk disebut soft landing.

    **Backtesting:**
    - Dotcom 2000: inversi selesai → crash datang 30 bulan kemudian
    - GFC 2008: inversi selesai → crash datang 16 bulan kemudian

    Inversi terakhir berakhir Maret 2026, artinya periode waspada berlangsung hingga **September 2027**. Selama itu parameter ini otomatis bernilai 1.
            """
        },
        'B1': {
            'judul': 'Apa itu HY OAS Velocity?',
            'isi': """
    **HY OAS** (High Yield Option-Adjusted Spread) = selisih yield *junk bond* korporat vs obligasi pemerintah AS yang paling aman.

    - Pasar percaya diri → spread rendah (investor mau pegang junk bond)
    - Pasar mulai takut → spread naik (investor buang junk bond, lari ke aset aman)

    **B1 mengukur *kecepatan* perubahan** dalam 6 bulan. Kalau naik/turun lebih dari 150 bps → ada sesuatu yang bergerak tidak normal.

    **Fungsi sebagai early warning event-triggered:**
    Saat Covid Feb 2020, HY OAS tiba-tiba spike padahal tidak ada masalah kredit. Itu sinyal bahwa "big money" sudah mulai bergerak keluar — meski publik masih berdebat soal bahaya pandemi.

    Logikanya: *"Kenapa spike padahal tidak ada masalah debt? Isu apa yang cukup besar sampai big fund khawatir?"*

    **Sumber:** [FRED BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
            """
        },
        'B2': {
            'judul': 'Apa itu HY OAS Level?',
            'isi': """
    Kalau B1 mengukur *kecepatan*, B2 mengukur *ketinggian absolut* spread HY OAS.

    **550 bps** adalah threshold historis di mana pasar sudah benar-benar panik — level yang hanya tercapai saat krisis sistemik besar.

    **Referensi historis:**
    - Kondisi normal: 250–400 bps
    - Covid March 2020 peak: ~1.100 bps
    - GFC 2008 peak: ~2.000 bps
    - Sekarang: ~282 bps ✅

    Kalau B1 dan B2 nyala merah bersamaan → sinyal konfirmasi kuat bahwa stress sudah sistemik.

    **Sumber:** [FRED BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
            """
        },
        'C': {
            'judul': 'Apa itu Shiller CAPE Ratio?',
            'isi': """
    **CAPE** (Cyclically Adjusted P/E) = versi "lebih jujur" dari rasio P/E biasa.

    P/E biasa menggunakan laba *tahun ini* — mudah terdistorsi kondisi siklus. CAPE menggunakan rata-rata laba **10 tahun terakhir yang sudah disesuaikan inflasi**, jadi jauh lebih stabil.

    Parameter ini mewakili **psikologi dan valuasi pasar**.

    **Cara baca:**
    - CAPE < 20 → Murah, historis ini waktu beli
    - CAPE 20–35 → Normal / sedikit mahal
    - CAPE > 35 → Sangat mahal, rentan koreksi besar
    - CAPE 44.19 → Peak Dotcom Bubble 2000 (tertinggi sepanjang sejarah)

    Sekarang ~41.66 — sangat dekat level Dotcom. Bukan berarti crash pasti terjadi besok, tapi kalau ada pemicu, koreksinya bisa dalam karena tidak ada *margin of safety*.

    **Sumber:** [multpl.com/shiller-pe](https://www.multpl.com/shiller-pe)
            """
        },
    }

    with col_params:
        for key, p in params.items():
            icon = "🔴" if p['skor'] else "🟢"
            val_color = "#ef4444" if p['skor'] else "#15803d"
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
            edu = EDUKASI.get(key, {})
            if edu:
                with st.expander(f"📖 {edu['judul']}"):
                    st.markdown(edu['isi'])

    # ── Trend chart ──
    st.markdown("---")
    st.markdown("#### 📈 Trend skor")

    if len(df_log) > 1:
        df_trend = df_log.copy()
        df_trend['date'] = pd.to_datetime(df_trend['date'])
        df_trend = df_trend.sort_values('date')

        fig2, ax2 = plt.subplots(figsize=(12, 3.5))
        fig2.patch.set_facecolor('#ffffff')
        ax2.set_facecolor('#ffffff')

        ax2.step(df_trend['date'], df_trend['total'], color='#1a56db', lw=2, where='post')
        ax2.fill_between(df_trend['date'], df_trend['total'], step='post', alpha=0.08, color='#1a56db')
        ax2.axhline(3, color='#f97316', lw=1, ls='--', alpha=0.7, label='Exit window (3)')
        ax2.axhline(2, color='#eab308', lw=1, ls='--', alpha=0.7, label='Waspada (2)')

        ax2.set_ylim(-0.3, 4.5)
        ax2.set_yticks([0,1,2,3,4])
        ax2.set_yticklabels(['0','1','2','3','4'], color='#64748b', fontsize=9, fontfamily='monospace')
        ax2.tick_params(colors='#64748b', labelsize=9)
        for sp in ax2.spines.values(): sp.set_color('#e2e8f0')
        ax2.legend(loc='upper left', facecolor='#ffffff', edgecolor='#e2e8f0',
                   labelcolor='#475569', fontsize=8)
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

# ─────────────────────────────────────────────
#  TAB 2 — BACKTESTING
# ─────────────────────────────────────────────
with tab2:

    st.markdown("#### Backtesting Crashmeter v3.0")
    st.markdown(
        "Ambil data historis dari FRED, hitung skor Crashmeter tiap bulan, "
        "dan evaluasi seberapa akurat sinyal exit-nya di tiap crash besar."
    )
    st.info(
        "⚠️ **Catatan overfitting:** Mengubah threshold berdasarkan data historis yang sama "
        "membuat model terlihat bagus di masa lalu tapi belum tentu valid ke depan. "
        "Gunakan fitur threshold dengan bijak — validasi selalu di event yang tidak dipakai untuk tuning.",
        icon=None
    )

    # ── Threshold sliders ──
    st.markdown("##### ⚙️ Parameter & threshold")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        thr_yc    = st.slider("A1: T10Y-3M threshold", 0.0, 2.0, 0.5, 0.05,
                              help="Skor 1 jika T10Y-3M di bawah nilai ini")
        thr_inv   = st.slider("A2: Periode inversi (bln)", 6, 24, 18, 1,
                              help="Skor 1 selama bulan ke-0 s/d bulan ini setelah inversi")
    with bc2:
        thr_hyv   = st.slider("B1: HY OAS velocity (bps)", 50, 300, 150, 10,
                              help="Skor 1 jika pergerakan 6-bln melebihi nilai ini")
        thr_hyl   = st.slider("B2: HY OAS level (bps)",   300, 800, 550, 10,
                              help="Skor 1 jika HY OAS di atas nilai ini")
    with bc3:
        thr_cape  = st.slider("C: Shiller CAPE threshold", 20, 45, 35, 1,
                              help="Skor 1 jika CAPE di atas nilai ini")
        exit_score = st.slider("Exit signal di skor ≥", 2, 4, 3, 1,
                               help="Batas skor yang dianggap sinyal exit")

    run_bt = st.button("▶ Jalankan Backtesting")

    if run_bt:
        with st.spinner("Mengambil data historis dari FRED (1996–sekarang)..."):
            try:
                # ── Fetch semua data historis ──
                START = "1996-01-01"

                def fred_history(series_id, api_key, start=START):
                    url = "https://api.stlouisfed.org/fred/series/observations"
                    p = {"series_id": series_id, "api_key": api_key,
                         "file_type": "json", "observation_start": start,
                         "sort_order": "asc", "limit": 10000}
                    r = requests.get(url, params=p, timeout=30)
                    r.raise_for_status()
                    obs = r.json().get("observations", [])
                    rows = [(o["date"], float(o["value"]))
                            for o in obs if o["value"] not in (".", "nan")]
                    return pd.DataFrame(rows, columns=["date", "value"])

                df_yc   = fred_history("T10Y3M",        fred_key)
                df_hy   = fred_history("BAMLH0A0HYM2",  fred_key)
                df_spx  = fred_history("SP500",         fred_key)
                df_cape_raw = fred_history("MEHOINUSA672N", fred_key)  # fallback

                # Shiller CAPE dari FRED (series SHILLER_PE_RATIO tidak ada,
                # pakai Multpl scrape monthly — atau gunakan series dari Yale via FRED)
                # Gunakan series yang tersedia: Cyclically Adjusted PE Ratio
                try:
                    df_cape_raw = fred_history("CAPE", fred_key, start=START)
                except:
                    df_cape_raw = None

                for df, name in [(df_yc,"T10Y3M"),(df_hy,"HY OAS"),(df_spx,"SP500")]:
                    df["date"] = pd.to_datetime(df["date"])
                    df.set_index("date", inplace=True)
                    df.columns = [name]

                # Resample ke bulanan
                df_m = pd.DataFrame()
                df_m["yc"]  = df_yc["T10Y3M"].resample("ME").last()
                df_m["hy"]  = df_hy["HY OAS"].resample("ME").last()
                df_m["spx"] = df_spx["SP500"].resample("ME").last()
                df_m = df_m.dropna(subset=["yc","hy","spx"])

                # CAPE — coba FRED, kalau tidak ada pakai approximation dari log
                if df_cape_raw is not None and len(df_cape_raw) > 10:
                    df_cape_raw["date"] = pd.to_datetime(df_cape_raw["date"])
                    df_cape_raw.set_index("date", inplace=True)
                    df_m["cape"] = df_cape_raw["value"].resample("ME").last().reindex(df_m.index, method=".ffill()")
                else:
                    # Hardcoded CAPE milestones untuk interpolasi kasar
                    cape_pts = {
                        "1996-01-31": 24.8, "2000-03-31": 44.2, "2002-10-31": 21.9,
                        "2007-10-31": 27.5, "2009-03-31": 13.3, "2013-01-31": 22.2,
                        "2018-01-31": 33.3, "2020-03-31": 24.8, "2021-12-31": 40.0,
                        "2022-10-31": 27.5, "2024-01-31": 34.0, "2026-05-31": 41.7,
                    }
                    cape_series = pd.Series(
                        {pd.Timestamp(k): v for k, v in cape_pts.items()}
                    ).sort_index()
                    df_m["cape"] = cape_series.reindex(
                        df_m.index.union(cape_series.index)
                    ).interpolate(method="time").reindex(df_m.index)

                df_m["cape"] = df_m["cape"].fillna(method=".ffill()")
                df_m = df_m.dropna()

                # ── Hitung HY velocity 6-bln ──
                df_m["hy_6m_ago"] = df_m["hy"].shift(6)
                df_m["hy_vel_bps"] = (df_m["hy"] - df_m["hy_6m_ago"]).abs() * 100

                # ── Deteksi inversi ──
                df_m["inverted"] = df_m["yc"] < 0
                # Untuk tiap bulan, hitung berapa bulan sejak inversi berakhir
                inv_end_dates = []
                last_inv_end  = None
                for i, (dt, row) in enumerate(df_m.iterrows()):
                    if i == 0:
                        inv_end_dates.append(None)
                        continue
                    prev_inv = df_m.iloc[i-1]["inverted"]
                    curr_inv = row["inverted"]
                    if prev_inv and not curr_inv:
                        last_inv_end = dt
                    inv_end_dates.append(last_inv_end)
                df_m["inv_end"] = inv_end_dates

                def months_since_inv_end(row):
                    if row["inv_end"] is None:
                        return 999  # tidak ada inversi sebelumnya
                    return (row.name - row["inv_end"]).days / 30.4

                df_m["months_post_inv"] = df_m.apply(months_since_inv_end, axis=1)

                # ── Hitung skor per bulan ──
                def skor_bulan(row):
                    a1 = 0 if row["yc"]  > thr_yc  else 1
                    a2 = 1 if row["months_post_inv"] < thr_inv else 0
                    b1 = 0 if row["hy_vel_bps"] < thr_hyv else 1
                    b2 = 0 if row["hy"] * 100 < thr_hyl else 1
                    c  = 1 if row["cape"] > thr_cape else 1 if row["cape"] > thr_cape else 0
                    c  = 1 if row["cape"] > thr_cape else 0
                    return a1 + a2 + b1 + b2 + c

                df_m["score"] = df_m.apply(skor_bulan, axis=1)
                df_m["exit_signal"] = df_m["score"] >= exit_score

                # ── Definisi crash events ──
                events = [
                    {"name": "Resesi 1990–91",  "peak": "1990-07-31", "trough": "1991-03-31", "color": "#8b5cf6"},
                    {"name": "Dotcom 2000–02",  "peak": "2000-03-31", "trough": "2002-10-31", "color": "#ef4444"},
                    {"name": "GFC 2007–09",     "peak": "2007-10-31", "trough": "2009-03-31", "color": "#f97316"},
                    {"name": "Covid 2020",      "peak": "2020-02-29", "trough": "2020-03-31", "color": "#06b6d4"},
                    {"name": "Rate Hike 2022",  "peak": "2022-01-31", "trough": "2022-10-31", "color": "#eab308"},
                ]

                # ── Metrics per event ──
                st.markdown("##### 📊 Hasil per crash event")

                metrics_rows = []
                for ev in events:
                    peak_dt   = pd.Timestamp(ev["peak"])
                    trough_dt = pd.Timestamp(ev["trough"])

                    # Cari sinyal exit pertama sebelum/sekitar peak
                    window = df_m[(df_m.index >= peak_dt - pd.DateOffset(months=24)) &
                                  (df_m.index <= peak_dt + pd.DateOffset(months=3))]
                    exit_rows = window[window["exit_signal"]]

                    if len(exit_rows):
                        first_exit = exit_rows.index[0]
                        lead_months = (peak_dt - first_exit).days / 30.4
                        spx_at_exit = df_m.loc[first_exit, "spx"] if first_exit in df_m.index else None
                        spx_at_peak = df_m.loc[peak_dt, "spx"]   if peak_dt   in df_m.index else None
                        spx_at_trough = df_m.loc[trough_dt, "spx"] if trough_dt in df_m.index else None

                        if spx_at_exit and spx_at_trough and spx_at_peak:
                            saved_pct  = (spx_at_exit - spx_at_trough) / spx_at_exit * 100
                            missed_pct = (spx_at_peak - spx_at_exit)   / spx_at_peak * 100
                        else:
                            saved_pct = missed_pct = None

                        metrics_rows.append({
                            "Event": ev["name"],
                            "Sinyal exit": first_exit.strftime("%b %Y"),
                            "Lead time": f"{lead_months:.0f} bln sebelum peak" if lead_months >= 0 else f"{abs(lead_months):.0f} bln setelah peak",
                            "SPX saat exit": f"{spx_at_exit:.0f}" if spx_at_exit else "—",
                            "SPX trough": f"{spx_at_trough:.0f}" if spx_at_trough else "—",
                            "Drawdown diselamatkan": f"{saved_pct:.1f}%" if saved_pct else "—",
                            "Upside missed": f"{missed_pct:.1f}%" if missed_pct else "—",
                        })
                    else:
                        metrics_rows.append({
                            "Event": ev["name"],
                            "Sinyal exit": "❌ Tidak terdeteksi",
                            "Lead time": "—", "SPX saat exit": "—",
                            "SPX trough": "—",
                            "Drawdown diselamatkan": "—", "Upside missed": "—",
                        })

                if metrics_rows:
                    st.dataframe(pd.DataFrame(metrics_rows), use_container_width=True, hide_index=True)

                # ── Chart: SPX + Score timeline ──
                st.markdown("##### 📈 SPX vs Crashmeter Score (1996–sekarang)")

                fig, (ax_spx, ax_score) = plt.subplots(
                    2, 1, figsize=(14, 8), sharex=True,
                    gridspec_kw={"height_ratios": [3, 1]}
                )
                fig.patch.set_facecolor("#ffffff")

                # SPX
                ax_spx.set_facecolor("#ffffff")
                ax_spx.plot(df_m.index, df_m["spx"], color="#1e40af", lw=1.5, label="S&P 500")
                ax_spx.set_ylabel("S&P 500", color="#374151", fontsize=10)
                ax_spx.tick_params(colors="#6b7280")
                for sp in ax_spx.spines.values(): sp.set_color("#e5e7eb")

                # Shade crash windows + exit signals
                for ev in events:
                    peak_dt   = pd.Timestamp(ev["peak"])
                    trough_dt = pd.Timestamp(ev["trough"])
                    ax_spx.axvspan(peak_dt, trough_dt, alpha=0.08, color=ev["color"])
                    ax_spx.axvline(peak_dt, color=ev["color"], lw=1, ls="--", alpha=0.5)
                    mid = peak_dt + (trough_dt - peak_dt) / 2
                    ax_spx.text(mid, ax_spx.get_ylim()[1] * 0.02,
                                ev["name"].split(" ")[0], fontsize=7,
                                color=ev["color"], ha="center", va="bottom")

                # Exit signal dots on SPX
                exit_pts = df_m[df_m["exit_signal"]]
                ax_spx.scatter(exit_pts.index, exit_pts["spx"],
                               color="#ef4444", s=12, zorder=5,
                               label=f"Exit signal (skor≥{exit_score})", alpha=0.7)
                ax_spx.legend(fontsize=8, loc="upper left",
                              facecolor="#ffffff", edgecolor="#e5e7eb")

                # Score
                ax_score.set_facecolor("#ffffff")
                score_colors_map = {0:"#22c55e", 1:"#22c55e", 2:"#eab308",
                                    3:"#f97316", 4:"#ef4444"}
                for i in range(len(df_m)-1):
                    sc = int(df_m["score"].iloc[i])
                    ax_score.fill_between(
                        [df_m.index[i], df_m.index[i+1]],
                        [sc, sc], color=score_colors_map.get(sc, "#94a3b8"), alpha=0.85
                    )
                ax_score.axhline(exit_score, color="#ef4444", lw=1, ls="--", alpha=0.6)
                ax_score.set_ylim(-0.2, 4.5)
                ax_score.set_yticks([0,1,2,3,4])
                ax_score.set_yticklabels(["0","1","2","3","4"], fontsize=8, color="#6b7280")
                ax_score.set_ylabel("CM Score", color="#374151", fontsize=9)
                ax_score.tick_params(colors="#6b7280")
                for sp in ax_score.spines.values(): sp.set_color("#e5e7eb")

                plt.tight_layout()
                st.pyplot(fig, use_container_width=True)

                # ── Per-event zoom chart ──
                st.markdown("##### 🔍 Zoom per event")
                ev_names = [e["name"] for e in events]
                sel_ev = st.selectbox("Pilih event", ev_names)
                ev = next(e for e in events if e["name"] == sel_ev)

                peak_dt   = pd.Timestamp(ev["peak"])
                trough_dt = pd.Timestamp(ev["trough"])
                w_start   = peak_dt - pd.DateOffset(months=30)
                w_end     = trough_dt + pd.DateOffset(months=12)
                df_zoom   = df_m[(df_m.index >= w_start) & (df_m.index <= w_end)]

                fig2, (az1, az2) = plt.subplots(
                    2, 1, figsize=(12, 6), sharex=True,
                    gridspec_kw={"height_ratios": [3, 1]}
                )
                fig2.patch.set_facecolor("#ffffff")

                az1.set_facecolor("#ffffff")
                az1.plot(df_zoom.index, df_zoom["spx"], color="#1e40af", lw=2)
                az1.axvspan(peak_dt, trough_dt, alpha=0.1, color=ev["color"])
                az1.axvline(peak_dt,   color=ev["color"], lw=1.5, ls="--",
                            label=f"Peak ({peak_dt.strftime('%b %Y')})")
                az1.axvline(trough_dt, color="#6b7280", lw=1.5, ls=":",
                            label=f"Trough ({trough_dt.strftime('%b %Y')})")

                exit_zoom = df_zoom[df_zoom["exit_signal"]]
                if len(exit_zoom):
                    az1.scatter(exit_zoom.index, exit_zoom["spx"],
                                color="#ef4444", s=30, zorder=5,
                                label=f"Exit signal")
                    first_exit_zoom = exit_zoom.index[0]
                    az1.axvline(first_exit_zoom, color="#ef4444", lw=1.5, ls="-",
                                alpha=0.6, label=f"1st exit ({first_exit_zoom.strftime('%b %Y')})")

                az1.set_title(f"{ev['name']} — SPX vs Crashmeter", fontsize=11, color="#111827")
                az1.set_ylabel("S&P 500", fontsize=9, color="#374151")
                az1.tick_params(colors="#6b7280")
                for sp in az1.spines.values(): sp.set_color("#e5e7eb")
                az1.legend(fontsize=8, facecolor="#ffffff", edgecolor="#e5e7eb")

                az2.set_facecolor("#ffffff")
                for i in range(len(df_zoom)-1):
                    sc = int(df_zoom["score"].iloc[i])
                    az2.fill_between(
                        [df_zoom.index[i], df_zoom.index[i+1]],
                        [sc, sc], color=score_colors_map.get(sc, "#94a3b8"), alpha=0.85
                    )
                az2.axhline(exit_score, color="#ef4444", lw=1, ls="--", alpha=0.6)
                az2.set_ylim(-0.2, 4.5)
                az2.set_yticks([0,1,2,3,4])
                az2.set_yticklabels(["0","1","2","3","4"], fontsize=8, color="#6b7280")
                az2.set_ylabel("CM Score", fontsize=9, color="#374151")
                az2.tick_params(colors="#6b7280")
                for sp in az2.spines.values(): sp.set_color("#e5e7eb")

                plt.tight_layout()
                st.pyplot(fig2, use_container_width=True)

                # ── Saran parameter ──
                st.markdown("##### 💡 Observasi otomatis")
                detected = sum(1 for r in metrics_rows if r["Sinyal exit"] != "❌ Tidak terdeteksi")
                total_ev = len(events)
                st.markdown(f"Dengan threshold saat ini, Crashmeter mendeteksi **{detected}/{total_ev}** crash events.")
                if detected < total_ev:
                    st.warning(
                        "Beberapa crash tidak terdeteksi. Coba turunkan threshold A1, B1, atau B2 "
                        "— tapi perhatikan apakah false positive ikut naik."
                    )
                false_signals = len(df_m[df_m["exit_signal"]]) - detected
                if false_signals > total_ev * 3:
                    st.warning(
                        f"Ada ~{false_signals} bulan dengan exit signal — kemungkinan ada false positive. "
                        "Coba naikkan threshold atau exit score."
                    )
                else:
                    st.success(f"Jumlah exit signal ({len(df_m[df_m['exit_signal']])} bulan total) terlihat reasonable.")

            except Exception as e:
                st.error(f"Error saat backtesting: {e}")
                st.exception(e)
    else:
        st.caption("Atur parameter di atas lalu klik **▶ Jalankan Backtesting**.")
