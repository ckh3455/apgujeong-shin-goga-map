'''Streamlit 앱: 압구정동 신고가 맵 (Google Sheets 기반)
----------------------------------------------------------------
· Google Sheets 한 장만 읽어 folium 지도 시각화 (엑셀 파일 없이 배포 가능)
· **30 초 캐시 + cache‑buster** → 실시간 갱신 체감 속도 개선
· 15 분마다 st_autorefresh() 자동 리프레시, 사이드바는 숨김
· 안내·홍보·제보 버튼을 지도 하단에 반응형 고정

실행/배포:
    pip install streamlit streamlit-folium streamlit-autorefresh pandas numpy folium
    streamlit run apgujeong_shin_goga_map.py
'''

# ────────────────── 패키지 ──────────────────
import streamlit as st
import pandas as pd
import numpy as np
import folium
import time
import re
from folium.plugins import MarkerCluster
from math import sin, cos, pi
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium  # iframe 렌더로 속도 개선

# ────────────────── 시트 / 옵션 ──────────────────
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

def pick_color(row, idx, size):
    key = (row['단지명'], int(row['평형']))
    if key in CUSTOM_COLORS:
        return CUSTOM_COLORS[key]
    if row['단지명'] in CUSTOM_COLORS:
        return CUSTOM_COLORS[row['단지명']]
    return DEFAULT_SINGLE_COLOR if size==1 else BRANCH_COLORS[idx % len(BRANCH_COLORS)]

# ────────────────── 데이터 로드 ──────────────────
@st.cache_data(ttl=30)
def load_sheet_df():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?gid={TAB_GID}&format=csv&cb={int(time.time())}"
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip()
    if '신고가' not in df.columns:
        df['신고가'] = np.nan
    for col in ['평형','2024년','2025년','신고가']:
        if col in df.columns:
            df[col] = (df[col].astype(str)
                             .str.replace(r'[ ,억원]', '', regex=True)
                             .replace('', np.nan)
                             .astype(float))
    return df

# ────────────────── 데이터 가공 ──────────────────

def build_dataframe():
    df = load_sheet_df()

    try:
        lat_col = next(c for c in df.columns if re.search(r'(lat|위도)', c, re.I))
        lon_col = next(c for c in df.columns if re.search(r'(lon|경도)', c, re.I))
    except StopIteration:
        st.error("❗ 위도/경도 컬럼을 찾을 수 없습니다.")
        st.stop()

    clean = lambda s: re.sub(r"[\u00a0\s]", "", str(s))
    df['lat'] = pd.to_numeric(df[lat_col].map(clean), errors='coerce')
    df['lon'] = pd.to_numeric(df[lon_col].map(clean), errors='coerce')
    df = df.dropna(subset=['lat','lon'])
    if df.empty:
        st.error("❗ 좌표 데이터가 없습니다.")
        st.stop()

    cond = (~df['신고가'].isna()) & (df['2025년'].isna() | (df['신고가']>df['2025년']))
    df['신고가_유효'] = np.where(cond, df['신고가'], np.nan)
    df['latest'] = np.where(df['신고가_유효'].notna(), df['신고가_유효'], df['2025년'])
    df['상승률(%)'] = np.where(df['2024년'].notna() & df['latest'].notna(),
                             ((df['latest']-df['2024년'])/df['2024년']*100).round(1), np.nan)
    df = (df.sort_values(by=['단지명','평형','신고가_유효','2025년','2024년'], ascending=[True,True,False,False,False])
            .drop_duplicates(subset=['단지명','평형']).reset_index(drop=True))
    return df

# ────────────────── 지도 생성 ──────────────────

def build_map(df:pd.DataFrame):
    m = folium.Map(location=[df['lat'].mean(), df['lon'].mean()], zoom_start=MAP_ZOOM, tiles='CartoDB positron')
    cluster = MarkerCluster().add_to(m)

    for name, g in df.groupby('단지명'):
        lat0, lon0 = g.iloc[0][['lat','lon']]
        folium.Marker([lat0,lon0], icon=folium.DivIcon(html=f"<div style='font-size:12px;font-weight:bold;background:rgba(255,255,255,0.75);padding:2px 4px;border-radius:4px;'>{name}</div>")).add_to(m)
        for i, (_, row) in enumerate(g.iterrows()):
            lat_c, lon_c = (lat0, lon0) if len(g)==1 else (
                lat0+SEPARATION*sin(2*pi*i/len(g)),
                lon0+SEPARATION*cos(2*pi*i/len(g))/np.cos(np.radians(lat0)))
            if len(g)!=1:
                folium.PolyLine([[lat0,lon0],[lat_c,lon_c]], color="#666", weight=1).add_to(m)
            popup_html=(f"<div style='font-size:16px;line-height:1.6;'><b>{row['단지명']} {int(row['평형'])}평</b><br>24년 최고가 {money(row['2024년'])}<br>25년 최고가 {money(row['2025년'])}<br>신고가 {shin(row['신고가_유효'])}<br><b>상승률 {rate(row['상승률(%)'])}</b></div>")
            folium.CircleMarker([lat_c,lon_c], radius=MARKER_RADIUS, fill=True, fill_color=pick_color(row,i,len(g)), fill_opacity=0.9, stroke=False,
                                 popup=folium.Popup(popup_html,max_width=420), tooltip=f"{int(row['평형'])}평").add_to(cluster)
            folium.Marker([lat_c,lon_c], icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:bold;transform:translate(-50%,-12px);'>{int(row['평형'])}평</div>")).add_to(m)

    # overlay_html (기존 변수를 그대로 사용)
    m.get_root().html.add_child(folium.Element(overlay_html))
    return m

# ────────────────── Streamlit UI ──────────────────

def main():
    st.set_page_config(page_title="압구정동 신고가 맵", layout="wide", initial_sidebar_state="collapsed")

    # 15분마다 자동 새로고침
    st_autorefresh(interval=15*60*1000, key="auto_refresh")

    # 지도 로딩 스피너
    with st.spinner("지도 로딩 중…"):
        df = build_dataframe()
        folium_map = build_map(df)
        # folium 지도 렌더 (iframe) — 훨씬 가벼움
        st_folium(folium_map, width="100%", height=800, returned_objects=[])

if __name__ == "__main__":
    main()
