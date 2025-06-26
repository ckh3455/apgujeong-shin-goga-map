"""Streamlit 앱: 압구정동 신고가 맵 (Google Sheets 기반)
----------------------------------------------------------------
· Google Sheets 한 장만 읽어 folium 지도 시각화 (엑셀 없이 배포 가능)
· 5 초 캐시 + cache‑buster → 사실상 실시간 갱신 (시트 ‘링크 보기’ 공개 필요)
· 15 분마다 st_autorefresh() 자동 리프레시, 사이드바는 숨김
· 안내·홍보·제보 버튼을 지도 하단에 반응형 고정

실행/배포:
    pip install streamlit streamlit-folium streamlit-autorefresh pandas numpy folium
    streamlit run apgujeong_shin_goga_map.py
"""

# ─────────────────── 패키지 ───────────────────
import streamlit as st
import pandas as pd, numpy as np, folium, time, re
from folium.plugins import MarkerCluster
from math import sin, cos, pi
from streamlit_autorefresh import st_autorefresh
from streamlit.components.v1 import html as st_html

# ─────────────────── 시트 / 옵션 ───────────────────
SHEET_ID = "1V0xg4JMhrcdEm8QAnjACiZXo-8gqcQKy8WoRfMY7wqE"
TAB_GID  = 1892600887
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScu-x_0R-XxNH19J8N5rbI9FkPLgBGOjzY_A9yiFAIMHelCmQ/viewform"

MAP_ZOOM, MARKER_RADIUS, SEPARATION = 16, 24, 0.00035
BRANCH_COLORS        = ['#FFC107','#00CAFF','#FFAAAA','#7965C1','#FF7601','#FCD8CD','lightblue','darkpurple','darkgreen','lightgreen']
DEFAULT_SINGLE_COLOR = '#A4DD00'
CUSTOM_COLORS        = {}

money = lambda x: "없음" if pd.isna(x) else f"{round(x/10000,2):.2f}".rstrip('0').rstrip('.')+'억'
shin  = lambda x: "내용없음" if pd.isna(x) else money(x)
rate  = lambda x: "N/A" if pd.isna(x) else f"{x} %"

def pick_color(row: pd.Series, idx: int, size: int):
    key = (row['단지명'], int(row['평형']))
    if key in CUSTOM_COLORS:
        return CUSTOM_COLORS[key]
    if row['단지명'] in CUSTOM_COLORS:
        return CUSTOM_COLORS[row['단지명']]
    return DEFAULT_SINGLE_COLOR if size == 1 else BRANCH_COLORS[idx % len(BRANCH_COLORS)]

@st.cache_data(ttl=5)
def load_sheet_df():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?gid={TAB_GID}&format=csv&cb={int(time.time())}"
    )
    df = pd.read_csv(url)
    num_cols = ['평형', '2024년', '2025년', '신고가']
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

def build_dataframe() -> pd.DataFrame:
    df = load_sheet_df()

    # ── 좌표 컬럼 자동 탐색 및 정규화 ──
    try:
        lat_col = next(c for c in df.columns if re.search(r'(lat|위도)', c, re.I))
        lon_col = next(c for c in df.columns if re.search(r'(lon|경도)', c, re.I))
    except StopIteration:
        st.error("❗ 시트에 lat/lon(또는 위도/경도) 컬럼이 없습니다.")
        st.stop()

    clean = lambda s: re.sub(r"[\\u00a0\\s]", "", str(s))
    df['lat'] = pd.to_numeric(df[lat_col].map(clean), errors='coerce')
    df['lon'] = pd.to_numeric(df[lon_col].map(clean), errors='coerce')

    if df[['lat', 'lon']].isna().any().any():
        st.error("❗ 시트에 좌표 데이터가 누락되었습니다.")
        st.stop()

    cond = (~df['신고가'].isna()) & (df['2025년'].isna() | (df['신고가'] > df['2025년']))
    df['신고가_유효'] = np.where(cond, df['신고가'], np.nan)
    df['latest']      = np.where(~df['신고가_유효'].isna(), df['신고가_유효'], df['2025년'])
    df['상승률(%)']    = np.where(
        (~df['2024년'].isna()) & (~df['latest'].isna()),
        ((df['latest'] - df['2024년']) / df['2024년'] * 100).round(1),
        np.nan,
    )
    return df

# 이후는 그대로 유지됩니다.
