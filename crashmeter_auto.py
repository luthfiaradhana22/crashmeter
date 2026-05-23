"""
Crashmeter v3.0 - Full Auto
Jalankan sebagai script biasa atau dari Colab.
Semua data diambil otomatis dari FRED API + scraping CAPE.
"""

import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from datetime import datetime, timedelta
import json, os, smtplib, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

# ============================================================
#  CONFIG — EDIT BAGIAN INI SAJA
# ============================================================
FRED_API_KEY   = os.environ.get('FRED_API_KEY', 'MASUKKAN_API_KEY_FRED_DI_SINI')   # https://fred.stlouisfed.org/docs/api/api_key.html
LOG_FILE       = 'crashmeter_log.csv'
CHART_FILE     = 'crashmeter_latest.png'

# Email alert (opsional) — isi jika mau notifikasi email
EMAIL_ENABLED  = False
EMAIL_FROM     = 'emailkamu@gmail.com'
EMAIL_TO       = 'emailkamu@gmail.com'
EMAIL_PASS     = 'app_password_gmail'   # Gmail App Password (bukan password biasa)
ALERT_ON_SCORE = 3                      # Kirim email jika skor >= angka ini
# ============================================================


# -------- FETCH DATA --------

def fred_get(series_id, n_obs=1, start_date=None):
    """Ambil data dari FRED API."""
    url = 'https://api.stlouisfed.org/fred/series/observations'
    params = {
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'sort_order': 'desc',
        'limit': n_obs,
    }
    if start_date:
        params['observation_start'] = start_date
        params['sort_order'] = 'asc'
        params['limit'] = 10
    
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    obs = r.json().get('observations', [])
    clean = [(o['date'], float(o['value'])) for o in obs if o['value'] not in ('.', 'nan')]
    return clean


def get_t10y3m():
    """Yield Curve T10Y-3M terbaru."""
    data = fred_get('T10Y3M', n_obs=5)
    if data:
        date, val = data[0]
        print(f"  T10Y3M  : {val:.4f}  (per {date})")
        return val, date
    raise ValueError("Gagal ambil T10Y3M dari FRED")


def get_hy_oas():
    """HY OAS sekarang dan 6 bulan lalu."""
    # Terbaru
    now_data = fred_get('BAMLH0A0HYM2', n_obs=5)
    if not now_data:
        raise ValueError("Gagal ambil HY OAS dari FRED")
    now_val, now_date = now_data[0][1], now_data[0][0]

    # 6 bulan lalu (ambil dari sekitar tanggal itu)
    six_m = (datetime.today() - timedelta(days=182)).strftime('%Y-%m-%d')
    hist_data = fred_get('BAMLH0A0HYM2', start_date=six_m)
    hist_val = hist_data[0][1] if hist_data else now_val

    print(f"  HY OAS  : {now_val:.4f}%  (per {now_date})")
    print(f"  HY OAS-6m: {hist_val:.4f}%")
    return now_val, hist_val, now_date


def get_cape():
    """
    Shiller CAPE dari multpl.com scraping.
    Fallback: ambil dari stooq jika scraping gagal.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get('https://www.multpl.com/shiller-pe', headers=headers, timeout=15)
        from html.parser import HTMLParser

        class CAPEParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.capture = False
                self.value = None
            def handle_starttag(self, tag, attrs):
                attrs_d = dict(attrs)
                if attrs_d.get('id') == 'current-value':
                    self.capture = True
            def handle_data(self, data):
                if self.capture and self.value is None:
                    stripped = data.strip().replace(',', '')
                    if stripped:
                        try:
                            self.value = float(stripped)
                        except:
                            pass
                        self.capture = False

        parser = CAPEParser()
        parser.feed(r.text)
        if parser.value:
            print(f"  CAPE    : {parser.value:.2f}  (scraped dari multpl.com)")
            return parser.value
    except Exception as e:
        print(f"  CAPE scraping gagal: {e}")
    
    print("  CAPE    : fallback ke nilai terakhir di log")
    return None


def get_inversion_end_from_log():
    """Baca tanggal akhir inversi dari log, atau default."""
    default = '2026-03-01'  # Update manual jika perlu
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE)
        if 'inversion_end_date' in df.columns and len(df):
            return df['inversion_end_date'].iloc[-1]
    return default


# -------- HITUNG SKOR --------

def hitung_skor(t10y3m, hy_now, hy_6m, cape, inversion_end_date):
    params = {}

    # A1
    a1 = 0 if t10y3m > 0.5 else 1
    if t10y3m > 1.0:     zona = 'Aman'
    elif t10y3m > 0.5:   zona = 'Transisi (0.5–1.0)'
    else:                 zona = 'BERBAHAYA'
    params['A1'] = {'label': 'Yield Curve T10Y-3M', 'nilai': f'{t10y3m:.3f}',
                    'skor': a1, 'zona': zona}

    # A2
    inv_end = datetime.strptime(inversion_end_date, '%Y-%m-%d')
    months = (datetime.today() - inv_end).days / 30.4
    a2 = 1 if months < 18 else 0
    params['A2'] = {'label': 'Pasca-inversi 18 bulan', 'nilai': f'{months:.1f} bln',
                    'skor': a2, 'zona': f'Sisa {max(0,18-months):.1f} bln' if a2 else 'Selesai'}

    # B1
    velocity_bps = abs((hy_now - hy_6m) * 100)
    b1 = 0 if velocity_bps < 150 else 1
    params['B1'] = {'label': 'HY OAS Velocity 6 bln', 'nilai': f'{velocity_bps:.0f} bps',
                    'skor': b1, 'zona': 'Aman' if b1 == 0 else 'SPIKE ALERT!'}

    # B2
    hy_bps = hy_now * 100
    b2 = 0 if hy_bps < 550 else 1
    params['B2'] = {'label': 'HY OAS Level', 'nilai': f'{hy_bps:.0f} bps',
                    'skor': b2, 'zona': 'Aman' if b2 == 0 else 'BERBAHAYA'}

    # C
    c = 1 if cape > 35 else 0
    params['C'] = {'label': 'Shiller CAPE', 'nilai': f'{cape:.2f}',
                   'skor': c, 'zona': f'Overvalued (peak Dotcom: 44.19)' if c else 'Aman (<35)'}

    total = a1 + a2 + b1 + b2 + c
    return params, total


# -------- STATUS STRING --------

def status_str(total):
    if total <= 1: return '✅ AMAN'
    if total == 2: return '⚠️  WASPADA'
    if total == 3: return '🚨 EXIT WINDOW DIMULAI'
    return '🔴 CRITICAL'


# -------- PRINT HASIL --------

def print_hasil(params, total, date_str):
    bar = '=' * 55
    print(f'\n{bar}')
    print(f'        CRASHMETER v3.0  |  {date_str}')
    print(bar)
    for key, p in params.items():
        mark = '🔴' if p['skor'] == 1 else '🟢'
        print(f"  {mark} {key}. {p['label']}")
        print(f"       {p['nilai']} — {p['zona']}  [skor: {p['skor']}]")
    print(bar)
    print(f'  TOTAL : {total}/4')
    print(f'  STATUS: {status_str(total)}')
    print(bar + '\n')


# -------- VISUALISASI --------

def buat_chart(params, total, date_str):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor('#0f1117')

    # Bar chart per parameter
    ax1 = axes[0]
    ax1.set_facecolor('#0f1117')
    keys = list(params.keys())
    scores = [params[k]['skor'] for k in keys]
    colors = ['#EF4444' if s else '#22C55E' for s in scores]
    bars = ax1.bar(keys, scores, color=colors, width=0.5, edgecolor='none')
    ax1.set_ylim(0, 1.5)
    ax1.set_yticks([0, 1])
    ax1.set_yticklabels(['0 — aman', '1 — bahaya'], color='#9CA3AF', fontsize=10)
    ax1.tick_params(colors='#9CA3AF', labelsize=11)
    for sp in ax1.spines.values(): sp.set_color('#374151')
    ax1.set_title('Skor per Parameter', color='white', fontsize=13, pad=10)
    for bar, key in zip(bars, keys):
        ax1.text(bar.get_x() + bar.get_width()/2,
                 bar.get_height() + 0.05,
                 params[key]['nilai'],
                 ha='center', va='bottom', color='white', fontsize=9)

    # Gauge
    ax2 = axes[1]
    ax2.set_facecolor('#0f1117')
    ax2.set_aspect('equal')
    ax2.axis('off')

    zones_def = [(0, 1, '#22C55E'), (1, 2, '#EAB308'), (2, 3, '#F97316'), (3, 4, '#EF4444')]
    for start, end, color in zones_def:
        t = np.linspace(np.pi - (start/4)*np.pi, np.pi - (end/4)*np.pi, 60)
        r_i, r_o = 0.5, 0.9
        xo, yo = np.cos(t)*r_o, np.sin(t)*r_o
        xi, yi = np.cos(t[::-1])*r_i, np.sin(t[::-1])*r_i
        ax2.fill(np.concatenate([xo, xi]), np.concatenate([yo, yi]), color=color, alpha=0.85)

    angle = np.pi - (min(total, 4)/4)*np.pi
    ax2.annotate('', xy=(np.cos(angle)*0.75, np.sin(angle)*0.75), xytext=(0, 0),
                 arrowprops=dict(arrowstyle='->', color='white', lw=2.5))
    ax2.add_patch(plt.Circle((0, 0), 0.06, color='white', zorder=5))

    color_map = {0:'#22C55E', 1:'#22C55E', 2:'#EAB308', 3:'#F97316', 4:'#EF4444'}
    ax2.text(0, -0.15, f'{total}/4', ha='center', color=color_map[total], fontsize=36, fontweight='bold')
    ax2.text(0, -0.35, status_str(total), ha='center', color='white', fontsize=11)
    ax2.set_xlim(-1.15, 1.15)
    ax2.set_ylim(-0.55, 1.1)

    for label, pos in zip(['0 Aman','1','2 Waspada','3 Exit','4 Critical'],
                           [-1.0, -0.68, 0, 0.68, 1.0]):
        ax2.text(pos, -0.03, label, ha='center', va='top', color='#6B7280', fontsize=8)

    ax2.set_title('Total Score', color='white', fontsize=13, pad=10)
    plt.suptitle(f'Crashmeter v3.0  —  {date_str}', color='#6B7280', fontsize=11)
    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=150, bbox_inches='tight', facecolor='#0f1117')
    plt.close()
    print(f'Chart disimpan: {CHART_FILE}')


# -------- LOGGING --------

def simpan_log(params, total, date_str, inversion_end_date,
               t10y3m, hy_now, hy_6m, cape):
    row = {
        'date': date_str,
        'inversion_end_date': inversion_end_date,
        't10y3m': t10y3m,
        'hy_oas_pct': hy_now,
        'hy_oas_6m_pct': hy_6m,
        'cape': cape,
        'skor_a1': params['A1']['skor'],
        'skor_a2': params['A2']['skor'],
        'skor_b1': params['B1']['skor'],
        'skor_b2': params['B2']['skor'],
        'skor_c':  params['C']['skor'],
        'total': total,
        'status': status_str(total)
    }
    df_new = pd.DataFrame([row])
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE)
        # Hindari duplikat tanggal yang sama
        df = df[df['date'] != date_str]
        df = pd.concat([df, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(LOG_FILE, index=False)
    print(f'Log tersimpan: {LOG_FILE} ({len(df)} entri)')
    return df


# -------- EMAIL ALERT --------

def kirim_email(params, total, date_str):
    if not EMAIL_ENABLED or total < ALERT_ON_SCORE:
        return
    
    subject = f'[CRASHMETER] Skor {total}/4 — {status_str(total)} | {date_str}'
    body = f"""
Crashmeter v3.0 Update — {date_str}

SKOR TOTAL: {total}/4
STATUS: {status_str(total)}

Detail:
"""
    for key, p in params.items():
        mark = '🔴' if p['skor'] else '🟢'
        body += f"  {mark} {key}. {p['label']}: {p['nilai']} [{p['zona']}] (skor {p['skor']})\n"
    
    body += "\n— Dikirim otomatis oleh Crashmeter v3.0"
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach chart
        if os.path.exists(CHART_FILE):
            with open(CHART_FILE, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-Disposition', 'attachment', filename=CHART_FILE)
                msg.attach(img)
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASS)
            s.send_message(msg)
        print(f'Email alert terkirim ke {EMAIL_TO}')
    except Exception as e:
        print(f'Email gagal: {e}')


# -------- MAIN --------

def run():
    print('\n🔄 Crashmeter v3.0 — Fetching data...\n')
    
    if FRED_API_KEY == 'MASUKKAN_API_KEY_FRED_DI_SINI':
        raise ValueError(
            "❌ FRED API Key belum diisi!\n"
            "Daftar gratis di: https://fred.stlouisfed.org/docs/api/api_key.html\n"
            "Lalu isi variabel FRED_API_KEY di bagian CONFIG."
        )
    
    date_str = datetime.today().strftime('%Y-%m-%d')
    inversion_end_date = get_inversion_end_from_log()
    
    # Fetch
    t10y3m, _ = get_t10y3m()
    hy_now, hy_6m, _ = get_hy_oas()
    cape = get_cape()
    
    # Fallback CAPE ke log terakhir jika scraping gagal
    if cape is None:
        if os.path.exists(LOG_FILE):
            df_log = pd.read_csv(LOG_FILE)
            if 'cape' in df_log.columns and len(df_log):
                cape = float(df_log['cape'].iloc[-1])
                print(f'  CAPE    : {cape:.2f} (dari log terakhir)')
        if cape is None:
            cape = 41.66  # hard fallback
            print(f'  CAPE    : {cape:.2f} (hardcoded fallback — update manual!)')
    
    # Hitung
    params, total = hitung_skor(t10y3m, hy_now, hy_6m, cape, inversion_end_date)
    
    # Output
    print_hasil(params, total, date_str)
    buat_chart(params, total, date_str)
    df_log = simpan_log(params, total, date_str, inversion_end_date,
                        t10y3m, hy_now, hy_6m, cape)
    kirim_email(params, total, date_str)
    
    return params, total, df_log


if __name__ == '__main__':
    run()
