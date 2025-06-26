"""Streamlit 앱: 압구정동 신고가 맵 (Google Sheets 기반)
----------------------------------------------------------------
· **Google Sheets 하나만** 읽어 folium 지도 시각화 → 서버에 엑셀 파일 없이도 배포 가능
· 5 초 캐시 + cache‑buster 로 사실상 실시간 갱신 (시트 ‘링크 보기’ 공개 필요)
· 15 분마다 `st_autorefresh()` 자동 리프레시, 사이드바는 숨김
· 안내·홍보·제보 버튼이 지도 하단에 반응형으로 고정

실행 / 배포:
    pip install streamlit streamlit-folium streamlit-autorefresh pandas numpy folium
    streamlit run apgujeong_shin_goga_map.py
"""

# ───────────────────── 패키지 ─────────────────────
import streamlit as st
import pandas as pd, numpy as np, folium, time, re
from folium.plugins import MarkerCluster
from math import sin, cos, pi
from streamlit_autorefresh import st_autorefresh
from streamlit.components.v1 import html as st_html

# ───────────────────── 시트 / 옵션 ─────────────────────
SHEET_ID = "1V0xg4JMhrcdEm8QAnjACiZXo-8gqcQKy8WoRfMY7wqE"  # Google Sheets ID
TAB_GID  = 1892600887                                        # 워크시트 gid
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScu-x_0R-XxNH19J8N5rbI9FkPLgBGOjzY_A9yiFAIMHelCmQ/viewform"

MAP_ZOOM, MARKER_RADIUS, SEPARATION = 16, 24, 0.00035
BRANCH_COLORS        = ['#FFC107','#00CAFF','#FFAAAA','#7965C1','#FF7601','#FCD8CD','lightblue','darkpurple','darkgreen','lightgreen']
DEFAULT_SINGLE_COLOR = '#A4DD00'
CUSTOM_COLORS        = {}

money = lambda x: "없음" if pd.isna(x) else f"{round(x/10000,2):.2f}".rstrip('0').rstrip('.')+'억'
shin  = lambda x: "내용없음" if pd.isna(x) else money(x)
rate  = lambda x: "N/A" if pd.isna(x) else f"{x} %"

def pick_color(row: pd.Series, idx: int, size: int):
    key = (row['단지명'], int(row['평형']))
    if key in CUSTOM_COLORS:
        return CUSTOM_COLORS[key]
    if row['단지명'] in CUSTOM_COLORS:
        return CUSTOM_COLORS[row['단지명']]
    return DEFAULT_SINGLE_COLOR if size == 1 else BRANCH_COLORS[idx % len(BRANCH_COLORS)]

# ───────────────────── Google Sheets (CSV + cache‑buster) ─────────────────────
@st.cache_data(ttl=5)  # 5 초 캐시 → 사실상 실시간
def load_sheet_df():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?gid={TAB_GID}&format=csv&cb={int(time.time())}"
    )
    df = pd.read_csv(url)
    # 예상 컬럼: 단지명 lat lon 평형 2024년 2025년 신고가 ...
    num_cols = ['평형', '2024년', '2025년', '신고가', 'lat', 'lon']
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

# ───────────────────── 데이터 처리 ─────────────────────

def build_dataframe() -> pd.DataFrame:
    df = load_sheet_df()

    # 필수 좌표‑칼럼 검증
    if df[['lat', 'lon']].isna().any().any():
        st.error("❗ 시트에 lat / lon 좌표가 누락되었습니다.")
        st.stop()

    # 유효 신고가·상승률 계산
    cond = (~df['신고가'].isna()) & (df['2025년'].isna() | (df['신고가'] > df['2025년']))
    df['신고가_유효'] = np.where(cond, df['신고가'], np.nan)
    df['latest']      = np.where(~df['신고가_유효'].isna(), df['신고가_유효'], df['2025년'])
    df['상승률(%)']    = np.where(
        (~df['2024년'].isna()) & (~df['latest'].isna()),
        ((df['latest'] - df['2024년']) / df['2024년'] * 100).round(1),
        np.nan,
    )
    return df

# ───────────────────── folium 지도 ─────────────────────

def build_map(df: pd.DataFrame) -> folium.Map:
    m = folium.Map(location=[df['lat'].mean(), df['lon'].mean()], zoom_start=MAP_ZOOM, tiles='CartoDB positron')
    cluster = MarkerCluster().add_to(m)

    for name, g in df.groupby('단지명'):
        lat0, lon0 = g.iloc[0][['lat', 'lon']]
        folium.Marker([
            lat0, lon0
        ], icon=folium.DivIcon(html=f"<div style='font-size:12px;font-weight:bold;background:rgba(255,255,255,0.75);padding:2px 4px;border-radius:4px;'>{name}</div>"))\
n        .add_to(m)

        for i, (_, row) in enumerate(g.iterrows()):
            lat_c, lon_c = (
                (lat0, lon0) if len(g) == 1 else (
                    lat0 + SEPARATION * sin(2 * pi * i / len(g)),
                    lon0 + SEPARATION * cos(2 * pi * i / len(g)) / np.cos(np.radians(lat0))
                )
            )
            if len(g) != 1:
                folium.PolyLine([[lat0, lon0], [lat_c, lon_c]], color="#666", weight=1).add_to(m)

            color = pick_color(row, i, len(g))
            folium.CircleMarker([
                lat_c, lon_c
            ], radius=MARKER_RADIUS, fill=True, fill_color=color, fill_opacity=0.9, stroke=False,
                popup=folium.Popup(
                    f"<b>{row['단지명']} {int(row['평형'])}평</b><br>24년 최고가 {money(row['2024년'])}<br>25년 최고가 {money(row['2025년'])}<br>신고가 {shin(row['신고가_유효'])}<br><b>상승률 {rate(row['상승률(%)'])}</b>",
                    max_width=280),
                tooltip=f"{int(row['평형'])}평").add_to(cluster)
            folium.Marker([
                lat_c, lon_c
            ], icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:bold;transform:translate(-50%,-12px);'>{int(row['평형'])}평</div>")).add_to(m)

    # ───────── overlay CSS & HTML ─────────
    m.get_root().html.add_child(folium.Element(f"""
    <style>
        body {{position:relative !important;}}
        .overlay-box {{position:absolute; z-index:9998;}}
        .legend {{bottom:20px; left:10px; width:520px;}}
        .promo  {{bottom:20px; right:10px; width:220px;}}
        .report-btn {{bottom:20px; left:50%; transform:translateX(-50%); z-index:9999;}}
        @media (max-width:768px) {{
            .legend {{bottom:120px; left:50%; transform:translateX(-50%); width:90%;}}
            .promo {{display:none;}}
            .report-btn {{bottom:30px;}}
        }}
    </style>"""))

    m.get_root().html.add_child(folium.Element("""
      <div class='overlay-box' style='top:8px; left:50%; transform:translateX(-50%); text-align:center; z-index:9999;'>
        <div style='font-size:20px; font-weight:bold; background:rgba(255,255,255,0.9); padding:2px 8px; border-radius:4px;'>압구정동 신고가 맵</div>
        <div style
