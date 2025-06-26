"""Streamlit 앱: 압구정동 신고가 맵 (Google Sheets 실시간 반영)
----------------------------------------------------------------
· 로컬 Excel + Google Sheets 병합 → folium 지도
· 15 분마다 st_autorefresh() 로 자동 갱신, 수동 새로고침 버튼도 제공
· streamlit-folium 으로 지도 깜빡임 없이 렌더링
· 사이드바에 신고가 제보(Google Form) 링크·디버그 데이터프레임 토글 포함

실행:
    pip install streamlit streamlit-autorefresh streamlit-folium gspread oauth2client pandas numpy folium openpyxl
    streamlit run apgujeong_shin_goga_map.py
"""

# ────────────── 패키지 ──────────────
import streamlit as st
# 페이지 설정은 최상단에서 단 한 번!

import os, re
import pandas as pd, numpy as np, folium, gspread, streamlit as st
from folium.plugins import MarkerCluster
from math import sin, cos, pi
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium  # (백업용)
from streamlit.components.v1 import html as st_html

# ────────────── 경로·키 ──────────────
LOCAL_PATHS = [
    r"C:/Users/USER/OneDrive/excel data/압구정동_단지_평형별_최고거래가_2015_2025_정리(앱스트림용).xlsx",
    r"D:/OneDrive/excel data/압구정동_단지_평형별_최고거래가_2015_2025_정리(앱스트림용).xlsx",
    r"D:/OneDrive/office work/앱만들기/압구정동_단지_평형별_최고거래가_2015_2025_정리(앱스트림용).xlsx",
]
SHEET_ID     = "1V0xg4JMhrcdEm8QAnjACiZXo-8gqcQKy8WoRfMY7wqE"
TAB_GID      = 1892600887
SERVICE_JSON = r"D:/OneDrive/office work/앱만들기/crypto-groove-464013-t8-b14eb7ee714c.json"
FORM_URL     = "https://docs.google.com/forms/d/e/1FAIpQLScu-x_0R-XxNH19J8N5rbI9FkPLgBGOjzY_A9yiFAIMHelCmQ/viewform"

# ────────────── 지도 옵션 ──────────────
MAP_ZOOM, MARKER_RADIUS, SEPARATION = 16, 24, 0.00035
BRANCH_COLORS        = ['#FFC107','#00CAFF','#FFAAAA','#7965C1','#FF7601','#FCD8CD','lightblue','darkpurple','darkgreen','lightgreen']
DEFAULT_SINGLE_COLOR = '#A4DD00'
CUSTOM_COLORS        = {}

# ────────────── 유틸 함수 ──────────────

def pick_file(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("❗ 실거래가 엑셀 파일을 찾지 못했습니다.")

LOCAL_FILE = pick_file(LOCAL_PATHS)

money = lambda x: "없음" if pd.isna(x) else f"{round(x/10000,2):.2f}".rstrip('0').rstrip('.')+'억'
shin  = lambda x: "내용없음" if pd.isna(x) else money(x)
rate  = lambda x: "N/A" if pd.isna(x) else f"{x} %"

def pick_color(row:pd.Series, idx:int, size:int):
    key = (row['단지명'], int(row['평형']))
    if key in CUSTOM_COLORS:
        return CUSTOM_COLORS[key]
    if row['단지명'] in CUSTOM_COLORS:
        return CUSTOM_COLORS[row['단지명']]
    return DEFAULT_SINGLE_COLOR if size == 1 else BRANCH_COLORS[idx % len(BRANCH_COLORS)]

# ────────────── Google Sheets (CSV + cache‑buster) ──────────────
import time

@st.cache_data(ttl=5)  # 5 초 캐시 → 사실상 실시간
def load_sheet_df():
    """공개 시트를 CSV로 직접 읽어와 Google 서버 캐시를 우회"""
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?gid={TAB_GID}&format=csv&cb={int(time.time())}"
    )
    df = pd.read_csv(csv_url)
    df['평형']  = pd.to_numeric(df['평형'], errors='coerce')
    df['신고가'] = pd.to_numeric(df['신고가'], errors='coerce')
    return df

# ────────────── 데이터 병합 ──────────────

def build_dataframe():
    df_xl = pd.read_excel(LOCAL_FILE, engine="openpyxl")
    df_sh = load_sheet_df()

    lat_col = next(c for c in df_xl.columns if re.search(r"(lat|위도)", c, re.I))
    lon_col = next(c for c in df_xl.columns if re.search(r"(lon|경도)", c, re.I))
    clean = lambda s: re.sub(r"[\u00a0\s]", "", str(s))
    df_xl['lat'] = pd.to_numeric(df_xl[lat_col].map(clean), errors='coerce')
    df_xl['lon'] = pd.to_numeric(df_xl[lon_col].map(clean), errors='coerce')
    df = df_xl.dropna(subset=['lat', 'lon']).copy()

    if not df_sh.empty:
        df = df.merge(df_sh[['단지명', '평형', '신고가']], on=['단지명', '평형'], how='left', suffixes=('', '_s'))
        df['신고가'] = df['신고가_s'].combine_first(df['신고가'])
        df.drop(columns=['신고가_s'], inplace=True)

    df[['2024년', '2025년', '신고가']] = df[['2024년', '2025년', '신고가']].apply(pd.to_numeric, errors='coerce')

    cond = (~df['신고가'].isna()) & (df['2025년'].isna() | (df['신고가'] > df['2025년']))
    df['신고가_유효'] = np.where(cond, df['신고가'], np.nan)
    df['latest'] = np.where(~df['신고가_유효'].isna(), df['신고가_유효'], df['2025년'])
    df['상승률(%)'] = np.where(
        (~df['2024년'].isna()) & (~df['latest'].isna()),
        ((df['latest'] - df['2024년']) / df['2024년'] * 100).round(1),
        np.nan
    )
    return df

# ────────────── folium 지도 ──────────────

def build_map(df: pd.DataFrame) -> folium.Map:
    """단지·평형별 마커를 그리고, 안내·버튼·홍보 박스를 겹치지 않도록 배치한 folium.Map 반환"""
    # ── 기본 지도 ──
    m = folium.Map(location=[df['lat'].mean(), df['lon'].mean()], zoom_start=MAP_ZOOM, tiles='CartoDB positron')
    cluster = MarkerCluster().add_to(m)

    # ── 단지·평형 마커 ──
    for name, g in df.groupby('단지명'):
        lat0, lon0 = g.iloc[0][['lat', 'lon']]
        folium.Marker(
            [lat0, lon0],
            icon=folium.DivIcon(html=f"<div style='font-size:12px;font-weight:bold;background:rgba(255,255,255,0.75);padding:2px 4px;border-radius:4px;'>{name}</div>")
        ).add_to(m)

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
            folium.CircleMarker(
                [lat_c, lon_c],
                radius=MARKER_RADIUS,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                stroke=False,
                popup=folium.Popup(
                    f"<b>{row['단지명']} {int(row['평형'])}평</b><br>24년 최고가 {money(row['2024년'])}<br>25년 최고가 {money(row['2025년'])}<br>신고가 {shin(row['신고가_유효'])}<br><b>상승률 {rate(row['상승률(%)'])}</b>",
                    max_width=280,
                ),
                tooltip=f"{int(row['평형'])}평",
            ).add_to(cluster)
            folium.Marker(
                [lat_c, lon_c],
                icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:bold;transform:translate(-50%,-12px);'>{int(row['평형'])}평</div>")
            ).add_to(m)

            # ───────────────────────────────────────
    # 📌 안내·버튼·홍보 박스 (반응형 레이아웃)
    #    • 데스크톱 : 좌·우 박스 bottom 80px, 중앙 버튼 bottom 20px
    #    • 모바일(≤768px) : 좌측 안내 박스를 화면 90% 폭으로, 홍보 박스는 숨김
    # ───────────────────────────────────────
    m.get_root().html.add_child(folium.Element(f"""
        <style>
    body {{position:relative !important;}}
    .overlay-box {{position:absolute; z-index:9998;}}
    .legend {{bottom:20px; left:10px; width:520px;}}
    .promo {{bottom:20px; right:10px; width:220px;}}
    .report-btn {{bottom:20px; left:50%; transform:translateX(-50%); z-index:9999;}}

    /* ▶︎ 모바일 레이아웃 조정 */
    @media (max-width:768px) {{
        .legend {{bottom:120px; left:50%; transform:translateX(-50%); width:90%;}}
        .promo {{display:none;}}
        .report-btn {{bottom:30px;}}
    }}
</style>
    """))

    # 상단 중앙 타이틀 (body기준)
    m.get_root().html.add_child(folium.Element("""
      <div class='overlay-box' style='top:8px; left:50%; transform:translateX(-50%); text-align:center; z-index:9999;'>
        <div style='font-size:20px; font-weight:bold; background:rgba(255,255,255,0.9); padding:2px 8px; border-radius:4px;'>압구정동 신고가 맵</div>
        <div style='font-size:14px; background:rgba(255,255,255,0.9); padding:0 6px; border-radius:4px;'>신고가가 생길 때마다 업데이트됩니다</div>
      </div>"""))

    # 좌측 하단 안내
    m.get_root().html.add_child(folium.Element(f"""
      <div class='overlay-box legend' style='font-size:11px; line-height:1.25; background:rgba(255,255,255,0.92); border:2px solid grey; border-radius:6px; padding:10px; columns:2 240px; column-gap:14px;'>
        <div style='font-size:14px; font-weight:bold; column-span:all; margin-bottom:4px;'>압구정동 신고가 맵 <span style='font-weight:normal;'>(실시간)</span></div>
        <ul style='margin:0; padding-left:14px; list-style-type:disc;'>
          <li>실거래 신고가 <b>미등록</b> 거래를 안내합니다.</li>
          <li>마커를 클릭해 단지·평형별 상세 확인.</li>
          <li><b>24년 최고가</b>: 2024년 기록 최대값.</li>
          <li><b>25년 최고가</b>: 2025년 실거래 최대값.</li>
          <li><b>상승률</b>: 24년 대비, 신고가가 있으면 신고가 기준.</li>
          <li>신고가는 허가 미발급·해약 등으로 취소·변동될 수 있습니다.</li>
          <li>누락·오류 신고가는 <b><a href='{FORM_URL}' target='_blank' style='font-weight:bold;'>신고가 제보</a></b>로 알려주세요.</li>
        </ul>
      </div>"""))

    # 우측 하단 홍보
    m.get_root().html.add_child(folium.Element("""
      <div class='overlay-box promo' style='font-size:12px; line-height:1.3; background:#ffe6f2; border:2px solid #ff99cc; border-radius:6px; padding:8px; text-align:center;'>
        <div style='font-weight:bold;'>압구정 거래는<br>"압구정 원 부동산"</div>
        <div style='margin-top:4px;'>T&nbsp;&nbsp;02&nbsp;&nbsp;540&nbsp;&nbsp;3334</div>
      </div>"""))

    # 중앙 하단 신고가 제보 버튼
    m.get_root().html.add_child(folium.Element(f"""
      <div class='overlay-box report-btn'>
        <a href='{FORM_URL}' target='_blank' style='background:#007bff; color:#fff; padding:10px 18px; border-radius:6px; font-size:14px; font-weight:bold; text-decoration:none;'>📝 신고가 제보하기</a>
      </div>"""))

    return m

# ────────────── Streamlit UI ──────────────

def main():
    # 페이지 기본 설정 & 자동 리프레시
    st.set_page_config(page_title="압구정동 신고가 맵", layout="wide", initial_sidebar_state="collapsed")
    st_autorefresh(interval=15 * 60 * 1000, key="auto_refresh")

    st.title("📈 압구정동 단지별 신고가 맵")    # (사이드바 섹션 제거 – 화면을 더 넓게 사용)

    # ── 데이터 로드 & 지도 생성 ──
    df = build_dataframe()
    folium_map = build_map(df)

        # ── 지도 렌더링 ──
    # st_folium 의 absolute overlay 미표시 이슈로 HTML 직접 임베드 방식으로 교체
    html_str = folium_map.get_root().render()
    st_html(html_str, height=820, scrolling=False)

    

# ────────────── Run ──────────────
if __name__ == "__main__":
    main()
