'''Streamlit 앱: 압구정동 신고가 맵 (Google Sheets 기반)
----------------------------------------------------------------
· Google Sheets 한 장만 읽어 folium 지도 시각화 (엑셀 파일 없이 배포 가능)
· 5 초 캐시 + cache‑buster → 사실상 실시간 갱신 (시트 ‘링크 보기’ 공개 필요)
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
from streamlit.components.v1 import html as st_html

# ────────────────── 시트 / 옵션 ──────────────────
SHEET_ID = "1V0xg4JMhrcdEm8QAnjACiZXo-8gqcQKy8WoRfMY7wqE"
TAB_GID  = 1892600887
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScu-x_0R-XxNH19J8N5rbI9FkPLgBGOjzY_A9yiFAIMHelCmQ/viewform"

MAP_ZOOM, MARKER_RADIUS, SEPARATION = 16, 24, 0.00035
BRANCH_COLORS        = ['#FFC107', '#00CAFF', '#FFAAAA', '#7965C1', '#FF7601', '#FCD8CD',
                        'lightblue', 'darkpurple', 'darkgreen', 'lightgreen']
DEFAULT_SINGLE_COLOR = '#A4DD00'
CUSTOM_COLORS        = {}

money = lambda x: "없음" if pd.isna(x) else f"{round(x/10000,2):.2f}".rstrip('0').rstrip('.') + '억'
shin  = lambda x: "내용없음" if pd.isna(x) else money(x)
rate  = lambda x: "N/A" if pd.isna(x) else f"{x} %"

def pick_color(row, idx, size):
    key = (row['단지명'], int(row['평형']))
    if key in CUSTOM_COLORS:
        return CUSTOM_COLORS[key]
    if row['단지명'] in CUSTOM_COLORS:
        return CUSTOM_COLORS[row['단지명']]
    return DEFAULT_SINGLE_COLOR if size == 1 else BRANCH_COLORS[idx % len(BRANCH_COLORS)]

# ────────────────── 데이터 로드 ──────────────────
@st.cache_data(ttl=5)
def load_sheet_df():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?gid={TAB_GID}&format=csv&cb={int(time.time())}"
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip()
    if '신고가' not in df.columns:
        df['신고가'] = np.nan
    num_cols = ['평형', '2024년', '2025년', '신고가']
    for col in num_cols:
        if col in df.columns:
            df[col] = (df[col]
                        .astype(str)
                        .str.replace(r'[ ,억원]', '', regex=True)
                        .replace('', np.nan)
                        .astype(float))
    return df

# ────────────────── 데이터 가공 ──────────────────

def build_dataframe() -> pd.DataFrame:
    df = load_sheet_df()
    try:
        lat_col = next(c for c in df.columns if re.search(r'(lat|위도)', c, re.I))
        lon_col = next(c for c in df.columns if re.search(r'(lon|경도)', c, re.I))
    except StopIteration:
        st.error("❗ 시트에 lat/lon (또는 위도/경도) 컬럼이 없습니다.")
        st.stop()

    clean = lambda s: re.sub(r"[\u00a0\s]", "", str(s))
    df['lat'] = pd.to_numeric(df[lat_col].map(clean), errors='coerce')
    df['lon'] = pd.to_numeric(df[lon_col].map(clean), errors='coerce')

    df = df.dropna(subset=['lat', 'lon']).copy()
    if df.empty:
        st.error("❗ 시트에 유효한 좌표(lat/lon) 데이터가 없습니다.")
        st.stop()

    cond = (~df['신고가'].isna()) & (df['2025년'].isna() | (df['신고가'] > df['2025년']))
    df['신고가_유효'] = np.where(cond, df['신고가'], np.nan)
    df['latest'] = np.where(df['신고가_유효'].notna(), df['신고가_유효'], df['2025년'])
    df['상승률(%)'] = np.where(
        df['2024년'].notna() & df['latest'].notna(),
        ((df['latest'] - df['2024년']) / df['2024년'] * 100).round(1),
        np.nan,
    )

    df = (df
           .sort_values(by=['단지명', '평형', '신고가_유효', '2025년', '2024년'],
                        ascending=[True, True, False, False, False])
           .drop_duplicates(subset=['단지명', '평형'], keep='first')
           .reset_index(drop=True))
    return df

# ────────────────── 지도 생성 ──────────────────

def build_map(df: pd.DataFrame) -> folium.Map:
    m = folium.Map(location=[df['lat'].mean(), df['lon'].mean()], zoom_start=MAP_ZOOM, tiles='CartoDB positron')
    cluster = MarkerCluster().add_to(m)

    for name, g in df.groupby('단지명'):
        lat0, lon0 = g.iloc[0][['lat', 'lon']]
        folium.Marker(
            [lat0, lon0],
            icon=folium.DivIcon(html=f"<div style='font-size:12px;font-weight:bold;background:rgba(255,255,255,0.75);padding:2px 4px;border-radius:4px;'>{name}</div>")
        ).add_to(m)

        for i, (_, row) in enumerate(g.iterrows()):
            lat_c, lon_c = (lat0, lon0) if len(g)==1 else (
                lat0 + SEPARATION*sin(2*pi*i/len(g)),
                lon0 + SEPARATION*cos(2*pi*i/len(g))/np.cos(np.radians(lat0))
            )
            if len(g) != 1:
                folium.PolyLine([[lat0, lon0], [lat_c, lon_c]], color="#666", weight=1).add_to(m)
            color = pick_color(row, i, len(g))
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
                [lat_c, lon_c], radius=MARKER_RADIUS, fill=True, fill_color=color, fill_opacity=0.9, stroke=False,
                popup=folium.Popup(popup_html, max_width=420),
                tooltip=f"{int(row['평형'])}평"
            ).add_to(cluster)
            folium.Marker(
                [lat_c, lon_c],
                icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:bold;transform:translate(-50%,-12px);'>{int(row['평형'])}평</div>")
            ).add_to(m)

    overlay_html = f"""
    <style>
        body {{position:relative !important; margin:0;}}
        .overlay-box {{position:absolute; z-index:9998;}}

        .legend, .promo, .report-btn {{bottom:20px;}}
        .legend {{left:10px; width:520px; font-size:13px; line-height:1.55;}}
        .promo  {{right:10px; width:260px; font-size:18px; line-height:1.4;}}
        .report-btn {{left:50%; transform:translateX(-50%); z-index:9999;}}

        @media (max-width:768px) {{
            .legend {{bottom:110px; left:50%; transform:translateX(-50%); width:92%; font-size:11.5px;}}
            .promo  {{right:10px; display:block; font-size:16px; width:220px;}}
            .report-btn {{bottom:30px; padding:0;}}
        }}
        @media (max-width:480px) {{
            .title-box h1 {{font-size:16px;}}
            .title-box p  {{font-size:11px; right:8px; position:absolute; top:4px;}}
            .legend {{bottom:100px; width:94%; font-size:11px; line-height:1.45;}}
        }}
    </style>

    <div class='overlay-box title-box' style='top:30px; left:50%; transform:translateX(-50%); text-align:center; z-index:9999;'>
        <h1 style='margin:0; font-size:20px; font-weight:bold; background:rgba(255,255,255,0.9); padding:4px 12px; border-radius:6px;'>압구정동 신고가 맵</h1>
        <p style='margin:0; font-size:13px; color:#555; background:rgba(255,255,255,0.9); padding:0 6px; border-radius:4px; position:absolute; top:4px; right:-110px;'>신고가가 생길 때마다 자동 업데이트됩니다</p>
    </div>

    <div class='overlay-box legend' style='background:rgba(255,255,255,0.95); padding:12px; border:2px solid #888; border-radius:8px;'>
        <b>📌 안내</b><br>
        실거래 등록전 <b>신고&nbsp;약정가</b> 내역을 표시합니다.<br>
        마커를 클릭하면 <b>단지·평형별</b> 상세 내역을 확인할 수 있습니다.<br>
        신고 약정가는 거래허가 불허·해약 등에 의해 취소될 수 있으며<br>
        금액에 오차가 있을 수 있으므로 감안해서 보시기 바랍니다.<br>
        상승률은 <b>24년 가격 대비</b> 상승률이며,<br>
        미등록 신고약정가가 있을 경우 신고약정가로 표시됩니다.<br>
        나타난 신고가 내역에 오류가 있거나 반영이 안된 건은<br>
        <b>“신고가 제보하기”</b> 버튼으로 의견을 주실 수 있습니다.
    </div>

    <div class='overlay-box promo' style='background:#ffe6f2; border:3px solid #ff99cc; border-radius:8px; padding:10px; text-align:center;'>
        압구정 <b>매수·매도 상담</b>은<br>
        “<b>압구정 원 부동산</b>”<br>
        ☎ 02&nbsp;540&nbsp;3334
    </div>

    <div class='overlay-box report-btn'>
        <a href='{FORM_URL}' target='_blank'
           style='background:#007bff; color:#fff; padding:12px 22px; border-radius:8px;
                  font-size:16px; font-weight:bold; text-decoration:none;'>
           📝 신고가 제보하기
        </a>
    </div>
    """
    m.get_root().html.add_child(folium.Element(overlay_html))
    return m

# ────────────────── Streamlit UI ──────────────────

def main():
    st.set_page_config(page_title="압구정동 신고가 맵",
                       layout="wide",
                       initial_sidebar_state="collapsed")
    st_autorefresh(interval=15 * 60 * 1000, key="auto_refresh")
    st.title("📈 압구정동 단지·평형별 신고가 맵")
    df = build_dataframe()
    folium_map = build_map(df)
    st_html(folium_map.get_root().render(), height=800, scrolling=False)

if __name__ == "__main__":
    main()
