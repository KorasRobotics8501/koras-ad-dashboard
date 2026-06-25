import datetime
from datetime import timedelta
import pandas as pd
import altair as alt
import streamlit as st

st.set_page_config(page_title="Koras 광고 대시보드", layout="wide")

# ---- 디자인 (코라스 파랑 톤) ----
BLUE = "#2563EB"
st.markdown("""
<style>
.block-container {padding-top: 3.5rem; padding-bottom: 2.5rem; max-width: 1200px;}
hr {margin: 1.1rem 0;}
#MainMenu, footer {visibility: hidden;}
.k-tag {display:inline-flex; align-items:center; gap:6px; font-size:11px; letter-spacing:0.08em;
        font-weight:500; color:#2563EB; background:rgba(37,99,235,0.10);
        padding:4px 10px; border-radius:999px; margin:4px 0 8px;}
.k-h1 {font-size:23px; font-weight:700; line-height:1.2; margin:0;}
.k-sec {display:flex; align-items:center; gap:8px; margin:0 0 10px;}
.k-bar {width:3px; height:15px; background:#2563EB; border-radius:2px; display:inline-block;}
.k-sec-t {font-size:15px; font-weight:600;}
.k-hero {border:0.5px solid rgba(37,99,235,0.25); border-radius:14px; padding:18px 20px;
         margin-bottom:6px; background:rgba(37,99,235,0.04);}
.k-cell {background:rgba(128,128,128,0.06); border-radius:10px; padding:14px 16px;}
.k-hero .lbl {font-size:12px; color:rgba(128,128,128,0.95); margin-bottom:6px;}
.k-hero .num {font-size:28px; font-weight:700; line-height:1.05; letter-spacing:-0.01em;}
.k-pill {display:inline-flex; align-items:center; gap:2px; font-size:11px; font-weight:600;
         padding:2px 8px; border-radius:999px; margin-top:9px;}
.k-up {background:rgba(22,163,74,0.14); color:#15803D;}
.k-dn {background:rgba(220,38,38,0.14); color:#DC2626;}
.k-strip {margin-top:14px; padding-top:12px; border-top:0.5px solid rgba(128,128,128,0.2);
          font-size:12px; color:rgba(128,128,128,0.95); display:flex; gap:20px; flex-wrap:wrap;}
.k-strip b {color:#2563EB; font-weight:700;}
table.k-tbl {width:100%; border-collapse:collapse; font-size:13px; color:inherit;}
table.k-tbl th {background:rgba(37,99,235,0.07); color:#2563EB; padding:9px 12px; font-weight:600;}
table.k-tbl td {padding:10px 12px; border-top:0.5px solid rgba(128,128,128,0.18);}
table.k-tbl tr.tot td {border-top:1.5px solid rgba(37,99,235,0.35);
          background:rgba(37,99,235,0.06); font-weight:700;}
.k-dot {width:7px; height:7px; border-radius:50%; display:inline-block; margin-right:7px; vertical-align:middle;}
.k-wrap {border:0.5px solid rgba(128,128,128,0.22); border-radius:14px; overflow:hidden;}
</style>
""", unsafe_allow_html=True)

START_DATE = st.secrets.get("GOOGLE_START_DATE", "2026-04-01")
TODAY = datetime.date.today().isoformat()


# ========================================================
#  데이터 불러오기
# ========================================================
@st.cache_data(ttl=3600)
def load_google():
    from google.ads.googleads.client import GoogleAdsClient
    cfg = {
        "developer_token": st.secrets["GOOGLE_DEVELOPER_TOKEN"],
        "client_id": st.secrets["GOOGLE_CLIENT_ID"],
        "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
        "refresh_token": st.secrets["GOOGLE_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    customer_id = str(st.secrets["GOOGLE_CUSTOMER_ID"])
    client = GoogleAdsClient.load_from_dict(cfg)
    ga = client.get_service("GoogleAdsService")
    data = {}

    camp_q = f"""
        SELECT segments.date, campaign.name, metrics.impressions,
               metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM campaign
        WHERE segments.date BETWEEN '{START_DATE}' AND '{TODAY}'
    """
    for batch in ga.search_stream(customer_id=customer_id, query=camp_q):
        for r in batch.results:
            key = (str(r.segments.date), r.campaign.name)
            data[key] = {
                "impressions": int(r.metrics.impressions),
                "clicks": int(r.metrics.clicks),
                "views": 0,
                "cost": r.metrics.cost_micros / 1_000_000,
                "conversions": float(r.metrics.conversions),
            }

    view_q = f"""
        SELECT segments.date, campaign.name, metrics.video_trueview_views
        FROM campaign
        WHERE segments.date BETWEEN '{START_DATE}' AND '{TODAY}'
    """
    try:
        for batch in ga.search_stream(customer_id=customer_id, query=view_q):
            for r in batch.results:
                key = (str(r.segments.date), r.campaign.name)
                if key not in data:
                    data[key] = {"impressions": 0, "clicks": 0, "views": 0,
                                 "cost": 0.0, "conversions": 0.0}
                data[key]["views"] += int(r.metrics.video_trueview_views)
    except Exception:
        pass

    rows = [{"date": d, "platform": "google", "campaign": c, **m}
            for (d, c), m in data.items()]
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_meta():
    token = st.secrets.get("META_ACCESS_TOKEN")
    acct = st.secrets.get("META_AD_ACCOUNT_ID")
    if not token or not acct:
        return pd.DataFrame()
    try:
        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        FacebookAdsApi.init(access_token=token)
        account = AdAccount(f"act_{acct}")
        params = {
            "level": "adset",      # 광고세트 단위
            "time_range": {"since": START_DATE, "until": TODAY},
            "time_increment": 1,
        }
        fields = ["campaign_name", "adset_name", "impressions", "clicks",
                  "spend", "reach", "actions", "date_start"]
        rows = []
        for row in account.get_insights(fields=fields, params=params):
            link_click = 0
            for a in (row.get("actions") or []):
                if a.get("action_type") == "link_click":
                    link_click = int(float(a.get("value", 0)))
                    break
            rows.append({
                "date": str(row.get("date_start")),
                "platform": "meta",
                # campaign 칸에 '광고세트명' (구글=캠페인 / 메타=광고세트)
                "campaign": row.get("adset_name") or row.get("campaign_name"),
                "impressions": int(row.get("impressions", 0) or 0),
                "clicks": int(row.get("clicks", 0) or 0),
                "views": int(row.get("reach", 0) or 0),
                "cost": float(row.get("spend", 0) or 0),
                "conversions": float(link_click),
            })
        return pd.DataFrame(rows)
    except Exception as e:
        st.warning(f"메타 데이터를 불러오지 못했어요: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_data():
    g = load_google()
    m = load_meta()
    df = pd.concat([g, m], ignore_index=True)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


df = load_data()
if df.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

min_d = df["date"].min().date()
max_d = df["date"].max().date()

# ========================================================
#  사이드바
# ========================================================
st.sidebar.title("Koras 광고")
default_start = max_d.replace(day=1)
if default_start < min_d:
    default_start = min_d
date_range = st.sidebar.date_input("기간", value=(default_start, max_d),
                                   min_value=min_d, max_value=max_d)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
else:
    start = end = date_range if not isinstance(date_range, (list, tuple)) else date_range[0]

if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("전월 대비 = 선택 기간 vs 직전 같은 길이 기간")

period_len = (end - start).days + 1
prev_end = start - timedelta(days=1)
prev_start = prev_end - timedelta(days=period_len - 1)

f = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].copy()
f_prev = df[(df["date"].dt.date >= prev_start) & (df["date"].dt.date <= prev_end)].copy()


def agg(d):
    return {
        "views": int(d["views"].sum()),
        "clicks": int(d["clicks"].sum()),
        "conversions": int(round(d["conversions"].sum())),
        "impressions": int(d["impressions"].sum()),
        "cost": float(d["cost"].sum()),
    }


def delta_str(cur, prev):
    if prev and prev != 0:
        return f"{(cur - prev) / prev * 100:+.1f}%"
    return None


cur = agg(f)
prev = agg(f_prev)

# ========================================================
#  헤더
# ========================================================
period_txt = f"{start.strftime('%Y.%m.%d')} – {end.strftime('%m.%d')}"
st.markdown(f"""
<div style="display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-bottom:16px;">
  <div>
    <div class="k-tag">KORAS ROBOTICS · 광고 리포트</div>
    <div class="k-h1">통합 광고 성과</div>
  </div>
  <div style="text-align:right; font-size:12px; color:rgba(128,128,128,0.95); line-height:1.6;">
    <div>{period_txt}</div>
    <div style="opacity:0.7;">전월 대비 · 구글 + 메타</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ========================================================
#  통합 히어로 카드
# ========================================================
def pill(cur_v, prev_v):
    if not prev_v:
        return '<span class="k-pill k-up" style="opacity:0.7;">신규</span>'
    pct = (cur_v - prev_v) / prev_v * 100
    if pct >= 0:
        return f'<span class="k-pill k-up">▲ {pct:.1f}%</span>'
    return f'<span class="k-pill k-dn">▼ {abs(pct):.1f}%</span>'


t_ctr = (cur["clicks"] / cur["impressions"] * 100) if cur["impressions"] else 0
t_cpc = (cur["cost"] / cur["clicks"]) if cur["clicks"] else 0

hero = f"""
<div class="k-hero">
  <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:10px;">
    <div class="k-cell"><div class="lbl">조회·도달</div><div class="num">{cur['views']:,}</div>{pill(cur['views'], prev['views'])}</div>
    <div class="k-cell"><div class="lbl">클릭수</div><div class="num">{cur['clicks']:,}</div>{pill(cur['clicks'], prev['clicks'])}</div>
    <div class="k-cell"><div class="lbl">전환수</div><div class="num">{cur['conversions']:,}</div>{pill(cur['conversions'], prev['conversions'])}</div>
    <div class="k-cell"><div class="lbl">노출수</div><div class="num">{cur['impressions']:,}</div>{pill(cur['impressions'], prev['impressions'])}</div>
  </div>
  <div class="k-strip">
    <span>비용 <b>{cur['cost']:,.0f}원</b></span>
    <span>CTR <b>{t_ctr:.2f}%</b></span>
    <span>CPC <b>{t_cpc:,.0f}원</b></span>
  </div>
</div>
"""
st.markdown(hero, unsafe_allow_html=True)
st.markdown('<div style="font-size:11px; color:rgba(128,128,128,0.8); margin:6px 0 18px;">※ \'조회·도달\'은 구글 조회수 + 메타 도달의 합이에요(성격이 다른 값이라 참고용).</div>', unsafe_allow_html=True)


# ========================================================
#  플랫폼별 상세 표
# ========================================================
def cells(d):
    a = agg(d)
    ctr = (a["clicks"] / a["impressions"] * 100) if a["impressions"] else 0
    cpc = (a["cost"] / a["clicks"]) if a["clicks"] else 0
    return [f"{a['views']:,}", f"{a['clicks']:,}", f"{a['conversions']:,}",
            f"{a['impressions']:,}", f"{a['cost']:,.0f}원", f"{ctr:.2f}%", f"{cpc:,.0f}원"]


st.markdown('<div class="k-sec"><span class="k-bar"></span><span class="k-sec-t">플랫폼별 상세</span></div>', unsafe_allow_html=True)

headers = ["구분", "조회·도달", "클릭", "전환", "노출", "비용", "CTR", "CPC"]
rows_def = [
    ("구글", "#2563EB", cells(f[f["platform"] == "google"]), False),
    ("메타", "#7AA5F5", cells(f[f["platform"] == "meta"]), False),
    ("총계", None, cells(f), True),
]
html = '<div class="k-wrap"><table class="k-tbl"><thead><tr>'
for i, h in enumerate(headers):
    align = "left" if i == 0 else "right"
    html += f"<th style='text-align:{align};'>{h}</th>"
html += "</tr></thead><tbody>"
for name, color, vals, is_total in rows_def:
    cls = " class='tot'" if is_total else ""
    dot = f"<span class='k-dot' style='background:{color};'></span>" if color else ""
    html += f"<tr{cls}><td style='text-align:left;'>{dot}{name}</td>"
    for v in vals:
        html += f"<td style='text-align:right;'>{v}</td>"
    html += "</tr>"
html += "</tbody></table></div>"
st.markdown(html, unsafe_allow_html=True)

st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

# ========================================================
#  그래프
# ========================================================
LABELS = {"views": "조회·도달", "clicks": "클릭수", "conversions": "전환수",
          "impressions": "노출수"}
BLUE_SCHEME = ["#2563EB", "#7AA5F5", "#1E3A8A", "#9DBEF7"]

plat_pick = st.radio("플랫폼", ["전체", "구글", "메타"], horizontal=True)
if plat_pick == "구글":
    g = f[f["platform"] == "google"]
    unit_label = "캠페인별"
elif plat_pick == "메타":
    g = f[f["platform"] == "meta"]
    unit_label = "광고세트별"
else:
    g = f
    unit_label = "캠페인/광고세트별"

if g.empty:
    st.info("선택한 조건에 데이터가 없어요.")
else:
    st.markdown('<div class="k-sec" style="margin-top:6px;"><span class="k-bar"></span><span class="k-sec-t">일별 추이</span></div>', unsafe_allow_html=True)
    metric_keys = ["views", "clicks", "conversions", "impressions"]
    metric_labels = [LABELS[k] for k in metric_keys]
    chosen = st.multiselect("표시할 지표", metric_labels, default=metric_labels)
    if chosen:
        cols = [k for k in metric_keys if LABELS[k] in chosen]
        daily = g.groupby("date")[cols].sum().reset_index()
        long = daily.melt("date", var_name="m", value_name="값")
        long["지표"] = long["m"].map(LABELS)
        long["상대값"] = long.groupby("m")["값"].transform(
            lambda s: s / s.max() * 100 if s.max() else s * 0)
        line = (
            alt.Chart(long).mark_line(point=True, strokeWidth=2.5).encode(
                x=alt.X("date:T", title="날짜"),
                y=alt.Y("상대값:Q", title="상대값 (지표별 최대=100)"),
                color=alt.Color("지표:N", title="지표",
                                scale=alt.Scale(range=BLUE_SCHEME)),
                tooltip=["date:T", "지표:N", alt.Tooltip("값:Q", title="실제값", format=",.0f")],
            ).properties(height=360)
        )
        st.altair_chart(line, width="stretch")
        st.caption("※ 지표마다 단위가 달라, 각 지표를 '자기 최대값=100' 기준으로 맞춰 그렸어요. 선에 마우스를 올리면 실제 숫자가 나와요.")

    st.markdown(f'<div class="k-sec" style="margin-top:8px;"><span class="k-bar"></span><span class="k-sec-t">{unit_label} 비교</span></div>', unsafe_allow_html=True)
    bar_label = st.selectbox("지표 선택", metric_labels, index=0)
    bcol = [k for k in metric_keys if LABELS[k] == bar_label][0]
    bar_df = g.groupby("campaign")[bcol].sum().reset_index().sort_values(bcol, ascending=False)
    bars = (
        alt.Chart(bar_df).mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("campaign:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-35)),
            y=alt.Y(f"{bcol}:Q", title=bar_label),
            tooltip=[alt.Tooltip("campaign:N", title="이름"),
                     alt.Tooltip(f"{bcol}:Q", title=bar_label, format=",.0f")],
        ).properties(height=380)
    )
    st.altair_chart(bars, width="stretch")
