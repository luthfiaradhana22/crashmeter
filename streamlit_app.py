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
        # Saat pakai start_date, ambil ascending dan pakai n_obs sebagai limit
        p.update({'observation_start': start_date, 'sort_order': 'asc', 'limit': n_obs})
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
    data = fred_get('T10Y3M', api_key, n_obs=2000, start_date=start)
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
        # limit 30 cukup untuk ambil beberapa obs sekitar 6 bulan lalu
        hy6   = fred_get('BAMLH0A0HYM2', api_key, n_obs=30, start_date=six_m)
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

    # ── Helpers ──────────────────────────────────────────────────────────────
    def fred_history(series_id, api_key, start="1996-01-01"):
        url = "https://api.stlouisfed.org/fred/series/observations"
        p   = {"series_id": series_id, "api_key": api_key,
               "file_type": "json", "observation_start": start,
               "sort_order": "asc", "limit": 10000}
        r   = requests.get(url, params=p, timeout=30)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        rows = [(o["date"], float(o["value"]))
                for o in obs if o["value"] not in (".", "nan")]
        df  = pd.DataFrame(rows, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")["value"]

    def build_monthly(api_key):
        """Fetch + resample semua series ke bulanan."""
        yc  = fred_history("T10Y3M",       api_key)
        hy  = fred_history("BAMLH0A0HYM2", api_key)
        spx = fred_history("SP500",        api_key)

        df = pd.DataFrame({
            "yc":  yc .resample("ME").last(),
            "hy":  hy .resample("ME").last(),
            "spx": spx.resample("ME").last(),
        }).dropna(subset=["yc","hy","spx"])

        # CAPE — interpolasi dari milestones historis
        cape_pts = {
            "1996-01-31":24.8, "2000-03-31":44.2, "2002-10-31":21.9,
            "2007-10-31":27.5, "2009-03-31":13.3, "2013-01-31":22.2,
            "2018-01-31":33.3, "2020-03-31":24.8, "2021-12-31":40.0,
            "2022-10-31":27.5, "2024-01-31":34.0, "2026-05-31":41.7,
        }
        cape_s = pd.Series({pd.Timestamp(k): v for k,v in cape_pts.items()}).sort_index()
        combined = df.index.union(cape_s.index)
        df["cape"] = cape_s.reindex(combined).interpolate(method="time").reindex(df.index).ffill().bfill()

        # HY velocity 6 bln
        df["hy_vel"] = (df["hy"] - df["hy"].shift(6)).abs() * 100

        # Deteksi bulan pasca-inversi
        df["inverted"] = df["yc"] < 0
        last_inv_end   = None
        post_inv       = []
        for i in range(len(df)):
            if i > 0 and df["inverted"].iloc[i-1] and not df["inverted"].iloc[i]:
                last_inv_end = df.index[i]
            if last_inv_end is not None:
                months = (df.index[i] - last_inv_end).days / 30.4
            else:
                months = 999
            post_inv.append(months)
        df["post_inv_months"] = post_inv
        return df

    def score_row(row, p):
        a1 = 0 if row["yc"]       > p["thr_yc"]  else 1
        a2 = 1 if row["post_inv_months"] < p["thr_inv"] else 0
        b1 = 0 if row["hy_vel"]   < p["thr_hyv"] else 1
        b2 = 0 if row["hy"]*100   < p["thr_hyl"] else 1
        c  = 0 if row["cape"]     < p["thr_cape"] else 1
        return a1+a2+b1+b2+c, {"A1":a1,"A2":a2,"B1":b1,"B2":b2,"C":c}

    def make_event_chart(df, ev, params, exit_score):
        """Buat figure per-event mirip gambar referensi."""
        peak_dt   = pd.Timestamp(ev["peak"])
        trough_dt = pd.Timestamp(ev["trough"])
        w_start   = peak_dt   - pd.DateOffset(months=ev.get("pre_months", 18))
        w_end     = trough_dt + pd.DateOffset(months=ev.get("post_months", 18))
        dz        = df[(df.index >= w_start) & (df.index <= w_end)].copy()

        if len(dz) < 3:
            return None, None

        dz["score"] = dz.apply(lambda r: score_row(r, params)[0], axis=1)

        # Key stats
        spx_peak   = dz.loc[peak_dt,   "spx"] if peak_dt   in dz.index else dz["spx"].max()
        spx_trough = dz.loc[trough_dt, "spx"] if trough_dt in dz.index else dz["spx"].min()
        drawdown   = (spx_trough - spx_peak) / spx_peak * 100

        exit_rows  = dz[(dz.index <= peak_dt + pd.DateOffset(months=3)) & (dz["score"] >= exit_score)]
        if len(exit_rows):
            exit_dt    = exit_rows.index[0]
            spx_exit   = dz.loc[exit_dt, "spx"]
            lead_months= (peak_dt - exit_dt).days / 30.4
            saved_pct  = (spx_exit - spx_trough) / spx_exit * 100
            missed_pct = (spx_peak - spx_exit)   / spx_peak * 100
            exit_score_val = int(dz.loc[exit_dt, "score"])
        else:
            exit_dt = spx_exit = lead_months = saved_pct = missed_pct = exit_score_val = None

        # ── Figure ──
        fig, (ax_spx, ax_cm) = plt.subplots(
            2, 1, figsize=(12, 6), sharex=True,
            gridspec_kw={"height_ratios": [3, 1.2], "hspace": 0.08}
        )
        fig.patch.set_facecolor("white")

        # Title
        fig.suptitle(f"Backtesting: {ev['name']}",
                     x=0.01, y=1.01, ha="left",
                     fontsize=14, fontweight="bold", color="#111827")
        if exit_dt:
            subtitle = (f"Crashmeter v3 signal: EXIT {exit_dt.strftime('%b %Y')} — "
                        f"SPX {spx_exit:.0f} ({-missed_pct:.1f}% dari peak {spx_peak:.0f})")
        else:
            subtitle = "Crashmeter v3 signal: tidak terdeteksi dalam window ini"
        fig.text(0.01, 0.985, subtitle, ha="left", fontsize=8.5,
                 color="#6b7280", style="italic", transform=fig.transFigure)

        # ── SPX ──
        ax_spx.set_facecolor("white")
        ax_spx.plot(dz.index, dz["spx"], color="#1e3a8a", lw=2, label="SPX Close Price")
        ax_spx.set_ylabel("SPX Close Price", fontsize=9, color="#374151")
        ax_spx.tick_params(colors="#6b7280", labelsize=8)
        for sp in ax_spx.spines.values(): sp.set_color("#e5e7eb")
        ax_spx.text(dz.index[-1], dz["spx"].iloc[-1], "SPX Close Price",
                    fontsize=7.5, color="#1e3a8a", va="center", ha="left")

        # Exit marker
        if exit_dt and exit_dt in dz.index:
            ax_spx.axvline(exit_dt, color="#dc2626", lw=1.5, ls="--", alpha=0.8)
            y_pos = spx_exit * 1.03
            ax_spx.annotate("EXIT",
                xy=(exit_dt, spx_exit), xytext=(exit_dt, y_pos),
                fontsize=8, fontweight="bold", color="white",
                ha="center",
                bbox=dict(boxstyle="round,pad=0.3", fc="#dc2626", ec="none"),
                arrowprops=dict(arrowstyle="-", color="#dc2626", lw=1))

        # Peak & trough markers
        ax_spx.axvline(peak_dt,   color="#6b7280", lw=1, ls=":", alpha=0.5)
        ax_spx.axvline(trough_dt, color="#6b7280", lw=1, ls=":", alpha=0.5)

        ax_spx.set_ylim(dz["spx"].min() * 0.92, dz["spx"].max() * 1.10)
        ax_spx.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"{x:,.0f}"))

        # ── Crashmeter score bars ──
        ax_cm.set_facecolor("white")
        score_clr = {0:"#93c5fd", 1:"#fbbf24", 2:"#fb923c", 3:"#dc2626", 4:"#7f1d1d"}
        for i in range(len(dz)-1):
            sc  = int(dz["score"].iloc[i])
            dt0 = dz.index[i]
            dt1 = dz.index[i+1]
            ax_cm.fill_between([dt0, dt1], [sc, sc], color=score_clr.get(sc,"#93c5fd"), alpha=0.9, step="post")

        if exit_dt:
            ax_cm.axvline(exit_dt, color="#dc2626", lw=1.5, ls="--", alpha=0.8)

        ax_cm.set_ylim(0, 4.5)
        ax_cm.set_yticks([0,1,2,3,4])
        ax_cm.set_yticklabels(["0","1","2","3","4"], fontsize=7.5, color="#6b7280")
        ax_cm.set_ylabel("CM Score", fontsize=8, color="#f97316")
        ax_cm.yaxis.label.set_color("#f97316")
        ax_cm.tick_params(colors="#6b7280", labelsize=7.5)
        for sp in ax_cm.spines.values(): sp.set_color("#e5e7eb")

        # Label score legend
        ax_cm.text(dz.index[-1], 0.2, "Crashmeter v3.0 Score (0-4)",
                   fontsize=7, color="#f97316", ha="right")

        plt.tight_layout()

        # Stats dict untuk display
        stats = {
            "peak_spx":    f"{spx_peak:.0f} ({peak_dt.strftime('%b %Y')})",
            "trough_spx":  f"{spx_trough:.0f} ({trough_dt.strftime('%b %Y')})",
            "drawdown":    f"{drawdown:.1f}%",
            "exit_signal": f"{exit_dt.strftime('%b %Y')} @ {spx_exit:.0f}" if exit_dt else "❌ Tidak terdeteksi",
            "saved":       f"{-missed_pct:.1f}% vs {drawdown:.1f}% (save {saved_pct:.0f}%)" if exit_dt else "—",
            "lead_time":   f"{lead_months:.0f} bulan" if exit_dt and lead_months > 0 else ("Setelah peak" if exit_dt else "—"),
        }
        return fig, stats

    # ── UI ───────────────────────────────────────────────────────────────────
    st.markdown("#### 🔬 Backtesting Crashmeter v3.0")
    st.caption(
        "Simulasi sinyal exit Crashmeter di setiap crash besar sejak 1996. "
        "Data historis diambil langsung dari FRED."
    )
    st.info(
        "⚠️ **Perhatian overfitting:** Threshold yang di-tune dari data historis yang sama "
        "bisa terlihat bagus di masa lalu tapi belum tentu valid ke depan. "
        "Gunakan slider sebagai eksplorasi, bukan final tuning.",
        icon=None
    )

    # ── Threshold controls ──
    with st.expander("⚙️ Ubah threshold & parameter", expanded=False):
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            thr_yc   = st.slider("A1: T10Y-3M min", 0.0, 2.0, 0.5, 0.05)
            thr_inv  = st.slider("A2: Periode pasca-inversi (bln)", 6, 24, 18, 1)
        with tc2:
            thr_hyv  = st.slider("B1: HY velocity maks (bps)", 50, 300, 150, 10)
            thr_hyl  = st.slider("B2: HY level maks (bps)", 300, 800, 550, 10)
        with tc3:
            thr_cape = st.slider("C: CAPE maks", 20, 45, 35, 1)
            exit_thr = st.slider("Exit signal di skor ≥", 2, 4, 3, 1)

    bt_params = {"thr_yc":thr_yc,"thr_inv":thr_inv,"thr_hyv":thr_hyv,
                 "thr_hyl":thr_hyl,"thr_cape":thr_cape}

    EVENTS = [
        {"name":"Dotcom Crash (2000–2002)",       "peak":"2000-03-31","trough":"2002-10-31","pre_months":18,"post_months":18},
        {"name":"Great Financial Crisis (2007–09)","peak":"2007-10-31","trough":"2009-03-31","pre_months":24,"post_months":18},
        {"name":"Covid Crash (2020)",              "peak":"2020-02-29","trough":"2020-03-31","pre_months":12,"post_months":12},
        {"name":"Rate Hike Bear (2022)",           "peak":"2022-01-31","trough":"2022-10-31","pre_months":12,"post_months":12},
    ]

    if st.button("▶ Jalankan Backtesting", type="primary"):
        with st.spinner("Mengambil data historis dari FRED..."):
            try:
                df_hist = build_monthly(fred_key)
            except Exception as e:
                st.error(f"Gagal ambil data: {e}")
                st.stop()

        st.success(f"Data siap: {len(df_hist)} bulan ({df_hist.index[0].strftime('%b %Y')} – {df_hist.index[-1].strftime('%b %Y')})")

        for ev in EVENTS:
            st.markdown(f"---")
            fig, stats = make_event_chart(df_hist, ev, bt_params, exit_thr)
            if fig is None:
                st.warning(f"{ev['name']}: data tidak cukup dalam range ini.")
                continue

            st.pyplot(fig, use_container_width=True)
            plt.close(fig)

            # Key stats + interpretasi — 2 kolom
            ks_col, interp_col = st.columns([1, 1], gap="large")

            with ks_col:
                st.markdown("""
                <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 18px'>
                <p style='font-size:10px;letter-spacing:0.08em;color:#94a3b8;margin:0 0 10px'>KEY STATS</p>
                """, unsafe_allow_html=True)

                def stat_row(label, value, highlight=False):
                    color = "#dc2626" if highlight else "#111827"
                    weight = "600" if highlight else "400"
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"font-size:13px;padding:3px 0;border-bottom:1px solid #f1f5f9'>"
                        f"<span style='color:#64748b'>{label}</span>"
                        f"<span style='color:{color};font-weight:{weight}'>{value}</span>"
                        f"</div>",
                        unsafe_allow_html=True
                    )

                stat_row("Peak SPX",            stats["peak_spx"])
                stat_row("Trough SPX",          stats["trough_spx"],   highlight=True)
                stat_row("Total drawdown",       stats["drawdown"],     highlight=True)
                stat_row("Signal EXIT Crashmeter", stats["exit_signal"])
                stat_row("Penyelamatan",         stats["saved"],        highlight=True)
                stat_row("Lead time ke bottom",  stats["lead_time"])
                st.markdown("</div>", unsafe_allow_html=True)

            with interp_col:
                # Auto-generate interpretasi berdasarkan stats
                has_exit = stats["exit_signal"] != "❌ Tidak terdeteksi"
                if has_exit:
                    interp = (
                        f"Crashmeter berhasil memberikan sinyal EXIT **{stats['lead_time']}** "
                        f"sebelum bottom. Dengan keluar di **{stats['exit_signal']}**, "
                        f"investor bisa menyelamatkan sebagian besar drawdown — "
                        f"**{stats['saved']}**.\n\n"
                        f"Total drawdown dari peak ke trough adalah **{stats['drawdown']}**. "
                    )
                    if "save" in stats["saved"] and int(stats["saved"].split("save ")[1].replace("%","").replace(")","")) > 40:
                        interp += "Sinyal datang cukup awal — masih ada window yang lega untuk eksekusi."
                    else:
                        interp += "Waktu exit cukup sempit — perlu eksekusi cepat begitu skor 3 tercapai."
                else:
                    interp = (
                        f"Crashmeter **tidak mendeteksi** sinyal exit yang jelas sebelum crash ini. "
                        f"Kemungkinan karena crash bersifat event-triggered (bukan sistemik dari debt/valuasi), "
                        f"atau semua parameter belum aktif bersamaan. "
                        f"Total drawdown yang terjadi: **{stats['drawdown']}**."
                    )

                st.markdown(
                    f"<div style='background:#fffbeb;border:1px solid #fde68a;border-radius:8px;"
                    f"padding:14px 18px;font-size:13px;line-height:1.7;color:#374151'>"
                    f"<p style='font-size:10px;letter-spacing:0.08em;color:#94a3b8;margin:0 0 8px'>INTERPRETASI</p>"
                    f"{interp.replace(chr(10), '<br>')}"
                    f"</div>",
                    unsafe_allow_html=True
                )

        # ── Summary tabel semua event ──
        st.markdown("---")
        st.markdown("##### 📋 Ringkasan semua event")
        summary = []
        for ev in EVENTS:
            _, stats = make_event_chart(df_hist, ev, bt_params, exit_thr)
            if stats:
                summary.append({
                    "Event": ev["name"],
                    "Exit signal": stats["exit_signal"],
                    "Lead time": stats["lead_time"],
                    "Total drawdown": stats["drawdown"],
                    "Diselamatkan": stats["saved"],
                })
        if summary:
            st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

    else:
        st.caption("Klik **▶ Jalankan Backtesting** untuk memulai.")
