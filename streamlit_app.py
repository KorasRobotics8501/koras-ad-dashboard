import datetime
import pandas as pd
import altair as alt
import streamlit as st

st.set_page_config(page_title="Koras 광고 대시보드", layout="wide")

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
            "level": "campaign",
            "time_range": {"since": START_DATE, "until": TODAY},
            "time_increment": 1,
        }
        fields = ["campaign_name", "impressions", "clicks", "spend",
                  "reach", "actions", "date_start"]
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
                "campaign": row.get("campaign_name"),
                "impressions": int(row.get("impressions", 0) or 0),
                "clicks": int(row.get("clicks", 0) or 0),
                "views": int(row.get("reach", 0) or 0),   # 메타는 도달
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

# ========================================================
#  사이드바 (기간 / 새로고침)
# ========================================================
st.sidebar.title("Koras 광고")
min_d = df["date"].min().date()
max_d = df["date"].max().date()
date_range = st.sidebar.date_input("기간", value=(min_d, max_d),
                                   min_value=min_d, max_value=max_d)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
else:
    start = end = date_range if not isinstance(date_range, (list, tuple)) else date_range[0]

if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

f_all = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].copy()

LABELS = {"views": "조회수", "clicks": "클릭수", "conversions": "전환수",
          "impressions": "노출수", "cost": "비용"}


def caption_line(d, show_cpm=True, show_conv=False):
    cost = d["cost"].sum()
    impr = int(d["impressions"].sum())
    clk = int(d["clicks"].sum())
    ctr = (clk / impr * 100) if impr else 0
    cpc = (cost / clk) if clk else 0
    parts = [f"비용 {cost:,.0f}원", f"CTR {ctr:.2f}%", f"CPC {cpc:,.0f}원"]
    if show_cpm:
        cpm = (cost / impr * 1000) if impr else 0
        parts.append(f"CPM {cpm:,.0f}원")
    parts.append(f"기간 {start} ~ {end}")
    st.caption("   ·   ".join(parts))


def trend_chart(d, metric_keys, metric_labels, key):
    chosen = st.multiselect("표시할 지표", metric_labels, default=metric_labels, key=key)
    if not chosen:
        return
    cols = [k for k, lab in zip(metric_keys, metric_labels) if lab in chosen]
    daily = d.groupby("date")[cols].sum().reset_index()
    long = daily.melt("date", var_name="m", value_name="값")
    long["지표"] = long["m"].map(LABELS)
    long["상대값"] = long.groupby("m")["값"].transform(
        lambda s: s / s.max() * 100 if s.max() else s * 0)
    chart = (
        alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("date:T", title="날짜"),
            y=alt.Y("상대값:Q", title="상대값 (지표별 최대=100)"),
            color=alt.Color("지표:N", title="지표"),
            tooltip=["date:T", "지표:N", alt.Tooltip("값:Q", title="실제값", format=",.0f")],
        ).properties(height=380)
    )
    st.altair_chart(chart, width="stretch")
    st.caption("※ 지표마다 단위가 달라, 각 지표를 '자기 최대값=100' 기준으로 맞춰 그렸어요. 선에 마우스를 올리면 실제 숫자가 나와요.")


def campaign_bar(d, metric_keys, metric_labels, key):
    label = st.selectbox("지표 선택", metric_labels, index=0, key=key)
    col = [k for k, lab in zip(metric_keys, metric_labels) if lab == label][0]
    by_c = d.groupby("campaign")[col].sum().sort_values(ascending=True)
    st.bar_chart(by_c, horizontal=True)


# ========================================================
#  3구역 탭 (통합 / 구글 / 메타) + 원본
# ========================================================
tab_all, tab_g, tab_m, tab_raw = st.tabs(["📊 통합", "🔵 구글", "🟦 메타", "📄 원본"])

# ---------- 통합 ----------
with tab_all:
    st.subheader("📊 통합 (구글 + 메타)")
    d = f_all
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("조회·도달", f"{int(d['views'].sum()):,}")
    c2.metric("클릭수", f"{int(d['clicks'].sum()):,}")
    c3.metric("전환수", f"{d['conversions'].sum():,.0f}")
    c4.metric("노출수", f"{int(d['impressions'].sum()):,}")
    caption_line(d, show_cpm=False)
    st.caption("※ 통합 '조회·도달'은 구글 조회수 + 메타 도달의 합이에요(성격이 다른 값이라 참고용).")
    st.divider()
    trend_chart(d, ["views", "clicks", "conversions", "impressions"],
                ["조회수", "클릭수", "전환수", "노출수"], key="t_all")
    st.divider()
    st.subheader("캠페인별 비교")
    campaign_bar(d, ["views", "clicks", "conversions", "impressions"],
                 ["조회수", "클릭수", "전환수", "노출수"], key="b_all")

# ---------- 구글 ----------
with tab_g:
    st.subheader("🔵 구글")
    d = f_all[f_all["platform"] == "google"]
    if d.empty:
        st.info("선택 기간에 구글 데이터가 없어요.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("조회수 (TrueView)", f"{int(d['views'].sum()):,}")
        c2.metric("클릭수", f"{int(d['clicks'].sum()):,}")
        c3.metric("전환수", f"{d['conversions'].sum():,.0f}")
        c4.metric("노출수", f"{int(d['impressions'].sum()):,}")
        caption_line(d, show_cpm=True)
        st.divider()
        trend_chart(d, ["views", "clicks", "conversions", "impressions"],
                    ["조회수", "클릭수", "전환수", "노출수"], key="t_g")
        st.divider()
        st.subheader("캠페인별 비교")
        campaign_bar(d, ["views", "clicks", "conversions", "impressions"],
                     ["조회수", "클릭수", "전환수", "노출수"], key="b_g")

# ---------- 메타 ----------
with tab_m:
    st.subheader("🟦 메타")
    d = f_all[f_all["platform"] == "meta"]
    if d.empty:
        st.info("선택 기간에 메타 데이터가 없어요.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("도달", f"{int(d['views'].sum()):,}")
        c2.metric("클릭수", f"{int(d['clicks'].sum()):,}")
        c3.metric("노출수", f"{int(d['impressions'].sum()):,}")
        caption_line(d, show_cpm=True)
        st.caption("※ 도달은 '순 사용자 수'라 날짜별 합산 시 중복이 있을 수 있어요(추세 참고용).")
        st.divider()
        trend_chart(d, ["views", "clicks", "impressions"],
                    ["도달", "클릭수", "노출수"], key="t_m")
        st.divider()
        st.subheader("캠페인별 비교")
        campaign_bar(d, ["views", "clicks", "impressions"],
                     ["도달", "클릭수", "노출수"], key="b_m")

# ---------- 원본 ----------
with tab_raw:
    st.subheader("📄 원본 데이터")
    st.caption(f"기간 {start} ~ {end}   ·   총 {len(f_all)}건")
    show = f_all.sort_values("date", ascending=False).copy()
    show["date"] = show["date"].dt.date
    st.dataframe(show, width="stretch", hide_index=True)
