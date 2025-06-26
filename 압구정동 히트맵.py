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

# ────────────────────── 패키지 ──────────────────────
import streamlit as st
import pandas as pd
import numpy as np
import folium
import time
import re
from folium.plugins import MarkerCluster
from math import sin, cos, pi
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium  # 성능용 남겨두되 현재는 사용 X
from streamlit.components.v1 import html as st_html  # folium HTML 직접 임베드

# ──────────────────── 시트 / 기본 옵션 ──────────────────
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

# ────────────────── 오버레이 HTML (전역) ──────────────────
# ────────────────── 오버레이 HTML (전역) ──────────────────
# f-string → 일반 문자열 + .format() 으로 변경
#   → CSS 중괄호는 {{ }} 로 이스케이프, FORM_URL 자리만 {FORM_URL}
overlay_html = """
<style>
  body {{position:relative !important; margin:0;}}
  .overlay-box {{position:absolute; z-index:9998;}}

  /* ── 기본(데스크톱) ── */
  .legend, .promo, .report-btn {{bottom:20px;}}
  .legend {{left:10px;  width:520px; font-size:12px; line-height:1.55;}}
  .promo  {{right:10px; width:240px; font-size:16px; line-height:1.4;}}
  .report-btn {{left:50%; transform:translateX(-50%); z-index:9999;}}
  .notice {{top:8px; right:10px; font-size:12px; color:#666;}}

  /* ── 모바일(≤768px) ── */
  @media (max-width:768px) {{
    .legend {{bottom:120px; left:2%;  width:46%; font-size:11px; line-height:1.45;}}
    .promo  {{bottom:120px; right:2%; width:42%; font-size:13px; line-height:1.45;}}
    .report-btn {{bottom:25px;}}
    .notice {{font-size:10px;}}
  }}

  /* ── 초소형(≤480px) ── */
  @media (max-width:480px) {{
    .legend {{width:48%; font-size:10.5px;}}
    .promo  {{width:48%; font-size:12px;}}
  }}
</style>

<!-- 자동 업데이트 알림 -->
<div class='overlay-box notice'>신고가가 생길 때마다 자동 업데이트됩니다</div>

<!-- 안내 박스 -->
<div class='overlay-box legend' style='background:rgba(255,255,255,0.95); padding:10px; border:1px solid #888; border-radius:8px;'>
  <b>📌 안내</b><br>
  실거래 등록 전 <b>신고&nbsp;약정가</b> 내역을 표시합니다.<br>
  마커를 클릭하면 <b>단지·평형별</b> 상세 내역을 확인할 수 있습니다.<br>
  신고 약정가는 거래허가 불허·해약 등에 의해 취소될 수 있으며 금액에 오차가 있을 수 있습니다.<br>
  상승률은 <b>24년 가격 대비</b> 상승률이며, 미등록 신고약정가가 있을 경우 신고약정가로 표시됩니다.<br>
  오류나 미반영 건은 <b>“신고가 제보하기”</b> 버튼으로 알려 주세요.
</div>

<!-- 홍보 박스 -->
<div class='overlay-box promo' style='background:#ffe6f2; border:2px solid #ff99cc; border-radius:8px; padding:10px; text-align:center;'>
  압구정 <b>매수·매도 상담</b>은<br>“<b>압구정 원 부동산</b>”<br>☎ 02&nbsp;540&nbsp;3334
</div>

<!-- 신고가 제보 버튼 -->
<div class='overlay-box report-btn'>
  <a href='{FORM_URL}' target='_blank' style='background:#007bff; color:#fff; padding:10px 18px; border-radius:8px; font-size:14px; font-weight:bold; text-decoration:none;'>📝 신고가 제보하기</a>
</div>
""".format(FORM_URL=FORM_URL)

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

    # 위도·경도 자동 탐색
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

    cond = (~df['신고가'].isna()) & (df['2025년'].isna() | (df['신고가'] > df['2025년']))
    df['신고가_유효'] = np.where(cond, df['신고가'], np.nan)
    df['latest'] = np.where(df['신고가_유효'].notna(), df['신고가_유효'], df['2025년'])
    df['상승률(%)'] = np.where(
        df['2024년'].notna() & df['latest'].notna(),
        ((df['latest'] - df['2024년']) / df['2024년'] * 100).round(1),
        np.nan,
    )

    df = (
        df.sort_values(by=['단지명','평형','신고가_유효','2025년','2024년'], ascending=[True,True,False,False,False])
          .drop_duplicates(subset=['단지명','평형'])
          .reset_index(drop=True)
    )
    return df

# ────────────────── 지도 생성 ──────────────────

def build_map(df: pd.DataFrame):
    """folium 지도 + 마커·팝업·오버레이를 구성해 반환"""
    m = folium.Map(
        location=[df['lat'].mean(), df['lon'].mean()],
        zoom_start=MAP_ZOOM,
        tiles='CartoDB positron',
    )

    cluster = MarkerCluster().add_to(m)

    # ── 단지별 루프 ──
    for name, grp in df.groupby('단지명'):
        lat0, lon0 = grp.iloc[0][['lat', 'lon']]

        # 단지명 라벨
        folium.Marker(
            [lat0, lon0],
            icon=folium.DivIcon(
                html=f"<div style='font-size:12px;font-weight:bold;background:rgba(255,255,255,0.75);padding:2px 4px;border-radius:4px;'>{name}</div>"
            ),
        ).add_to(m)

        # 평형별 마커
        for i, (_, row) in enumerate(grp.iterrows()):
            # 동일 단지에 여러 평형 → 원형 분기 배치
            lat_c, lon_c = (
                (lat0, lon0)
                if len(grp) == 1
                else (
                    lat0 + SEPARATION * sin(2 * pi * i / len(grp)),
                    lon0 + SEPARATION * cos(2 * pi * i / len(grp)) / np.cos(np.radians(lat0)),
                )
            )
            if len(grp) != 1:
                folium.PolyLine([[lat0, lon0], [lat_c, lon_c]], color="#666", weight=1).add_to(m)

            color = pick_color(row, i, len(grp))
            popup_html = (
                f"<div style='font-size:16px; line-height:1.6;'>"
                f"<b>{row['단지명']} {int(row['평형'])}평</b><br>"
                f"24년 최고가 {money(row['2024년'])}<br>"
                f"25년 최고가 {money(row['2025년'])}<br>"
                f"신고가 {shin(row['신고가_유효'])}<br>"
                f"<b>상승률 {rate(row['상승률(%)'])}</b>"
                "</div>"
            )

            folium.CircleMarker(
                [lat_c, lon_c],
                radius=MARKER_RADIUS,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                stroke=False,
                popup=folium.Popup(popup_html, max_width=420),
                tooltip=f"{int(row['평형'])}평",
            ).add_to(cluster)

            # 평형 숫자 라벨
            folium.Marker(
                [lat_c, lon_c],
                icon=folium.DivIcon(
                    html=f"<div style='font-size:11px;font-weight:bold;transform:translate(-50%,-12px);'>{int(row['평형'])}평</div>"
                ),
            ).add_to(m)

    # 오버레이(UI) 삽입
    m.get_root().html.add_child(folium.Element(overlay_html))
    return m

# ────────────────── Streamlit UI ──────────────────

def main():
    st.set_page_config(
        page_title="압구정동 신고가 맵",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 15분마다 전체 리프레시
    st_autorefresh(interval=15 * 60 * 1000, key="auto_refresh")

        # ▶︎ 지도 + 데이터 빌드 (스피너 제공)
    with st.spinner("지도 로딩 중…"):
        df = build_dataframe()
        folium_map = build_map(df)
        # folium 전체 HTML 직접 임베드 — 오버레이 보존
        map_html = folium_map.get_root().render()
        st_html(map_html, height=800, scrolling=False)


if __name__ == "__main__":
    main()
